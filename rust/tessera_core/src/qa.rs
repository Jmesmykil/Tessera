//! Automatic sheet inspection. Each check can FAIL, not merely report.
//!
//! Written after a sheet with three empty columns and fourteen duplicate frames
//! reached a person before it reached a check. A human should never be the first
//! detector of something a program can measure.

use crate::sheet::SheetMeta;

pub struct Finding {
    pub check: &'static str,
    pub ok: bool,
    pub detail: String,
}

fn cell_coverage(pixels: &[f32], width: u32, meta: &SheetMeta) -> Vec<f64> {
    meta.frames
        .iter()
        .map(|f| {
            let mut opaque = 0u64;
            for y in f.y_px..f.y_px + meta.cell_h_px {
                for x in f.x_px..f.x_px + meta.cell_w_px {
                    if pixels[((y * width + x) * 4 + 3) as usize] > 0.0 {
                        opaque += 1;
                    }
                }
            }
            opaque as f64 / (meta.cell_w_px as f64 * meta.cell_h_px as f64)
        })
        .collect()
}

pub fn inspect(pixels: &[f32], width: u32, height: u32, meta: &SheetMeta) -> Vec<Finding> {
    let mut findings = Vec::new();
    let coverage = cell_coverage(pixels, width, meta);

    let empty: Vec<u32> = coverage
        .iter()
        .zip(&meta.frames)
        .filter(|(c, _)| **c < 0.02)
        .map(|(_, f)| f.frame_index)
        .collect();
    findings.push(Finding {
        check: "cells non-empty",
        ok: empty.is_empty(),
        detail: format!("{}/{} cells carry subject", coverage.len() - empty.len(), coverage.len()),
    });

    let lo = coverage.iter().cloned().fold(f64::MAX, f64::min);
    let hi = coverage.iter().cloned().fold(f64::MIN, f64::max);
    let ratio = if lo > 0.0 { hi / lo } else { f64::INFINITY };
    findings.push(Finding {
        check: "coverage consistent",
        ok: ratio <= 6.0,
        detail: format!("min {lo:.3} max {hi:.3} ratio {ratio:.1}x (limit 6.0x)"),
    });

    let mut offsets: Vec<(i64, i64)> = meta
        .frames
        .iter()
        .map(|f| ((f.anchor_px.0 as i64 - f.x_px as i64), (f.anchor_px.1 as i64 - f.y_px as i64)))
        .collect();
    offsets.sort_unstable();
    offsets.dedup();
    findings.push(Finding {
        check: "anchor stable",
        ok: offsets.len() == 1,
        detail: format!("{} distinct in-cell anchor offset(s)", offsets.len()),
    });

    let inside = meta.frames.iter().all(|f| match f.bbox_px {
        None => true,
        Some((x, y, w, h)) => {
            x >= f.x_px && y >= f.y_px
                && x + w <= f.x_px + meta.cell_w_px
                && y + h <= f.y_px + meta.cell_h_px
        }
    });
    findings.push(Finding {
        check: "subject inside cell",
        ok: inside,
        detail: if inside { "every bbox fits its cell".into() } else { "a bbox escapes its cell".into() },
    });

    // Duplicate cells inside a row are the signature of samples running past the
    // end of an action, where the rig holds its final pose.
    let mut dupes = 0usize;
    let mut rows: std::collections::HashMap<u32, Vec<u64>> = std::collections::HashMap::new();
    for f in &meta.frames {
        let mut acc: u64 = 0;
        let mut y = f.y_px;
        while y < f.y_px + meta.cell_h_px {
            let mut x = f.x_px;
            while x < f.x_px + meta.cell_w_px {
                let o = ((y * width + x) * 4) as usize;
                acc = acc
                    .wrapping_mul(31)
                    .wrapping_add((pixels[o] * 255.0) as u64 * 7)
                    .wrapping_add((pixels[o + 3] * 255.0) as u64);
                x += 2;
            }
            y += 2;
        }
        rows.entry(f.yaw_index).or_default().push(acc);
    }
    for values in rows.values() {
        let mut seen = values.clone();
        seen.sort_unstable();
        seen.dedup();
        dupes += values.len() - seen.len();
    }
    // A single frame per row cannot duplicate anything, and a STATIC subject
    // legitimately produces one. Only flag repeats when more than one frame was
    // actually asked for — otherwise the check calls correct behaviour a defect,
    // which is worse than not checking at all.
    let per_row = rows.values().map(|v| v.len()).max().unwrap_or(0);
    findings.push(Finding {
        check: "frames distinct",
        ok: dupes == 0 || per_row <= 1,
        detail: if per_row <= 1 {
            "single frame per direction — nothing to repeat".to_string()
        } else {
            format!("{dupes} duplicate frame(s) across {} yaw row(s)", rows.len())
        },
    });

    let opaque = pixels.chunks(4).filter(|p| p[3] > 0.0).count();
    let lit = pixels
        .chunks(4)
        .filter(|p| p[3] > 0.0 && p[0].max(p[1]).max(p[2]) > 0.06)
        .count();
    let share = if opaque > 0 { lit as f64 / opaque as f64 } else { 0.0 };
    findings.push(Finding {
        check: "not crushed to black",
        ok: share > 0.5,
        detail: format!("{:.1}% of opaque pixels carry visible value (want >50%)", share * 100.0),
    });

    let _ = height;
    findings
}

pub fn passed(findings: &[Finding]) -> bool {
    findings.iter().all(|f| f.ok)
}

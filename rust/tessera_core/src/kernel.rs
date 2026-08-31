//! The ASCII universal kernel, in Rust.
//!
//! This is a PORT, not a reimplementation, and the difference matters. ASCII,
//! ASCII Studio for Blender and ASCII Studio for Unity each implement the same
//! frozen contract in their own language, and a release is invalid the moment any
//! host's output diverges. The golden vector in `tests/golden.rs` is what makes
//! that claim checkable here rather than merely intended: same payload
//! fingerprint, same settings, byte-identical glyph text.
//!
//! Two properties are load-bearing and easy to lose in a port:
//!
//! * Glyphs are BITMAPS in the payload, never rasterised from a font. Coverage is
//!   arithmetic over unpacked bits, so it is identical on every machine with no
//!   font, canvas or DOM anywhere in the path.
//! * Selection has two routes. Below `edge_threshold` of local range a cell has no
//!   orientation worth matching and the tone ramp is the CORRECT answer, not an
//!   approximation; above it, the 4x4-style signature correlation preserves the
//!   silhouette edge that a tone-only match would mush.

use serde::Deserialize;
use std::path::Path;

#[derive(Debug, Deserialize)]
struct GlyphEntry {
    char: String,
    rows: Vec<u32>,
}

#[derive(Debug, Deserialize)]
struct Payload {
    schema: String,
    version: String,
    cell_width: u32,
    cell_height: u32,
    glyphs: Vec<GlyphEntry>,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum ColorMode {
    Source,
    Tint,
    Mono,
    Palette,
}

#[derive(Debug, Clone)]
pub struct Settings {
    pub columns: u32,
    pub cell_aspect: f64,
    pub gamma: f64,
    pub contrast: f64,
    pub structure_strength: f64,
    pub edge_threshold: f64,
    pub invert: bool,
    pub background: [u8; 4],
    pub glyphs: Option<String>,
    pub color_mode: ColorMode,
    pub tint: [u8; 4],
    pub palette: Vec<[u8; 4]>,
    pub density: f64,
    pub jitter: f64,
    pub seed: u32,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            columns: 96,
            cell_aspect: 0.5,
            gamma: 1.0,
            contrast: 1.0,
            structure_strength: 0.7,
            edge_threshold: 0.08,
            invert: false,
            background: [0, 0, 0, 255],
            glyphs: None,
            color_mode: ColorMode::Source,
            tint: [255, 255, 255, 255],
            palette: vec![[42, 46, 48, 255], [108, 116, 120, 255], [170, 178, 182, 255]],
            density: 1.0,
            jitter: 0.0,
            seed: 0,
        }
    }
}

impl Settings {
    /// The sprite preset. Every value that differs from stock is a deliberate
    /// correction rather than taste — see `sprite_defaults` in the crate docs.
    pub fn sprite(kernel: &Kernel) -> Self {
        Self {
            // 0.5 is a TERMINAL value: terminal cells are about twice as tall as
            // they are wide. A sprite is emitted as square pixels through the
            // kernel's own cell, so preserving real proportions needs w/h. Left
            // at 0.5 every sprite is squashed vertically and it reads as a
            // modelling error rather than a settings error.
            cell_aspect: kernel.cell_width as f64 / kernel.cell_height as f64,
            background: [0, 0, 0, 0],
            color_mode: ColorMode::Source,
            glyphs: Some(kernel.chars.iter().collect()),
            ..Default::default()
        }
    }

    pub fn validate(&self) -> Result<(), String> {
        if !(8..=1024).contains(&self.columns) {
            return Err("columns must be in [8, 1024]".into());
        }
        if !(0.1..=2.0).contains(&self.cell_aspect) {
            return Err("cell_aspect must be in [0.1, 2.0]".into());
        }
        if !(0.1..=4.0).contains(&self.gamma) {
            return Err("gamma must be in [0.1, 4.0]".into());
        }
        if !(0.0..=1.0).contains(&self.structure_strength) {
            return Err("structure_strength must be in [0, 1]".into());
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy)]
pub struct Cell {
    pub glyph: u16,
    pub foreground: [u8; 4],
    pub background: [u8; 4],
    pub luminance: f64,
}

#[derive(Debug, Clone)]
pub struct Frame {
    pub width: u32,
    pub height: u32,
    pub cells: Vec<Cell>,
}

pub struct Kernel {
    pub version: String,
    pub cell_width: u32,
    pub cell_height: u32,
    pub chars: Vec<char>,
    pub rows: Vec<Vec<u32>>,
    pub signatures: Vec<Vec<f64>>,
    pub coverage: Vec<f64>,
    pub ramp: Vec<usize>,
    pub fingerprint: String,
}

impl Kernel {
    pub fn load(path: impl AsRef<Path>) -> Result<Self, String> {
        let text = std::fs::read_to_string(path.as_ref()).map_err(|e| e.to_string())?;
        Self::from_str(&text)
    }

    pub fn from_str(text: &str) -> Result<Self, String> {
        let payload: Payload = serde_json::from_str(text).map_err(|e| e.to_string())?;
        if payload.schema != "com.astral.ascii.kernel/1" {
            return Err(format!("unsupported schema {}", payload.schema));
        }
        // The fingerprint is sha256 over the canonically-serialised payload, so it
        // must be computed the same way every host computes it — sorted keys, no
        // whitespace — or the divergence gate compares two different things.
        let value: serde_json::Value = serde_json::from_str(text).map_err(|e| e.to_string())?;
        let fingerprint = crate::sha256::hex(canonical_json(&value).as_bytes());

        let cw = payload.cell_width;
        let ch = payload.cell_height;
        let chars: Vec<char> = payload
            .glyphs
            .iter()
            .map(|g| g.char.chars().next().unwrap_or(' '))
            .collect();
        let rows: Vec<Vec<u32>> = payload.glyphs.iter().map(|g| g.rows.clone()).collect();

        let signatures: Vec<Vec<f64>> = rows
            .iter()
            .map(|r| {
                let mut sig = Vec::with_capacity((cw * ch) as usize);
                for y in 0..ch as usize {
                    for x in 0..cw {
                        let bit = 1u32 << (cw - 1 - x);
                        sig.push(if r.get(y).copied().unwrap_or(0) & bit != 0 { 1.0f64 } else { 0.0 });
                    }
                }
                sig
            })
            .collect();
        let coverage: Vec<f64> = signatures
            .iter()
            .map(|s| s.iter().sum::<f64>() / s.len() as f64)
            .collect();
        let mut ramp: Vec<usize> = (0..chars.len()).collect();
        ramp.sort_by(|&a, &b| {
            coverage[a]
                .partial_cmp(&coverage[b])
                .unwrap_or(std::cmp::Ordering::Equal)
                .then(a.cmp(&b))
        });

        Ok(Self {
            version: payload.version,
            cell_width: cw,
            cell_height: ch,
            chars,
            rows,
            signatures,
            coverage,
            ramp,
            fingerprint,
        })
    }

    #[inline]
    pub fn luminance(r: f64, g: f64, b: f64) -> f64 {
        0.2126 * r + 0.7152 * g + 0.0722 * b
    }

    fn tone(&self, value: f64, s: &Settings) -> f64 {
        let v = value.clamp(0.0, 1.0);
        let v = (v - 0.5) * s.contrast + 0.5;
        let v = v.clamp(0.0, 1.0).powf(1.0 / s.gamma);
        if s.invert { 1.0 - v } else { v }
    }

    fn allowed(&self, s: &Settings) -> Result<Vec<usize>, String> {
        let Some(glyphs) = &s.glyphs else {
            return Ok(self.ramp.clone());
        };
        let mut wanted: Vec<char> = Vec::new();
        for c in glyphs.chars() {
            if !wanted.contains(&c) {
                wanted.push(c);
            }
        }
        let unknown: String = wanted.iter().filter(|c| !self.chars.contains(c)).collect();
        if !unknown.is_empty() {
            return Err(format!("unsupported glyphs: {unknown}"));
        }
        Ok(self.ramp.iter().copied().filter(|&i| wanted.contains(&self.chars[i])).collect())
    }

    fn noise(x: u32, y: u32, seed: u32) -> f64 {
        let mut v = (x.wrapping_mul(73856093)) ^ (y.wrapping_mul(19349663)) ^ (seed.wrapping_mul(83492791));
        v ^= v >> 13;
        v = v.wrapping_mul(1274126177);
        ((v & 0x00FF_FFFF) as f64) / 16_777_215.0
    }

    fn select_ramp(&self, lum: f64, allowed: &[usize]) -> usize {
        let mut best = allowed[0];
        let mut best_d = f64::INFINITY;
        for &i in allowed {
            let d = (self.coverage[i] - lum).abs();
            if d < best_d {
                best_d = d;
                best = i;
            }
        }
        best
    }

    fn select_structural(&self, sample: &[f64], lum: f64, strength: f64, allowed: &[usize]) -> usize {
        let mean = sample.iter().sum::<f64>() / sample.len() as f64;
        let dev: Vec<f64> = sample.iter().map(|v| v - mean).collect();
        let norm = dev.iter().map(|v| v * v).sum::<f64>().sqrt();
        let mut best = allowed[0];
        let mut best_score = f64::NEG_INFINITY;
        for &i in allowed {
            let sig = &self.signatures[i];
            let sm = self.coverage[i];
            let correlation = if norm > 0.0 {
                let sdev: Vec<f64> = sig.iter().map(|v| v - sm).collect();
                let snorm = sdev.iter().map(|v| v * v).sum::<f64>().sqrt();
                if snorm > 0.0 {
                    dev.iter().zip(&sdev).map(|(a, b)| a * b).sum::<f64>() / (norm * snorm)
                } else {
                    0.0
                }
            } else {
                0.0
            };
            let score = strength * correlation + (1.0 - strength) * (1.0 - (sm - lum).abs());
            if score > best_score {
                best_score = score;
                best = i;
            }
        }
        best
    }

    /// RGBA in 0..1, row-major, top-down. `mask` is optional per-pixel weight.
    pub fn convert_rgba(
        &self,
        pixels: &[f32],
        source_width: u32,
        source_height: u32,
        s: &Settings,
        mask: Option<&[f32]>,
    ) -> Result<Frame, String> {
        s.validate()?;
        if pixels.len() != (source_width * source_height * 4) as usize {
            return Err("RGBA buffer length does not match dimensions".into());
        }
        let allowed = self.allowed(s)?;
        let columns = s.columns.min(source_width);
        let rows = ((source_height as f64 / source_width as f64) * columns as f64 * s.cell_aspect)
            .round()
            .max(1.0) as u32;

        let mut cells = Vec::with_capacity((columns * rows) as usize);
        for gy in 0..rows {
            let y0 = gy * source_height / rows;
            let y1 = ((gy + 1) * source_height / rows).max(y0 + 1);
            for gx in 0..columns {
                let x0 = gx * source_width / columns;
                let x1 = ((gx + 1) * source_width / columns).max(x0 + 1);
                let mut sample = Vec::with_capacity((self.cell_width * self.cell_height) as usize);
                let (mut sr, mut sg, mut sb, mut sa, mut weight) = (0.0f64, 0.0, 0.0, 0.0, 0.0);
                for sy in 0..self.cell_height {
                    let py = (y0 + (sy * 2 + 1) * (y1 - y0) / (self.cell_height * 2))
                        .min(source_height - 1);
                    for sx in 0..self.cell_width {
                        let px = (x0 + (sx * 2 + 1) * (x1 - x0) / (self.cell_width * 2))
                            .min(source_width - 1);
                        let p = (py * source_width + px) as usize;
                        let m = mask.map(|m| m[p] as f64).map(|m| m.clamp(0.0, 1.0)).unwrap_or(1.0);
                        let o = p * 4;
                        let (r, g, b, a) = (pixels[o] as f64, pixels[o + 1] as f64, pixels[o + 2] as f64, pixels[o + 3] as f64);
                        sample.push(self.tone(Self::luminance(r, g, b), s) * m);
                        sr += r * m;
                        sg += g * m;
                        sb += b * m;
                        sa += a * m;
                        weight += m;
                    }
                }
                let mut lum = sample.iter().sum::<f64>() / sample.len() as f64;
                lum = (lum + (Self::noise(gx, gy, s.seed) - 0.5) * s.jitter * 0.3).clamp(0.0, 1.0);
                let local_range = sample.iter().cloned().fold(f64::MIN, f64::max)
                    - sample.iter().cloned().fold(f64::MAX, f64::min);
                let mut glyph = if local_range >= s.edge_threshold && s.structure_strength > 0.0 {
                    self.select_structural(&sample, lum, s.structure_strength, &allowed)
                } else {
                    self.select_ramp(lum, &allowed)
                };

                let foreground = if weight > 0.0 {
                    let src = [
                        round_half_even((sr / weight) * 255.0).clamp(0.0, 255.0) as u8,
                        round_half_even((sg / weight) * 255.0).clamp(0.0, 255.0) as u8,
                        round_half_even((sb / weight) * 255.0).clamp(0.0, 255.0) as u8,
                        round_half_even((sa / weight) * 255.0).clamp(0.0, 255.0) as u8,
                    ];
                    let fg = match s.color_mode {
                        ColorMode::Tint => [s.tint[0], s.tint[1], s.tint[2],
                            ((src[3] as u32 * s.tint[3] as u32) / 255) as u8],
                        ColorMode::Mono => [255, 255, 255, src[3]],
                        ColorMode::Palette => {
                            let scaled = lum.clamp(0.0, 1.0) * (s.palette.len() - 1) as f64;
                            let c = s.palette[round_half_even(scaled) as usize];
                            [c[0], c[1], c[2], ((src[3] as u32 * c[3] as u32) / 255) as u8]
                        }
                        ColorMode::Source => src,
                    };
                    if Self::noise(gx, gy, s.seed.wrapping_add(17)) > s.density {
                        glyph = self.chars.iter().position(|&c| c == ' ').unwrap_or(allowed[0]);
                    }
                    fg
                } else {
                    glyph = 0;
                    [0, 0, 0, 0]
                };

                cells.push(Cell { glyph: glyph as u16, foreground, background: s.background, luminance: lum });
            }
        }
        Ok(Frame { width: columns, height: rows, cells })
    }

    /// Render a glyph frame back to RGBA in 0..1 at an integer scale.
    pub fn render_rgba(&self, frame: &Frame, scale: u32) -> (u32, u32, Vec<f32>) {
        let width = frame.width * self.cell_width * scale;
        let height = frame.height * self.cell_height * scale;
        let mut out = vec![0.0f32; (width * height * 4) as usize];
        for gy in 0..frame.height {
            for gx in 0..frame.width {
                let cell = frame.cells[(gy * frame.width + gx) as usize];
                let bits = &self.rows[cell.glyph as usize];
                for py in 0..self.cell_height * scale {
                    let by = (py / scale) as usize;
                    for px in 0..self.cell_width * scale {
                        let bx = px / scale;
                        let ink = bits.get(by).copied().unwrap_or(0) & (1 << (self.cell_width - 1 - bx)) != 0;
                        let colour = if ink { cell.foreground } else { cell.background };
                        let x = gx * self.cell_width * scale + px;
                        let y = gy * self.cell_height * scale + py;
                        let o = ((y * width + x) * 4) as usize;
                        out[o] = colour[0] as f32 / 255.0;
                        out[o + 1] = colour[1] as f32 / 255.0;
                        out[o + 2] = colour[2] as f32 / 255.0;
                        out[o + 3] = colour[3] as f32 / 255.0;
                    }
                }
            }
        }
        (width, height, out)
    }

    pub fn text(&self, frame: &Frame) -> String {
        let mut out = String::new();
        for y in 0..frame.height {
            for x in 0..frame.width {
                out.push(self.chars[frame.cells[(y * frame.width + x) as usize].glyph as usize]);
            }
            if y + 1 < frame.height {
                out.push('\n');
            }
        }
        out
    }
}

/// Serde's default map ordering is insertion order; the fingerprint needs sorted
/// keys and no whitespace, matching every other host's canonical form.
/// Python's `round()` is round-half-to-EVEN. Rust's `f64::round` is
/// half-away-from-zero. A colour channel landing exactly on .5 is common enough
/// that the two disagree across a whole sheet, so the reference behaviour wins.
pub fn round_half_even(v: f64) -> f64 {
    let floor = v.floor();
    let diff = v - floor;
    if (diff - 0.5).abs() < f64::EPSILON {
        if (floor as i64) % 2 == 0 { floor } else { floor + 1.0 }
    } else {
        v.round()
    }
}

fn canonical_json(value: &serde_json::Value) -> String {
    match value {
        serde_json::Value::Object(map) => {
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            let inner: Vec<String> = keys
                .iter()
                .map(|k| format!("{}:{}", serde_json::to_string(k).unwrap(), canonical_json(&map[*k])))
                .collect();
            format!("{{{}}}", inner.join(","))
        }
        serde_json::Value::Array(items) => {
            let inner: Vec<String> = items.iter().map(canonical_json).collect();
            format!("[{}]", inner.join(","))
        }
        other => serde_json::to_string(other).unwrap(),
    }
}

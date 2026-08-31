//! The sheet driver: many frames that have to agree with each other.
//!
//! Two invariants, both asserted by the QA pass and both learned from sheets that
//! lacked them: ONE cell size that every frame fits inside, and an ANCHOR that
//! lands on the same point of every cell. A walk cycle whose feet wander by a cell
//! reads as a limp; eight directions at eight scales cannot be flipped through.
//!
//! Placement is in whole cells. A cell is the unit of art, and half-cell placement
//! smears a sprite across the pixel grid it was just quantised onto. Sub-cell
//! precision is preserved where it is useful instead: the metadata carries each
//! anchor in pixels as a float.

use crate::kernel::{Cell, ColorMode, Frame, Kernel, Settings};

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Anchor {
    Center,
    Bottom,
    Feet,
    /// Anchor every frame at the SAME point in the source frame, ignoring where
    /// the subject sits inside it.
    ///
    /// The other three modes align each frame by its own content box, which is
    /// right for a walk cycle — you want the contact point steady. It is wrong
    /// for a jump: re-anchoring per frame subtracts the vertical travel, so the
    /// sheet shows a slime that never leaves the ground. Every element sheet
    /// captured before this existed had `anchor_px` identical across all 14
    /// time samples, which is exactly that defect, and only the two elements
    /// with the flattest surfaces tripped the duplicate-frame check.
    Frame,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Fill {
    /// Silhouette drives coverage, colour drives colour. The sprite default.
    Solid,
    /// Stock kernel behaviour: luminance drives coverage. ASCII-art look.
    Tone,
}

#[derive(Debug, Clone)]
pub struct View {
    pub pixels: Vec<f32>,
    pub width: u32,
    pub height: u32,
    pub yaw_index: u32,
    pub frame_index: u32,
    pub yaw_degrees: f32,
    pub frame_number: i32,
}

#[derive(Debug, Clone, Copy)]
pub struct BBox {
    pub x: u32,
    pub y: u32,
    pub w: u32,
    pub h: u32,
}

#[derive(Debug, Clone)]
pub struct FrameMeta {
    pub row: u32,
    pub column: u32,
    pub yaw_index: u32,
    pub frame_index: u32,
    pub yaw_degrees: f32,
    pub frame_number: i32,
    pub empty: bool,
    pub x_px: u32,
    pub y_px: u32,
    pub bbox_px: Option<(u32, u32, u32, u32)>,
    pub anchor_px: (f32, f32),
}

#[derive(Debug, Clone)]
pub struct SheetMeta {
    pub rows: u32,
    pub columns: u32,
    pub cell_w_px: u32,
    pub cell_h_px: u32,
    pub anchor_x_px: u32,
    pub anchor_y_px: u32,
    pub width_px: u32,
    pub height_px: u32,
    pub frames: Vec<FrameMeta>,
    pub kernel_fingerprint: String,
}

fn is_ink(kernel: &Kernel, cell: &Cell) -> bool {
    cell.foreground[3] > 0 && kernel.chars[cell.glyph as usize] != ' '
}

fn content_bbox(kernel: &Kernel, frame: &Frame) -> Option<BBox> {
    let (mut x0, mut y0, mut x1, mut y1) = (u32::MAX, u32::MAX, 0u32, 0u32);
    let mut found = false;
    for y in 0..frame.height {
        for x in 0..frame.width {
            if is_ink(kernel, &frame.cells[(y * frame.width + x) as usize]) {
                x0 = x0.min(x); y0 = y0.min(y);
                x1 = x1.max(x); y1 = y1.max(y);
                found = true;
            }
        }
    }
    found.then(|| BBox { x: x0, y: y0, w: x1 - x0 + 1, h: y1 - y0 + 1 })
}

fn anchor_of(kernel: &Kernel, frame: &Frame, bbox: &BBox, mode: Anchor) -> (f64, f64) {
    let cx = bbox.x as f64 + bbox.w as f64 / 2.0;
    match mode {
        // The centre of the captured frame, the same for every view, so whatever
        // the subject does inside that frame survives into the sheet.
        Anchor::Frame => (frame.width as f64 / 2.0, frame.height as f64 / 2.0),
        Anchor::Center => (cx, bbox.y as f64 + bbox.h as f64 / 2.0),
        Anchor::Bottom => (cx, (bbox.y + bbox.h) as f64),
        // `feet` is the centroid of the ink actually occupying the lowest row, not
        // the box centre: a walk cycle leans, and pinning a leaning body by its box
        // slides the contact point out from under it.
        Anchor::Feet => {
            let lowest = bbox.y + bbox.h - 1;
            let inked: Vec<u32> = (bbox.x..bbox.x + bbox.w)
                .filter(|&x| is_ink(kernel, &frame.cells[(lowest * frame.width + x) as usize]))
                .collect();
            let centre = if inked.is_empty() {
                cx
            } else {
                inked.iter().sum::<u32>() as f64 / inked.len() as f64 + 0.5
            };
            (centre, (bbox.y + bbox.h) as f64)
        }
    }
}

fn occupancy(view: &View) -> Vec<f32> {
    let mut out = vec![0.0; view.pixels.len()];
    for i in (0..view.pixels.len()).step_by(4) {
        let a = view.pixels[i + 3];
        if a > 0.0 {
            out[i] = a; out[i + 1] = a; out[i + 2] = a; out[i + 3] = a;
        }
    }
    out
}

fn alpha_channel(view: &View) -> Vec<f32> {
    (0..(view.width * view.height) as usize).map(|i| view.pixels[i * 4 + 3]).collect()
}

/// Convert one view, deciding coverage and colour by different rules under `Solid`.
///
/// The kernel maps LUMINANCE to coverage, which is right for ASCII art and wrong
/// for sprites: a red torso sits near 0.37 luminance, so tone-driven selection can
/// never choose a solid tile no matter how opaque the model is, and the sprite
/// comes out dotted. Two passes fix it without touching the kernel — a shape pass
/// over the silhouette painted white, and a colour pass masked by alpha so
/// transparent neighbours cannot drag an edge cell toward black.
/// Convert one view to a glyph frame. Public so a test can compare the
/// high-depth and byte-quantised renderers on the same real frame.
pub fn convert_view(kernel: &Kernel, s: &Settings, view: &View, fill: Fill) -> Result<Frame, String> {
    convert(kernel, s, view, fill)
}

fn convert(kernel: &Kernel, s: &Settings, view: &View, fill: Fill) -> Result<Frame, String> {
    let mask = alpha_channel(view);
    let colour = kernel.convert_rgba(&view.pixels, view.width, view.height, s, Some(&mask))?;
    if fill == Fill::Tone {
        return Ok(colour);
    }
    let shape = kernel.convert_rgba(&occupancy(view), view.width, view.height, s, None)?;
    let cells = shape
        .cells
        .iter()
        .zip(&colour.cells)
        .map(|(sh, co)| Cell {
            glyph: sh.glyph,
            foreground: co.foreground,
            background: co.background,
            // Solid fill runs the kernel twice — silhouette for coverage,
            // alpha-masked colour for colour — so the float colour must come
            // from the same pass as the byte colour: the colour pass.
            foreground_linear: co.foreground_linear,
            luminance: sh.luminance,
        })
        .collect();
    Ok(Frame { width: colour.width, height: colour.height, cells })
}

pub struct BuildOptions {
    pub anchor: Anchor,
    pub fill: Fill,
    pub padding: u32,
    pub scale: u32,
}

impl Default for BuildOptions {
    fn default() -> Self {
        Self { anchor: Anchor::Feet, fill: Fill::Solid, padding: 1, scale: 1 }
    }
}

pub fn build(
    kernel: &Kernel,
    settings: &Settings,
    views: &[View],
    options: &BuildOptions,
) -> Result<(u32, u32, Vec<f32>, SheetMeta), String> {
    if views.is_empty() {
        return Err("no views to pack".into());
    }
    let mut converted = Vec::with_capacity(views.len());
    for view in views {
        let frame = convert(kernel, settings, view, options.fill)?;
        let bbox = content_bbox(kernel, &frame);
        converted.push((view, frame, bbox));
    }

    // Measure outward FROM THE ANCHOR, not from the bounding boxes: two frames of
    // equal size whose anchors sit at different heights need different room above.
    let (mut left, mut right, mut top, mut bottom) = (0.0f64, 0.0f64, 0.0f64, 0.0f64);
    for (_, frame, bbox) in &converted {
        let Some(b) = bbox else { continue };
        let (ax, ay) = anchor_of(kernel, frame, b, options.anchor);
        left = left.max(ax - b.x as f64);
        right = right.max((b.x + b.w) as f64 - ax);
        top = top.max(ay - b.y as f64);
        bottom = bottom.max((b.y + b.h) as f64 - ay);
    }
    let cell_w = (left.ceil() + right.ceil()) as u32 + 2 * options.padding;
    let cell_h = (top.ceil() + bottom.ceil()) as u32 + 2 * options.padding;
    let cell_w = cell_w.max(1);
    let cell_h = cell_h.max(1);
    let anchor_x = left.ceil() as u32 + options.padding;
    let anchor_y = top.ceil() as u32 + options.padding;

    let mut yaws: Vec<u32> = views.iter().map(|v| v.yaw_index).collect();
    yaws.sort_unstable(); yaws.dedup();
    let mut frames: Vec<u32> = views.iter().map(|v| v.frame_index).collect();
    frames.sort_unstable(); frames.dedup();
    let (rows, columns) = (yaws.len() as u32, frames.len() as u32);

    let sheet_w = columns * cell_w;
    let sheet_h = rows * cell_h;
    let empty_cell = Cell { glyph: 0, foreground: [0; 4], background: [0; 4],
                            foreground_linear: [0.0; 4], luminance: 0.0 };
    let mut cells = vec![empty_cell; (sheet_w * sheet_h) as usize];
    let mut metas = Vec::with_capacity(converted.len());

    for (view, frame, bbox) in &converted {
        let row = yaws.iter().position(|&y| y == view.yaw_index).unwrap() as u32;
        let column = frames.iter().position(|&f| f == view.frame_index).unwrap() as u32;
        let (ox, oy, placed) = match bbox {
            None => (0u32, 0u32, false),
            Some(b) => {
                let (ax, ay) = anchor_of(kernel, frame, b, options.anchor);
                let ox = anchor_x as i64 - crate::kernel::round_half_even(ax - b.x as f64) as i64;
                let oy = anchor_y as i64 - crate::kernel::round_half_even(ay - b.y as f64) as i64;
                (ox.max(0) as u32, oy.max(0) as u32, true)
            }
        };
        if placed {
            let b = bbox.unwrap();
            let base_x = column * cell_w + ox;
            let base_y = row * cell_h + oy;
            for y in b.y..b.y + b.h {
                for x in b.x..b.x + b.w {
                    let cell = frame.cells[(y * frame.width + x) as usize];
                    if !is_ink(kernel, &cell) { continue; }
                    let (tx, ty) = (base_x + (x - b.x), base_y + (y - b.y));
                    if tx < sheet_w && ty < sheet_h {
                        cells[(ty * sheet_w + tx) as usize] = cell;
                    }
                }
            }
        }
        let px = kernel.cell_width * options.scale;
        let py = kernel.cell_height * options.scale;
        metas.push(FrameMeta {
            row, column,
            yaw_index: view.yaw_index, frame_index: view.frame_index,
            yaw_degrees: view.yaw_degrees, frame_number: view.frame_number,
            empty: !placed,
            x_px: column * cell_w * px,
            y_px: row * cell_h * py,
            bbox_px: bbox.map(|b| (
                (column * cell_w + ox) * px, (row * cell_h + oy) * py, b.w * px, b.h * py)),
            anchor_px: (((column * cell_w + anchor_x) * px) as f32,
                        ((row * cell_h + anchor_y) * py) as f32),
        });
    }
    metas.sort_by_key(|m| (m.row, m.column));

    let composite = Frame { width: sheet_w, height: sheet_h, cells };
    let (width, height, pixels) = kernel.render_rgba_hd(&composite, options.scale);
    let px = kernel.cell_width * options.scale;
    let py = kernel.cell_height * options.scale;
    let meta = SheetMeta {
        rows, columns,
        cell_w_px: cell_w * px, cell_h_px: cell_h * py,
        anchor_x_px: anchor_x * px, anchor_y_px: anchor_y * py,
        width_px: width, height_px: height,
        frames: metas,
        kernel_fingerprint: kernel.fingerprint.clone(),
    };
    let _ = ColorMode::Source; // keep the enum re-exported for hosts
    Ok((width, height, pixels, meta))
}

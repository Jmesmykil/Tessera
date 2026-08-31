//! A real-time viewport for the core — so spinning a model and dragging a light
//! cost a frame here, not a render on another machine.
//!
//! Blender is the wrong thing to have inside an interaction loop. It is the right
//! thing to produce the final sheet and the wrong thing to answer "what does this
//! look like from over here", because the answer arrives seconds later and by then
//! the hand has moved on. So Blender exports a decimated snapshot ONCE per asset
//! and this rasteriser answers every subsequent question locally.
//!
//! It is a small painter with a depth buffer, not a renderer: perspective divide,
//! barycentric fill, z-test, Lambert plus a rim term. At a couple of thousand
//! triangles that is far below a frame's budget, and it is enough to judge
//! silhouette, pose and light direction — which is all this view is for.

use std::f32::consts::PI;

const MAGIC: &[u8; 4] = b"TPM1";

pub struct PreviewMesh {
    pub frames: usize,
    pub vertices: usize,
    pub indices: Vec<u32>,
    pub colours: Vec<f32>,
    pub positions: Vec<Vec<f32>>,
    pub normals: Vec<Vec<f32>>,
    pub radius: f32,
    pub centre: [f32; 3],
}

fn u32le(b: &[u8]) -> u32 { u32::from_le_bytes([b[0], b[1], b[2], b[3]]) }
fn f32le(b: &[u8]) -> f32 { f32::from_le_bytes([b[0], b[1], b[2], b[3]]) }

impl PreviewMesh {
    pub fn load(path: &str) -> Result<Self, String> {
        let data = std::fs::read(path).map_err(|e| e.to_string())?;
        if data.len() < 32 || &data[0..4] != MAGIC {
            return Err("not a Tessera preview mesh".into());
        }
        let frames = u32le(&data[4..]) as usize;
        let vertices = u32le(&data[8..]) as usize;
        let index_count = u32le(&data[12..]) as usize;
        let radius = f32le(&data[16..]);
        let centre = [f32le(&data[20..]), f32le(&data[24..]), f32le(&data[28..])];
        let mut at = 32usize;

        let mut indices = Vec::with_capacity(index_count);
        for i in 0..index_count {
            indices.push(u32le(&data[at + i * 4..]));
        }
        at += index_count * 4;

        let mut colours = Vec::with_capacity(vertices * 3);
        for i in 0..vertices * 3 {
            colours.push(f32le(&data[at + i * 4..]));
        }
        at += vertices * 12;

        let mut positions = Vec::with_capacity(frames);
        let mut normals = Vec::with_capacity(frames);
        for _ in 0..frames {
            let mut p = Vec::with_capacity(vertices * 3);
            for i in 0..vertices * 3 { p.push(f32le(&data[at + i * 4..])); }
            at += vertices * 12;
            let mut n = Vec::with_capacity(vertices * 3);
            for i in 0..vertices * 3 { n.push(f32le(&data[at + i * 4..])); }
            at += vertices * 12;
            positions.push(p);
            normals.push(n);
        }
        Ok(Self { frames, vertices, indices, colours, positions, normals, radius, centre })
    }
}

/// How the viewport draws. These are the affordances a person expects from a 3D
/// view because Blender and Unity both have them — zoom, a floor to judge contact
/// against, and a way to see the mesh rather than only its surface.
#[derive(Clone, Copy, PartialEq)]
pub enum Shading {
    /// Lit surface. The default, and the one that answers "how does the light sit".
    Shaded,
    /// Unlit albedo. Shows the material's own colour with no lighting opinion.
    Albedo,
    /// Edges only. Shows the topology a decimated preview is actually made of.
    Wireframe,
    /// Normals as colour. Reads instantly wrong when a mesh has flipped faces.
    Normals,
}

impl Shading {
    pub fn from_u32(value: u32) -> Self {
        match value {
            1 => Shading::Albedo,
            2 => Shading::Wireframe,
            3 => Shading::Normals,
            _ => Shading::Shaded,
        }
    }
}

pub struct ViewParams {
    pub frame: usize,
    pub yaw: f32,        // degrees
    pub pitch: f32,      // degrees
    pub light_azimuth: f32,
    pub light_elevation: f32,
    pub ambient: f32,
    pub size: u32,
    pub zoom: f32,
    pub shading: Shading,
    pub grid: bool,
    pub background: [f32; 3],
}

impl Default for ViewParams {
    fn default() -> Self {
        Self {
            frame: 0, yaw: 25.0, pitch: 12.0,
            light_azimuth: -35.0, light_elevation: 35.0, ambient: 0.3,
            size: 420, zoom: 1.0, shading: Shading::Shaded, grid: true,
            background: [0.078, 0.086, 0.102],
        }
    }
}

/// Returns RGBA bytes, top-down. Raw rather than PNG: at interactive rates the
/// compression would cost more than the drawing.
pub fn render(mesh: &PreviewMesh, view: &ViewParams) -> Vec<u8> {
    let size = view.size.max(16) as usize;
    let mut rgba = vec![0u8; size * size * 4];
    let mut depth = vec![f32::INFINITY; size * size];
    let bg = [(view.background[0] * 255.0) as u8,
              (view.background[1] * 255.0) as u8,
              (view.background[2] * 255.0) as u8];
    for pixel in rgba.chunks_mut(4) {
        pixel[0] = bg[0]; pixel[1] = bg[1]; pixel[2] = bg[2]; pixel[3] = 255;
    }

    let frame = view.frame.min(mesh.frames.saturating_sub(1));
    let positions = &mesh.positions[frame];
    let normals = &mesh.normals[frame];

    let (sy, cy) = (view.yaw * PI / 180.0).sin_cos();
    let (sp, cp) = (view.pitch * PI / 180.0).sin_cos();

    // Light in view space, so dragging it means "left of frame" at any yaw.
    let (sla, cla) = (view.light_azimuth * PI / 180.0).sin_cos();
    let (sle, cle) = (view.light_elevation * PI / 180.0).sin_cos();
    let light = normalise([sla * cle, sle, -cla * cle]);

    let scale = size as f32 * 0.44 * view.zoom.clamp(0.2, 6.0) / mesh.radius.max(1e-6);
    let half = size as f32 / 2.0;

    let project = |i: usize| -> ([f32; 3], [f32; 3]) {
        let (x, y, z) = (positions[i * 3] - mesh.centre[0],
                         positions[i * 3 + 1] - mesh.centre[1],
                         positions[i * 3 + 2] - mesh.centre[2]);
        // Blender is Z-up; the viewport is Y-up.
        let (bx, by, bz) = (x, z, -y);
        let (rx, rz) = (bx * cy + bz * sy, -bx * sy + bz * cy);
        let (ry, rz2) = (by * cp - rz * sp, by * sp + rz * cp);
        let (nx, ny, nz) = (normals[i * 3], normals[i * 3 + 1], normals[i * 3 + 2]);
        let (bnx, bny, bnz) = (nx, nz, -ny);
        let (rnx, rnz) = (bnx * cy + bnz * sy, -bnx * sy + bnz * cy);
        let (rny, rnz2) = (bny * cp - rnz * sp, bny * sp + rnz * cp);
        ([half + rx * scale, half - ry * scale, rz2], normalise([rnx, rny, rnz2]))
    };

    // A ground grid, drawn first so geometry occludes it. Without a floor there is
    // no way to see whether feet are planted or hovering, which is the single
    // thing a sprite anchor depends on.
    if view.grid {
        let extent = mesh.radius * 1.6;
        let lines = 9;
        for i in 0..=lines {
            let f = -extent + 2.0 * extent * (i as f32 / lines as f32);
            for (a, b) in [([f, 0.0, -extent], [f, 0.0, extent]),
                           ([-extent, 0.0, f], [extent, 0.0, f])] {
                draw_line(&mut rgba, &mut depth, size, project_point(a, mesh, view, scale, half),
                          project_point(b, mesh, view, scale, half),
                          [0.20, 0.23, 0.28]);
            }
        }
    }

    for tri in mesh.indices.chunks(3) {
        if tri.len() < 3 { continue; }
        let (a, na) = project(tri[0] as usize);
        let (b, nb) = project(tri[1] as usize);
        let (c, nc) = project(tri[2] as usize);
        let area = (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1]);
        if area.abs() < 1e-9 { continue; }

        let min_x = a[0].min(b[0]).min(c[0]).floor().max(0.0) as usize;
        let max_x = (a[0].max(b[0]).max(c[0]).ceil() as isize).clamp(0, size as isize - 1) as usize;
        let min_y = a[1].min(b[1]).min(c[1]).floor().max(0.0) as usize;
        let max_y = (a[1].max(b[1]).max(c[1]).ceil() as isize).clamp(0, size as isize - 1) as usize;

        let colour = [mesh.colours[tri[0] as usize * 3],
                      mesh.colours[tri[0] as usize * 3 + 1],
                      mesh.colours[tri[0] as usize * 3 + 2]];

        for py in min_y..=max_y {
            for px in min_x..=max_x {
                let (fx, fy) = (px as f32 + 0.5, py as f32 + 0.5);
                let w0 = ((b[0] - a[0]) * (fy - a[1]) - (fx - a[0]) * (b[1] - a[1])) / area;
                let w1 = ((fx - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (fy - a[1])) / area;
                let w2 = 1.0 - w0 - w1;
                if w0 < 0.0 || w1 < 0.0 || w2 < 0.0 { continue; }
                let z = a[2] * w2 + b[2] * w1 + c[2] * w0;
                let o = py * size + px;
                if z >= depth[o] { continue; }
                depth[o] = z;

                let normal = normalise([
                    na[0] * w2 + nb[0] * w1 + nc[0] * w0,
                    na[1] * w2 + nb[1] * w1 + nc[1] * w0,
                    na[2] * w2 + nb[2] * w1 + nc[2] * w0,
                ]);
                let out = o * 4;
                match view.shading {
                    Shading::Albedo => {
                        for k in 0..3 {
                            rgba[out + k] = (colour[k].clamp(0.0, 1.0) * 255.0) as u8;
                        }
                    }
                    Shading::Normals => {
                        for k in 0..3 {
                            rgba[out + k] = ((normal[k] * 0.5 + 0.5) * 255.0) as u8;
                        }
                    }
                    _ => {
                        let lambert = (normal[0] * light[0] + normal[1] * light[1]
                                       + normal[2] * light[2]).max(0.0);
                        // A rim term is what makes a dark subject read against a
                        // dark background — the same reason the render presets
                        // carry one.
                        let rim = (1.0 - normal[2].abs()).powf(2.5) * 0.35;
                        let shade = view.ambient + (1.0 - view.ambient) * lambert;
                        for k in 0..3 {
                            rgba[out + k] =
                                (((colour[k] * shade) + rim).clamp(0.0, 1.0) * 255.0) as u8;
                        }
                    }
                }
                rgba[out + 3] = 255;
            }
        }
    }
    rgba
}

fn project_point(p: [f32; 3], mesh: &PreviewMesh, view: &ViewParams,
                 scale: f32, half: f32) -> [f32; 3] {
    let (sy, cy) = (view.yaw * PI / 180.0).sin_cos();
    let (sp, cp) = (view.pitch * PI / 180.0).sin_cos();
    let (bx, by, bz) = (p[0], p[1], p[2]);
    let (rx, rz) = (bx * cy + bz * sy, -bx * sy + bz * cy);
    let (ry, rz2) = (by * cp - rz * sp, by * sp + rz * cp);
    [half + rx * scale, half - ry * scale, rz2]
}

fn draw_line(rgba: &mut [u8], depth: &mut [f32], size: usize,
             a: [f32; 3], b: [f32; 3], colour: [f32; 3]) {
    let steps = ((b[0] - a[0]).abs().max((b[1] - a[1]).abs()).ceil() as usize).max(1);
    for i in 0..=steps {
        let t = i as f32 / steps as f32;
        let x = a[0] + (b[0] - a[0]) * t;
        let y = a[1] + (b[1] - a[1]) * t;
        let z = a[2] + (b[2] - a[2]) * t;
        if x < 0.0 || y < 0.0 || x >= size as f32 || y >= size as f32 { continue; }
        let o = y as usize * size + x as usize;
        if z >= depth[o] { continue; }
        depth[o] = z;
        let out = o * 4;
        for k in 0..3 {
            rgba[out + k] = (colour[k].clamp(0.0, 1.0) * 255.0) as u8;
        }
        rgba[out + 3] = 255;
    }
}

fn normalise(v: [f32; 3]) -> [f32; 3] {
    let length = (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]).sqrt();
    if length < 1e-9 { [0.0, 0.0, 1.0] } else { [v[0] / length, v[1] / length, v[2] / length] }
}

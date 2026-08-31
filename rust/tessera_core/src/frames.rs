//! The TSF frame bridge, read side. Format is documented in `tessera/frames.py`;
//! top-down is stated there and honoured here, because a silently flipped sheet
//! passes review — every frame looks plausible alone.

use crate::sheet::View;
use std::io::Read;
use std::path::Path;

const MAGIC: &[u8; 4] = b"TSF1";

fn u32le(b: &[u8]) -> u32 { u32::from_le_bytes([b[0], b[1], b[2], b[3]]) }
fn i32le(b: &[u8]) -> i32 { i32::from_le_bytes([b[0], b[1], b[2], b[3]]) }
fn f32le(b: &[u8]) -> f32 { f32::from_le_bytes([b[0], b[1], b[2], b[3]]) }

pub fn read_views(path: impl AsRef<Path>) -> Result<Vec<View>, String> {
    let mut data = Vec::new();
    std::fs::File::open(path.as_ref())
        .map_err(|e| e.to_string())?
        .read_to_end(&mut data)
        .map_err(|e| e.to_string())?;
    if data.len() < 16 || &data[0..4] != MAGIC {
        return Err("not a Tessera frame file".into());
    }
    let width = u32le(&data[4..8]);
    let height = u32le(&data[8..12]);
    let count = u32le(&data[12..16]);
    let per = (width * height * 4) as usize;
    let mut offset = 16usize;
    let mut views = Vec::with_capacity(count as usize);
    for _ in 0..count {
        if offset + 16 + per * 4 > data.len() {
            return Err("frame file is truncated".into());
        }
        let yaw_index = u32le(&data[offset..]);
        let frame_index = u32le(&data[offset + 4..]);
        let yaw_degrees = f32le(&data[offset + 8..]);
        // Signed: a Blender action may start before frame 0.
        let frame_number = i32le(&data[offset + 12..]);
        offset += 16;
        let mut pixels = Vec::with_capacity(per);
        for i in 0..per {
            pixels.push(f32le(&data[offset + i * 4..]));
        }
        offset += per * 4;
        views.push(View { pixels, width, height, yaw_index, frame_index, yaw_degrees, frame_number });
    }
    Ok(views)
}

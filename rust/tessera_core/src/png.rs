//! PNG output. Filter 0 throughout: glyph output is large flat runs that deflate
//! already collapses well, so per-scanline filter search costs time for nothing.

use flate2::write::ZlibEncoder;
use flate2::Compression;
use std::io::Write;

fn chunk(tag: &[u8; 4], payload: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(payload.len() + 12);
    out.extend_from_slice(&(payload.len() as u32).to_be_bytes());
    out.extend_from_slice(tag);
    out.extend_from_slice(payload);
    let mut crc = crc32(tag);
    crc = crc32_continue(crc, payload);
    out.extend_from_slice(&crc.to_be_bytes());
    out
}

fn crc_table() -> [u32; 256] {
    let mut table = [0u32; 256];
    let mut n = 0;
    while n < 256 {
        let mut c = n as u32;
        let mut k = 0;
        while k < 8 {
            c = if c & 1 != 0 { 0xEDB8_8320 ^ (c >> 1) } else { c >> 1 };
            k += 1;
        }
        table[n] = c;
        n += 1;
    }
    table
}

fn crc32(data: &[u8]) -> u32 {
    crc32_continue(0xFFFF_FFFF ^ 0xFFFF_FFFF, data) // start from the standard init
}

fn crc32_continue(previous: u32, data: &[u8]) -> u32 {
    let table = crc_table();
    let mut c = previous ^ 0xFFFF_FFFF;
    for &byte in data {
        c = table[((c ^ byte as u32) & 0xFF) as usize] ^ (c >> 8);
    }
    c ^ 0xFFFF_FFFF
}

pub fn encode_rgba(width: u32, height: u32, pixels: &[f32]) -> Result<Vec<u8>, String> {
    if width == 0 || height == 0 {
        return Err("width and height must be positive".into());
    }
    let expected = (width * height * 4) as usize;
    if pixels.len() != expected {
        return Err(format!("expected {expected} channel values, got {}", pixels.len()));
    }
    let row_bytes = (width * 4) as usize;
    let mut raw = Vec::with_capacity((row_bytes + 1) * height as usize);
    for y in 0..height as usize {
        raw.push(0u8); // filter: None
        let start = y * row_bytes;
        for &value in &pixels[start..start + row_bytes] {
            raw.push((value * 255.0).round().clamp(0.0, 255.0) as u8);
        }
    }
    let mut encoder = ZlibEncoder::new(Vec::new(), Compression::new(9));
    encoder.write_all(&raw).map_err(|e| e.to_string())?;
    let compressed = encoder.finish().map_err(|e| e.to_string())?;

    let mut ihdr = Vec::new();
    ihdr.extend_from_slice(&width.to_be_bytes());
    ihdr.extend_from_slice(&height.to_be_bytes());
    ihdr.extend_from_slice(&[8, 6, 0, 0, 0]); // depth 8, RGBA, deflate, adaptive, no interlace

    let mut out = Vec::new();
    out.extend_from_slice(&[0x89, b'P', b'N', b'G', 0x0D, 0x0A, 0x1A, 0x0A]);
    out.extend_from_slice(&chunk(b"IHDR", &ihdr));
    out.extend_from_slice(&chunk(b"IDAT", &compressed));
    out.extend_from_slice(&chunk(b"IEND", &[]));
    Ok(out)
}

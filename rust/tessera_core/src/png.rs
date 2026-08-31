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

/// Peak RGB value in the sheet. Alpha is coverage and is never scaled by this —
/// only the colour carries energy.
pub fn peak_energy(pixels: &[f32]) -> f32 {
    pixels
        .chunks_exact(4)
        .flat_map(|p| p[..3].iter().copied())
        .fold(0.0f32, f32::max)
}

/// Scale RGB so the brightest sample lands at 1.0, returning the divisor.
///
/// A capture of an emissive subject carries values well above 1.0 — that
/// over-range IS the glow. Writing it to an 8-bit PNG clips it to white and the
/// sprite arrives in the engine as a flat matte with the light thrown away.
/// Normalising instead keeps the whole range and hands the engine one number to
/// multiply back by, so a shader can reconstruct the original energy exactly.
/// Returns 1.0 when nothing exceeds 1.0, leaving ordinary sheets untouched.
pub fn normalise_energy(pixels: &mut [f32]) -> f32 {
    let peak = peak_energy(pixels);
    if peak <= 1.0 || !peak.is_finite() {
        return 1.0;
    }
    for p in pixels.chunks_exact_mut(4) {
        p[0] /= peak;
        p[1] /= peak;
        p[2] /= peak;
    }
    peak
}

/// 16-bit RGBA PNG.
///
/// These sprites live in soft translucent falloff — measured alpha runs 40-170
/// of 255 across the element sheets — which is exactly the range where 8 bits
/// band visibly. Sixteen bits costs storage and nothing else; PNG requires the
/// samples big-endian.
pub fn encode_rgba16(width: u32, height: u32, pixels: &[f32]) -> Result<Vec<u8>, String> {
    if width == 0 || height == 0 {
        return Err("width and height must be positive".into());
    }
    let expected = (width * height * 4) as usize;
    if pixels.len() != expected {
        return Err(format!("expected {expected} channel values, got {}", pixels.len()));
    }
    let row_samples = (width * 4) as usize;
    let mut raw = Vec::with_capacity((row_samples * 2 + 1) * height as usize);
    for y in 0..height as usize {
        raw.push(0u8); // filter: None
        let start = y * row_samples;
        for &value in &pixels[start..start + row_samples] {
            let sample = (value * 65535.0).round().clamp(0.0, 65535.0) as u16;
            raw.extend_from_slice(&sample.to_be_bytes());
        }
    }
    let mut encoder = ZlibEncoder::new(Vec::new(), Compression::new(9));
    encoder.write_all(&raw).map_err(|e| e.to_string())?;
    let compressed = encoder.finish().map_err(|e| e.to_string())?;

    let mut ihdr = Vec::new();
    ihdr.extend_from_slice(&width.to_be_bytes());
    ihdr.extend_from_slice(&height.to_be_bytes());
    ihdr.extend_from_slice(&[16, 6, 0, 0, 0]); // depth 16, RGBA, deflate, adaptive, no interlace

    let mut out = Vec::new();
    out.extend_from_slice(&[0x89, b'P', b'N', b'G', 0x0D, 0x0A, 0x1A, 0x0A]);
    out.extend_from_slice(&chunk(b"IHDR", &ihdr));
    out.extend_from_slice(&chunk(b"IDAT", &compressed));
    out.extend_from_slice(&chunk(b"IEND", &[]));
    Ok(out)
}

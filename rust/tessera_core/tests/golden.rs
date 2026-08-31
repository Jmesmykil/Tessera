//! The port is only a port if it produces the same bytes.
//!
//! `golden-vector.json` pins one conversion — a 40x20 synthetic source at
//! columns=20, structure_strength=0.7 — to an exact glyph grid, and every host
//! asserts against it. If this test passes, the Rust kernel and the Python,
//! JavaScript and C# kernels are the same kernel.

use tessera_core::{ColorMode, Kernel, Settings};

fn assets() -> std::path::PathBuf {
    std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../assets")
}

/// The exact source the golden vector describes: "40x20 binary checker with
/// abs(x-2*y)<2 diagonal".
fn golden_source(width: u32, height: u32) -> Vec<f32> {
    let mut pixels = Vec::with_capacity((width * height * 4) as usize);
    for y in 0..height {
        for x in 0..width {
            // Taken from the reference host's own test, not inferred from the
            // vector's prose description — a 5px checker, phase `== 0`.
            let checker = ((x / 5) + (y / 5)) % 2 == 0;
            let diagonal = (x as i32 - 2 * y as i32).abs() < 2;
            let v = if checker || diagonal { 1.0 } else { 0.0 };
            pixels.extend_from_slice(&[v, v, v, 1.0]);
        }
    }
    pixels
}

#[test]
fn fingerprint_matches_the_shipped_payload() {
    let kernel = Kernel::load(assets().join("kernel.json")).expect("kernel loads");
    let golden: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(assets().join("golden-vector.json")).unwrap())
            .unwrap();
    assert_eq!(
        kernel.fingerprint,
        golden["kernel_fingerprint"].as_str().unwrap(),
        "Rust kernel fingerprint disagrees with the shipped golden vector"
    );
}

#[test]
fn golden_vector_text_matches() {
    let kernel = Kernel::load(assets().join("kernel.json")).unwrap();
    let golden: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(assets().join("golden-vector.json")).unwrap())
            .unwrap();
    let width = 40u32;
    let height = 20u32;
    let settings = Settings {
        columns: golden["settings"]["columns"].as_u64().unwrap() as u32,
        structure_strength: golden["settings"]["structure_strength"].as_f64().unwrap(),
        color_mode: ColorMode::Source,
        ..Default::default()
    };
    let frame = kernel
        .convert_rgba(&golden_source(width, height), width, height, &settings, None)
        .expect("conversion succeeds");
    assert_eq!(frame.width, golden["width"].as_u64().unwrap() as u32);
    assert_eq!(frame.height, golden["height"].as_u64().unwrap() as u32);
    assert_eq!(kernel.text(&frame), golden["text"].as_str().unwrap());
}

#[test]
fn sprite_preset_fixes_the_terminal_cell_aspect() {
    let kernel = Kernel::load(assets().join("kernel.json")).unwrap();
    let sprite = Settings::sprite(&kernel);
    assert!((sprite.cell_aspect - kernel.cell_width as f64 / kernel.cell_height as f64).abs() < 1e-9);
    assert_ne!(sprite.cell_aspect, 0.5, "0.5 is the terminal value and squashes sprites");
    assert_eq!(sprite.background[3], 0, "sprites need a transparent cutout");
}

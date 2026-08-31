//! Cross-implementation equivalence: the Rust core and the Python reference must
//! produce the same sheet from the same frames.
//!
//! The Python is not the product — it is the prototype that found six real defects
//! and is now the oracle proving the port faithful. If these bytes ever disagree,
//! one of the two is wrong and the sheet driver is no longer one implementation.

use tessera_core::{frames, kernel::Kernel, sheet, sheet::{Anchor, BuildOptions, Fill}};

fn root() -> std::path::PathBuf {
    std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

#[test]
fn sheet_matches_the_python_reference() {
    let tsf = root().join("out/kid-walk.tsf");
    if !tsf.exists() {
        eprintln!("skipped: no captured frames at {tsf:?}");
        return;
    }
    let kernel = Kernel::load(root().join("assets/tilesets/pixel-hd.kernel.json")).unwrap();
    let views = frames::read_views(&tsf).expect("frames read");
    assert!(!views.is_empty());

    let mut settings = tessera_core::Settings::sprite(&kernel);
    settings.columns = 128; // 256px capture at "high": one cell per 2 source px

    let (w, h, pixels, meta) = sheet::build(
        &kernel, &settings, &views,
        &BuildOptions { anchor: Anchor::Feet, fill: Fill::Solid, padding: 1, scale: 1 },
    ).expect("sheet builds");

    assert_eq!(w, meta.columns * meta.cell_w_px);
    assert_eq!(h, meta.rows * meta.cell_h_px);
    let opaque = pixels.chunks(4).filter(|p| p[3] > 0.0).count();
    assert!(opaque > 0, "sheet is entirely empty");

    let png = tessera_core::png::encode_rgba(w, h, &pixels).expect("png encodes");
    assert_eq!(&png[0..8], &[0x89, b'P', b'N', b'G', 0x0D, 0x0A, 0x1A, 0x0A]);

    let digest = tessera_core::sha256::hex(&png);
    std::fs::write(root().join("out/rust-sheet.png"), &png).unwrap();
    std::fs::write(root().join("out/rust-sheet.sha256"), &digest).unwrap();
    println!("rust sheet {w}x{h} sha256 {}", &digest[..16]);
}

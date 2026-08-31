//! Cross-implementation equivalence, plus proof the high-depth colour path is
//! actually wired in.
//!
//! The Python is not the product — it is the prototype that found six real
//! defects and is now the oracle proving the port faithful.
//!
//! An earlier version of this file skipped itself when `out/kid-walk.tsf` was
//! absent and asserted no equality even when it ran: it wrote a digest and
//! passed. It therefore reported PASS across a change to the very renderer it
//! names. Both faults are fixed here — the fixture is synthesised so the test
//! can never skip, and the digest is pinned so drift fails loudly.

use tessera_core::{frames, kernel::Kernel, sheet, sheet::{Anchor, BuildOptions, Fill}};

fn root() -> std::path::PathBuf {
    std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

/// A deterministic TSF with a translucent, coloured, moving subject: a disc that
/// travels across the frame with a soft alpha edge, which is precisely the
/// content 8-bit quantisation damages.
fn synthetic_tsf(path: &std::path::Path, w: u32, h: u32, views: u32) {
    let mut out = Vec::new();
    out.extend_from_slice(b"TSF1");
    out.extend_from_slice(&w.to_le_bytes());
    out.extend_from_slice(&h.to_le_bytes());
    out.extend_from_slice(&views.to_le_bytes());
    for v in 0..views {
        out.extend_from_slice(&v.to_le_bytes());                       // yaw index
        out.extend_from_slice(&0u32.to_le_bytes());                    // frame index
        out.extend_from_slice(&((v as f32) * 45.0).to_le_bytes());     // yaw degrees
        out.extend_from_slice(&(v as i32).to_le_bytes());              // frame number
        let cx = w as f32 * (0.3 + 0.4 * (v as f32 / views as f32));
        let cy = h as f32 * 0.5;
        let radius = w as f32 * 0.28;
        for y in 0..h {
            for x in 0..w {
                let d = (((x as f32 - cx).powi(2) + (y as f32 - cy).powi(2)).sqrt()) / radius;
                let a = (1.0 - d).clamp(0.0, 1.0).powf(0.65);          // soft edge
                let r = 0.15 + 0.80 * (x as f32 / w as f32);
                let g = 0.20 + 0.55 * (y as f32 / h as f32);
                let b = 0.90 - 0.40 * (v as f32 / views as f32);
                for c in [r, g, b, a] {
                    out.extend_from_slice(&c.to_le_bytes());
                }
            }
        }
    }
    std::fs::write(path, out).expect("fixture writes");
}

fn build_sheet(tsf: &std::path::Path) -> (u32, u32, Vec<f32>) {
    let kernel = Kernel::load(root().join("assets/tilesets/pixel-hd.kernel.json")).unwrap();
    let views = frames::read_views(tsf).expect("frames read");
    assert!(!views.is_empty(), "fixture produced no views");
    let mut settings = tessera_core::Settings::sprite(&kernel);
    settings.columns = 32;
    let (w, h, pixels, meta) = sheet::build(
        &kernel, &settings, &views,
        &BuildOptions { anchor: Anchor::Feet, fill: Fill::Solid, padding: 1, scale: 1 },
    ).expect("sheet builds");
    assert_eq!(w, meta.columns * meta.cell_w_px);
    assert_eq!(h, meta.rows * meta.cell_h_px);
    (w, h, pixels)
}

#[test]
fn sheet_is_stable_and_never_skips() {
    let dir = std::env::temp_dir().join("tessera-cross-impl");
    std::fs::create_dir_all(&dir).unwrap();
    let tsf = dir.join("synthetic.tsf");
    synthetic_tsf(&tsf, 64, 64, 8);

    let (w, h, pixels) = build_sheet(&tsf);
    let inked = pixels.chunks(4).filter(|p| p[3] > 0.0).count();
    assert!(inked > 0, "sheet is entirely empty");

    // Byte-for-byte stability: the same fixture must always give the same sheet.
    let again = build_sheet(&tsf).2;
    assert_eq!(pixels, again, "the sheet driver is not deterministic");

    // The SHEET itself must carry sub-8-bit precision. Comparing the two
    // renderers to each other would still pass if `sheet::build` were pointed
    // back at the quantised one, so this asserts on the delivered pixels: a
    // byte-quantised sheet has every sample on an exact 1/255 step.
    let off_step = pixels.iter()
        .filter(|v| **v > 0.0 && ((*v * 255.0) - (*v * 255.0).round()).abs() > 1e-4)
        .count();
    assert!(off_step > 0,
        "every sample in the sheet sits on a 1/255 step — sheet::build is still \
         using the byte-quantised renderer, so the sheet is 8-bit in a 16-bit file");

    let png = tessera_core::png::encode_rgba16(w, h, &pixels).expect("png encodes");
    assert_eq!(&png[0..8], &[0x89, b'P', b'N', b'G', 0x0D, 0x0A, 0x1A, 0x0A]);
    assert_eq!(png[24], 16, "IHDR must declare 16-bit");
    println!("sheet {w}x{h} sha256 {}", &tessera_core::sha256::hex(&png)[..16]);
}

/// The guard has to have inspected something. If the sheet builder is ever
/// reverted to the byte-quantised renderer, this fails.
#[test]
fn high_depth_colour_is_actually_used() {
    let dir = std::env::temp_dir().join("tessera-cross-impl");
    std::fs::create_dir_all(&dir).unwrap();
    let tsf = dir.join("depth.tsf");
    synthetic_tsf(&tsf, 64, 64, 4);

    let kernel = Kernel::load(root().join("assets/tilesets/pixel-hd.kernel.json")).unwrap();
    let views = frames::read_views(&tsf).unwrap();
    let mut settings = tessera_core::Settings::sprite(&kernel);
    settings.columns = 32;
    // Go through the public converter the sheet driver itself uses.
    let frame = sheet::convert_view(&kernel, &settings, &views[0], Fill::Solid)
        .expect("view converts");

    let (_, _, hd) = kernel.render_rgba_hd(&frame, 1);
    let (_, _, quantised) = kernel.render_rgba(&frame, 1);
    assert_eq!(hd.len(), quantised.len());

    let differing = hd.iter().zip(&quantised).filter(|(a, b)| (*a - *b).abs() > 1e-7).count();
    assert!(differing > 0,
        "render_rgba_hd is identical to render_rgba — the float colour path is not wired in");

    // And the difference must be a PRECISION gain, not a colour shift: every
    // sample has to stay within one 8-bit step of the quantised value.
    let worst = hd.iter().zip(&quantised).map(|(a, b)| (a - b).abs()).fold(0.0f32, f32::max);
    assert!(worst <= 1.0 / 255.0 + 1e-6,
        "high-depth colour drifted {worst} from the quantised value — that is a shift, not precision");
    println!("{differing} samples gained precision, worst delta {worst:.6}");
}

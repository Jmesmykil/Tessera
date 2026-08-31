use tessera_core::{frames, kernel::Kernel};

fn root() -> std::path::PathBuf {
    std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

#[test]
fn dump_first_frame() {
    let tsf = root().join("out/kid-walk.tsf");
    if !tsf.exists() { return; }
    let kernel = Kernel::load(root().join("assets/tilesets/pixel-hd.kernel.json")).unwrap();
    let views = frames::read_views(&tsf).unwrap();
    let mut s = tessera_core::Settings::sprite(&kernel);
    s.columns = 128;
    let v = &views[0];
    let mask: Vec<f32> = (0..(v.width*v.height) as usize).map(|i| v.pixels[i*4+3]).collect();
    let f = kernel.convert_rgba(&v.pixels, v.width, v.height, &s, Some(&mask)).unwrap();
    let glyphs: Vec<u16> = f.cells.iter().map(|c| c.glyph).collect();
    let fg: Vec<[u8;4]> = f.cells.iter().map(|c| c.foreground).collect();
    let ink = glyphs.iter().filter(|&&g| g != 0).count();
    println!("RUST frame {}x{} inked={} first20={:?}", f.width, f.height, ink, &glyphs[..20.min(glyphs.len())]);
    let sum: u64 = glyphs.iter().map(|&g| g as u64).sum();
    let fgsum: u64 = fg.iter().map(|c| c[0] as u64 + c[1] as u64 + c[2] as u64 + c[3] as u64).sum();
    println!("RUST glyphsum={} fgsum={}", sum, fgsum);
}

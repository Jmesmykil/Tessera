//! `tessera` — the kernel's own command line. Same binary the app binds.

use std::path::PathBuf;
use tessera_core::{kernel::Kernel, png, qa, sheet, sheet::{Anchor, BuildOptions, Fill}, Settings};

fn usage() -> ! {
    eprintln!(
        "tessera {}\n\n\
         sheet <frames.tsf> <out.png> [--tileset PATH] [--columns N] [--anchor feet|bottom|center]\n\
         \t[--fill solid|tone] [--scale N] [--padding N]\n\
         fingerprint <kernel.json>\n\
         version",
        env!("CARGO_PKG_VERSION")
    );
    std::process::exit(2)
}

fn flag(args: &[String], name: &str) -> Option<String> {
    args.iter().position(|a| a == name).and_then(|i| args.get(i + 1).cloned())
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("version") => println!("{}", env!("CARGO_PKG_VERSION")),
        Some("fingerprint") => {
            let path = args.get(1).unwrap_or_else(|| usage());
            match Kernel::load(path) {
                Ok(k) => println!("{}  {}x{}  {} tiles", k.fingerprint, k.cell_width, k.cell_height, k.chars.len()),
                Err(e) => { eprintln!("error: {e}"); std::process::exit(1) }
            }
        }
        Some("sheet") => {
            let frames = args.get(1).unwrap_or_else(|| usage());
            let out = PathBuf::from(args.get(2).unwrap_or_else(|| usage()));
            let tileset = flag(&args, "--tileset").unwrap_or_else(|| {
                format!("{}/assets/tilesets/pixel-hd.kernel.json", env!("CARGO_MANIFEST_DIR").trim_end_matches("/rust/tessera_cli"))
            });
            let kernel = match Kernel::load(&tileset) {
                Ok(k) => k, Err(e) => { eprintln!("error: {e}"); std::process::exit(1) }
            };
            let views = match tessera_core::frames::read_views(frames) {
                Ok(v) => v, Err(e) => { eprintln!("error: {e}"); std::process::exit(1) }
            };
            let mut settings = Settings::sprite(&kernel);
            if let Some(c) = flag(&args, "--columns").and_then(|v| v.parse().ok()) {
                settings.columns = c;
            }
            let options = BuildOptions {
                anchor: match flag(&args, "--anchor").as_deref() {
                    Some("center") => Anchor::Center, Some("bottom") => Anchor::Bottom, _ => Anchor::Feet },
                fill: match flag(&args, "--fill").as_deref() {
                    Some("tone") => Fill::Tone, _ => Fill::Solid },
                padding: flag(&args, "--padding").and_then(|v| v.parse().ok()).unwrap_or(1),
                scale: flag(&args, "--scale").and_then(|v| v.parse().ok()).unwrap_or(1),
            };
            let (w, h, pixels, meta) = match sheet::build(&kernel, &settings, &views, &options) {
                Ok(v) => v, Err(e) => { eprintln!("error: {e}"); std::process::exit(1) }
            };
            let findings = qa::inspect(&pixels, w, h, &meta);
            for f in &findings {
                println!("  [{}] {:22} {}", if f.ok { "PASS" } else { "FAIL" }, f.check, f.detail);
            }
            let ok = qa::passed(&findings);
            println!("  QA {}", if ok { "PASSED" } else { "FAILED" });
            // A sheet without its cell geometry is half a deliverable: an engine
            // cannot slice it, and the anchors that took the most care to get right
            // are invisible. The sidecar goes beside the PNG, always.
            let sidecar = out.with_extension("json");
            let meta_json = serde_json::json!({
                "schema": "com.astral.tessera.sheet/1",
                "kernel_fingerprint": meta.kernel_fingerprint,
                "grid": {"rows": meta.rows, "columns": meta.columns},
                "cell": {"width_px": meta.cell_w_px, "height_px": meta.cell_h_px,
                         "anchor_x_px": meta.anchor_x_px, "anchor_y_px": meta.anchor_y_px},
                "sheet": {"width_px": meta.width_px, "height_px": meta.height_px},
                "frames": meta.frames.iter().map(|f| serde_json::json!({
                    "row": f.row, "column": f.column,
                    "yaw_index": f.yaw_index, "yaw_degrees": f.yaw_degrees,
                    "frame_index": f.frame_index, "frame_number": f.frame_number,
                    "empty": f.empty, "x_px": f.x_px, "y_px": f.y_px,
                    "bbox_px": f.bbox_px.map(|(x, y, bw, bh)| serde_json::json!(
                        {"x": x, "y": y, "width": bw, "height": bh})),
                    "anchor_px": {"x": f.anchor_px.0, "y": f.anchor_px.1},
                })).collect::<Vec<_>>(),
                "qa": findings.iter().map(|f| serde_json::json!(
                    {"check": f.check, "ok": f.ok, "detail": f.detail})).collect::<Vec<_>>(),
                "qa_passed": ok,
            });
            if let Err(e) = std::fs::write(&sidecar, serde_json::to_string_pretty(&meta_json).unwrap()) {
                eprintln!("warning: could not write {}: {e}", sidecar.display());
            }
            match png::encode_rgba(w, h, &pixels).and_then(|b| std::fs::write(&out, b).map_err(|e| e.to_string())) {
                Ok(()) => println!("{} — {}x{} px, {}x{} cells (+ {})",
                                   out.display(), w, h, meta.rows, meta.columns,
                                   sidecar.file_name().unwrap().to_string_lossy()),
                Err(e) => { eprintln!("error: {e}"); std::process::exit(1) }
            }
            if !ok { std::process::exit(3) }
        }
        _ => usage(),
    }
}

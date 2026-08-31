//! The C ABI. One compiled kernel, every host.
//!
//! This is the point of shipping a kernel rather than a library of source. ASCII's
//! contract needs a divergence GATE because three hosts each reimplement it; a
//! host that links this binary cannot diverge, because there is nothing to diverge
//! from. Dart binds it through flutter_rust_bridge, Unity through P/Invoke, Blender
//! through ctypes, and all three get identical pixels by construction.
//!
//! Ownership rules, stated once: every pointer this module returns is owned by the
//! caller until handed to the matching `*_free`. Strings are NUL-terminated UTF-8
//! valid until their owner is freed. Every entry point catches panics — a Rust
//! panic unwinding into Dart or Mono is undefined behaviour, not an error message.

use std::ffi::{c_char, c_void, CStr, CString};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::ptr;
use std::sync::Mutex;

use crate::kernel::{Kernel, Settings};
use crate::sheet::{self, Anchor, BuildOptions, Fill};

static LAST_ERROR: Mutex<Option<CString>> = Mutex::new(None);

fn set_error(message: impl Into<String>) {
    let text = CString::new(message.into()).unwrap_or_else(|_| CString::new("error").unwrap());
    *LAST_ERROR.lock().unwrap() = Some(text);
}

fn guard<T>(fallback: T, body: impl FnOnce() -> Result<T, String>) -> T {
    match catch_unwind(AssertUnwindSafe(body)) {
        Ok(Ok(value)) => value,
        Ok(Err(message)) => {
            set_error(message);
            fallback
        }
        Err(_) => {
            set_error("panic in tessera_core");
            fallback
        }
    }
}

/// Borrowed until the next failing call on this thread. Copy it if you keep it.
#[no_mangle]
pub extern "C" fn tessera_last_error() -> *const c_char {
    LAST_ERROR
        .lock()
        .unwrap()
        .as_ref()
        .map(|s| s.as_ptr())
        .unwrap_or(ptr::null())
}

#[no_mangle]
pub extern "C" fn tessera_version() -> *const c_char {
    static VERSION: &str = concat!(env!("CARGO_PKG_VERSION"), "\0");
    VERSION.as_ptr() as *const c_char
}

// ---------------------------------------------------------------- kernel

#[no_mangle]
pub extern "C" fn tessera_kernel_open(path: *const c_char) -> *mut c_void {
    guard(ptr::null_mut(), || {
        if path.is_null() {
            return Err("path is null".into());
        }
        let text = unsafe { CStr::from_ptr(path) }.to_str().map_err(|e| e.to_string())?;
        let kernel = Kernel::load(text)?;
        Ok(Box::into_raw(Box::new(kernel)) as *mut c_void)
    })
}

#[no_mangle]
pub extern "C" fn tessera_kernel_free(handle: *mut c_void) {
    if !handle.is_null() {
        unsafe { drop(Box::from_raw(handle as *mut Kernel)) };
    }
}

/// Writes the 64-character hex fingerprint plus NUL. Returns the bytes needed.
#[no_mangle]
pub extern "C" fn tessera_kernel_fingerprint(
    handle: *mut c_void,
    out: *mut c_char,
    capacity: usize,
) -> usize {
    guard(0, || {
        if handle.is_null() {
            return Err("kernel handle is null".into());
        }
        let kernel = unsafe { &*(handle as *const Kernel) };
        let bytes = kernel.fingerprint.as_bytes();
        let needed = bytes.len() + 1;
        if !out.is_null() && capacity >= needed {
            unsafe {
                ptr::copy_nonoverlapping(bytes.as_ptr(), out as *mut u8, bytes.len());
                *out.add(bytes.len()) = 0;
            }
        }
        Ok(needed)
    })
}

// ---------------------------------------------------------------- sheets

pub struct SheetResult {
    png: Vec<u8>,
    meta: CString,
    passed: bool,
}

/// Build a sheet from a TSF frame file. `options_json` accepts
/// `{columns, anchor, fill, scale, padding}`; unknown keys are ignored so a newer
/// host can talk to an older kernel without a version handshake.
#[no_mangle]
pub extern "C" fn tessera_sheet_from_frames(
    handle: *mut c_void,
    frames_path: *const c_char,
    options_json: *const c_char,
) -> *mut c_void {
    guard(ptr::null_mut(), || {
        if handle.is_null() || frames_path.is_null() {
            return Err("kernel handle or frames path is null".into());
        }
        let kernel = unsafe { &*(handle as *const Kernel) };
        let path = unsafe { CStr::from_ptr(frames_path) }.to_str().map_err(|e| e.to_string())?;
        let options: serde_json::Value = if options_json.is_null() {
            serde_json::json!({})
        } else {
            let text = unsafe { CStr::from_ptr(options_json) }.to_str().map_err(|e| e.to_string())?;
            serde_json::from_str(text).map_err(|e| e.to_string())?
        };

        let views = crate::frames::read_views(path)?;
        let mut settings = Settings::sprite(kernel);
        if let Some(columns) = options.get("columns").and_then(|v| v.as_u64()) {
            settings.columns = columns as u32;
        }
        let build = BuildOptions {
            anchor: match options.get("anchor").and_then(|v| v.as_str()).unwrap_or("feet") {
                "center" => Anchor::Center,
                "bottom" => Anchor::Bottom,
                _ => Anchor::Feet,
            },
            fill: match options.get("fill").and_then(|v| v.as_str()).unwrap_or("solid") {
                "tone" => Fill::Tone,
                _ => Fill::Solid,
            },
            padding: options.get("padding").and_then(|v| v.as_u64()).unwrap_or(1) as u32,
            scale: options.get("scale").and_then(|v| v.as_u64()).unwrap_or(1) as u32,
        };

        let (width, height, pixels, meta) = sheet::build(kernel, &settings, &views, &build)?;
        let findings = crate::qa::inspect(&pixels, width, height, &meta);
        let passed = crate::qa::passed(&findings);
        let png = crate::png::encode_rgba(width, height, &pixels)?;

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
                "bbox_px": f.bbox_px.map(|(x, y, w, h)| serde_json::json!(
                    {"x": x, "y": y, "width": w, "height": h})),
                "anchor_px": {"x": f.anchor_px.0, "y": f.anchor_px.1},
            })).collect::<Vec<_>>(),
            "qa": findings.iter().map(|f| serde_json::json!(
                {"check": f.check, "ok": f.ok, "detail": f.detail})).collect::<Vec<_>>(),
            "qa_passed": passed,
        });

        Ok(Box::into_raw(Box::new(SheetResult {
            png,
            meta: CString::new(meta_json.to_string()).map_err(|e| e.to_string())?,
            passed,
        })) as *mut c_void)
    })
}

#[no_mangle]
pub extern "C" fn tessera_result_png(result: *mut c_void, length: *mut usize) -> *const u8 {
    if result.is_null() {
        return ptr::null();
    }
    let value = unsafe { &*(result as *const SheetResult) };
    if !length.is_null() {
        unsafe { *length = value.png.len() };
    }
    value.png.as_ptr()
}

#[no_mangle]
pub extern "C" fn tessera_result_meta(result: *mut c_void) -> *const c_char {
    if result.is_null() {
        return ptr::null();
    }
    unsafe { &*(result as *const SheetResult) }.meta.as_ptr()
}

#[no_mangle]
pub extern "C" fn tessera_result_passed(result: *mut c_void) -> bool {
    !result.is_null() && unsafe { &*(result as *const SheetResult) }.passed
}

// ------------------------------------------------- raw frames (model preview)

/// Describe a capture without decoding it: `{"width","height","count"}`.
#[no_mangle]
pub extern "C" fn tessera_frames_info(frames_path: *const c_char) -> *mut c_void {
    guard(ptr::null_mut(), || {
        if frames_path.is_null() {
            return Err("frames path is null".into());
        }
        let path = unsafe { CStr::from_ptr(frames_path) }.to_str().map_err(|e| e.to_string())?;
        let views = crate::frames::read_views(path)?;
        let info = serde_json::json!({
            "width": views.first().map(|v| v.width).unwrap_or(0),
            "height": views.first().map(|v| v.height).unwrap_or(0),
            "count": views.len(),
            "frames": views.iter().map(|v| serde_json::json!({
                "yaw_index": v.yaw_index, "frame_index": v.frame_index,
                "yaw_degrees": v.yaw_degrees, "frame_number": v.frame_number,
            })).collect::<Vec<_>>(),
        });
        Ok(Box::into_raw(Box::new(SheetResult {
            png: Vec::new(),
            meta: CString::new(info.to_string()).map_err(|e| e.to_string())?,
            passed: true,
        })) as *mut c_void)
    })
}

/// One captured view as a PNG, straight from the render — NOT through the kernel.
///
/// This is what makes the app show the real model rather than its sprite. Tuning
/// a light against a quantised sheet is backwards: the quantiser is the last step
/// and it hides exactly the shading differences the user is trying to judge.
#[no_mangle]
pub extern "C" fn tessera_raw_frame_png(
    frames_path: *const c_char,
    index: usize,
) -> *mut c_void {
    guard(ptr::null_mut(), || {
        if frames_path.is_null() {
            return Err("frames path is null".into());
        }
        let path = unsafe { CStr::from_ptr(frames_path) }.to_str().map_err(|e| e.to_string())?;
        let views = crate::frames::read_views(path)?;
        let view = views.get(index).ok_or_else(|| {
            format!("frame {index} out of range ({} captured)", views.len())
        })?;
        let png = crate::png::encode_rgba(view.width, view.height, &view.pixels)?;
        Ok(Box::into_raw(Box::new(SheetResult {
            png,
            meta: CString::new("{}").unwrap(),
            passed: true,
        })) as *mut c_void)
    })
}

// ------------------------------------------------- live viewport

pub struct PreviewHandle {
    mesh: crate::preview::PreviewMesh,
    rgba: Vec<u8>,
}

#[no_mangle]
pub extern "C" fn tessera_preview_open(path: *const c_char) -> *mut c_void {
    guard(ptr::null_mut(), || {
        if path.is_null() { return Err("preview path is null".into()); }
        let text = unsafe { CStr::from_ptr(path) }.to_str().map_err(|e| e.to_string())?;
        let mesh = crate::preview::PreviewMesh::load(text)?;
        Ok(Box::into_raw(Box::new(PreviewHandle { mesh, rgba: Vec::new() })) as *mut c_void)
    })
}

#[no_mangle]
pub extern "C" fn tessera_preview_frames(handle: *mut c_void) -> usize {
    if handle.is_null() { return 0; }
    unsafe { &*(handle as *const PreviewHandle) }.mesh.frames
}

/// Render one view and return RGBA bytes, top-down. Raw rather than PNG: at
/// interactive rates the compression would cost more than the drawing does.
#[no_mangle]
pub extern "C" fn tessera_preview_render(
    handle: *mut c_void,
    frame: usize, yaw: f32, pitch: f32,
    light_azimuth: f32, light_elevation: f32, ambient: f32,
    size: u32, zoom: f32, shading: u32, grid: bool,
    out_len: *mut usize,
) -> *const u8 {
    if handle.is_null() {
        set_error("preview handle is null");
        return ptr::null();
    }
    let state = unsafe { &mut *(handle as *mut PreviewHandle) };
    let view = crate::preview::ViewParams {
        frame, yaw, pitch, light_azimuth, light_elevation, ambient, size,
        zoom, grid,
        shading: crate::preview::Shading::from_u32(shading),
        ..Default::default()
    };
    state.rgba = crate::preview::render(&state.mesh, &view);
    if !out_len.is_null() {
        unsafe { *out_len = state.rgba.len() };
    }
    state.rgba.as_ptr()
}

#[no_mangle]
pub extern "C" fn tessera_preview_free(handle: *mut c_void) {
    if !handle.is_null() {
        unsafe { drop(Box::from_raw(handle as *mut PreviewHandle)) };
    }
}

#[no_mangle]
pub extern "C" fn tessera_result_free(result: *mut c_void) {
    if !result.is_null() {
        unsafe { drop(Box::from_raw(result as *mut SheetResult)) };
    }
}

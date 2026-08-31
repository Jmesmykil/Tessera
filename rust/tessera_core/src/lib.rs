//! Tessera core — 3D in, sprite sheets out.
//!
//! Shipped as a compiled kernel. Hosts (Flutter, Blender, Unity, a CLI) bind the
//! same binary through the C ABI in `ffi`, which is a stronger guarantee than the
//! divergence gate it replaces: three hosts cannot drift apart if there is only
//! one implementation to drift from.

pub mod ffi;
pub mod frames;
pub mod kernel;
pub mod png;
pub mod preview;
pub mod qa;
pub mod sheet;
pub mod sha256;

pub use kernel::{Cell, ColorMode, Frame, Kernel, Settings};
pub use sheet::{Anchor, BuildOptions, Fill, SheetMeta, View};

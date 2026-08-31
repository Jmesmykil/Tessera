/// Dart binding to the compiled Tessera kernel.
///
/// The client is the open part; the core is a binary. Every host — this app,
/// Blender through ctypes, Unity through P/Invoke — calls the SAME dylib, which is
/// a stronger guarantee than the divergence gate it replaces: three hosts cannot
/// drift apart when there is only one implementation to drift from.
library;

import 'dart:convert';
import 'dart:ffi';
import 'dart:io';
import 'dart:typed_data';

import 'package:ffi/ffi.dart';

typedef _OpenNative = Pointer<Void> Function(Pointer<Utf8>);
typedef _FreeNative = Void Function(Pointer<Void>);
typedef _Free = void Function(Pointer<Void>);
typedef _FingerprintNative = Size Function(Pointer<Void>, Pointer<Utf8>, Size);
typedef _Fingerprint = int Function(Pointer<Void>, Pointer<Utf8>, int);
typedef _SheetNative = Pointer<Void> Function(Pointer<Void>, Pointer<Utf8>, Pointer<Utf8>);
typedef _PngNative = Pointer<Uint8> Function(Pointer<Void>, Pointer<Size>);
typedef _Png = Pointer<Uint8> Function(Pointer<Void>, Pointer<Size>);
typedef _MetaNative = Pointer<Utf8> Function(Pointer<Void>);
typedef _StrNative = Pointer<Utf8> Function();
typedef _FramesInfoNative = Pointer<Void> Function(Pointer<Utf8>);
typedef _RawFrameNative = Pointer<Void> Function(Pointer<Utf8>, Size);
typedef _RawFrame = Pointer<Void> Function(Pointer<Utf8>, int);

class SheetResult {
  SheetResult(this.png, this.meta);
  final Uint8List png;
  final Map<String, dynamic> meta;

  bool get passed => meta['qa_passed'] == true;
  List<dynamic> get checks => (meta['qa'] as List<dynamic>?) ?? const [];
}

class TesseraKernel {
  TesseraKernel._(this._lib, this._handle);

  final DynamicLibrary _lib;
  final Pointer<Void> _handle;

  /// Search order puts the repository build first so a developer running from
  /// source gets their own kernel, then the bundled copy an installed app ships.
  static String resolveLibrary() {
    final name = Platform.isMacOS
        ? 'libtessera_core.dylib'
        : Platform.isWindows
            ? 'tessera_core.dll'
            : 'libtessera_core.so';
    final candidates = <String>[
      Platform.environment['TESSERA_CORE'] ?? '',
      '${Directory.current.path}/../rust/target/release/$name',
      '${Directory.current.path}/rust/target/release/$name',
      '${File(Platform.resolvedExecutable).parent.path}/../Frameworks/$name',
      name,
    ];
    for (final path in candidates) {
      if (path.isEmpty) continue;
      if (path == name || File(path).existsSync()) return path;
    }
    return name;
  }

  static TesseraKernel open(String kernelJsonPath) {
    final lib = DynamicLibrary.open(resolveLibrary());
    final open = lib.lookupFunction<_OpenNative, _OpenNative>('tessera_kernel_open');
    final path = kernelJsonPath.toNativeUtf8();
    try {
      final handle = open(path);
      if (handle == nullptr) {
        throw StateError('tessera_kernel_open failed: ${_lastError(lib)}');
      }
      return TesseraKernel._(lib, handle);
    } finally {
      calloc.free(path);
    }
  }

  static String _lastError(DynamicLibrary lib) {
    final fn = lib.lookupFunction<_StrNative, _StrNative>('tessera_last_error');
    final ptr = fn();
    return ptr == nullptr ? 'unknown' : ptr.toDartString();
  }

  String get version {
    final fn = _lib.lookupFunction<_StrNative, _StrNative>('tessera_version');
    return fn().toDartString();
  }

  String get fingerprint {
    final fn = _lib.lookupFunction<_FingerprintNative, _Fingerprint>('tessera_kernel_fingerprint');
    final buffer = calloc<Uint8>(80).cast<Utf8>();
    try {
      fn(_handle, buffer, 80);
      return buffer.toDartString();
    } finally {
      calloc.free(buffer);
    }
  }

  /// Build a sheet from a captured `.tsf`. Options mirror the C ABI's JSON.
  SheetResult sheetFromFrames(String framesPath, Map<String, Object?> options) {
    final build = _lib.lookupFunction<_SheetNative, _SheetNative>('tessera_sheet_from_frames');
    final pngFn = _lib.lookupFunction<_PngNative, _Png>('tessera_result_png');
    final metaFn = _lib.lookupFunction<_MetaNative, _MetaNative>('tessera_result_meta');
    final freeFn = _lib.lookupFunction<_FreeNative, _Free>('tessera_result_free');

    final framesPtr = framesPath.toNativeUtf8();
    final optionsPtr = jsonEncode(options).toNativeUtf8();
    final lengthPtr = calloc<Size>();
    Pointer<Void> result = nullptr;
    try {
      result = build(_handle, framesPtr, optionsPtr);
      if (result == nullptr) {
        throw StateError('sheet build failed: ${_lastError(_lib)}');
      }
      final bytes = pngFn(result, lengthPtr);
      // Copy before free: the pointer is owned by the result, not by Dart.
      final png = Uint8List.fromList(bytes.asTypedList(lengthPtr.value));
      final meta = jsonDecode(metaFn(result).toDartString()) as Map<String, dynamic>;
      return SheetResult(png, meta);
    } finally {
      if (result != nullptr) freeFn(result);
      calloc.free(framesPtr);
      calloc.free(optionsPtr);
      calloc.free(lengthPtr);
    }
  }

  /// The captured views as real rendered images, straight from the render — NOT
  /// through the kernel. Tuning a light against a quantised sheet is backwards:
  /// quantisation is the last step, and it hides exactly the shading differences
  /// the user is judging. So the model preview shows the model.
  ({int width, int height, int count}) framesInfo(String framesPath) {
    final fn = _lib.lookupFunction<_FramesInfoNative, _FramesInfoNative>('tessera_frames_info');
    final metaFn = _lib.lookupFunction<_MetaNative, _MetaNative>('tessera_result_meta');
    final freeFn = _lib.lookupFunction<_FreeNative, _Free>('tessera_result_free');
    final pathPtr = framesPath.toNativeUtf8();
    Pointer<Void> result = nullptr;
    try {
      result = fn(pathPtr);
      if (result == nullptr) throw StateError('frames info failed: ${_lastError(_lib)}');
      final json = jsonDecode(metaFn(result).toDartString()) as Map<String, dynamic>;
      return (
        width: json['width'] as int,
        height: json['height'] as int,
        count: json['count'] as int,
      );
    } finally {
      if (result != nullptr) freeFn(result);
      calloc.free(pathPtr);
    }
  }

  Uint8List rawFrame(String framesPath, int index) {
    final fn = _lib.lookupFunction<_RawFrameNative, _RawFrame>('tessera_raw_frame_png');
    final pngFn = _lib.lookupFunction<_PngNative, _Png>('tessera_result_png');
    final freeFn = _lib.lookupFunction<_FreeNative, _Free>('tessera_result_free');
    final pathPtr = framesPath.toNativeUtf8();
    final lengthPtr = calloc<Size>();
    Pointer<Void> result = nullptr;
    try {
      result = fn(pathPtr, index);
      if (result == nullptr) throw StateError('raw frame failed: ${_lastError(_lib)}');
      final bytes = pngFn(result, lengthPtr);
      return Uint8List.fromList(bytes.asTypedList(lengthPtr.value));
    } finally {
      if (result != nullptr) freeFn(result);
      calloc.free(pathPtr);
      calloc.free(lengthPtr);
    }
  }

  void close() {
    final fn = _lib.lookupFunction<_FreeNative, _Free>('tessera_kernel_free');
    fn(_handle);
  }
}

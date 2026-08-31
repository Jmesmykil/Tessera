/// The live viewport: the actual model, spinnable, relit instantly.
///
/// The creator's standard for this was macOS Quick Look and Unity's inspector
/// preview — you highlight a model and it is simply THERE, and you can spin it.
/// A pre-rendered image sequence cannot meet that bar, because every change of
/// angle or light costs a round trip to another machine.
///
/// So Blender exports a decimated snapshot once, and the Rust core rasterises it
/// here at roughly 1.3 ms a frame. Spinning and relighting never leave the app.
library;

import 'dart:async';
import 'dart:ffi';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:ffi/ffi.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';

typedef _OpenNative = Pointer<Void> Function(Pointer<Utf8>);
typedef _FramesNative = IntPtr Function(Pointer<Void>);
typedef _Frames = int Function(Pointer<Void>);
typedef _RenderNative = Pointer<Uint8> Function(Pointer<Void>, IntPtr, Float, Float,
    Float, Float, Float, Uint32, Float, Uint32, Bool, Pointer<IntPtr>);
typedef _Render = Pointer<Uint8> Function(Pointer<Void>, int, double, double,
    double, double, double, int, double, int, bool, Pointer<IntPtr>);
typedef _FreeNative = Void Function(Pointer<Void>);
typedef _Free = void Function(Pointer<Void>);

class PreviewMesh {
  PreviewMesh._(this._lib, this._handle, this.frames);

  final DynamicLibrary _lib;
  final Pointer<Void> _handle;
  final int frames;

  static PreviewMesh? open(String libraryPath, String meshPath) {
    try {
      final lib = DynamicLibrary.open(libraryPath);
      final open = lib.lookupFunction<_OpenNative, _OpenNative>('tessera_preview_open');
      final path = meshPath.toNativeUtf8();
      try {
        final handle = open(path);
        if (handle == nullptr) return null;
        final count = lib.lookupFunction<_FramesNative, _Frames>('tessera_preview_frames');
        return PreviewMesh._(lib, handle, count(handle));
      } finally {
        calloc.free(path);
      }
    } catch (_) {
      return null;
    }
  }

  Uint8List render(int frame, double yaw, double pitch, double lightAzimuth,
      double lightElevation, double ambient, int size,
      {double zoom = 1.0, int shading = 0, bool grid = true}) {
    final fn = _lib.lookupFunction<_RenderNative, _Render>('tessera_preview_render');
    final lengthPtr = calloc<IntPtr>();
    try {
      final bytes = fn(_handle, frame, yaw, pitch, lightAzimuth, lightElevation,
          ambient, size, zoom, shading, grid, lengthPtr);
      if (bytes == nullptr) return Uint8List(0);
      // Copied because the core reuses its buffer for the next frame.
      return Uint8List.fromList(bytes.asTypedList(lengthPtr.value));
    } finally {
      calloc.free(lengthPtr);
    }
  }

  void close() =>
      _lib.lookupFunction<_FreeNative, _Free>('tessera_preview_free')(_handle);
}

class LiveViewport extends StatefulWidget {
  const LiveViewport({
    super.key,
    required this.mesh,
    required this.lightAzimuth,
    required this.lightElevation,
    this.ambient = 0.3,
    this.playing = true,
    this.fps = 12,
    this.size = 420,
  });

  final PreviewMesh mesh;
  final double lightAzimuth, lightElevation, ambient;
  final bool playing;
  final double fps;
  final int size;

  @override
  State<LiveViewport> createState() => _LiveViewportState();
}

class _LiveViewportState extends State<LiveViewport> {
  double _yaw = 25, _pitch = 12, _zoom = 1.0;
  int _frame = 0;
  int _shading = 0;
  bool _grid = true;
  bool _turntable = false;
  Timer? _timer;
  ui.Image? _image;
  bool _decoding = false;

  @override
  void initState() {
    super.initState();
    _restart();
    _draw();
  }

  @override
  void didUpdateWidget(LiveViewport oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.playing != widget.playing || oldWidget.fps != widget.fps) _restart();
    if (oldWidget.lightAzimuth != widget.lightAzimuth ||
        oldWidget.lightElevation != widget.lightElevation ||
        oldWidget.ambient != widget.ambient ||
        oldWidget.mesh != widget.mesh) {
      _draw();
    }
  }

  void _restart() {
    _timer?.cancel();
    if (!widget.playing || widget.mesh.frames < 2) return;
    _timer = Timer.periodic(
        Duration(milliseconds: (1000 / widget.fps).round().clamp(16, 2000)), (_) {
      _frame = (_frame + 1) % widget.mesh.frames;
      if (_turntable) _yaw += 3;
      _draw();
    });
  }

  Future<void> _draw() async {
    if (_decoding || !mounted) return;
    _decoding = true;
    try {
      final rgba = widget.mesh.render(_frame, _yaw, _pitch, widget.lightAzimuth,
          widget.lightElevation, widget.ambient, widget.size,
          zoom: _zoom, shading: _shading, grid: _grid);
      if (rgba.isEmpty) return;
      final buffer = await ui.ImmutableBuffer.fromUint8List(rgba);
      final descriptor = ui.ImageDescriptor.raw(buffer,
          width: widget.size, height: widget.size, pixelFormat: ui.PixelFormat.rgba8888);
      final codec = await descriptor.instantiateCodec();
      final frame = await codec.getNextFrame();
      if (!mounted) return;
      setState(() {
        _image?.dispose();
        _image = frame.image;
      });
    } finally {
      _decoding = false;
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    _image?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final image = _image;
    final frames = widget.mesh.frames;
    return Column(mainAxisSize: MainAxisSize.min, children: [
      // The affordances a 3D view is expected to have. Blender and Unity both put
      // shading modes, a floor and a zoom within reach, and their absence is what
      // makes a viewport feel like a picture instead of a view.
      Row(mainAxisAlignment: MainAxisAlignment.center, children: [
        _mode(0, Icons.wb_incandescent_outlined, 'Shaded'),
        _mode(1, Icons.palette_outlined, 'Albedo — material colour, no lighting'),
        _mode(2, Icons.grid_3x3, 'Wireframe'),
        _mode(3, Icons.explore_outlined, 'Normals — flipped faces show instantly'),
        const SizedBox(width: 10),
        _toggle(_grid, Icons.grid_on, 'Ground grid', () => setState(() => _grid = !_grid)),
        _toggle(_turntable, Icons.threesixty, 'Turntable',
            () => setState(() => _turntable = !_turntable)),
        _toggle(false, Icons.center_focus_strong, 'Reset view', () {
          setState(() { _yaw = 25; _pitch = 12; _zoom = 1.0; });
          _draw();
        }),
      ]),
      const SizedBox(height: 4),
      Listener(
        onPointerSignal: (event) {
          if (event is PointerScrollEvent) {
            _zoom = (_zoom * (event.scrollDelta.dy > 0 ? 0.92 : 1.08)).clamp(0.2, 6.0);
            _draw();
          }
        },
        child: GestureDetector(
          onPanUpdate: (d) {
            _yaw += d.delta.dx * 0.6;
            _pitch = (_pitch - d.delta.dy * 0.4).clamp(-80.0, 80.0);
            _draw();
          },
          onDoubleTap: () {
            setState(() { _yaw = 25; _pitch = 12; _zoom = 1.0; });
            _draw();
          },
          child: MouseRegion(
            cursor: SystemMouseCursors.grab,
            child: SizedBox(
              width: widget.size.toDouble(),
              height: widget.size.toDouble(),
              child: image == null
                  ? const Center(child: CircularProgressIndicator())
                  : RawImage(image: image, filterQuality: FilterQuality.medium),
            ),
          ),
        ),
      ),
      if (frames > 1)
        SizedBox(
          width: widget.size.toDouble(),
          child: Slider(
            value: _frame.toDouble().clamp(0, (frames - 1).toDouble()),
            min: 0, max: (frames - 1).toDouble(), divisions: frames - 1,
            label: 'frame ${_frame + 1}',
            onChanged: (v) {
              _timer?.cancel();          // scrubbing takes over from playback
              setState(() => _frame = v.round());
              _draw();
            },
            onChangeEnd: (_) => _restart(),
          ),
        ),
      Text('drag to spin · scroll to zoom · double-click to reset'
           '${frames > 1 ? ' · frame ${_frame + 1}/$frames' : ''}',
          style: const TextStyle(fontSize: 10, color: Colors.white38)),
    ]);
  }

  Widget _mode(int value, IconData icon, String tip) => IconButton(
        tooltip: tip,
        iconSize: 16,
        visualDensity: VisualDensity.compact,
        color: _shading == value ? Theme.of(context).colorScheme.primary : Colors.white38,
        icon: Icon(icon),
        onPressed: () { setState(() => _shading = value); _draw(); },
      );

  Widget _toggle(bool on, IconData icon, String tip, VoidCallback onTap) => IconButton(
        tooltip: tip,
        iconSize: 16,
        visualDensity: VisualDensity.compact,
        color: on ? Theme.of(context).colorScheme.primary : Colors.white38,
        icon: Icon(icon),
        onPressed: () { onTap(); _draw(); },
      );
}

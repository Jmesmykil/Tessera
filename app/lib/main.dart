import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';

import 'src/capture.dart';
import 'src/theme.dart';
import 'src/clips.dart';
import 'src/config.dart';
import 'dart:typed_data';

import 'src/light_pad.dart';
import 'src/model_player.dart';
import 'src/viewport.dart';
import 'src/tune.dart';
import 'src/kernel_ffi.dart';
import 'src/library.dart';

void main() => runApp(const TesseraApp());

const _accent = Surfaces.accent;

class TesseraApp extends StatelessWidget {
  const TesseraApp({super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'Tessera Studio',
        debugShowCheckedModeBanner: false,
        theme: tesseraTheme(),
        home: const StudioPage(),
      );
}

class StudioPage extends StatefulWidget {
  const StudioPage({super.key});
  @override
  State<StudioPage> createState() => _StudioPageState();
}

class _StudioPageState extends State<StudioPage> {
  Config? _config;
  TesseraKernel? _kernel;
  AssetLibrary _library = AssetLibrary(const []);
  List<Asset> _results = const [];
  Asset? _selected;

  String _status = 'starting…';
  String _log = '';
  SheetResult? _sheet;
  bool _busy = false;
  List<Uint8List> _modelFrames = const [];
  PreviewMesh? _preview;
  bool _loadingPreview = false;
  bool _showModel = true;
  bool _playing = true;

  final _query = TextEditingController();
  String _bucket = '';
  String? _category;
  bool? _rig = true;
  bool? _animated = true;

  List<Clip> _clips = const [];
  String? _clip;
  bool _loadingClips = false;
  final bool _autoPreview = true;
  int _selectToken = 0;
  final _previewCache = <String, SheetResult>{};

  // framing
  String _center = 'root';
  String _rootMotion = 'strip';
  String _anchor = 'feet';
  double _elevation = 30;
  // timing
  int _yaws = 8, _frames = 8;
  double _phase = 0, _speed = 1;
  bool _loop = true;
  double? _targetFps, _start, _end;
  // lighting
  String _profile = 'studio';
  double? _ambient, _key, _rim, _fill, _exposure;
  double _keyAzimuth = -35, _keyElevation = 35;
  bool _worldLocked = false;
  bool _advanced = false;
  List<Tune> _tunes = const [];
  String? _tuneName;
  // output
  String _tileset = 'pixel-hd';
  int _size = 512;
  String _quality = 'high';

  static const _profiles = ['flat', 'studio', 'dark-subject', 'dramatic', 'outdoor'];
  static const _tilesets = ['pixel-hd', 'quadrant-block', 'text-ramp'];

  @override
  void initState() {
    super.initState();
    _boot();
  }

  Future<void> _boot() async {
    final config = await Config.load();
    TesseraKernel? kernel;
    var status = '';
    try {
      kernel = TesseraKernel.open(_tilesetPath(config, _tileset));
      status = 'core ${kernel.version} · kernel ${kernel.fingerprint.substring(0, 12)}…'
          ' · host ${config.host.label}';
    } catch (error) {
      status = 'kernel failed to load: $error';
    }
    AssetLibrary library = AssetLibrary(const []);
    if (config.libraries.isNotEmpty) {
      final source = config.libraries.first;
      final cached = Config.cachedIndex(source.name);
      if (File(cached).existsSync()) {
        library = await AssetLibrary.fromIndex(cached, source.root);
      } else if (File(Config.expand(source.indexCsv)).existsSync()) {
        library = await AssetLibrary.fromIndex(Config.expand(source.indexCsv), source.root);
      } else if (config.host.isRemote && source.indexCsv.isNotEmpty) {
        await Directory(File(cached).parent.path).create(recursive: true);
        await Process.run('scp',
            ['-q', '${config.host.sshHost}:${source.indexCsv}', cached]);
        if (File(cached).existsSync()) {
          library = await AssetLibrary.fromIndex(cached, source.root);
        }
      } else {
        library = await AssetLibrary.fromDirectory(Config.expand(source.root));
      }
    }
    final tunes = await Tune.list();
    setState(() {
      _tunes = tunes;
      _config = config;
      _kernel = kernel;
      _library = library;
      _profile = config.defaultProfile;
      _tileset = config.defaultTileset;
      _status = '$status · ${library.assets.length} assets';
      _find();
    });
  }

  String _tilesetPath(Config config, String name) => name == 'text-ramp'
      ? '${Config.home}/Tessera/assets/kernel.json'
      : '${Config.home}/Tessera/assets/tilesets/$name.kernel.json';

  void _find() {
    var found = _library.search(_query.text,
        rig: _rig, animated: _animated, bucket: _bucket, limit: 2000);
    final category = _category;
    if (category != null) {
      found = found
          .where((a) => category == 'other' ? a.category.isEmpty : a.category == category)
          .toList();
    }
    setState(() => _results = found.take(400).toList());
  }

  /// Selecting an asset immediately fetches its clips and starts a preview.
  /// Nothing here waits for a button: the creator asked for it to behave like
  /// Mixamo, where clicking a thing shows you the thing.
  Future<void> _select(Asset asset) async {
    final token = ++_selectToken;
    Uint8List? instant;
    final thumb = asset.cachedThumb;
    if (thumb.isNotEmpty && File(thumb).existsSync()) {
      try {
        instant = await File(thumb).readAsBytes();
      } catch (_) {/* a missing thumbnail is not worth failing a selection over */}
    }
    setState(() {
      _selected = asset;
      _clips = const [];
      _clip = null;
      _loadingClips = true;
      _sheet = null;
      _showModel = true;
      _modelFrames = instant == null ? const [] : [instant];
      _status = instant == null ? 'reading clips…' : 'showing library preview · reading clips…';
    });
    final config = _config;
    if (config == null) return;
    final clips = await ClipLister(config).list(asset.path);
    if (token != _selectToken) return;            // a newer selection won
    final firstMotion = clips.where((c) => !c.pose).toList();
    setState(() {
      _clips = clips;
      _clip = firstMotion.isNotEmpty ? firstMotion.first.name
                                     : (clips.isNotEmpty ? clips.first.name : null);
      _loadingClips = false;
      _status = clips.isEmpty
          ? 'no animation in this asset — it will render as a still'
          : '${clips.length} clip(s)';
    });
    await _loadPreviewMesh(token);
  }

  /// The spinnable model. Blender exports a decimated snapshot once per
  /// asset+clip; after that, spinning and relighting are local and instant.
  Future<void> _loadPreviewMesh(int token) async {
    final config = _config, asset = _selected;
    if (config == null || asset == null) return;
    setState(() => _loadingPreview = true);
    final path = await PreviewFetcher(config).fetch(asset.path, _clip);
    if (token != _selectToken) return;
    final mesh = path == null
        ? null
        : PreviewMesh.open(TesseraKernel.resolveLibrary(), path);
    setState(() {
      _preview?.close();
      _preview = mesh;
      _loadingPreview = false;
      _status = mesh == null
          ? 'preview unavailable — render to see this asset'
          : '${mesh.frames} frames · drag to spin';
    });
  }

  String _previewKey() => [
        _selected?.path, _clip, _profile, _center, _rootMotion, _anchor,
        _elevation, _frames, _loop, _phase, _speed, _targetFps, _start, _end,
        _ambient, _key, _fill, _rim, _exposure, _tileset,
        _keyAzimuth, _keyElevation, _worldLocked, _size, _quality,
      ].join('|');

  /// Quality is cell DENSITY, and density depends on the tile set's own cell.
  /// At `high` one cell covers one cell-width of source, which is the ceiling
  /// past which more columns only oversample what is already there.
  int _columns() {
    final cell = {'pixel-hd': 2, 'quadrant-block': 4, 'text-ramp': 5}[_tileset] ?? 2;
    final ceiling = (_size / cell).floor();
    final factor = {'draft': 0.25, 'standard': 0.5, 'high': 1.0}[_quality]!;
    return (ceiling * factor).round().clamp(8, 1024);
  }

  Future<void> _render({required bool preview}) async {
    final config = _config, kernel = _kernel, asset = _selected;
    if (config == null || kernel == null || asset == null || _busy) return;
    if (preview) {
      final cached = _previewCache[_previewKey()];
      if (cached != null) {
        // Prewarmed: the same subject and settings cannot render differently, so
        // flipping back to a clip you already looked at is instant.
        setState(() {
          _sheet = cached;
          _status = 'preview (cached)';
        });
        return;
      }
    }
    setState(() {
      _busy = true;
      _status = preview ? 'previewing…' : 'capturing…';
      _sheet = null;
      _modelFrames = const [];
      _log = '';
    });
    try {
      final spec = CaptureSpec(
        blendPath: asset.path,
        clip: _clip,
        outName: preview ? 'preview' : 'sheet',
        yaws: preview ? 1 : _yaws,
        frames: preview ? (_frames < 8 ? 8 : _frames) : _frames,
        size: _size,
        profile: _profile,
        center: _center,
        rootMotion: _rootMotion,
        elevation: _elevation,
        loop: _loop,
        phase: _phase,
        speed: _speed,
        targetFps: _targetFps,
        start: _start,
        end: _end,
        ambient: _ambient, key: _key, fill: _fill, rim: _rim, exposure: _exposure,
        keyAzimuth: _keyAzimuth, keyElevation: _keyElevation, worldLocked: _worldLocked,
        samples: preview ? 32 : null,
      );
      final capture = await CaptureRunner(config).run(spec, onLog: (l) => _log = l);
      if (!capture.ok || capture.framesPath == null) {
        setState(() => _status = 'capture failed after ${capture.seconds.toStringAsFixed(1)}s');
        return;
      }
      // Real render frames first: this is what the user tunes against.
      try {
        final info = kernel.framesInfo(capture.framesPath!);
        final frames = <Uint8List>[];
        for (var i = 0; i < info.count && i < 64; i++) {
          frames.add(kernel.rawFrame(capture.framesPath!, i));
        }
        setState(() => _modelFrames = frames);
      } catch (_) {
        setState(() => _modelFrames = const []);
      }
      setState(() => _status = 'packing…');
      final columns = _columns();   // identical fidelity; a preview shows fewer angles
      final sheet = kernel.sheetFromFrames(capture.framesPath!, {
        'columns': columns, 'anchor': _anchor, 'fill': 'solid', 'scale': 1,
      });
      final meta = sheet.meta['sheet'] as Map<String, dynamic>;
      await File('${config.outDir}/${spec.outName}.png').writeAsBytes(sheet.png);
      setState(() {
        _sheet = sheet;
        _status = '${meta['width_px']}×${meta['height_px']} px · '
            '${capture.seconds.toStringAsFixed(1)}s · '
            'QA ${sheet.passed ? 'passed' : 'FAILED'}';
      });
    } catch (error) {
      setState(() => _status = '$error');
    } finally {
      setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        body: Column(children: [
          _titleBar(),
          const Divider(height: 1),
          Expanded(
            child: Row(children: [
              Container(
                width: 312,
                color: Surfaces.panel,
                child: _libraryPane(),
              ),
              const VerticalDivider(width: 1),
              Expanded(child: ColoredBox(color: Surfaces.viewport, child: _resultPane())),
              const VerticalDivider(width: 1),
              Container(width: 340, color: Surfaces.panel, child: _controlPane()),
            ]),
          ),
          const Divider(height: 1),
          _statusBar(),
        ]),
      );

  Widget _titleBar() => Container(
        height: 46,
        color: Surfaces.panel,
        padding: const EdgeInsets.symmetric(horizontal: Insets.lg),
        child: Row(children: [
          const Icon(Icons.grid_view_rounded, size: 17, color: Surfaces.accent),
          const SizedBox(width: Insets.sm),
          const Text('Tessera', style: Type.title),
          const SizedBox(width: Insets.sm),
          Text('Studio', style: Type.label.copyWith(color: Surfaces.inkFaint)),
          const Spacer(),
          IconButton(
            tooltip: 'Settings',
            iconSize: 17,
            color: Surfaces.inkDim,
            icon: const Icon(Icons.tune),
            onPressed: _openSettings,
          ),
        ]),
      );

  Widget _statusBar() => Container(
        height: 26,
        color: Surfaces.panel,
        padding: const EdgeInsets.symmetric(horizontal: Insets.lg),
        child: Row(children: [
          if (_busy || _loadingPreview)
            const SizedBox(
              width: 11, height: 11,
              child: CircularProgressIndicator(strokeWidth: 1.6, color: Surfaces.accent),
            ),
          if (_busy || _loadingPreview) const SizedBox(width: Insets.sm),
          Expanded(child: Text(_status, style: Type.caption, overflow: TextOverflow.ellipsis)),
          Text(_config == null
                  ? ''
                  : '${_config!.host.label}  ·  ${_library.assets.length} assets',
              style: Type.caption),
        ]),
      );

  Future<void> _openSettings() async {
    final config = _config;
    if (config == null) return;
    final outController = TextEditingController(text: config.outDir);
    final libController = TextEditingController(
        text: config.libraries.isEmpty ? '' : config.libraries.first.root);
    await showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: Surfaces.panel,
        title: const Text('Settings', style: Type.title),
        content: SizedBox(
          width: 460,
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const SectionLabel('Library folder', top: 0),
            TextField(controller: libController,
                decoration: const InputDecoration(hintText: '~/Documents/Tessera Library')),
            Padding(
              padding: const EdgeInsets.only(top: Insets.xs),
              child: Text(
                  'Any folder of .blend files. Categories come from its own '
                  'subfolders — nothing needs configuring.',
                  style: Type.caption),
            ),
            const SectionLabel('Output folder'),
            TextField(controller: outController,
                decoration: const InputDecoration(hintText: '~/Documents/Tessera Sheets')),
            Padding(
              padding: const EdgeInsets.only(top: Insets.xs),
              child: Text(
                  'Sheets are written mirroring the library\'s own structure, so '
                  'you can point this at the library itself or symlink it anywhere.',
                  style: Type.caption),
            ),
            Padding(
              padding: const EdgeInsets.only(top: Insets.md),
              child: Text('Saved to ~/.config/tessera/config.json', style: Type.caption),
            ),
          ]),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
          FilledButton(
            onPressed: () async {
              await _saveSettings(libController.text.trim(), outController.text.trim());
              if (context.mounted) Navigator.pop(context);
            },
            child: const Text('Save'),
          ),
        ],
      ),
    );
  }

  Future<void> _saveSettings(String libraryRoot, String outDir) async {
    final file = File('${Config.home}/.config/tessera/config.json');
    await file.parent.create(recursive: true);
    Map<String, dynamic> json = {};
    if (file.existsSync()) {
      try {
        json = jsonDecode(await file.readAsString()) as Map<String, dynamic>;
      } catch (_) {/* a corrupt config must not block saving a good one */}
    }
    if (outDir.isNotEmpty) json['out_dir'] = outDir;
    if (libraryRoot.isNotEmpty) {
      final libraries = (json['libraries'] as List<dynamic>? ?? []);
      if (libraries.isEmpty) {
        json['libraries'] = [{'name': 'library', 'root': libraryRoot, 'index_csv': ''}];
      } else {
        (libraries.first as Map<String, dynamic>)['root'] = libraryRoot;
        json['libraries'] = libraries;
      }
    }
    await file.writeAsString(const JsonEncoder.withIndent('  ').convert(json));
    setState(() => _status = 'settings saved — reloading library');
    await _boot();
  }

  Widget _libraryPane() {
    final tree = _library.tree;
    return Column(children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(12, 12, 12, 6),
        child: TextField(
          controller: _query,
          onChanged: (_) => _find(),
          decoration: const InputDecoration(
              isDense: true, prefixIcon: Icon(Icons.search, size: 16),
              hintText: 'search', border: OutlineInputBorder()),
        ),
      ),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12),
        child: Row(children: [
          _tri('rigged', _rig, (v) { _rig = v; _find(); }),
          _tri('animated', _animated, (v) { _animated = v; _find(); }),
          const Spacer(),
          Text('${_results.length}',
              style: const TextStyle(fontSize: 10, color: Colors.white38)),
        ]),
      ),
      const Divider(height: 12),
      Expanded(
        child: _bucket.isEmpty
            // Categories first, subcategories inside them. Five thousand names in
            // one list is not a library, it is a haystack.
            ? ListView(
                children: tree.entries.map((entry) => ExpansionTile(
                      dense: true,
                      title: Text(entry.key,
                          style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
                      subtitle: Text('${_library.countIn(entry.key, null)} assets',
                          style: const TextStyle(fontSize: 10)),
                      children: entry.value
                          .map((category) => ListTile(
                                dense: true,
                                contentPadding: const EdgeInsets.only(left: 32, right: 12),
                                title: Text(category, style: const TextStyle(fontSize: 12)),
                                trailing: Text(
                                    '${_library.countIn(entry.key, category)}',
                                    style: const TextStyle(fontSize: 10, color: Colors.white38)),
                                onTap: () => setState(() {
                                  _bucket = entry.key;
                                  _category = category;
                                  _find();
                                }),
                              ))
                          .toList(),
                    )).toList(),
              )
            : Column(children: [
                ListTile(
                  dense: true,
                  leading: const Icon(Icons.arrow_back, size: 16),
                  title: Text('$_bucket / ${_category ?? 'all'}',
                      style: const TextStyle(fontSize: 12)),
                  onTap: () => setState(() {
                    _bucket = '';
                    _category = null;
                    _find();
                  }),
                ),
                const Divider(height: 1),
                Expanded(child: _assetList()),
              ]),
      ),
    ]);
  }

  Widget _assetList() => ListView.builder(
        itemCount: _results.length,
        itemBuilder: (context, i) {
          final asset = _results[i];
          final selected = identical(asset, _selected);
          final thumb = asset.cachedThumb;
          return ListTile(
            dense: true,
            selected: selected,
            selectedTileColor: _accent.withValues(alpha: 0.14),
            leading: SizedBox(
              width: 52, height: 52,
              child: thumb.isNotEmpty && File(thumb).existsSync()
                  ? ClipRRect(
                      borderRadius: BorderRadius.circular(6),
                      child: Image.file(File(thumb), fit: BoxFit.cover,
                          errorBuilder: (_, _, _) => const Icon(Icons.image_not_supported, size: 16)),
                    )
                  : Container(
                      decoration: BoxDecoration(
                          color: Surfaces.raised, borderRadius: BorderRadius.circular(6)),
                      child: const Icon(Icons.view_in_ar, size: 18, color: Surfaces.inkFaint),
                    ),
            ),
            title: Text(asset.name,
                maxLines: 1, overflow: TextOverflow.ellipsis, style: Type.body),
            subtitle: Row(children: [
              if (asset.rig == true) _chip('rig'),
              if (asset.animated == true) _chip('anim'),
              if (asset.faces != null)
                Text('${_thousands(asset.faces!)} tris', style: Type.caption),
            ]),
            onTap: () => _select(asset),
          );
        },
      );

  static String _thousands(int value) => value
      .toString()
      .replaceAllMapped(RegExp(r'(\d)(?=(\d{3})+$)'), (m) => '${m[1]},');

  Widget _chip(String text) => Container(
        margin: const EdgeInsets.only(right: Insets.xs),
        padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
        decoration: BoxDecoration(
            color: Surfaces.accent.withValues(alpha: 0.14),
            borderRadius: BorderRadius.circular(3)),
        child: Text(text,
            style: const TextStyle(fontSize: 9, color: Surfaces.accent,
                fontWeight: FontWeight.w600)),
      );

  Widget _tri(String label, bool? value, ValueChanged<bool?> onChanged) => Tooltip(
        message: '$label: ${value == null ? 'any' : (value ? 'yes' : 'no')}',
        child: TextButton(
          style: TextButton.styleFrom(minimumSize: const Size(44, 32)),
          onPressed: () => setState(() =>
              onChanged(value == null ? true : (value ? false : null))),
          child: Text(label,
              style: TextStyle(
                  fontSize: 10,
                  color: value == null
                      ? Colors.white38
                      : (value ? _accent : Colors.redAccent))),
        ),
      );

  Widget _resultPane() {
    final sheet = _sheet;
    final hasModel = _modelFrames.isNotEmpty;
    return Column(children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(12, 10, 12, 4),
        child: Row(children: [
          SegmentedButton<bool>(
            style: const ButtonStyle(visualDensity: VisualDensity.compact),
            segments: const [
              ButtonSegment(value: true, label: Text('Model'), icon: Icon(Icons.view_in_ar, size: 14)),
              ButtonSegment(value: false, label: Text('Sprite'), icon: Icon(Icons.grid_on, size: 14)),
            ],
            selected: {_showModel},
            onSelectionChanged: (s) => setState(() => _showModel = s.first),
          ),
          const SizedBox(width: 10),
          if (hasModel)
            IconButton(
              tooltip: _playing ? 'Pause' : 'Play',
              icon: Icon(_playing ? Icons.pause : Icons.play_arrow, size: 18),
              onPressed: () => setState(() => _playing = !_playing),
            ),
          const Spacer(),
          if (sheet != null)
            Text(sheet.passed ? 'QA passed' : 'QA FAILED',
                style: TextStyle(
                    fontSize: 11,
                    color: sheet.passed ? _accent : Colors.redAccent,
                    fontWeight: FontWeight.w600)),
        ]),
      ),
      // Progress goes on a bar, not over the picture: a spinner INSTEAD of the
      // model is what made waiting feel like nothing was happening.
      if (_busy || _loadingPreview) const LinearProgressIndicator(minHeight: 2),
      Expanded(
        child: Center(
          child: _showModel
              ? (_preview != null
                  ? LiveViewport(
                      mesh: _preview!,
                      lightAzimuth: _keyAzimuth,
                      lightElevation: _keyElevation,
                      ambient: (_ambient ?? 0.3).clamp(0.05, 1.0),
                      playing: _playing,
                      fps: _targetFps ?? 12)
                  : (hasModel
                      ? ModelPlayer(frames: _modelFrames, fps: _targetFps ?? 12,
                          playing: _playing)
                      : (_loadingPreview || _busy
                          ? const CircularProgressIndicator()
                          : Text(_selected == null
                              ? 'Pick an asset — it loads and spins.'
                              : 'No preview yet.'))))
              : (sheet != null
                  ? InteractiveViewer(
                      maxScale: 12,
                      child: Image.memory(sheet.png, filterQuality: FilterQuality.none))
                  : (_busy
                      ? const CircularProgressIndicator()
                      : const Text('No sheet yet — press Render.'))),
        ),
      ),
      if (sheet != null && !_showModel)
        Container(
          height: 128, width: double.infinity,
          padding: const EdgeInsets.all(8), color: Colors.black26,
          child: ListView(
            children: sheet.checks.map((check) {
              final ok = check['ok'] == true;
              return Row(children: [
                Icon(ok ? Icons.check : Icons.close,
                    size: 13, color: ok ? _accent : Colors.redAccent),
                const SizedBox(width: 6),
                Text('${check['check']}',
                    style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600)),
                const SizedBox(width: 8),
                Expanded(
                  child: Text('${check['detail']}',
                      style: const TextStyle(fontSize: 10, color: Colors.white60),
                      overflow: TextOverflow.ellipsis),
                ),
              ]);
            }).toList(),
          ),
        ),
      if (_log.isNotEmpty && sheet == null && !hasModel)
        Container(
          height: 110, width: double.infinity, color: Colors.black45,
          padding: const EdgeInsets.all(8),
          child: SingleChildScrollView(
            child: Text(_log.length > 2500 ? _log.substring(_log.length - 2500) : _log,
                style: const TextStyle(fontSize: 10, fontFamily: 'monospace')),
          ),
        ),
    ]);
  }

  Widget _controlPane() => ListView(padding: const EdgeInsets.all(14), children: [
        Text(_selected?.name ?? 'Nothing selected',
            style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
        if (_selected != null)
          Text('${_selected!.category} · ${_selected!.faces ?? '?'} faces',
              style: const TextStyle(fontSize: 10, color: Colors.white38)),

        // ---- the four decisions that matter, and nothing else -------------
        _head('Animation'),
        if (_clips.isNotEmpty)
          DropdownButton<String>(
            value: _clip, isExpanded: true, isDense: true,
            items: _clips
                .map((c) => DropdownMenuItem(
                      value: c.name,
                      child: Text(c.pose ? '${c.label} · pose' : '${c.label} · ${c.frames}f',
                          style: TextStyle(
                              fontSize: 12,
                              color: c.pose ? Colors.white38 : Colors.white)),
                    ))
                .toList(),
            onChanged: (v) {
              setState(() => _clip = v);
              _loadPreviewMesh(_selectToken);
            },
          )
        else
          Text(_loadingClips ? 'reading clips…' : 'no animation — renders as a still',
              style: const TextStyle(fontSize: 11, color: Colors.white38)),

        _head('Light'),
        Center(
          child: LightPad(
            azimuth: _keyAzimuth,
            elevation: _keyElevation,
            onChanged: (a, e) => setState(() { _keyAzimuth = a; _keyElevation = e; }),
            onCommit: () {},   // the viewport relights itself; no round trip
          ),
        ),
        Center(
          child: Text('azimuth ${_keyAzimuth.toStringAsFixed(0)}°   '
                      'elevation ${_keyElevation.toStringAsFixed(0)}°',
              style: const TextStyle(fontSize: 10, color: Colors.white38)),
        ),
        const SizedBox(height: 6),
        _choice('look', _profile, _profiles, (v) => _profile = v, preview: true),

        _head('Sheet'),
        _int('angles', _yaws, (v) => _yaws = v, max: 16),
        _choice('quality', _quality, const ['draft', 'standard', 'high'],
            (v) => _quality = v),

        const SizedBox(height: 14),
        SizedBox(
          height: 40,
          child: FilledButton(
            onPressed: _busy || _selected == null ? null : () => _render(preview: false),
            child: Text(_busy ? 'working…' : 'Render sheet'),
          ),
        ),

        // ---- everything else, folded away --------------------------------
        const SizedBox(height: 8),
        Theme(
          data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
          child: ExpansionTile(
            tilePadding: EdgeInsets.zero,
            initiallyExpanded: _advanced,
            onExpansionChanged: (v) => _advanced = v,
            title: const Text('Advanced',
                style: TextStyle(fontSize: 11, letterSpacing: 1, color: Colors.white54)),
            children: [
              _head('Framing'),
              _choice('centre on', _center, const ['root', 'origin', 'bbox'], (v) => _center = v),
              _choice('root motion', _rootMotion, const ['strip', 'keep'], (v) => _rootMotion = v),
              _choice('anchor', _anchor, const ['feet', 'bottom', 'center'], (v) => _anchor = v),
              _slider('camera tilt', _elevation, -20, 80, (v) => _elevation = v),
              _head('Timing'),
              _int('frames', _frames, (v) => _frames = v),
              _optional('target fps', _targetFps, (v) => _targetFps = v),
              _optional('start', _start, (v) => _start = v),
              _optional('end', _end, (v) => _end = v),
              _slider('phase', _phase, 0, 1, (v) => _phase = v),
              _slider('speed', _speed, 0.1, 4, (v) => _speed = v),
              SwitchListTile(
                dense: true, contentPadding: EdgeInsets.zero,
                title: const Text('loop (drop endpoint)', style: TextStyle(fontSize: 11)),
                value: _loop, onChanged: (v) => setState(() => _loop = v),
              ),
              _head('Light detail'),
              SwitchListTile(
                dense: true, contentPadding: EdgeInsets.zero,
                title: const Text('lock lights to world', style: TextStyle(fontSize: 11)),
                subtitle: const Text('off = lights ride the camera, so every angle matches',
                    style: TextStyle(fontSize: 9)),
                value: _worldLocked, onChanged: (v) => setState(() => _worldLocked = v),
              ),
              _optional('ambient', _ambient, (v) => _ambient = v),
              _optional('key', _key, (v) => _key = v),
              _optional('fill', _fill, (v) => _fill = v),
              _optional('rim', _rim, (v) => _rim = v),
              _optional('exposure', _exposure, (v) => _exposure = v),
              _head('Output'),
              _choice('tile set', _tileset, _tilesets, (v) {
                _tileset = v;
                final config = _config;
                if (config != null) {
                  try {
                    _kernel?.close();
                    _kernel = TesseraKernel.open(_tilesetPath(config, v));
                  } catch (_) {}
                }
              }),
              _choice('capture px', '$_size', const ['256', '512', '1024', '2048'],
                  (v) => _size = int.parse(v)),
            ],
          ),
        ),

        // ---- tunes: the unit a whole game is made from --------------------
        const Divider(height: 24),
        Row(children: [
          Expanded(
            child: DropdownButton<String>(
              value: _tuneName, isExpanded: true, isDense: true,
              hint: const Text('tune', style: TextStyle(fontSize: 12)),
              items: _tunes
                  .map((t) => DropdownMenuItem(
                      value: t.name,
                      child: Text(t.name, style: const TextStyle(fontSize: 12))))
                  .toList(),
              onChanged: (v) => _applyTune(v),
            ),
          ),
          IconButton(
            tooltip: 'Save these settings as a tune',
            icon: const Icon(Icons.save_outlined, size: 18),
            onPressed: _saveTune,
          ),
        ]),
        const SizedBox(height: 20),
      ]);

  Tune _currentTune(String name) => Tune(
        name: name, profile: _profile,
        keyAzimuth: _keyAzimuth, keyElevation: _keyElevation,
        ambient: _ambient, key: _key, fill: _fill, rim: _rim, exposure: _exposure,
        worldLocked: _worldLocked, center: _center, rootMotion: _rootMotion,
        anchor: _anchor, elevation: _elevation, yaws: _yaws, frames: _frames,
        loop: _loop, phase: _phase, speed: _speed, targetFps: _targetFps,
        tileset: _tileset, size: _size, quality: _quality,
      );

  void _applyTune(String? name) {
    final tune = _tunes.where((t) => t.name == name).firstOrNull;
    if (tune == null) return;
    setState(() {
      _tuneName = tune.name;
      _profile = tune.profile;
      _keyAzimuth = tune.keyAzimuth; _keyElevation = tune.keyElevation;
      _ambient = tune.ambient; _key = tune.key; _fill = tune.fill;
      _rim = tune.rim; _exposure = tune.exposure; _worldLocked = tune.worldLocked;
      _center = tune.center; _rootMotion = tune.rootMotion; _anchor = tune.anchor;
      _elevation = tune.elevation; _yaws = tune.yaws; _frames = tune.frames;
      _loop = tune.loop; _phase = tune.phase; _speed = tune.speed;
      _targetFps = tune.targetFps; _tileset = tune.tileset;
      _size = tune.size; _quality = tune.quality;
      _status = 'tune "${tune.name}" applied';
    });
    if (_autoPreview) _render(preview: true);
  }

  Future<void> _saveTune() async {
    final controller = TextEditingController(text: _tuneName ?? 'my game');
    final name = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Save tune', style: TextStyle(fontSize: 15)),
        content: TextField(
          controller: controller, autofocus: true,
          decoration: const InputDecoration(labelText: 'name'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
          FilledButton(
              onPressed: () => Navigator.pop(context, controller.text.trim()),
              child: const Text('Save')),
        ],
      ),
    );
    if (name == null || name.isEmpty) return;
    await _currentTune(name).save();
    final tunes = await Tune.list();
    setState(() {
      _tunes = tunes;
      _tuneName = name;
      _status = 'tune "$name" saved — every asset rendered with it will match';
    });
  }

  Widget _head(String text) => SectionLabel(text);

  Widget _choice(String label, String value, List<String> options,
          void Function(String) apply, {bool preview = false}) =>
      Row(children: [
        SizedBox(width: 96, child: Text(label, style: Type.label)),
        Expanded(
          child: DropdownButton<String>(
            value: value, isExpanded: true, isDense: true,
            items: options
                .map((o) => DropdownMenuItem(
                    value: o, child: Text(o, style: const TextStyle(fontSize: 12))))
                .toList(),
            onChanged: (v) {
              setState(() => apply(v!));
              if (preview && _autoPreview) _render(preview: true);
            },
          ),
        ),
      ]);

  Widget _int(String label, int value, void Function(int) apply, {int max = 32}) => Row(children: [
        SizedBox(width: 96, child: Text(label, style: Type.label)),
        Expanded(
          child: Slider(
            value: value.toDouble().clamp(1, max.toDouble()),
            min: 1, max: max.toDouble(), divisions: max - 1,
            label: '$value',
            onChanged: (v) => setState(() => apply(v.round())),
          ),
        ),
        SizedBox(width: 30, child: Text('$value', style: Type.label)),
      ]);

  Widget _slider(String label, double value, double min, double max,
          void Function(double) apply) =>
      Row(children: [
        SizedBox(width: 96, child: Text(label, style: Type.label)),
        Expanded(
          child: Slider(
            value: value.clamp(min, max), min: min, max: max,
            onChanged: (v) => setState(() => apply(double.parse(v.toStringAsFixed(2)))),
          ),
        ),
        SizedBox(width: 38, child: Text(value.toStringAsFixed(2), style: Type.caption)),
      ]);

  /// Every timing and lighting value is a float the user may leave unset — blank
  /// means "take it from the action or the preset", which is not the same as zero.
  Widget _optional(String label, double? value, void Function(double?) apply) =>
      Row(children: [
        SizedBox(width: 96, child: Text(label, style: Type.label)),
        Expanded(
          child: TextField(
            decoration: const InputDecoration(
                isDense: true, hintText: 'auto', border: OutlineInputBorder()),
            style: const TextStyle(fontSize: 12),
            onChanged: (text) =>
                setState(() => apply(text.trim().isEmpty ? null : double.tryParse(text))),
          ),
        ),
      ]);
}

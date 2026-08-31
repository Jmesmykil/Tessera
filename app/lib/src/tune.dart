/// A tune: every setting that decides how a sprite looks, saved under a name.
///
/// The creator's reason for this is the whole point of it — "so they can make a
/// whole game with the same settings". A game's sprites have to agree with each
/// other, and agreement across hundreds of assets cannot come from remembering
/// where a slider was. A tune is therefore the unit that gets reused, not the
/// individual control.
library;

import 'dart:convert';
import 'dart:io';

class Tune {
  Tune({
    required this.name,
    this.profile = 'studio',
    this.keyAzimuth = -35,
    this.keyElevation = 35,
    this.ambient,
    this.key,
    this.fill,
    this.rim,
    this.exposure,
    this.worldLocked = false,
    this.center = 'root',
    this.rootMotion = 'strip',
    this.anchor = 'feet',
    this.elevation = 30,
    this.yaws = 8,
    this.frames = 8,
    this.loop = true,
    this.phase = 0,
    this.speed = 1,
    this.targetFps,
    this.tileset = 'pixel-hd',
    this.size = 512,
    this.quality = 'high',
  });

  factory Tune.fromJson(Map<String, dynamic> j) => Tune(
        name: j['name'] as String? ?? 'tune',
        profile: j['profile'] as String? ?? 'studio',
        keyAzimuth: (j['key_azimuth'] as num?)?.toDouble() ?? -35,
        keyElevation: (j['key_elevation'] as num?)?.toDouble() ?? 35,
        ambient: (j['ambient'] as num?)?.toDouble(),
        key: (j['key'] as num?)?.toDouble(),
        fill: (j['fill'] as num?)?.toDouble(),
        rim: (j['rim'] as num?)?.toDouble(),
        exposure: (j['exposure'] as num?)?.toDouble(),
        worldLocked: j['world_locked'] as bool? ?? false,
        center: j['center'] as String? ?? 'root',
        rootMotion: j['root_motion'] as String? ?? 'strip',
        anchor: j['anchor'] as String? ?? 'feet',
        elevation: (j['elevation'] as num?)?.toDouble() ?? 30,
        yaws: j['yaws'] as int? ?? 8,
        frames: j['frames'] as int? ?? 8,
        loop: j['loop'] as bool? ?? true,
        phase: (j['phase'] as num?)?.toDouble() ?? 0,
        speed: (j['speed'] as num?)?.toDouble() ?? 1,
        targetFps: (j['target_fps'] as num?)?.toDouble(),
        tileset: j['tileset'] as String? ?? 'pixel-hd',
        size: j['size'] as int? ?? 512,
        quality: j['quality'] as String? ?? 'high',
      );

  String name;
  String profile;
  double keyAzimuth, keyElevation;
  double? ambient, key, fill, rim, exposure;
  bool worldLocked;
  String center, rootMotion, anchor;
  double elevation;
  int yaws, frames;
  bool loop;
  double phase, speed;
  double? targetFps;
  String tileset;
  int size;
  String quality;

  Map<String, dynamic> toJson() => {
        'name': name, 'profile': profile,
        'key_azimuth': keyAzimuth, 'key_elevation': keyElevation,
        'ambient': ambient, 'key': key, 'fill': fill, 'rim': rim,
        'exposure': exposure, 'world_locked': worldLocked,
        'center': center, 'root_motion': rootMotion, 'anchor': anchor,
        'elevation': elevation, 'yaws': yaws, 'frames': frames,
        'loop': loop, 'phase': phase, 'speed': speed, 'target_fps': targetFps,
        'tileset': tileset, 'size': size, 'quality': quality,
      };

  Tune copy() => Tune.fromJson(toJson());

  static String get _dir =>
      '${Platform.environment['HOME']}/.config/tessera/tunes';

  static Future<List<Tune>> list() async {
    final dir = Directory(_dir);
    if (!dir.existsSync()) return const [];
    final out = <Tune>[];
    for (final entity in dir.listSync()) {
      if (entity is File && entity.path.endsWith('.json')) {
        try {
          out.add(Tune.fromJson(
              jsonDecode(await entity.readAsString()) as Map<String, dynamic>));
        } catch (_) {/* a malformed tune must not hide the good ones */}
      }
    }
    out.sort((a, b) => a.name.compareTo(b.name));
    return out;
  }

  Future<File> save() async {
    final safe = name.replaceAll(RegExp(r'[^A-Za-z0-9_-]'), '_');
    final file = File('$_dir/$safe.json');
    await file.parent.create(recursive: true);
    await file.writeAsString(const JsonEncoder.withIndent('  ').convert(toJson()));
    return file;
  }
}

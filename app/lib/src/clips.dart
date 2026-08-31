/// Clip discovery — the reason "none of the animations are working".
///
/// A rigged BlendKit asset routinely leaves `animation_data.action` EMPTY and
/// keeps its motion as NLA strips. Dragon Man Blue has six of them (Idle 1-40,
/// Walk 1-32, Run 1-22, plus A and T poses) and no assigned action at all, so code
/// that reads only `.action` finds nothing, concludes the subject is static, and
/// renders eight copies of a bind pose.
///
/// Listing clips is also what makes the app read like Mixamo: pick a character,
/// pick an animation. So the list is fetched the moment an asset is selected,
/// before the user asks for anything.
library;

import 'dart:convert';
import 'dart:io';

import 'config.dart';

class Clip {
  Clip({required this.name, required this.start, required this.end,
        required this.frames, required this.pose, this.source = ''});

  factory Clip.fromJson(Map<String, dynamic> json) => Clip(
        name: json['name'] as String,
        start: (json['start'] as num).toDouble(),
        end: (json['end'] as num).toDouble(),
        frames: json['frames'] as int? ?? 1,
        pose: json['pose'] as bool? ?? false,
        source: json['source'] as String? ?? '',
      );

  final String name;
  final double start, end;
  final int frames;
  final bool pose;
  final String source;

  /// Trim the author's own frame-count suffix; the count is shown separately.
  String get label => name.replaceAll(RegExp(r'\s*\(\d+-\d+\)\s*$'), '').trim();
}

/// Fetching the spinnable preview mesh. Cached per asset+clip, because the
/// geometry cannot change unless one of those does — and the whole point is that
/// the app never asks Blender twice for the same thing.
class PreviewFetcher {
  PreviewFetcher(this.config);
  final Config config;

  /// Bumped whenever the exporter changes shape. Without it a cached mesh from an
  /// older exporter is served forever — which is exactly how a one-frame preview
  /// survived the fix that made it twelve.
  static const int formatVersion = 2;

  String cachePath(String blendPath, String? clip) {
    final key = 'v$formatVersion|$blendPath|${clip ?? ''}'.hashCode.toRadixString(16);
    return '${Config.home}/.cache/tessera/preview/$key.tpm';
  }

  Future<String?> fetch(String blendPath, String? clip, {int frames = 12}) async {
    final local = File(cachePath(blendPath, clip));
    if (local.existsSync() && local.lengthSync() > 64) return local.path;
    await local.parent.create(recursive: true);
    final remote = 'out/preview-${local.uri.pathSegments.last}';
    final clipFlag = (clip == null || clip.isEmpty) ? '' : "--clip '$clip'";

    if (config.host.isRemote) {
      // A quoted tilde is a literal directory; hand the remote shell $HOME instead.
      final dir = config.host.workdir.startsWith('~')
          ? '\$HOME${config.host.workdir.substring(1)}'
          : "'${config.host.workdir}'";
      final run = await Process.run('ssh', [
        '-n', '-o', 'BatchMode=yes', config.host.sshHost,
        "cd $dir && tessera/blender/gpu_lock.sh 900 ${config.host.blender} --background --factory-startup "
            "'$blendPath' --python tessera/blender/capture.py -- "
            "--preview-mesh '$remote' --preview-only 1 --frames $frames $clipFlag",
      ]);
      if (run.exitCode != 0) return null;
      final copy = await Process.run('scp', [
        '-q', '${config.host.sshHost}:${config.host.workdir}/$remote', local.path,
      ]);
      if (copy.exitCode != 0 || !local.existsSync()) return null;
      return local.path;
    }

    final run = await Process.run(config.host.blender, [
      '--background', '--factory-startup', blendPath,
      '--python', 'tessera/blender/capture.py', '--',
      '--preview-mesh', local.path, '--preview-only', '1', '--frames', '$frames',
      if (clip != null && clip.isNotEmpty) ...['--clip', clip],
    ], workingDirectory: '${Config.home}/Tessera');
    return (run.exitCode == 0 && local.existsSync()) ? local.path : null;
  }
}


class ClipLister {
  ClipLister(this.config);
  final Config config;

  String _cachePath(String blendPath) {
    final key = blendPath.hashCode.toRadixString(16);
    return '${Config.home}/.cache/tessera/clips/$key.json';
  }

  /// Cached per asset: the list cannot change unless the .blend does, and a
  /// re-listing costs a full Blender start for information already known.
  Future<List<Clip>> list(String blendPath) async {
    final cached = File(_cachePath(blendPath));
    if (cached.existsSync()) {
      return _parse(await cached.readAsString());
    }
    final remoteOut = 'out/clips-${blendPath.hashCode.toRadixString(16)}.json';
    late ProcessResult result;
    if (config.host.isRemote) {
      final dir = config.host.workdir.startsWith('~')
          ? '\$HOME${config.host.workdir.substring(1)}'
          : "'${config.host.workdir}'";
      result = await Process.run('ssh', [
        '-n', '-o', 'BatchMode=yes', config.host.sshHost,
        "cd $dir && tessera/blender/gpu_lock.sh 900 ${config.host.blender} --background --factory-startup "
            "'$blendPath' --python tessera/blender/capture.py -- "
            "--clips-json '$remoteOut'",
      ]);
      if (result.exitCode != 0) return const [];
      final fetch = await Process.run('ssh', [
        '-n', '-o', 'BatchMode=yes', config.host.sshHost,
        "cat ${config.host.workdir.replaceFirst('~', '\$HOME')}/$remoteOut",
      ]);
      if (fetch.exitCode != 0) return const [];
      await cached.parent.create(recursive: true);
      await cached.writeAsString(fetch.stdout as String);
      return _parse(fetch.stdout as String);
    }
    final local = '${Config.home}/Tessera/$remoteOut';
    result = await Process.run(config.host.blender, [
      '--background', '--factory-startup', blendPath,
      '--python', 'tessera/blender/capture.py', '--', '--clips-json', local,
    ], workingDirectory: '${Config.home}/Tessera');
    if (result.exitCode != 0 || !File(local).existsSync()) return const [];
    final text = await File(local).readAsString();
    await cached.parent.create(recursive: true);
    await cached.writeAsString(text);
    return _parse(text);
  }

  List<Clip> _parse(String text) {
    try {
      final json = jsonDecode(text) as Map<String, dynamic>;
      return (json['clips'] as List<dynamic>)
          .map((e) => Clip.fromJson(e as Map<String, dynamic>))
          .toList();
    } catch (_) {
      return const [];
    }
  }
}

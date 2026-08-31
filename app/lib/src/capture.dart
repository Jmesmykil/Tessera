/// Running a capture, wherever Blender actually lives.
///
/// The render host is configuration, not an assumption: here Blender runs on a
/// Linux box over SSH while the client runs on a Mac; elsewhere it is the same
/// machine. Both go through one path so the UI never branches on where the work
/// happens.
///
/// Remote runs stage the capture script before every job. A host holding a stale
/// script produces output that disagrees with the kernel in ways that look like
/// asset problems.
library;

import 'dart:io';

import 'config.dart';

class CaptureSpec {
  CaptureSpec({
    required this.blendPath,
    required this.outName,
    this.clip,
    this.yaws = 8,
    this.frames = 8,
    this.size = 512,
    this.profile = 'studio',
    this.center = 'root',
    this.rootMotion = 'strip',
    this.elevation = 30.0,
    this.loop = true,
    this.phase = 0.0,
    this.speed = 1.0,
    this.targetFps,
    this.start,
    this.end,
    this.ambient,
    this.key,
    this.fill,
    this.rim,
    this.exposure,
    this.samples,
    this.keyAzimuth,
    this.keyElevation,
    this.worldLocked,
    this.previewMesh,
    this.previewOnly = false,
  });

  final String blendPath;
  final String outName;
  final String? clip;
  final int yaws, frames, size;
  final String profile, center, rootMotion;
  final double elevation, phase, speed;
  final bool loop;
  final double? targetFps, start, end, ambient, key, fill, rim, exposure;
  final int? samples;
  final double? keyAzimuth, keyElevation;
  final bool? worldLocked;
  final String? previewMesh;
  final bool previewOnly;

  List<String> toFlags(String remoteOut) {
    final flags = <String>['--out', remoteOut,
      '--yaws', '$yaws', '--frames', '$frames', '--size', '$size',
      '--profile', profile, '--center', center, '--root-motion', rootMotion,
      '--elevation', '$elevation', '--loop', loop ? '1' : '0',
      '--phase', '$phase', '--speed', '$speed'];
    void maybe(String name, num? value) {
      if (value != null) flags.addAll([name, '$value']);
    }
    maybe('--fps', targetFps);
    maybe('--start', start);
    maybe('--end', end);
    maybe('--ambient', ambient);
    maybe('--key', key);
    maybe('--fill', fill);
    maybe('--rim', rim);
    maybe('--exposure', exposure);
    maybe('--samples', samples);
    maybe('--key-azimuth', keyAzimuth);
    maybe('--key-elevation', keyElevation);
    if (worldLocked != null) flags.addAll(['--world-locked', worldLocked! ? '1' : '0']);
    return flags;
  }
}

class CaptureResult {
  CaptureResult({required this.ok, required this.log, this.framesPath, required this.seconds});
  final bool ok;
  final String log;
  final String? framesPath;
  final double seconds;
}

class CaptureRunner {
  CaptureRunner(this.config);
  final Config config;

  String get _packageRoot => '${Config.home}/Tessera';

  /// A quoted `~` is a literal directory name. The tilde is handed to the remote
  /// shell as $HOME rather than shipped inside quotes where it can never expand.
  String get _remoteDir {
    final dir = config.host.workdir;
    return dir.startsWith('~') ? '\$HOME${dir.substring(1)}' : "'$dir'";
  }

  Future<void> _stage() async {
    if (!config.host.isRemote) return;
    await Process.run('rsync', [
      '-a', '--exclude', 'out', '--exclude', '__pycache__', '--exclude', 'vendor-kernel',
      '--exclude', 'app', '--exclude', 'rust',
      '$_packageRoot/', '${config.host.sshHost}:${config.host.workdir}/',
    ]);
  }

  Future<CaptureResult> run(CaptureSpec spec,
      {void Function(String line)? onLog}) async {
    final started = DateTime.now();
    await _stage();
    final remoteOut = 'out/${spec.outName}.tsf';
    final flags = spec.toFlags(remoteOut);

    late ProcessResult result;
    if (config.host.isRemote) {
      final env = config.host.env.entries.map((e) => '${e.key}=${e.value}').join(' ');
      // Through the host lock: three concurrent headless EEVEE contexts on this
      // box hang for tens of minutes instead of failing, so the app must queue
      // behind any batch already rendering.
      final argv = ['tessera/blender/gpu_lock.sh', '1800',
                    config.host.blender, '--background', '--factory-startup',
                    "'${spec.blendPath}'", '--python', 'tessera/blender/capture.py', '--',
                    ...flags.map((f) => f.startsWith('--') ? f : "'$f'")];
      result = await Process.run('ssh', [
        '-n', '-o', 'BatchMode=yes', config.host.sshHost,
        'cd $_remoteDir && $env ${argv.join(' ')}',
      ]);
    } else {
      result = await Process.run(config.host.blender, [
        '--background', '--factory-startup', spec.blendPath,
        '--python', 'tessera/blender/capture.py', '--', ...flags,
      ], workingDirectory: _packageRoot, environment: config.host.env);
    }

    final log = ('${result.stdout}\n${result.stderr}')
        .split('\n')
        .where((l) => !l.startsWith('Fra:') && !l.startsWith('Read blend'))
        .join('\n');
    onLog?.call(log);
    final seconds = DateTime.now().difference(started).inMilliseconds / 1000.0;
    if (result.exitCode != 0) return CaptureResult(ok: false, log: log, seconds: seconds);

    final localPath = '${config.outDir}/${spec.outName}.tsf';
    if (config.host.isRemote) {
      final fetch = await Process.run('scp', [
        '-q', '${config.host.sshHost}:${config.host.workdir}/$remoteOut', localPath,
      ]);
      if (fetch.exitCode != 0) {
        return CaptureResult(ok: false, log: '$log\n${fetch.stderr}', seconds: seconds);
      }
      return CaptureResult(ok: true, log: log, framesPath: localPath, seconds: seconds);
    }
    return CaptureResult(
        ok: true, log: log, framesPath: '$_packageRoot/$remoteOut', seconds: seconds);
  }
}

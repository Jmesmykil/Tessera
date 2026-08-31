/// The one provider every install has, with nothing configured.
///
/// This is not a placeholder standing in for a future network provider — it
/// is the honest answer for sources that have no automatable route at all
/// (Mixamo has no public API; several free-asset sites publish nothing but a
/// browser download button). The user downloads a file the way they already
/// do today, and this provider's only job is the part Tessera can actually
/// help with: putting that file where the existing library browser will find
/// it, named the way the rest of the app expects.
///
/// It performs no network I/O and needs no credential, so it is always
/// `readyOffline` — the Generate tab has a working action even on a machine
/// with zero external services configured.
library;

import 'dart:io';

import 'provider.dart';

class ManualImportProvider implements GenerateProvider {
  const ManualImportProvider();

  static const _importableExtensions = {'.blend', '.fbx', '.glb', '.gltf'};

  @override
  String get id => 'manual';

  @override
  String get displayName => 'Import a downloaded file';

  @override
  String get description =>
      'Files you already downloaded yourself (Mixamo, itch.io packs, a '
      'Sketchfab export, anything). Stays on this machine — copies the file '
      'into your library folder, nothing more.';

  @override
  Set<GenerateCapability> get capabilities => const {GenerateCapability.manualImport};

  @override
  bool get callsNetwork => false;

  @override
  String? get credentialConfigKey => null;

  @override
  GenerateReadiness readiness(Map<String, dynamic> generateConfig) =>
      GenerateReadiness.readyOffline;

  @override
  Future<GenerateResult> run(GenerateRequest request,
      {Map<String, dynamic> generateConfig = const {},
      void Function(String line)? onLog}) async {
    final source = request.sourceFile;
    if (source == null || source.isEmpty) {
      return const GenerateResult.failed('no file selected to import');
    }
    final file = File(source);
    if (!file.existsSync()) {
      return GenerateResult.failed('file not found: $source');
    }

    final extension = _extensionOf(source);
    if (!_importableExtensions.contains(extension)) {
      return GenerateResult.failed(
          "unsupported file type '$extension' — expected one of "
          '${_importableExtensions.join(', ')}');
    }

    final destinationDir =
        Directory('${request.libraryRoot}/${request.subfolder}');
    await destinationDir.create(recursive: true);
    final destination = _uniqueDestination(destinationDir.path, source);

    onLog?.call('copying ${file.path} -> $destination');
    await file.copy(destination);

    final notes = <String>[];
    if (extension != '.blend') {
      // Deliberately not silent: the existing library walk only recognises
      // `.blend` files (`AssetLibrary.fromDirectory` skips everything else),
      // so an imported FBX/glTF will not show up in Browse until a one-time
      // Blender import turns it into a `.blend` alongside it. Tracked as
      // follow-up work in GENERATE_TAB_SPEC.md — this provider does not run
      // Blender itself.
      notes.add(
          'copied as $extension — run a Blender import pass to convert it to '
          '.blend before it appears in the library browser');
    }

    return GenerateResult.ok(destination, notes: notes);
  }

  static String _extensionOf(String path) {
    final dot = path.lastIndexOf('.');
    return dot < 0 ? '' : path.substring(dot).toLowerCase();
  }

  /// Never overwrites an existing asset: two generated characters named the
  /// same thing are common, and silently clobbering one is worse than an
  /// ugly `-2` suffix.
  static String _uniqueDestination(String dir, String sourcePath) {
    final name = sourcePath.split(Platform.pathSeparator).last;
    final dot = name.lastIndexOf('.');
    final stem = dot < 0 ? name : name.substring(0, dot);
    final ext = dot < 0 ? '' : name.substring(dot);
    var candidate = '$dir/$name';
    var attempt = 1;
    while (File(candidate).existsSync()) {
      attempt += 1;
      candidate = '$dir/$stem-$attempt$ext';
    }
    return candidate;
  }
}

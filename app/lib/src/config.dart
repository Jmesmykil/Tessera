/// Configuration. Generic everywhere, pre-pointed at this workstation.
///
/// Nothing in the client knows a path on anyone's machine. Layers resolve the way
/// a person expects: an explicit argument beats an environment variable, which
/// beats the user's config, which beats the shipped profile. The shipped profile
/// is still USEFUL rather than empty — it describes a real library and a real
/// render host — so the app works out of the box without a path being compiled in.
library;

import 'dart:convert';
import 'dart:io';

class RenderHost {
  RenderHost({this.kind = 'local', this.sshHost = '', this.blender = 'blender',
              this.workdir = '~/Tessera', this.env = const {}});

  factory RenderHost.fromJson(Map<String, dynamic> json) => RenderHost(
        kind: json['kind'] as String? ?? 'local',
        sshHost: json['ssh_host'] as String? ?? '',
        blender: json['blender'] as String? ?? 'blender',
        workdir: json['workdir'] as String? ?? '~/Tessera',
        env: (json['env'] as Map<String, dynamic>? ?? {})
            .map((k, v) => MapEntry(k, '$v')),
      );

  final String kind;
  final String sshHost;
  final String blender;
  final String workdir;
  final Map<String, String> env;

  bool get isRemote => kind == 'ssh';
  String get label => isRemote ? 'ssh $sshHost' : 'local';
}

class LibrarySource {
  LibrarySource({required this.name, required this.root, this.indexCsv = ''});

  factory LibrarySource.fromJson(Map<String, dynamic> json) => LibrarySource(
        name: json['name'] as String? ?? 'library',
        root: json['root'] as String? ?? '',
        indexCsv: json['index_csv'] as String? ?? '',
      );

  final String name;
  final String root;
  final String indexCsv;
}

class Config {
  Config({required this.libraries, required this.host, required this.outDir,
          required this.source, this.defaultProfile = 'studio',
          this.defaultTileset = 'pixel-hd'});

  final List<LibrarySource> libraries;
  final RenderHost host;
  final String outDir;
  final String source;
  final String defaultProfile;
  final String defaultTileset;

  static String get home => Platform.environment['HOME'] ?? '';

  static String expand(String path) =>
      path.startsWith('~') ? '$home${path.substring(1)}' : path;

  /// The cached catalogue: the only part of a 100 GB library small enough to copy,
  /// so browsing never shells out per keystroke. Asset paths stay remote, because
  /// that is where the render happens.
  static String cachedIndex(String libraryName) =>
      '$home/.cache/tessera/$libraryName-INDEX.csv';

  static Future<Config> load() async {
    final candidates = <String>[
      Platform.environment['TESSERA_CONFIG'] ?? '',
      '$home/.config/tessera/config.json',
      '$home/Tessera/profiles/default.json',
    ];
    for (final candidate in candidates) {
      if (candidate.isEmpty) continue;
      final file = File(candidate);
      if (!file.existsSync()) continue;
      final json = jsonDecode(await file.readAsString()) as Map<String, dynamic>;
      return Config(
        libraries: (json['libraries'] as List<dynamic>? ?? [])
            .map((e) => LibrarySource.fromJson(e as Map<String, dynamic>))
            .toList(),
        host: RenderHost.fromJson(json['host'] as Map<String, dynamic>? ?? {}),
        outDir: expand(json['out_dir'] as String? ?? '~/Tessera/out'),
        defaultProfile: json['default_profile'] as String? ?? 'studio',
        defaultTileset: json['default_tileset'] as String? ?? 'pixel-hd',
        source: candidate,
      );
    }
    return Config(
      libraries: const [],
      host: RenderHost(),
      outDir: '$home/Tessera/out',
      source: 'built-in defaults',
    );
  }
}

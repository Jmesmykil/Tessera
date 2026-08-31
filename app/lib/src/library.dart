/// Asset discovery over whatever the user actually has.
///
/// A curated collection ships an index with rig/animated/category already
/// computed; someone else has a folder of .blend files and nothing else. Both
/// answer the same queries. What a bare directory cannot know comes back as NULL,
/// never false — a confident wrong answer would silently drop every rigged
/// character from a search whose whole purpose was to find them.
library;

import 'dart:io';

class Asset {
  Asset({required this.name, required this.path, this.category = '', this.top = '',
         this.rig, this.animated, this.faces, this.license = '', this.thumb = ''});

  final String name;
  final String path;
  final String category;
  final String top;
  final bool? rig;
  final bool? animated;
  final int? faces;
  final String license;
  final String thumb;

  /// Thumbnails are cached locally: 10,634 small JPEGs are the browsing
  /// experience, and they are the only part of a 100 GB library worth copying.
  String get cachedThumb => thumb.isEmpty
      ? ''
      : '${Platform.environment['HOME']}/.cache/tessera/thumbs/'
          '${thumb.replaceFirst(RegExp(r'^_thumbs/'), '')}';

  String get marks =>
      '${rig == null ? '?' : (rig! ? 'R' : '-')}${animated == null ? '?' : (animated! ? 'A' : '-')}';
}

/// A CSV reader that survives quoted fields, because asset names contain commas.
List<String> _splitCsvLine(String line) {
  final out = <String>[];
  final buffer = StringBuffer();
  var quoted = false;
  for (var i = 0; i < line.length; i++) {
    final ch = line[i];
    if (ch == '"') {
      if (quoted && i + 1 < line.length && line[i + 1] == '"') {
        buffer.write('"');
        i++;
      } else {
        quoted = !quoted;
      }
    } else if (ch == ',' && !quoted) {
      out.add(buffer.toString());
      buffer.clear();
    } else {
      buffer.write(ch);
    }
  }
  out.add(buffer.toString());
  return out;
}

bool? _truthy(String? value) {
  final text = (value ?? '').trim().toLowerCase();
  if (['1', 'true', 'yes', 'y'].contains(text)) return true;
  if (['0', 'false', 'no', 'n'].contains(text)) return false;
  return null;
}

class AssetLibrary {
  AssetLibrary(this.assets);
  final List<Asset> assets;

  static Future<AssetLibrary> fromIndex(String csvPath, String root) async {
    final file = File(csvPath);
    if (!file.existsSync()) return AssetLibrary(const []);
    final lines = await file.readAsLines();
    if (lines.isEmpty) return AssetLibrary(const []);
    final header = _splitCsvLine(lines.first);
    int col(String name) => header.indexOf(name);
    final (iRel, iName, iTop, iCat, iRig, iAnim, iFaces, iLic, iThumb) = (
      col('rel'), col('name'), col('top'), col('category'),
      col('rig'), col('animated'), col('faceCount'), col('license'), col('thumb'),
    );
    final out = <Asset>[];
    for (final line in lines.skip(1)) {
      if (line.trim().isEmpty) continue;
      final f = _splitCsvLine(line);
      String at(int i) => (i >= 0 && i < f.length) ? f[i] : '';
      final rel = at(iRel);
      if (!rel.endsWith('.blend')) continue;
      out.add(Asset(
        name: at(iName).isEmpty ? rel.split('/').last : at(iName),
        path: '$root/$rel',
        top: at(iTop),
        category: at(iCat),
        rig: _truthy(at(iRig)),
        animated: _truthy(at(iAnim)),
        faces: int.tryParse(at(iFaces).split('.').first),
        license: at(iLic),
        thumb: at(iThumb),
      ));
    }
    return AssetLibrary(out);
  }

  /// A plain folder of .blend files, organised by the folders it is already in.
  ///
  /// Nothing here is configured or hardcoded: whatever directory structure the
  /// user keeps their models in IS the category tree. The first folder under the
  /// library root becomes the bucket and the rest becomes the subcategory, so
  /// `humans/rigged/women/x.blend` files itself under humans → rigged/women
  /// exactly as a curated index would have.
  static Future<AssetLibrary> fromDirectory(String root) async {
    final dir = Directory(root);
    if (!dir.existsSync()) return AssetLibrary(const []);
    final base = dir.absolute.path.replaceAll(RegExp(r'/+$'), '');
    final out = <Asset>[];
    await for (final entity in dir.list(recursive: true, followLinks: false)) {
      if (entity is! File || !entity.path.endsWith('.blend')) continue;
      final relative = entity.path.startsWith(base)
          ? entity.path.substring(base.length + 1)
          : entity.path;
      final parts = relative.split('/');
      final folders = parts.sublist(0, parts.length - 1);
      out.add(Asset(
        name: parts.last.replaceAll('.blend', ''),
        path: entity.path,
        top: folders.isEmpty ? 'library' : folders.first,
        category: folders.length > 1 ? folders.sublist(1).join('/') : '',
      ));
    }
    out.sort((a, b) => a.name.compareTo(b.name));
    return AssetLibrary(out);
  }

  List<String> get buckets =>
      (assets.map((a) => a.top).where((t) => t.isNotEmpty).toSet().toList()..sort());

  /// bucket -> subcategories, both sorted, blanks folded into 'other'. This is the
  /// organisation the creator asked for: categories AND subcategories, not a flat
  /// list of five thousand names.
  Map<String, List<String>> get tree {
    final out = <String, Set<String>>{};
    for (final asset in assets) {
      if (asset.top.isEmpty) continue;
      out.putIfAbsent(asset.top, () => <String>{})
          .add(asset.category.isEmpty ? 'other' : asset.category);
    }
    return {
      for (final key in out.keys.toList()..sort())
        key: out[key]!.toList()..sort(),
    };
  }

  int countIn(String bucket, String? category) => assets
      .where((a) =>
          a.top == bucket &&
          (category == null ||
              (category == 'other' ? a.category.isEmpty : a.category == category)))
      .length;

  List<Asset> search(String query, {bool? rig, bool? animated, String? bucket,
                                    int? maxFaces, int limit = 200}) {
    final needle = query.toLowerCase();
    final out = <Asset>[];
    for (final asset in assets) {
      if (needle.isNotEmpty &&
          !asset.name.toLowerCase().contains(needle) &&
          !asset.category.toLowerCase().contains(needle)) {
        continue;
      }
      if (rig != null && asset.rig != rig) continue;
      if (animated != null && asset.animated != animated) continue;
      if (bucket != null && bucket.isNotEmpty && asset.top != bucket) continue;
      if (maxFaces != null && asset.faces != null && asset.faces! > maxFaces) continue;
      out.add(asset);
      if (out.length >= limit) break;
    }
    return out;
  }
}

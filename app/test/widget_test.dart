import 'package:flutter_test/flutter_test.dart';
import 'package:tessera_studio/src/library.dart';

void main() {
  group('library', () {
    test('unknown rig/animated stays null, never false', () {
      // A directory walk cannot know whether a .blend is rigged. Answering "no"
      // would silently drop every rigged character from a search meant to find them.
      final asset = Asset(name: 'x', path: '/x.blend');
      expect(asset.rig, isNull);
      expect(asset.animated, isNull);
      expect(asset.marks, '??');
    });

    test('filters do not match assets whose flag is unknown', () {
      final library = AssetLibrary([
        Asset(name: 'rigged', path: '/a.blend', rig: true, animated: true),
        Asset(name: 'unknown', path: '/b.blend'),
      ]);
      expect(library.search('', rig: true).length, 1);
      expect(library.search('', rig: false).length, 0);
      expect(library.search('').length, 2);
    });

    test('search matches name and category', () {
      final library = AssetLibrary([
        Asset(name: 'Ninja Girl', path: '/a.blend', category: 'woman'),
        Asset(name: 'Old Door', path: '/b.blend', category: 'furniture'),
      ]);
      expect(library.search('ninja').single.name, 'Ninja Girl');
      expect(library.search('furn').single.name, 'Old Door');
    });

    test('buckets are sorted and exclude blanks', () {
      final library = AssetLibrary([
        Asset(name: 'a', path: '/a.blend', top: 'weapons'),
        Asset(name: 'b', path: '/b.blend', top: 'animals'),
        Asset(name: 'c', path: '/c.blend'),
      ]);
      expect(library.buckets, ['animals', 'weapons']);
    });
  });
}

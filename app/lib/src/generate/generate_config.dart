/// Reads the `generate` section of the existing Tessera config file.
///
/// Deliberately separate from `src/config.dart` rather than added to it: the
/// Generate tab is unintegrated and optional, and this reader must be safe to
/// import without pulling generate-tab concerns into the core `Config` class
/// other screens already depend on. Both read the same file — there is only
/// ever one `~/.config/tessera/config.json` — this just looks at one more key
/// of it and never writes a default value into it.
library;

import 'dart:convert';
import 'dart:io';

/// `generate.<provider id>` -> that provider's own settings (typically just
/// `{"api_key": "..."}`). An absent or empty section is normal and means
/// every credentialed provider reports `missingCredential`.
class GenerateConfig {
  const GenerateConfig(this.providers);

  final Map<String, Map<String, dynamic>> providers;

  static String get _home => Platform.environment['HOME'] ?? '';
  static String get _path => '$_home/.config/tessera/config.json';

  Map<String, dynamic> forProvider(String id) => providers[id] ?? const {};

  static Future<GenerateConfig> load() async {
    final file = File(_path);
    if (!file.existsSync()) return const GenerateConfig({});
    try {
      final json = jsonDecode(await file.readAsString()) as Map<String, dynamic>;
      final section = json['generate'] as Map<String, dynamic>? ?? {};
      return GenerateConfig(section.map(
          (key, value) => MapEntry(key, (value as Map<String, dynamic>? ?? {}))));
    } catch (_) {
      // A corrupt or partially-written config must not block the rest of the
      // app — every provider simply reads as unconfigured.
      return const GenerateConfig({});
    }
  }
}

/// The Generate provider contract — one interface, many acquisition strategies.
///
/// This mirrors the shape `AssetLibrary` already uses for browsing: one type
/// answers the same questions regardless of whether the assets came from a
/// curated index or a bare folder walk. Here, one interface answers the same
/// questions regardless of whether an asset came from a manual download the
/// user already made, or (in future) a credentialed call to an external
/// generator.
///
/// A provider that talks to a network service is NOT implemented in this
/// package yet — see `docs/GENERATE_TAB_SPEC.md`. What ships here is the
/// contract, plus one fully-working provider (`ManualImportProvider`) that
/// needs no credentials and never leaves the machine, so the Generate tab has
/// at least one useful thing to do with zero configuration.
library;

/// What a provider can produce. A provider may claim more than one.
enum GenerateCapability {
  /// Turns a text prompt into a 3D model.
  textToModel,

  /// Turns a reference image into a 3D model.
  imageToModel,

  /// Supplies (or attaches) a skeleton and skinning weights.
  rigging,

  /// Supplies stock animation clips for a rigged character.
  animationLibrary,

  /// The provider itself does no network fetch — it only organizes a file the
  /// user already downloaded through their own browser.
  manualImport,
}

/// Whether a provider is safe to run with nothing configured.
enum GenerateReadiness {
  /// No credential needed and nothing about running it leaves the machine.
  readyOffline,

  /// A credential is required and is present in the user's config.
  readyOnline,

  /// A credential is required and is missing — the provider must refuse to
  /// run rather than prompt implicitly for one.
  missingCredential,
}

/// A single acquisition request. Fields a provider does not use are left null;
/// nothing here is a lowest-common-denominator payload shared over a network —
/// it is an in-process value object.
class GenerateRequest {
  const GenerateRequest({
    required this.libraryRoot,
    this.prompt,
    this.referenceImage,
    this.sourceFile,
    this.subfolder = 'generated',
  });

  /// The root of the user's asset library (`config.libraries.first.root`,
  /// expanded). Never a path baked into this package.
  final String libraryRoot;

  /// A text prompt, for providers that support [GenerateCapability.textToModel].
  final String? prompt;

  /// A reference image path, for [GenerateCapability.imageToModel].
  final String? referenceImage;

  /// A file already sitting on disk — the manual-download-then-import case.
  final String? sourceFile;

  /// Folder under [libraryRoot] new assets land in. Categories in Tessera are
  /// derived from folder structure, so this alone decides where the asset
  /// shows up in the existing library browser.
  final String subfolder;
}

/// The result of one acquisition attempt. Never partial: a provider either
/// lands a complete, openable asset file or reports failure — nothing is
/// written into the library folder on a failed or cancelled run.
class GenerateResult {
  const GenerateResult.ok(this.assetPath, {this.notes = const []})
      : ok = true,
        message = '';

  const GenerateResult.failed(this.message)
      : ok = false,
        assetPath = null,
        notes = const [];

  final bool ok;

  /// Absolute path to the asset now inside the library folder, on success.
  final String? assetPath;

  /// Human-readable failure reason, on failure.
  final String message;

  /// Non-fatal call-outs surfaced to the user — e.g. "no NLA track found,
  /// imported as a static prop" — that a caller may want to show without
  /// treating the run as failed.
  final List<String> notes;
}

/// One acquisition source, behind the interface the Generate tab talks to.
///
/// Implementations must not perform any network I/O, prompt for credentials,
/// or write into the library folder from a constructor or a getter — only
/// from [run], and only after [readiness] has been checked by the caller.
abstract class GenerateProvider {
  /// Stable identifier, used as the config-file key and as a cache-path
  /// component. Lower-case, no spaces.
  String get id;

  /// Name shown in the Generate tab.
  String get displayName;

  /// One-line description of what this provider does and where it sends
  /// data, e.g. "Sends your prompt to a third-party service — leaves this
  /// machine." A provider that never leaves the machine says so plainly too.
  String get description;

  Set<GenerateCapability> get capabilities;

  /// True if invoking [run] ever makes a network call. Drives the "leaves
  /// this machine" label and the consent prompt — never inferred from
  /// whether a credential exists, so a provider cannot quietly change
  /// category by adding a key.
  bool get callsNetwork;

  /// The config.json key this provider reads its credential from
  /// (`generate.<key>`), or null if it needs none.
  String? get credentialConfigKey;

  /// Checks configuration only — must not touch the network.
  GenerateReadiness readiness(Map<String, dynamic> generateConfig);

  /// Performs one acquisition. Callers must have already checked
  /// [readiness] and, for any provider with [callsNetwork] true, obtained
  /// explicit per-run user consent — this method does not ask.
  Future<GenerateResult> run(GenerateRequest request,
      {Map<String, dynamic> generateConfig = const {},
      void Function(String line)? onLog});
}

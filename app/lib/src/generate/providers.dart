/// The provider catalogue the Generate tab would list.
///
/// Only [ManualImportProvider] is wired to a real [GenerateProvider]
/// implementation today. Everything else here is a [ProviderDescriptor] —
/// data describing a credentialed service this design was evaluated against
/// (see `docs/GENERATE_TAB_SPEC.md` for the verdict and sources on each),
/// deliberately NOT backed by any network code yet. Listing the shape now
/// means the Generate tab's UI and the config schema can be built and
/// reviewed before the first line of an HTTP client is written.
library;

import 'manual_import_provider.dart';
import 'provider.dart';

/// How a provider gets an asset onto the machine at all.
enum ProviderKind {
  /// This app runs the whole acquisition through a documented API.
  api,

  /// No public API exists (or none this design could recommend automating
  /// against). The user downloads through the service's own site or app;
  /// Tessera's part starts after the file already exists locally.
  manualOnly,
}

class ProviderDescriptor {
  const ProviderDescriptor({
    required this.id,
    required this.displayName,
    required this.kind,
    required this.capabilities,
    required this.credentialConfigKey,
    required this.leavesMachine,
    required this.docsUrl,
    required this.note,
  });

  final String id;
  final String displayName;
  final ProviderKind kind;
  final Set<GenerateCapability> capabilities;

  /// Null for a manual-only provider, or one with no credential requirement.
  final String? credentialConfigKey;

  final bool leavesMachine;
  final String docsUrl;

  /// The one-line verdict from GENERATE_TAB_SPEC.md — kept alongside the
  /// descriptor so the UI and the doc cannot drift apart silently.
  final String note;
}

/// The provider actually runnable right now.
const manualImportProvider = ManualImportProvider();

/// Everything evaluated for this design. Ordered as recommended for the
/// Generate tab's provider list, not alphabetically.
const List<ProviderDescriptor> knownProviders = [
  ProviderDescriptor(
    id: 'manual',
    displayName: 'Import a downloaded file',
    kind: ProviderKind.manualOnly,
    capabilities: {GenerateCapability.manualImport},
    credentialConfigKey: null,
    leavesMachine: false,
    docsUrl: '',
    note: 'Always available. Zero configuration, zero network.',
  ),
  ProviderDescriptor(
    id: 'polyhaven',
    displayName: 'Poly Haven',
    kind: ProviderKind.api,
    capabilities: {GenerateCapability.imageToModel},
    credentialConfigKey: null,
    leavesMachine: true,
    docsUrl: 'https://polyhaven.com/our-api',
    note: 'CC0, free, no login or key required — but a props/environment '
        'library, not a character generator; thin on rigged, animated '
        'subjects.',
  ),
  ProviderDescriptor(
    id: 'meshy',
    displayName: 'Meshy',
    kind: ProviderKind.api,
    capabilities: {
      GenerateCapability.textToModel,
      GenerateCapability.imageToModel,
      GenerateCapability.rigging,
      GenerateCapability.animationLibrary,
    },
    credentialConfigKey: 'meshy',
    leavesMachine: true,
    docsUrl: 'https://docs.meshy.ai/en/api',
    note: 'Documented API, but the API tier requires a paid (Pro+) Meshy '
        'plan. Auto-rig + a 600+ clip animation library makes it the best '
        'fit for landing a ready-to-capture character in one pass.',
  ),
  ProviderDescriptor(
    id: 'tripo',
    displayName: 'Tripo',
    kind: ProviderKind.api,
    capabilities: {
      GenerateCapability.textToModel,
      GenerateCapability.imageToModel,
      GenerateCapability.rigging,
    },
    credentialConfigKey: 'tripo',
    leavesMachine: true,
    docsUrl: 'https://developers.tripo3d.ai/en',
    note: 'Documented pay-as-you-go API with its own auto-rig endpoint '
        '(biped/quadruped/avian/etc.); no confirmed stock animation library, '
        'so a rigged result still needs animation from elsewhere.',
  ),
  ProviderDescriptor(
    id: 'rodin',
    displayName: 'Rodin (Hyper3D)',
    kind: ProviderKind.api,
    capabilities: {GenerateCapability.imageToModel},
    credentialConfigKey: 'rodin',
    leavesMachine: true,
    docsUrl: 'https://docs.hyper3d.ai/en',
    note: 'Documented API, permissive output terms, but no confirmed '
        'rigging/animation endpoint — highest-fidelity mesh quality, most '
        'follow-up work.',
  ),
  ProviderDescriptor(
    id: 'sloyd',
    displayName: 'Sloyd',
    kind: ProviderKind.api,
    capabilities: {
      GenerateCapability.textToModel,
      GenerateCapability.imageToModel,
      GenerateCapability.rigging,
    },
    credentialConfigKey: 'sloyd',
    leavesMachine: true,
    docsUrl: 'https://www.sloyd.ai/api',
    note: 'Game-asset-first, can export straight to .blend, but public '
        'documentation at review time said API signups were paused — '
        'verify current availability before building against it.',
  ),
  ProviderDescriptor(
    id: 'sketchfab',
    displayName: 'Sketchfab',
    kind: ProviderKind.api,
    capabilities: {GenerateCapability.manualImport},
    credentialConfigKey: 'sketchfab',
    leavesMachine: true,
    docsUrl: 'https://sketchfab.com/developers/download-api',
    note: 'A library, not a generator. Downloads require the END USER to '
        'complete an OAuth login inside the app per Sketchfab policy — no '
        'server-side automation without a separate agreement with them.',
  ),
  ProviderDescriptor(
    id: 'mixamo',
    displayName: 'Mixamo',
    kind: ProviderKind.manualOnly,
    capabilities: {GenerateCapability.manualImport},
    credentialConfigKey: null,
    leavesMachine: true,
    docsUrl: 'https://www.mixamo.com',
    note: 'No public API. Adobe\'s general terms bar accessing services by '
        'any means other than the interface they provide, so the '
        'reverse-engineered downloaders that exist on GitHub are a ToS '
        'violation risk, not a design option. Manual browser download, then '
        'Import a downloaded file.',
  ),
  ProviderDescriptor(
    id: 'quaternius',
    displayName: 'Quaternius',
    kind: ProviderKind.manualOnly,
    capabilities: {GenerateCapability.manualImport},
    credentialConfigKey: null,
    leavesMachine: true,
    docsUrl: 'https://quaternius.com',
    note: 'CC0 and free, but no public API could be confirmed — packs are '
        'zip downloads from the site or itch.io. Manual browser download, '
        'then Import a downloaded file.',
  ),
];

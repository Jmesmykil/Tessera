# Generate tab — integration spec

Status: design only. Nothing in this document is wired into the running app.
The scaffolding that ships alongside it (`app/lib/src/generate/`) compiles
and is not imported from `main.dart`.

## 1. What this is

Today, Tessera's only way to get an asset is to already have a `.blend` file
sitting in the library folder. The **Generate** tab adds a second on-ramp: a
peer tab, next to the existing library browser, for *acquiring* a model or
animation from somewhere else and landing it in that same folder — after
which the existing pipeline (clip discovery → preview → capture → sheet)
runs on it completely unchanged.

This spec does not propose replacing manual curation. Most of the named
services turn out to have exactly one honest integration: help the user do
the download they were already going to do, then organize the result. That
is treated as a first-class outcome here, not a fallback.

## 2. Non-negotiables this design is built around

These come from the task, restated as constraints on every design decision
below, because a few of the researched services make it tempting to violate
one of them for convenience.

1. **Optional, and off by default.** A machine with no `generate` section in
   `~/.config/tessera/config.json` runs Tessera exactly as it does today.
   No provider list is fetched, no key is prompted for, no feature is
   greyed out in a way that nags.
2. **Every external call is opt-in per action**, clearly labelled as
   leaving the machine, and never fired as a side effect of opening the tab,
   typing in a field, or switching providers.
3. **Credentials live only in the user's own config file**, never in this
   repository, never as a shipped default, never logged.
4. **ToS and legal footing are load-bearing**, not a footnote. Where the
   honest answer is "there is no API, only a browser download," this design
   says that and stops there for that service — it does not paper over it
   with a scraper.
5. **Everything acquired becomes an ordinary library asset**: a `.blend`
   file (or a file one Blender import pass turns into one) inside the
   user's configured library folder, in a subfolder. Nothing about capture,
   preview, or QA changes to accommodate it.

## 3. Per-service verdicts

Researched 2026-08-30. Pricing and API availability for AI-generation
startups changes often; treat prices as indicative and re-check before
building against any of them.

| Service | Verdict |
|---|---|
| **Mixamo** | No public API. Manual browser download only — automating it is a documented ToS risk (§3.1). |
| **Meshy** | Real, documented API; best fit of the generators — auto-rig + a large stock animation library can produce a capture-ready character in one pipeline. Requires a paid (Pro+) plan just to unlock API access. |
| **Tripo** | Real, documented, pay-as-you-go API with its own auto-rig endpoint. No confirmed stock animation library — a rigged Tripo model still needs animation from somewhere else. |
| **Rodin (Hyper3D)** | Real API, permissive output terms, best-regarded mesh quality of the group. No confirmed rigging or animation endpoint. Pricier, more enterprise-leaning tiers. |
| **Sloyd** | Purpose-built for game-ready output (LODs, clean topology, auto-rig) and can reportedly export straight to `.blend`. Public docs at review time said API signups were paused — **could not verify current availability**; treat as "promising, unconfirmed" rather than ready to build against. |
| **Sketchfab** | Not a generator — a library of existing (often CC-licensed) models, some rigged/animated. API requires the *end user* to complete an OAuth login inside the app; no server-side automation without a separate agreement with Sketchfab. Legitimate integration, but the OAuth flow and per-model license/attribution display it requires make it a second-slice feature, not a first one. |
| **Poly Haven** | CC0, free, no login or key needed for the public API — the lowest-friction, lowest-risk integration researched. Thin library of rigged/animated characters; mostly props, kits, and environment pieces. Good for proving the acquisition→import pipe end-to-end; not a substitute for a character generator. |
| **Quaternius** | CC0, free, thousands of low-poly (often rigged/animated) game assets. **No public API found** — packs are zip downloads from the site or itch.io. Treated the same as Mixamo: manual download, then import. |
| **Adobe Substance 3D (Automation Service / Firefly Services)** | Real, documented API — but it automates *material/texture and scene* pipelines on assets you already have, not "type a prompt, get a character." Wrong shape for this tab; not recommended for the Generate use case at all. |
| **Kaedim** | Has an API/SDK, but pricing is quote-only/enterprise and public self-serve docs are thin. Too much integration friction and too little verifiable detail for a first slice; revisit if a user specifically asks for it. |
| **Luma AI (Genie)** | Has a developer API (usage-billed), but the consumer product is priced ($30–300/mo) and positioned more for cinematic/video-adjacent 3D than game-sprite source models. Lowest priority of the researched options. |

Everything past this table expands on the ones that inform the design:
Mixamo (because "no" needs justifying), Meshy (the reference API shape), and
the manual-only sources (because they define the acquisition→import flow
that even the API providers fall back through).

### 3.1 Mixamo, in detail

Mixamo has never published a public, documented API. Every "Mixamo API"
project that exists (there are several actively maintained ones on GitHub —
Selenium bots, reverse-engineered internal-endpoint clients) works by
automating the same private web session a browser uses, because that is the
only thing there is to automate.

Adobe's general Terms of Use state that a user agrees "not to access or
attempt to access the Services by any means other than the interface
provided by Adobe" — Mixamo runs under Adobe's account and terms
([adobe.com/legal/terms](https://www.adobe.com/legal/terms.html)). A
Selenium bot or a client against the undocumented internal endpoint is, on
its face, exactly what that clause is written to prohibit. Community threads
on scope of use for the *output* (characters/animations may not be
redistributed as standalone assets — they must be incorporated into a
project — and content may not be used to train ML) are a separate, narrower
question from whether *automating retrieval* is permitted; the retrieval
question is the one this design has to answer, and the answer is no.

**Verdict: manual only.** The Generate tab's Mixamo entry is a `manualOnly`
descriptor: it explains what Mixamo is, links to it, and tells the user to
download the FBX from their browser like they do today. The moment that file
exists on disk, `ManualImportProvider` (shipped in this scaffolding) takes
over.

Sources:
[Mixamo automation projects exist on GitHub](https://github.com/paulpierre/MixamoHarvester) ·
[Adobe General Terms of Use](https://www.adobe.com/legal/terms.html) ·
[Mixamo licensing/redistribution FAQ discussion](https://community.adobe.com/t5/mixamo-discussions/mixamo-faq-licensing-royalties-ownership-eula-and-tos/td-p/13234775)

### 3.2 Meshy, in detail (the reference API shape)

- **Auth**: API key, Bearer token, created from the account's API settings
  page. Requires the account to be on a Pro-tier (or above) *paid* plan —
  the free web tier does not unlock API access.
  ([docs.meshy.ai](https://docs.meshy.ai/en/api/text-to-3d))
- **Cost**: pay-as-you-go credits purchased up front, no subscription
  required for the API itself. A Text-to-3D or Image-to-3D generation is
  ~20 credits (25 in "Ultra" mode); texturing is ~10 credits.
  ([meshy.ai/pricing](https://www.meshy.ai/pricing))
- **Rate limits**: 20 requests/second; 10 queued tasks (Pro) or 30 (Premium).
  ([docs.meshy.ai/rate-limits](https://docs.meshy.ai/en/api/rate-limits))
- **Output**: GLB/FBX/OBJ/USDZ, textured.
- **Why it matters for Tessera specifically**: Meshy's Auto Rigging detects
  humanoid/quadruped body plans, builds a bone hierarchy and skin weights
  automatically, and its Animation Generator applies from a library of 600+
  stock clips (walk, idle, attack, ...) to the rigged result
  ([meshy.ai/features/ai-auto-rigging](https://www.meshy.ai/features/ai-auto-rigging),
  [meshy.ai/features/ai-animation-generator](https://www.meshy.ai/features/ai-animation-generator)).
  That is the one API-backed path researched that can plausibly produce a
  *rigged, animated* character in one pipeline — the same shape `capture.py`
  already expects — rather than a static mesh needing rigging from
  somewhere else entirely.
- **Format caveat (unverified)**: whether Meshy's exported FBX encodes clips
  as `bpy`-visible actions cleanly on Blender import, or as a single blended
  take that needs splitting, could not be verified without a Meshy account
  and a real export to inspect. Flagged as a first-slice risk, not a
  blocker — see §7.

### 3.3 The manual-only sources define the common path

Mixamo, Quaternius, and (functionally, given its OAuth requirement)
Sketchfab all resolve to the same shape: *the user gets a file through a
browser; Tessera's job starts once that file exists.* Poly Haven is the one
fully-automatable source with zero ToS or credential friction, but it is
weak on the thing users will actually ask this tab for (rigged, animated
characters) — good for proving the pipe, not the main draw.

Because three-plus of nine researched services collapse to "manual download,
then import," that path is not a degraded fallback in this design — it is
the default provider, always present, and it is what ships as working code
in this PR (`ManualImportProvider`). Every credentialed API provider is
additive on top of it, not a replacement for it.

## 4. Provider abstraction

`library.dart` already answers "where do assets come from" two ways behind
one type — a curated CSV index (`AssetLibrary.fromIndex`) and a bare
directory walk (`AssetLibrary.fromDirectory`) — so the rest of the app never
branches on which one is active. The Generate tab needs the same shape for
"where does a *new* asset come from," and the code in
`app/lib/src/generate/` follows it:

```
GenerateProvider (abstract interface)
 ├─ ManualImportProvider        — implemented, ships in this PR
 ├─ PolyHavenProvider           — future: no-key REST fetch (§3, table)
 ├─ MeshyProvider               — future: credentialed REST + poll/webhook
 ├─ TripoProvider               — future: credentialed REST + poll/webhook
 ├─ RodinProvider                — future: credentialed REST + poll/webhook
 ├─ SketchfabProvider            — future: end-user OAuth + Download API
 └─ (Mixamo, Quaternius have no runnable provider — manualOnly descriptors
    that route straight to ManualImportProvider once a file exists)
```

`app/lib/src/generate/provider.dart` defines:

- `GenerateCapability` — `textToModel`, `imageToModel`, `rigging`,
  `animationLibrary`, `manualImport`. A provider declares every capability
  it has; the tab's UI (not built yet) would use this to decide what inputs
  to show (a prompt box, an image picker, a file picker) rather than special
  casing providers by name.
- `GenerateReadiness` — `readyOffline` (no credential needed, e.g. manual
  import), `readyOnline` (credential present), `missingCredential`. Computed
  from config only — a provider must be able to answer this without a
  network round-trip, so the tab can grey out a provider instantly rather
  than spinner-checking each one on open.
- `GenerateRequest` / `GenerateResult` — the acquisition call and its
  outcome. A result is either a complete asset path plus advisory `notes`,
  or a failure message; nothing in between, and nothing partially written.
- `GenerateProvider` — `id`, `displayName`, `description` (must state where
  data goes), `capabilities`, `callsNetwork` (drives the consent UI,
  independent of whether a credential happens to be configured),
  `credentialConfigKey`, `readiness(...)`, `run(...)`.

`app/lib/src/generate/providers.dart` holds `ProviderDescriptor` — pure data
for every service in the table above, plus `knownProviders`, the list the
tab would render. Only `manual` resolves to a live `GenerateProvider`
today; the rest exist so the UI, the config schema, and this document's
verdicts can be reviewed together before any HTTP client is written against
a service whose pricing or API availability might have moved by then
(Sloyd's is a live example — see §3, table).

`app/lib/src/generate/generate_config.dart` reads the `generate` object out
of the *existing* `~/.config/tessera/config.json` — it does not add a new
config file, and it does not touch `src/config.dart`, so nothing about how
the rest of the app loads its configuration changes. An absent `generate`
key is the expected, fully-supported state.

## 5. Acquisition → import → library flow

```
 ┌──────────────┐     ┌───────────────────┐     ┌────────────────────────┐
 │ 1. Acquire    │ ──▶ │ 2. Import         │ ──▶ │ 3. Land in library     │
 │ (provider-    │     │ (make it openable │     │ (existing browse/clip/ │
 │  specific)    │     │  by capture.py)   │     │  capture pipeline)     │
 └──────────────┘     └───────────────────┘     └────────────────────────┘
```

**1. Acquire.** Either the user hands the tab a file they already downloaded
(manual providers), or — for a credentialed API provider, after the consent
moment in §6 — the app submits a prompt/image, polls or waits on a webhook,
and downloads the resulting file to a scratch location
(`~/.cache/tessera/generate/<provider>/<job-id>/`), never straight into the
library folder. A failed or cancelled job leaves nothing in the library.

**2. Import.** `AssetLibrary.fromDirectory` (in the existing, untouched
`library.dart`) only recognises files ending in `.blend`
(`if (... || !entity.path.endsWith('.blend')) continue;`). Every generator
and asset site researched here outputs FBX or glTF/GLB, never a native
`.blend` (Sloyd is the possible exception — see §3, table — unverified).
That means an import step is required before *any* acquired asset is
visible to Browse, regardless of provider:

- Run Blender headless, `--background --factory-startup`, importing the
  FBX/GLB and saving as a `.blend` next to it — the same invocation shape
  `capture.py` already uses, just a new small script
  (e.g. `tessera/blender/import_asset.py`) rather than a change to
  `capture.py` itself. **Not built in this PR** — flagged as required
  follow-up work, not assumed away.
- `ManualImportProvider` (built in this PR) does the file-organizing half of
  step 2 without Blender: it copies the source file into the target library
  subfolder and, if the file is not already `.blend`, attaches a `notes`
  entry saying a Blender import pass is still needed before Browse will see
  it. It never invokes Blender itself — this environment's ground rules for
  this task exclude that, and more importantly, a background import should
  be a visible, resumable step the user can see happen, not something that
  silently runs during a file copy.

**3. Land in library.** Once a `.blend` exists under the configured library
root, in a subfolder, it needs zero further integration — `library.dart`'s
existing directory walk derives its category from that subfolder exactly as
it does for anything the user drops there by hand. A reasonable default
layout:

```
<library root>/generated/<provider-id>/<slug>.blend
```

so "generated" becomes its own top-level bucket in the existing category
tree, and `<provider-id>` becomes the subcategory — e.g. `generated/meshy`,
`generated/manual`. This needs no change to `library.dart`; it is exactly
the folder convention that file already expects.

### 5.1 What happens to rigs and animations specifically

`capture.py`'s `list_clips` (tessera/blender/capture.py) looks in three
places, in this priority: an object's `animation_data.action`, every strip
on every `animation_data.nla_track`, and finally any orphaned
`bpy.data.actions` not wired to anything. Any of the three is enough for a
clip to show up — the function exists specifically because BlendKit assets
routinely carry motion as NLA strips with `action` left empty. This matters
here because it means the import step in §5 does **not** need to produce
one particular representation: whatever Blender's FBX/glTF importer does
with an incoming animation (assigns an action directly, stacks multiple
takes as NLA strips, or leaves unused actions sitting in `bpy.data.actions`)
is already something `list_clips` will find.

Two integration risks are real enough to name rather than assume away:

- **Bone-naming heuristics may not match.** `tracking_point()`'s `"root"`
  mode looks for a pose bone named exactly `root`, `hips`, `pelvis`, `cog`,
  or `torso` (case-folded, exact match) before falling back to the first
  parentless bone. Mixamo rigs prefix every bone (`mixamo:Hips`), which does
  not exact-match `hips` — this design expects it falls through cleanly to
  the parentless-bone fallback (Mixamo's Hips is typically the rig's
  parentless root), but **that fallback path was not verified against an
  actual Mixamo FBX** as part of this design; it should be checked with one
  real character before this ships.
- **`action_slot` assignment.** `capture.py`'s own comment notes that
  Blender 4.4+/5.x requires setting `action_slot` alongside `action`, or the
  assignment silently evaluates to nothing. This is already handled by
  `apply_clip` for actions the file already ships with; an import script
  that reassigns or renames actions during cleanup must preserve that same
  care, or an imported character will render as a static pose with no error
  anywhere — exactly the failure mode `capture.py`'s own docstring warns
  about.

Neither risk blocks the design; both are called out so nobody discovers
them by way of a silent bind-pose render.

## 6. Credential storage and the consent moment

**Storage.** A provider's credential lives at
`~/.config/tessera/config.json` → `generate.<provider-id>` → whatever shape
that provider needs (typically `{"api_key": "..."}`). This is the same file
`Config.load()` already reads for library and render-host settings — no new
file, no new location, no key ever written by this codebase as a default.
The Settings dialog (`_openSettings` in `main.dart`, unmodified by this
design) is the natural place a future implementation would add a per-provider
key field, following the same "load existing json, set one field, write it
back" pattern `_saveSettings` already uses.

**Consent.** Configuring a key is necessary but not sufficient to run a
network provider. Every `run()` call on a provider with `callsNetwork ==
true` must be preceded, in the same user gesture, by an explicit
confirmation naming the destination and what leaves the machine — e.g.
*"Send this prompt and reference image to Meshy? This leaves your machine."*
— with the affirmative action labelled with the provider's name, not a bare
"OK". No such prompt fires from typing in a field, selecting a provider from
a list, or the tab simply being open; it fires only on the action that would
actually make the call. A "don't ask again for this provider" option is
reasonable to offer, persisted per-provider in the same config file — but
never on by default, and never bundled as "don't ask again for anything."

**Never gated on presence of a key.** Whether the consent prompt appears is
decided by `callsNetwork`, not by whether `credentialConfigKey` is set —
this keeps a future bug (a provider that reads a key without needing one
yet) from silently downgrading a consent requirement.

## 7. Failure and offline behaviour

- **No config at all**: the tab renders every provider from
  `knownProviders`; `manual` shows `readyOffline`, everything credentialed
  shows `missingCredential` with an inline note on how to add the key (not a
  link that auto-navigates anywhere) and no network probe to "check" it.
- **Key present, service down or erroring**: the specific run fails with the
  provider's own error surfaced verbatim in the log pane (this app already
  has a convention for this — `_log` / the black log panel in `main.dart`'s
  `_resultPane`) rather than a generic "something went wrong." Nothing is
  written to the library folder. The cache entry for that attempt is left in
  `~/.cache/tessera/generate/...` for inspection, not deleted — mirroring
  how `CaptureRunner` already treats a failed capture.
- **Partial success** (e.g. Meshy returns a mesh but rigging fails): treated
  as a failure of the *whole* request from the library's point of view — no
  half-finished asset lands in a folder the browser will show. A future
  version could offer "keep the mesh, skip rigging" as an explicit choice,
  but that is a user decision each time, never a silent default.
- **Rate limiting / quota exhaustion**: surfaced as the failure message
  verbatim (Meshy and Tripo both return structured errors for this); no
  automatic retry loop — an agent or a UI that retries a rate-limited call
  in a loop is exactly the kind of implicit repeated network access this
  design is supposed to prevent.
- **Manual import of a bad file**: `ManualImportProvider` checks the
  extension before copying and fails cleanly on anything unrecognised; it
  does not attempt to sniff or validate FBX/glTF *content*, since it has no
  way to open one without Blender.

## 8. What is deliberately NOT in this slice

- No UI. `main.dart` is untouched; there is no tab to click.
- No network client code for any credentialed provider — see §4 on why the
  descriptors are data rather than stub HTTP calls.
- No Blender import script (`import_asset.py` in §5) — a real requirement,
  called out rather than built, since building it means running Blender to
  verify it, which this task's ground rules exclude.
- No OAuth flow for Sketchfab.

## Recommended first slice

The smallest version of this tab that is genuinely useful, in build order:

1. **Ship `ManualImportProvider` behind a real tab.** One panel: a file
   picker, a target-subfolder field (defaulting to `generated/manual`), an
   Import button, and the existing library refresh already triggered by
   `_boot()` after a settings save. This alone turns "download a Mixamo FBX,
   then go find it in a Finder window and drag it into the right folder"
   into two clicks, for every manual-only source in the table (Mixamo,
   Quaternius, Sketchfab-by-hand, or literally anything else) — with zero
   credentials, zero ToS exposure, and zero new dependencies.
2. **Write the Blender import script** (`tessera/blender/import_asset.py`):
   given an FBX/GLB path, import, save as `.blend` alongside it, and print
   a `list_clips`-style summary so the user sees immediately whether
   anything animated came through. Wire `ManualImportProvider`'s "still
   needs a Blender pass" note (§5) to a button that runs it. This closes the
   only gap between "imported" and "shows up in Browse" for every source in
   this design, generator or manual.
3. **Add one credentialed provider: Meshy.** It is the only researched
   service that can plausibly produce a rigged, animated character in one
   API-backed pass (§3.2), which is the actual thing "Mixamo, but for
   generated models" promises. Build the consent prompt (§6) and the
   readiness/failure states (§7) against this one real provider before
   generalizing to Tripo or Rodin — the interface in `provider.dart` should
   not need to change to add them once Meshy is proven out.

Explicitly **not** in the first slice: Sketchfab (OAuth flow is real work
for a source that's "nice to have," not core), Rodin/Tripo/Sloyd (additive
once the Meshy path is proven, and Sloyd's API access needs re-verifying
regardless), and Poly Haven (low effort, but doesn't serve the stated
"characters and animations" use case — worth adding opportunistically, not
worth sequencing ahead of Meshy).

## Could not verify

- **Sloyd's current API availability.** Public documentation encountered
  during research stated API signups were paused as of a date that had
  already passed at review time. Descriptor included regardless because the
  service's fit (game-ready, rigging, `.blend` export) is strong enough to
  be worth re-checking, not because availability was confirmed.
- **Whether a Mixamo FBX's bone names actually fall through
  `tracking_point()`'s parentless-bone fallback cleanly** (§5.1) — reasoned
  through from `capture.py`'s source, not tested against a real file, since
  this task's ground rules exclude running Blender.
- **Whether Meshy's exported animation clips land as one `bpy` action per
  clip or need splitting on Blender import** (§3.2) — would require a Meshy
  account and a real export to check.
- **Kaedim's and Luma Genie's exact API terms and rate limits** — both sit
  behind quote-only or thin public documentation; verdicts above are
  necessarily coarser than Meshy/Tripo/Rodin's.

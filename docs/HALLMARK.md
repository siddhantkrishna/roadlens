# ROADLENS Hallmark redesign

## Starting point and scope

Base: `6866f82f50648021c161d5d3d67d2310897f8402`, the latest `main` with successful
Intel CI and packaging checks at the start of this work. The earlier unmerged
`568eb8d` redesign is preserved on `codex/native-ui-redesign`; suitable tested
widgets can be reused without adding that entire commit to this branch.

The installed Hallmark 2.0.0 skill and its redesign, app-screen, craft, states,
dark-mode, data-visualization and gate references govern the work. Upstream:
https://github.com/Nutlope/hallmark. This is an original native Qt adaptation,
not a web-theme import. No CSS/HTML linter will be presented as a Python UI check.

## Before audit

Authentic Qt captures were generated with `scripts/capture_screenshots.py` using
only the public Intel fixture. Originals are retained locally under
`artifacts/hallmark-before/` until the reviewed comparison images are published.
The source and screenshots show these concrete problems:

| Finding | Evidence | Intended repair |
| --- | --- | --- |
| Too many competing actions | Monitor source rail presents ten source/playback actions | Source selection and playback near the video; secondary management elsewhere |
| Video is obscured | Pipeline and analytics paint diagnostic strips across the frame | Compact labels and geometry; diagnostics outside the image |
| Technical configuration first | Scene editor begins with kind, ID and deadband fields | Choose measurement, draw, Save; advanced properties disclosed |
| Dense default measurements | Two tables and four metric cards occupy Monitor continuously | Count, flow and conditions first; secondary tables on request |
| Inconsistent hierarchy | Cyan wordmark, green figures, repeated frames and uppercase labels | One accent; sentence-case labels; whitespace and shared typography |
| Scattered appearance values | Colors/fonts occur in desktop, previews and charts | Central roles for QSS, painting and icons |
| Missing focus treatment | Original stylesheet has no explicit keyboard focus rule | Instant focus treatment without a layout shift |
| Dense Analysis | Session IDs, clock metadata, raw events and charts compete | Session selector, measured charts, readable records |

These correspond to applicable Hallmark gates 26a, 48, 63 and 67 and the app-screen
hierarchy/state guidance. No browser gate score or physical-camera result is
claimed. Existing camera identity, capture/inference workers, analytics,
configuration precision, SQLite schema, report contents and licensing stay.

## Native interpretation

- Theme blocks are Python color/typography tokens; QSS consumes those tokens.
- Native layouts, scroll areas and aspect-preserving rectangles replace CSS grids
  and overflow rules. Qt logical pixels and device-pixel-aware icons support scaling.
- No decorative animation is introduced. Focus and state changes are immediate.
- Native labels, buddies, accessible names/descriptions and shortcuts replace ARIA.
- Charts use real measurements, zero baselines, units and explicitly missing data.
- Hardware permissions, VoiceOver and long-run thermal behavior remain manual
  unless physically exercised and recorded.

## Milestones and verification

The requested 40 milestones are committed individually, immediately after their
scoped checks. `artifacts/hallmark-milestones.tsv` preserves each hash, description
and validation-log filename. The final count is verified with:

```sh
git rev-list --count 6866f82..HEAD
git log --reverse --format='%h %s' 6866f82..HEAD
```

## Screenshot review and corrections

The final images were captured with the macOS **Cocoa** platform, at native
Retina resolution, by `scripts/capture_screenshots.py`. They exercise real ONNX
inference and the public 12-frame recording; no detections, counts or sessions
were invented. Local review also covered 880-, 1280- and 1920-point windows,
expanded details, checked controls, and Analysis/Settings/editor dark variants.
Those extra captures stay in ignored `artifacts/hallmark-review-final/`.

Native screenshot inspection found issues that headless size-hint tests missed:
header overlap, content shrinking toward its size hint, missing progress text,
and custom charts inheriting the OS palette despite an explicit light setting.
Expanding capped layout rows, a fixed brand label, noncollapsing status labels,
and propagated semantic appearance roles repair these. Regression tests cover
content width, brand separation, child colors and visible control state.

An independent read-only review named five additional concrete findings. Its
single confirmation round on corrected native captures marked all five resolved:

| Finding | Correction |
| --- | --- |
| Unchecked boxes disappear into the surface | Visible semantic border and checked mark, preserving native checkbox interaction |
| Drawing mode unclear at entry | Selected congestion tool and explicit drawing instruction |
| Generic line label loses measurement identity | `upper` is visible on the canvas and in the measurement list |
| Session timestamp truncates the zone | Readable timestamp explicitly ends in UTC |
| Completed short session still says Observing | Display says Insufficient data with a measurement explanation |

Geometry names now use contrast plates over footage and Save has primary action
emphasis. Heatmap colors remain the existing scientific intensity encoding;
they do not decorate application chrome. Analysis deliberately scrolls vertically
when its measured charts and records exceed the viewport. No horizontal scrolling
is required at the supported minimum window size.

| Workspace | Before | After |
| --- | --- | --- |
| Monitor | [Baseline](images/monitor-before.png) | [Redesigned](images/monitor.png) |
| Analysis | [Baseline](images/history-before.png) | [Redesigned](images/history.png) |
| Configure road | [Baseline](images/scene-editor-before.png) | [Redesigned](images/scene-editor.png) |

Additional captures: [Settings](images/settings.png), [dark Monitor](images/monitor-dark.png).
Hashes, public footage provenance and licensing for all captures are recorded in
[public-assets.json](public-assets.json). The reviewer confirmation covered the
five named findings; it is not a claim of exhaustive interaction, VoiceOver or
physical-camera validation.


## Final verification (2026-10-31)

- Complete suite: **154 passed, 1 skipped** (the opt-in physical camera test).
  Real ONNX and public recorded-video integration tests ran; no weights were
  missing and no model checks were skipped.
- Ruff lint and format: pass across 42 Python files. `pip check`: pass.
  Bandit: no findings at the medium severity/medium confidence gate. Locked
  dependency audit: no known vulnerabilities across 35 dependencies.
- The public-source allowlist, reviewed asset hashes, offline secret scan and
  staged/working equality check pass. Private files and generated binaries stay
  ignored. Screenshot metadata contains only display DPI.
- PyInstaller rebuilt the approximately 262 MiB Intel `ROADLENS.app`; nested
  helper signing and `codesign --verify --deep --strict` pass. The packaged Cocoa
  executable launched from `/tmp`, completed the 12-frame public recording,
  exited 0 and saved the expected one car crossing in SQLite.
- Source distribution/wheel build and content inspection pass. Packaging includes
  all reviewed comparison/settings/dark screenshots in the source distribution,
  and all native desktop modules and required original notices in the wheel.
- The traffic analyzer, statistical services and SQLite schema are unchanged.
  The necessary pipeline changes implement nonblocking playback pause/resume and
  clean raw-image delivery, with continuity and worker-lifecycle regression tests.

Hardware prompts/capture/reconnect, VoiceOver, sustained thermal behavior and
Apple Silicon remain manual checks. Local builds are ad-hoc signed, not
notarized. The model's exact preferred-source/export provenance still gates any
public app/model distribution; the source-only branch and PR include neither.

Launch from the project directory:

```sh
.venv/bin/python -m roadlens.desktop
# Build, then launch the standalone app:
.venv/bin/python scripts/build_app.py
open dist/ROADLENS.app
```

Manual camera steps: start a real camera and accept the macOS prompt; if denied,
enable ROADLENS / ROADLENS Camera (or the launching terminal during development)
in System Settings → Privacy & Security → Camera, then restart capture. An iPhone
also needs Continuity Camera enabled and Apple's normal account/connectivity
requirements. None of these permission steps were exercised by the automated run.

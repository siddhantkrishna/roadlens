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

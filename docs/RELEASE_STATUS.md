# ROADLENS source-release verification

Verified 2026-10-29 on Intel macOS, CPython 3.14.7. Repository:
[siddhantkrishna/roadlens](https://github.com/siddhantkrishna/roadlens).

## Local checks

- **123 passed, 1 skipped** in the complete suite. Real ONNX/recorded-footage
  tests ran. The skipped test requires explicit access to a physical camera.
- Lint, formatting and `pip check` pass. The original vision/tracking and
  traffic intelligence algorithms, database schema and existing tests remain.
- Regression coverage includes compact bounded labels, narrow/long-name layouts,
  scene IDs and save/reload, native cancellation, duplicate camera names,
  restart state, camera-filtered history, invalid preferences/heatmaps, PNG
  overwrite protection, diagnostic selections and exact staged-source scanning.
- Bandit has no medium/high-severity findings at the configured confidence gate.
  Its low-severity subprocess notices are argument-list calls without a shell.
  The SQL identifier suppression covers an explicit literal table allowlist.
- `pip-audit` reports no known advisories for all 35 locked dependencies.
- Secret/privacy checks cover the exact source candidates and reject any staged/
  working mismatch, private paths/types, unreviewed binary assets and symlinks.
  Only exact reviewed public checksums are entropy exceptions. Public screenshots
  show real inference on the licensed Intel fixture, with no personal feed,
  device identifier or local path. They retain only display-DPI metadata.
- Two independent offline pipelines each processed all 12 public-fixture frames
  with zero capture drops in 2.612 seconds; peak process RSS was 419.2 MiB in
  that short run. This is not live-camera or sustained thermal/load validation.
- SQLite counts, occupancy, flow, queues, baseline availability and actual dwell
  remain source/session scoped. The reviewed fixture produces one car crossing
  in `image_up`; absent calibration is not replaced with guessed physical speed.

Generated reports, model-inspection tooling, recordings, databases, app bundles
and archives remain under ignored local directories. Git source contains only
reviewed media and source. No app/model artifact is uploaded by the workflows.

## Packaging and publication

The Intel app build is verified locally with PyInstaller, nested helper signing
and `codesign --verify --deep --strict`; packaged recording smoke tests exercise
its real CPU inference and SQLite lifecycle. This bundle is for local verification,
not a public download. The manual GitHub packaging workflow performs the same
kind of ephemeral verification and deliberately uploads no model or app.

Source distribution/wheel metadata include AGPL-3.0-only and LICENSE/NOTICE;
source archives include the public fixtures, screenshots, tests and build scripts.
Use [RELEASING.md](RELEASING.md) to reproduce validation, inspect archive contents,
create a commit and publish source without force-pushing. Actual remote commits
and hosted check status are authoritative on
[GitHub Actions](https://github.com/siddhantkrishna/roadlens/actions).
This document records local checks rather than inventing a hosted CI result.

## Genuine limitations

Physical camera permission prompts, iPhone/webcam reconnects, Apple Silicon and
extended thermal/load behavior are not claimed. Native discovery/helper builds
may take until their bounded calls return during cancellation; Qt does not block.
The explicit OpenCV camera fallback cannot guarantee interruption of a wedged
external driver. Diagnostics and errors report these operational states.

Public app/model distribution remains blocked: the pinned file's embedded AGPL,
producer/version/date/shape metadata were read and its hash verified, but its
original editable checkpoint and exact export chain have not been independently
established. See [MODEL_PROVENANCE.md](MODEL_PROVENANCE.md) and
[LICENSING.md](LICENSING.md). Publish the verified AGPL source separately;
exclude weights and generated apps until corresponding-source and redistribution
obligations are resolved. Local app builds are ad-hoc signed, not notarized.

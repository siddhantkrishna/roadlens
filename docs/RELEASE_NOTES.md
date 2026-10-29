# ROADLENS 0.1.0 — source release

Native PySide6 desktop over local OpenCV/ByteTrack vehicle vision and traffic
intelligence, with no cloud inference or web application.

- MacBook/available Continuity Camera and video sources; bounded worker pipelines.
- Compact vehicle labels, readable/resizable tables and improved operational states.
- Road/lane/queue/exclusion editing with validated save/reload and counting lines.
- Directional counts, occupancy, queues/congestion, calibrated-speed availability,
  baseline anomalies, measured flow, dwell heatmaps and session history.
- Local SQLite and PDF/CSV/JSON/PNG export paths, with overwrite protection.
- Cancellation, source identity, corrupt-history and configuration regression fixes.
- AGPL-3.0-only original source, dependency/media notices and explicit model provenance.
- Secret/privacy gate, dependency auditing, tests and an Intel packaging check workflow.

Install from source using the [README](../README.md). No downloadable app/model is
published with this release. Model files remain a separate, explicit acquisition;
public app/model redistribution still requires the evidence listed in
[LICENSING.md](LICENSING.md). Local app builds are ad-hoc signed, not notarized.

Camera permission prompts, physical iPhone/webcam reconnects, Apple Silicon and
extended thermal/load tests are not claimed. Missing calibration and insufficient
anomaly history remain explicitly unavailable; no measurements are fabricated.

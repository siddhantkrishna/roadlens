# Current release verification

The current source release passes **154 tests** with **one opt-in physical camera
test skipped**. See [release verification](docs/RELEASE_STATUS.md),
[audit repairs](docs/AUDIT.md), and [model provenance](docs/MODEL_PROVENANCE.md).
The Hallmark redesign also passed native Cocoa screenshot review, real packaged
recording inference from outside the checkout, and strict ad-hoc signature
verification. Its 40 milestones preserve the existing analyzer and SQLite schema.
No new physical-camera, VoiceOver or sustained thermal validation is claimed.

The previous stage records below are historical; their counts are not current.

---

# Step 3 desktop verification

Verified 2026-10-29 on macOS 26.6.2, Intel x86_64, CPython 3.14.7,
PySide6 Essentials 6.12.0 and PyInstaller 6.22.3.

- Complete suite: **86 passed, 1 skipped**. The skip is the explicitly opt-in
  physical camera test; real ONNX/recorded-footage tests were included.
- Ruff lint and formatting pass for `src`, `tests` and `scripts`. `pip check`
  reports no broken requirements. The outstanding Step 2 E501 was fixed.
- Qt tests cover normalized pointer/keyboard scene editing, geometry validation,
  source imports, camera-discovery failure, settings/preferences validation,
  bounded camera-filtered SQLite reads, responsive worker execution, orderly
  close, frozen helper lookup and preference paths after moving the app.
- A real video runs through the actual Qt controller, existing capture/DNN/
  ByteTrack/traffic services and SQLite. It processes all 12 fixture frames;
  its one `car` crossing in `image_up` matches the reviewed scene. A simultaneous
  missing-video pipeline fails visibly while the good pipeline completes.
- CSV and JSON export all six session tables; native PDF export is exercised
  through its Qt worker. Existing PDF destinations are rejected. Monitor,
  history, settings, scene editor and the rendered two-page PDF were visually
  inspected. Evidence is under `artifacts/desktop-qa/` (gitignored).
- `scripts/build_app.py` produces a self-contained, approximately 262 MB Intel
  `dist/ROADLENS.app`. `codesign --verify --deep --strict` passes, including the
  embedded AVFoundation helper. The app contains the checksum-verified model,
  Qt frameworks/plugins, Python, CPU vision libraries, an icon and licenses.
- The packaged executable was launched from `/tmp`, outside the checkout,
  in both Cocoa/native-window and offscreen modes. Both recording smoke tests
  exited 0 and persisted a completed SQLite session with the expected one-car
  crossing and real observed dwell. No system Python or source model path is
  used by the bundle. The font cache persists between bundle launches. A copied app at
  `/tmp/roadlens-installed-step3/ROADLENS.app` also completed the recording
  check with the same result. LaunchServices startup and the native video-import
  dialog were exercised separately without opening cameras.

No physical camera was opened for Step 3 validation. Permission prompts,
MacBook/iPhone simultaneous live capture, disconnect/reconnect, negotiated
formats and extended CPU/memory/thermal behavior still require manual checks.
The bundle is ad-hoc signed, not Developer ID signed/notarized, and Apple Silicon
was not validated. Installation, launch/build commands and manual camera steps
are in [DESKTOP.md](DESKTOP.md).

The earlier stage's verification record follows; hardware observations below
are historical and were not repeated as part of Step 3.

---

# Verification on this machine

Verified 2026-10-29, macOS 26.6.2, x86_64, CPython 3.14.7, OpenCV 4.13.0
(Cocoa GUI and AVFoundation), Supervision 0.25.1. No PyTorch or Python Objective-C
bindings are needed.

- Real YOLOv8n ONNX weights loaded, warmed up, and passed SHA-256 verification.
  The real bus-photo test detects a bus above 0.6 confidence; the empty-image
  test produces no detections.
- The standard suite passed **35 tests**, including actual ONNX inference,
  recorded traffic with tracked cars and nonzero direction vectors, independent
  simultaneous pipelines, and source failure isolation. **One opt-in hardware
  test is skipped** during the standard run.
- The opt-in hardware test passed separately against the built-in FaceTime HD
  camera. Native discovery identified both the built-in camera and an iPhone
  with `AVCaptureDeviceTypeContinuityCamera`.
- The local preview successfully ran both real camera pipelines simultaneously:
  10 inference frames per source, no reconnects, and clean worker shutdown.
  Capture slots discarded superseded frames instead of accumulating a queue.
  No camera images were saved during this verification.
- The bundled real traffic excerpt processed all 12 frames in offline mode with
  no capture drops. A separate GUI preview run checked the recorded-video path.
  Annotated verification images are in `artifacts/traffic-check/` (gitignored).
- Ruff lint/format checks and `pip check` passed.

Physical iPhone unplug/replug and extended thermal/load testing were not performed.
The reconnect fault test covers absent-device retries and cancellation; timestamp
gap tests cover tracker resets. Camera availability and permissions remain macOS
responsibilities. Direction and velocity use image coordinates; road-speed
measurement would require calibration.

OpenCV's Intel wheel uses AVFoundation for some codecs. The execution sandbox
could not discover hardware cameras or decode the downloaded H.264 sample;
both worked when run normally outside the sandbox. The bundled Motion JPEG
fixture also works inside the sandbox. Run the app from a normal local terminal
with camera permission for hardware verification.

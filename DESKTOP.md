# ROADLENS native desktop (Step 3)

Requires Intel macOS 14 or later. The PySide6 interface runs on the main thread;
the existing Python capture and inference workers run independently for each
source. Qt worker threads handle discovery, database history and exports. There
is no web server, browser interface, cloud inference, account or runtime download.

## Launch from this checkout

```sh
cd /path/to/roadlens
.venv/bin/python -m pip install -e '.[dev,build]'
.venv/bin/python -m roadlens.desktop
```

The installed GUI entry point is `.venv/bin/roadlens-desktop`. The original
`roadlens run`, `report`, `export`, `heatmap`, scene and footage validation
commands still work. To load a Step 1/2 TOML configuration:

```sh
.venv/bin/roadlens-desktop --config roadlens.toml
```

TOML relative paths retain their existing working-directory semantics. The
desktop saves absolute paths when importing configuration through its menu.

## Use the desktop

- **Monitor:** Discover cameras, add the actual MacBook/iPhone by native device
  identity, and start one source or all sources. Discovery does not start capture.
  All previews appear together; selecting a source selects its statistics.
  Import videos with the button or Command+O. Imported recordings process every
  frame without pacing, using video timestamps; TOML can select paced playback.
- **Configure scene:** Start a source, stop it on an informative frame, then
  configure geometry. Select road/lane/queue/exclusion polygons or a counting
  line; click points, drag vertices, set an ID and direction labels, then Apply.
  Select existing geometry to edit/delete it. Undo removes the last vertex.
  Keyboard: arrows move the selected vertex, Backspace deletes it, Enter applies,
  Escape clears the draft. Save also validates and applies a current draft. Invalid drafts stay open. You can
  also load an existing scene JSON, including calibration. Invalid polygons,
  duplicate IDs and invalid lines are rejected by the existing scene models.
- **Scene lifecycle:** Changes apply on the next Start, which creates a new
  analysis session with an immutable scene copy. Existing sessions keep their
  original geometry/settings. Scene files and their calibration are preserved;
  physical speed remains unavailable until measured calibration is verified.
  Loading verified calibration JSON is the calibration workflow; no calibration
  is inferred from the preview.
- **Live statistics:** Visible tracks, line/category/direction crossing counts,
  image occupancy, per-zone queues and congestion come from the existing traffic
  analyzer. The queue card shows the largest zone queue, since overlapping zones
  can contain the same vehicles. Missing geometry shows unavailable metrics.
- **History and analysis:** Local SQLite sessions, camera filter, directional
  counts, measured flow charts, saved dwell heatmaps, and events including queue,
  stall, congestion and baseline anomalies. Use the Flow series selector to inspect one line/direction/vehicle class.
  Flow updates when measured windows
  are written (10 seconds by default), and a partial window is saved on Stop/EOF.
  Dark-to-bright heatmap color means zero to the displayed observed
  vehicle-seconds/cell maximum. No camera image is saved with the heatmap.
  The UI displays at most 200 sessions, 200 events and 240 windows per read.
- **Export:** Select a history session, choose PDF/CSV/JSON, then export.
  PDF is a paginated session summary with counts, recent windows/events and a
  heatmap. CSV/JSON use the existing service to export all six tables for that
  session. Each CSV/JSON operation creates a new folder; PDF and PNG refuse to
  overwrite existing files. All exports run off the UI thread.
- **Settings and diagnostics:** Model/database selection, negotiated camera
  resolution/FPS, inference cap, CPU threads, detector thresholds, retention,
  traffic windows and queue/congestion settings. Stop all sources before Apply. Loaded numeric values retain their exact precision
  until that field is edited; tooltips show the exact configured value.
  Diagnostics show source state, resolved device ID, FPS, inference duration,
  frame age, capture drops, reconnects, processed frames, errors and local paths.

Default data location:

```text
~/Library/Application Support/ROADLENS/
  desktop.json             saved settings and sources (no auto-start)
  traffic.sqlite3          SQLite/WAL traffic records
  scenes/                  immutable scene revisions
  logs/roadlens.log         rotating diagnostics
```

Choose an existing Step 2 SQLite database in Settings, then Apply, to continue
using its history. The desktop does not copy or replace that database. It uses
its existing schema and retention behavior: finalized sessions older than the
configured retention are pruned on the next analysis start. Export valuable
history before reducing retention. The normal default remains 7 days.
`--data-dir /absolute/path` isolates preferences, logs and the default database.
An unreadable/invalid preferences file produces a startup error; recover it
manually rather than having ROADLENS discard it.

## Build and install the standalone Intel app

Build on an Intel Mac with this environment and the checksum-verified local
model. The packaging step compiles and includes the native AVFoundation helper;
the installed app does not require Python, pip, a compiler or network access.

```sh
cd /path/to/roadlens
.venv/bin/python -m pip install -e '.[dev,build]'
.venv/bin/roadlens fetch-model  # only if models/yolov8n.onnx is absent
.venv/bin/python scripts/build_app.py
open dist/ROADLENS.app
```

The build uses PyInstaller's native app bundle support and Qt hooks. Python, Qt
frameworks/plugins, CPU vision dependencies, the ONNX model, camera helper,
icon, instructions and installed third-party license notices are included.
Matplotlib (a Supervision import dependency) uses a persistent font cache in
`~/Library/Caches/ROADLENS/matplotlib`; the first launch may take longer while
macOS fonts are indexed.
The build verifies the model hash and checks the resulting ad-hoc signature with
`codesign --verify --deep --strict`. Build outputs are gitignored. To install,
quit the app and drag `dist/ROADLENS.app` to `/Applications`, then open ROADLENS
from Finder/Spotlight. User data is outside the bundle and survives replacement.

The local bundle is **ad-hoc signed**, not notarized. For another Mac, transfer
it as an archive preserving symlinks (`ditto -c -k --sequesterRsrc --keepParent
 dist/ROADLENS.app ROADLENS.zip`). macOS may require Finder → right-click → Open
or System Settings → Privacy & Security → Open Anyway for a trusted local build.
Public distribution needs an Apple Developer ID, signing/notarization and review
of model/Qt distribution terms; see THIRD_PARTY.md. This Intel bundle is not a
validated Apple Silicon build.

## Camera permissions and iPhone

Start a camera and accept the macOS prompt. If denied, go to **System Settings →
Privacy & Security → Camera**, enable **ROADLENS / ROADLENS Camera** (or the
launching Terminal/Codex app when developing), and restart capture. The nested
camera helper includes `NSCameraUsageDescription` and explicitly opts into
Continuity Camera; so does the outer app. The source shows connecting/reconnecting
and frame age rather than presenting an old frame as a healthy live feed.

For iPhone: enable **Settings → General → AirPlay & Continuity → Continuity
Camera**, use the same Apple Account with two-factor authentication, enable
Wi-Fi/Bluetooth, and keep the phone nearby, locked and mounted. A trusted USB
cable is supported by macOS. Device availability is controlled by macOS; absent
hardware cannot be simulated or made available by camera-index scanning.

## Intel performance and verification

Default: 1280×720 request at 15 capture FPS, 640 model input, 8 inference FPS per
source, 2 OpenCV threads. Use two simultaneous feeds as a starting point and
reduce capture size/inference cap if CPU/thermals demand it. Each source retains
one pending capture and one pending inference result; Qt polls the latest result
at 60 ms. Charts and tables have bounded read sizes. Source-local model/tracker
instances preserve isolation. Stop and window close request cancellation without
joining on the Qt thread; the window stays open until workers finalize their
sessions. Native discovery/helper compilation can delay cancellation until their
own bounded subprocess calls return; a cancelled discovery never opens a camera. A wedged external driver can still delay shutdown, particularly the
explicit OpenCV camera fallback documented in README.md.

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
.venv/bin/ruff check src tests scripts
.venv/bin/ruff format --check src tests scripts
.venv/bin/python -m pip check

# Real recorded-video desktop smoke test, without opening hardware:
QT_QPA_PLATFORM=offscreen .venv/bin/python -m roadlens.desktop \
  --data-dir artifacts/desktop-smoke --smoke-test assets/traffic.avi \
  --scene assets/traffic.scene.json

# The same test through the packaged executable, from any working directory:
QT_QPA_PLATFORM=offscreen dist/ROADLENS.app/Contents/MacOS/ROADLENS \
  --data-dir /tmp/roadlens-bundle-check \
  --smoke-test /path/to/roadlens/assets/traffic.avi \
  --scene /path/to/roadlens/assets/traffic.scene.json
```

The automated suite never opens physical cameras. Validate permission prompts,
MacBook/iPhone simultaneous capture, unplug/replug, resolution negotiation,
long-run CPU/memory/thermals and Finder launch on the target Mac manually.

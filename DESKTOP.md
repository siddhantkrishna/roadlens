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

- **Monitor:** Select a source beside the video. **Import video** (Command+O)
  reads a real first frame on a worker; **Sources…** opens camera discovery and
  source management. Find/Add uses native device identity and does not open the
  camera until Start. All sources exposes simultaneous previews. Start/Pause/
  Resume/Stop control the selected source. Offline recording pause retains every
  frame; live resume resets tracking after the gap. Camera Connecting, stale,
  reconnecting, failure and completion states are explicit.
- **Configure road:** Use clean footage, with optional detections. Count vehicles
  draws a two-point line; Measure congestion draws a road polygon. Select a shape
  or drag its vertices. Enter applies a draft; Save validates and applies it.
  Invalid drafts stay open. Undo reverses applied geometry, drags and deletion;
  Command+Z is scoped to the canvas, preserving normal text-field undo. L/R selects
  the drawing tool, arrows nudge, Escape clears a draft, and Command+Backspace
  deletes a measurement. Advanced exposes IDs, line directions, other polygon
  types, validated JSON import and verified calibration editing. Original scene
  schema and numeric precision are preserved.
- **Scene lifecycle:** Changes apply on the next Start, creating a new session
  with an immutable scene/settings snapshot. Existing sessions retain their
  original configuration. No calibration or geometry is inferred from footage.
- **Measurements:** Count means observed crossings, not global unique vehicles.
  Traffic flow selects one counting line rather than summing overlapping lines.
  Conditions require appropriate geometry and observation time; insufficient data
  remains explicit. Details provides per-zone measurements and operational state.
- **Analysis:** Select a saved session, then a line/direction/class for flow.
  Windows represent actual observed time (10-second target by default; partial
  window finalized at Stop/EOF). Separate condition selectors show occupancy (%),
  congested time (%) or queue (vehicles). The class view uses a number when only
  one class is present. Dwell legends use vehicle-seconds/cell or vehicle-seconds/
  m² when the stored grid is physically calibrated. A heatmap is not a saved
  camera photograph. Crossings, queues and anomalies opens filterable readable
  records. Reads remain bounded to 200 sessions, 200 events and 240 windows.
- **Sessions and comparison:** Camera filtering and compatible finalized-session
  comparison preserve source/scene/analysis/clock identity. Totals explicitly
  acknowledge differing durations; incompatible sessions are not compared.
- **Export:** Choose Export… in Analysis for PDF/CSV/JSON. PDF is paginated;
  CSV/JSON export all six session tables into a new folder. PDF/PNG refuse to
  overwrite existing files. Workers keep the UI responsive and completion offers
  Show folder. Existing raw service exports remain unchanged.
- **Settings:** Appearance (System/Light/Dark), Camera, Performance, Storage,
  Detection and traffic thresholds, Privacy and diagnostics, Import configuration.
  Save settings requires stopped sources; Revert changes reloads saved values.
  Loaded numbers retain exact precision until edited. Camera settings distinguish
  requested sizes/rates from actual received format. Diagnostics use measured
  FPS, inference time, frame age, drops, reconnects, frames and peak process RSS.
  They include private local paths/device IDs: review before sharing. Focus pauses
  diagnostic text refresh for copying.
- **Keyboard/accessibility:** Command+1/2/3 opens Monitor/Analysis/Settings;
  Command+L focuses source selection; Command+, opens Settings. Native menus,
  accessible names/descriptions, label buddies, visible focus and logical Tab
  order support keyboard use. Automated keyboard/scale checks are not a substitute
  for manual VoiceOver validation. No animation is needed for state transitions.

Default data location:

```text
~/Library/Application Support/ROADLENS/
  desktop.json             saved settings and sources (no auto-start)
  appearance.json          system/light/dark preference
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

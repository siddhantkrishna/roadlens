# Local traffic intelligence

ROADLENS preserves the camera/detector/ByteTrack engine and adds analytics after
tracking. Analytics run when a source has a scene file or a SQLite database is
configured. Without either, the original vision-only commands behave as before.
No additional Python dependencies, server or network service are needed.

## Run the real, reviewed example

From the repository with `.venv` active:

```sh
roadlens run --video assets/traffic.avi --offline \
  --scene assets/traffic.scene.json --database data/traffic.sqlite3
roadlens report --database data/traffic.sqlite3
roadlens export --database data/traffic.sqlite3 --format json --output-dir artifacts/json
roadlens export --database data/traffic.sqlite3 --format csv --output-dir artifacts/csv
```

`report` lists camera histories, session IDs and observed crossing events. Use
`--camera CAMERA_ID` to restrict reports/exports, or `export --session SESSION_ID`
to export one analysis run. Existing export files are never overwritten.
The CSV contains one file per table, including headers for empty tables. Nested
measurement and geometry fields remain JSON within CSV cells. JSON exports
decode these fields into structured values. Formula-like string cells in CSV
receive a leading apostrophe for safe spreadsheet opening.

Render an actual collected heatmap without a background camera image:

```sh
roadlens heatmap --database data/traffic.sqlite3 --session SESSION_ID \
  --output artifacts/heatmap.png
```

The PNG uses a relative color scale whose maximum is displayed. Its exported
grid retains the actual **observed vehicle-seconds per cell**, including real
zeros. It never creates density outside collected trajectories.

## Configure each camera's scene

```sh
roadlens scene init my-road.json
roadlens scene check my-road.json
roadlens run --camera default --scene my-road.json --database data/traffic.sqlite3
```

An initialized scene deliberately has no geometry or calibration. Edit the JSON,
validate it, then inspect its lines/polygons in the local preview. The bundled
[traffic.scene.json](assets/traffic.scene.json) is specific to the included clip;
do not apply it to another camera. `--scene` applies only to a single CLI source.
Use separate scene paths in TOML for simultaneous sources:

```toml
[[sources]]
name = "junction-west"
camera_id = "fixed-west-camera"
kind = "camera"
value = "paste-native-device-id"
scene = "west-road.json"

[[sources]]
name = "junction-east"
camera_id = "fixed-east-camera"
kind = "camera"
value = "paste-other-native-device-id"
scene = "east-road.json"

[analytics]
database = "data/traffic.sqlite3"
window_seconds = 10.0
max_gap = 2.0
stationary_speed = 0.005
stationary_seconds = 3.0
stalled_seconds = 30.0
queue_min_vehicles = 3
queue_link_distance = 0.12
queue_seconds = 3.0
congestion_occupancy = 0.5
trajectory_interval = 0.5
baseline_min_windows = 20
baseline_max_windows = 120
anomaly_z = 3.5
retention_days = 7
grid_width = 64
grid_height = 36
```

`camera_id` defaults to the source name. Use a stable explicit ID to retain a
camera's history when its display name changes. Simultaneous sources cannot use
the same camera ID. The database binds native live cameras to their resolved
device fingerprints and rejects reusing an ID for a different live device.
OpenCV indices have the original engine's hardware identity limitations; prefer
native AVFoundation IDs. A recording may be explicitly assigned to a known
camera; its source timeline and analysis session remain separate from live runs.

## Geometry and editing models

Scene coordinates are normalized **[0, 1]** with origin at the top left. Vehicle
membership/crossings use the **bounding box bottom center**, an image estimate of
ground contact. Directions and speeds from the vision tracker remain unchanged.

- `zones`: ID, name, `polygon`, and kind `road`, `lane`, `queue` or `exclude`.
  Polygons may be concave, must have positive area and cannot self-intersect,
  touch nonadjacent edges, or repeat the closing vertex. Exclusion regions remove
  anchor observations and their boxes from analytics, trajectories and heatmaps.
  They do not redact the original live preview or opt-in frame snapshots.
- `lines`: ID, `start`, `end`, `forward`, `reverse`, `hysteresis`. The endpoints
  define a **finite** directed segment. The signed side is
  `cross(end-start, point-start)`. A transition from negative to positive is
  `forward`; positive to negative is `reverse`. For a left-to-right horizontal
  line, forward points down the image. Names are configured labels, not inferred
  compass directions. Hysteresis is perpendicular distance in normalized image
  coordinates; the deadband prevents jitter-driven counts.
- `overlap_group`: optional shared road/coverage label for related cameras.
  It records a relationship; it does not establish physical vehicle identities.
- `version`: schema version 1. `revision`: positive scene editing revision.
  Unknown fields and invalid geometry fail validation.

Typed immutable editing models are in `roadlens.traffic.scene`. `Scene.with_zone`,
`with_line` and `without(..., collection="zones" | "lines")` return a new revision;
`Scene.save` atomically saves JSON. `Zone`, `CountingLine`, `Calibration` and
`Scene.from_dict` validate edits before they reach analysis. Geometry is fixed
for an analysis session; load an edited file in a new session. The scene and full
analysis settings are snapshotted in SQLite so old sessions remain inspectable.

## Counting, lifecycle and coverage

A crossing requires observations on opposite stable sides of the line and an
intersection of the observed movement segment with the finite line. Appearing
on a line, remaining in its deadband, or crossing its infinite extension does
not count. Crossing times are the observation that confirms the side change;
the intersection location is interpolated between observed anchors.

Each session assigns a lifecycle key containing tracker epoch, temporary ID and
a monotonically increasing incarnation. A lifecycle contributes at most **one
event per line and direction**; a U-turn can contribute one event in each
direction. Event keys also have a database uniqueness constraint, making retries
idempotent. A new epoch, a gap longer than `max_gap`, expired IDs and category
changes start fresh states. They cannot bridge a crossing over an unobserved
gap. Duplicate frame timestamps are ignored; rewinding a recording requires a
new session. States and trajectories held in memory are bounded.

This is deduplication of **tracked crossing observations**, not physical vehicle
re-identification. An unresolved tracking ID switch can fragment a vehicle's
history and can still cause duplicate physical-vehicle counts. Conversely,
ambiguous fragments are never merged solely because they are nearby.

Histories and counts remain per camera and session. Cross-camera unique vehicle
totals are **always unavailable** because feeds may overlap. ROADLENS neither
sums these into unique vehicles nor invents cross-camera identities. Replaying
the same recording creates another labeled observation session; historical event
totals are event observations across runs, not deduplicated physical vehicles.

## Measurements and event definitions

Measurements use source/video timestamps, not inference execution speed. SQLite
stores wall-clock UTC analysis start/end separately; video times are never
presented as the recording's capture date.

- **Counts and flow:** counts per category, line and direction. Flow is interval
  crossings × 60 / **observed seconds**. Rates are unavailable for zero exposure.
  Flow keys are `line/direction/category`. A short interval produces a noisy rate;
  it is not a minute of actually observed traffic.
- **Occupancy:** union of detected vehicle bounding boxes clipped to each road
  zone, minus exclusions, divided by that zone's rasterized image area. The grid
  avoids double-counting overlapping boxes. Aggregates integrate the previous
  observed sample over the next valid observation interval. This is sampled
  **image occupancy**, not lane capacity or ground-area density. Empty or
  unresolved raster regions report occupancy unavailable.
- **Zones:** current per-category vehicle counts and aggregate category
  vehicle-seconds. Zones can overlap; their values must not be summed as unique
  vehicles or total road occupancy.
- **Queues:** only configured `queue` zones participate. Vehicles must remain
  below `stationary_speed` in normalized image units/second for
  `stationary_seconds`. Connected nearby anchors must reach
  `queue_min_vehicles` and persist for `queue_seconds`. Emits queue-start/clear
  events and measured queued vehicle counts. No queue length in meters is
  inferred. Tune the spatial threshold for the scene's perspective/lane layout.
- **Stalls:** a vehicle continuously below the same movement threshold for
  `stalled_seconds` in a `road` or `lane` zone emits a stalled observation once
  per episode. An active configured queue suppresses stall alarms for its
  members. Observed movement clears a stall. Loss of observations does not
  establish that a vehicle moved or remained stationary.
- **Congestion:** `observing` during stationary warmup, then `congested` for an
  active queue or occupancy above threshold with at least the configured number
  of slow vehicles; otherwise `free`. Aggregates include congested seconds.
  This is a documented scene-tuned rule, not a learned congestion ground truth.
- **Trajectories:** sampled normalized ground-anchor positions with temporary
  lifecycle keys and source times. Heatmaps accumulate dwell only when the same
  track has continuous consecutive observations. Camera/tracker gaps add no dwell.

Long observation gaps emit `observation_gap` events, close the current partial
window, reset crossing/queue/movement state, and skip missing exposure. No empty
windows, zero-flow intervals or stationary durations are filled into the gap.
The system cannot recover crossings that occurred between dropped observations;
run recordings with `--offline` for frame-complete analysis.

## Speed availability and calibration

Uncalibrated scenes report `speed_unavailable_reason` and store/export speed as
**null**, never zero. A first observation also lacks enough temporal evidence.
To enable optional planar speed, supply a `calibration` object with:

- `image_points`: at least four noncollinear normalized points on the road plane.
- `ground_points_m`: their independently measured paired 2D coordinates in meters.
- `reference_size`: `[width, height]` used for calibration.
- `verified: true`: confirmation that measurements, correspondences, ground plane,
  mounting and image geometry were checked against the actual scene.
- `max_error_m`: maximum reprojection residual (default 0.5 m).

Degenerate transforms and excessive residuals are rejected. Speed is measured
only inside the calibration's convex hull, with matching frame aspect ratio and
at least 0.2 seconds of continuous position observations. It is a ground-plane
displacement estimate in meters/second. Resize with unchanged aspect ratio is
supported; camera movement, a changed crop/zoom, lens distortion or an incorrect
ground-contact anchor invalidate the scene calibration. Recalibrate and start
a new session after such changes. No calibration is included for the sample
footage because its ground distances have not been independently measured.

## Statistical anomalies

Baselines begin empty and learn from **prior complete observation windows** for
flow, occupancy and queue counts. Until `baseline_min_windows` are available,
`baseline_ready` is false and no statistical anomalies are asserted. Partial
windows and intervals across camera gaps cannot train the baseline.

Each series uses the rolling median and scaled median absolute deviation (MAD).
A deviation must pass `anomaly_z` and a minimum absolute change: 5 crossings/min,
0.1 image occupancy, or 2 queued vehicles. A scale floor handles constant real
baselines. Anomaly events persist the observed value, prior median, robust
z-score and number of prior observations. The current observation is tested
before it is added to the baseline. Defaults require 20 earlier windows.

Baseline reuse requires the same camera, source-clock type, scene revision,
calibration, vision settings and analytics definition. Baselines are rolling
operating measurements, not seasonal/time-of-day forecasts or incident certainty.

## Database, errors and privacy

SQLite uses versioned migrations, foreign keys, WAL, full synchronous commits,
and one connection per camera worker. Initialization is coordinated across
threads/processes. Events, trajectory samples and completed measurements in an
update commit atomically. A persistence failure surfaces as a failed pipeline;
the system does not continue presenting unpersisted aggregate counts as saved.
Healthy independent camera pipelines continue.

Tables store current camera settings, session settings/scene snapshots, aggregate
measurements, detected events, sampled trajectories and cumulative dwell grids.
Settings contain source fingerprints instead of raw device IDs/video paths.
New database files are mode 0600 and new data directories are mode 0700. A small
`.init.lock` sidecar coordinates initialization. Database contents are local and
are not application-encrypted; exports are local explicit actions.

No frames, faces, license plates, audio or appearance embeddings are written by
analytics. The existing `--output-dir` preview snapshot option remains opt-in.
Completed sessions older than `retention_days` are deleted at the next analytics
startup, cascading through events, trajectories, measurements and heatmaps.
Running/unclosed sessions are retained to avoid deleting another active run;
after a crash, their `running` status means the run was not finalized. Exports
and opt-in JPEGs are outside database retention and must be managed separately.

## Accuracy validation

```sh
roadlens validate-footage --video assets/traffic.avi \
  --scene assets/traffic.scene.json --annotations assets/traffic.annotations.json \
  --output artifacts/traffic-accuracy.json
python -m pytest -q
```

The annotation file is bound to video bytes and scene geometry by SHA-256.
All 12 frames were visually reviewed: **one silver car crosses the finite line
upward between frames 3 and 5**. The real YOLO/ByteTrack/analytics pipeline found
one car crossing at source time 0.3333 seconds, with zero extra or missed
crossings on this fixture. This is a reproducible single-event check, not an
estimate of general road accuracy. Precision/recall are unavailable when their
denominators are empty; absent predictions are not treated as perfect accuracy.

The validator processes every reviewed frame without drops and matches category,
line, direction and annotated time interval one-to-one. It refuses mismatched
video/scene hashes and returns exit code 2 for count/matching disagreements.
Use the same annotation format on longer manually reviewed recordings to assess
your actual scene, including occlusion, small objects and ID switches.

Unit tests separately exercise hysteresis, finite lines, deduplication, reverse
direction, category counts, epochs, expiration, time gaps, queue/stall timing,
occupancy union, time-weighted rates, baseline warmup, known-plane speed and
SQLite migrations, transaction rollback, concurrent writers and isolation.
Queue/stall thresholds and real physical speed have not been validated against
long labeled field footage or measured road distances.

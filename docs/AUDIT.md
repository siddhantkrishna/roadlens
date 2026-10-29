# Release audit and repairs

Scope: one local Intel Core i9 / 16 GB Mac running one or two sources. Reviewed
all application entry points, camera bridge/capture, detector/tracker pipeline,
traffic geometry/counting/queue/baseline logic, SQLite writes/retention/exports,
Qt worker lifecycle, scene editor, packaging, tests and release documents.
The existing detection/tracking and traffic algorithms were retained.

## Confirmed defects repaired

| Trigger | Defect | Repair / regression coverage |
| --- | --- | --- |
| Long imported filename | Every vehicle label repeated the source/epoch and could cover the frame | Compact `Car #12 \| 0.87` labels; pixel-bounded header, line/zone and status text; annotation test |
| Narrow split table | Equal-width columns clipped headings | Header-sized minimum column widths, horizontal scrolling, elided cells with full tooltips; narrow-window test |
| Long source name | Preview title could force the layout wider than the window | Wrapping, bounded size policies and source tooltips; long-name layout test |
| Delete geometry then add another | Geometry IDs based on object count could collide | Choose the first unused ID; save/load regression |
| Save a drawn scene | Save required a separate Apply and could reject a valid pending draft | Save validates/applies the draft; invalid drafts stay open; unchanged geometry keeps its revision |
| Two physical devices with the same name | Name uniqueness rejected a distinct camera | Disambiguate display names while retaining real native device IDs and camera history identity |
| Restart a source | Last run's traffic cards stayed visible during warm-up | Reset measurements immediately; show unavailable analytics explicitly |
| Stop during discovery | A late discovery could still construct a camera capture after Stop | Check cancellation before constructing the native capture; event-driven regression opens no hardware |
| Slow native discovery during shutdown | Pipeline could finish before its native capture worker | Wait in the worker for native discovery's own bounded subprocess timeouts; Qt stays responsive |
| Filter history with an explicit session | A session from a different camera bypassed the filter | Apply camera conditions to the selected-session query too; camera isolation regression |
| Corrupt stored heatmap | NaN/negative/invalid grids could become false zero/colored pixels | Shared finite, nonnegative, bounded grid validation for UI, PDF and PNG |
| Existing PNG export path | Check-then-write could overwrite another file created concurrently | Exclusive PNG creation; existing destinations remain untouched |
| Corrupt history callback | A queued UI completion could raise outside the worker's error handling | Surface an unavailable-history state without repeated modal dialogs |
| Invalid preferences root | A JSON list/null produced an uncaught attribute error | Validate object shape and report a normal configuration error |
| Reading/copying diagnostics | Refreshing every 60 ms cleared selections and wasted redraws | Update once per second; pause while focused; preserve readable/copyable diagnostics |
| Scrolling a live table | Periodic rebuilds reset the scroll position | Batch updates and restore scroll position |
| Staged secret, sanitized working copy | Release scan read clean working bytes while the index still held different bytes | Reject index/working-copy drift; regression with a constructed fixture |

## Verified engine behavior retained

Finite, directional, hysteresis-controlled counting; per-track lifecycle
suppression; gap/reconnect resets; source/class isolation; exclusion-zone
analytics; occupancy and persistent queues; calibrated-speed availability;
observed-time flow windows; baseline warm-up; actual dwell accumulation; SQLite
atomic writes/migrations and retention; CSV formula safety; PDF/JSON/CSV exports.
The public clip still produces one reviewed car crossing in `image_up`.

Frames/results use bounded one-frame slots. UI queries are bounded and use
separate connections/workers. No abstraction or dependency replaced the working
vision or traffic service. Hardware capture and sustained thermal/load behavior
require physical verification; short recorded-video runs do not establish them.

Model metadata/provenance and source/binary decisions are documented separately
in [MODEL_PROVENANCE.md](MODEL_PROVENANCE.md). CI has read-only permissions and
pinned Actions. Packaging verification uploads no weights or app. No private
camera images or generated app binaries belong in Git.

"""Bounded desktop queries and native PDF summaries; no shared SQLite connections."""

import json
import os
import sqlite3
import tempfile
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPdfWriter, QTextLayout, QTextOption

from roadlens.traffic.service import heatmap_pixels


def qimage(image: np.ndarray) -> QImage:
    image = np.ascontiguousarray(image)
    height, width = image.shape[:2]
    return QImage(image.data, width, height, image.strides[0], QImage.Format.Format_BGR888).copy()


def heatmap_image(row: dict | None) -> tuple[QImage, float]:
    if row is None:
        return QImage(), 0.0
    pixels, maximum = heatmap_pixels(json.loads(row["grid_json"]))
    return qimage(pixels), maximum


def read_history(database: Path, camera: str = "", session: str | None = None) -> dict:
    empty = {
        "sessions": [],
        "session": None,
        "counts": [],
        "events": [],
        "windows": [],
        "heatmap": None,
        "event_total": 0,
    }
    if not database.is_file():
        return empty
    connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        sessions = [
            dict(row)
            for row in connection.execute(
                "SELECT s.*,c.name FROM sessions s JOIN cameras c ON c.id=s.camera_id "
                "WHERE (?='' OR s.camera_id=? OR c.name=?) "
                "ORDER BY s.started_at DESC,s.id DESC LIMIT 200",
                (camera, camera, camera),
            )
        ]
        selected = (
            connection.execute(
                "SELECT s.*,c.name FROM sessions s JOIN cameras c ON c.id=s.camera_id "
                "WHERE s.id=? AND (?='' OR s.camera_id=? OR c.name=?)",
                (session, camera, camera, camera),
            ).fetchone()
            if session
            else (sessions[0] if sessions else None)
        )
        if selected is None:
            return {**empty, "sessions": sessions}
        selected = dict(selected)
        key = selected["id"]
        counts = [
            dict(row)
            for row in connection.execute(
                "SELECT object_id,category,direction,COUNT(*) AS count FROM events "
                "WHERE session_id=? AND kind='crossing' GROUP BY object_id,category,direction "
                "ORDER BY object_id,category,direction",
                (key,),
            )
        ]
        events = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM events WHERE session_id=? "
                "ORDER BY source_time DESC,id DESC LIMIT 200",
                (key,),
            )
        ]
        windows = [
            json.loads(row[0])
            for row in connection.execute(
                "SELECT data_json FROM measurements WHERE session_id=? "
                "ORDER BY end_time DESC,id DESC LIMIT 240",
                (key,),
            )
        ][::-1]
        heatmap = connection.execute("SELECT * FROM heatmaps WHERE session_id=?", (key,)).fetchone()
        total = connection.execute(
            "SELECT COUNT(*) FROM events WHERE session_id=?", (key,)
        ).fetchone()[0]
        return {
            "sessions": sessions,
            "session": selected,
            "counts": counts,
            "events": events,
            "windows": windows,
            "heatmap": dict(heatmap) if heatmap else None,
            "event_total": total,
        }
    finally:
        connection.close()


def export_pdf(database: Path, session: str, output: Path) -> Path:
    """A paginated summary of a consistent database snapshot, never overwriting a file."""
    data = read_history(database, session=session)
    row = data["session"]
    if row is None:
        raise ValueError("The selected session no longer exists")
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(suffix=".pdf", dir=output.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        writer = QPdfWriter(str(temporary))
        writer.setResolution(96)
        writer.setTitle("ROADLENS Traffic Session")
        writer.setCreator("ROADLENS - local traffic intelligence")
        painter = QPainter(writer)
        if not painter.isActive():
            raise OSError("Could not initialize the PDF writer")
        page, y = 0, 0
        width = writer.width()

        def new_page():
            nonlocal page, y
            if page and not writer.newPage():
                raise OSError("Could not add PDF page")
            page += 1
            painter.fillRect(0, 0, width, 65, QColor("#102c36"))
            painter.setPen(QColor("#ffffff"))
            painter.setFont(QFont("Helvetica", 18, QFont.Weight.Bold))
            painter.drawText(20, 36, "ROADLENS / Traffic intelligence")
            painter.setFont(QFont("Helvetica", 9))
            painter.drawText(20, 54, f"Local session report  |  page {page}")
            y = 88

        def text(value: str, *, heading=False):
            nonlocal y
            painter.setFont(
                QFont(
                    "Helvetica",
                    11 if heading else 9,
                    QFont.Weight.Bold if heading else QFont.Weight.Normal,
                )
            )
            layout = QTextLayout(value, painter.font())
            option = QTextOption()
            option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
            layout.setTextOption(option)
            layout.beginLayout()
            lines = []
            while True:
                line = layout.createLine()
                if not line.isValid():
                    break
                line.setLineWidth(width - 40)
                lines.append(line)
            layout.endLayout()
            for line in lines:
                if y + line.height() > writer.height() - 24:
                    new_page()
                painter.setPen(QColor("#12313c"))
                line.draw(painter, QPointF(20, y))
                y += line.height()
            y += 10

        try:
            new_page()
            text(f"{row['name']} / {row['camera_id']}", heading=True)
            for label, value in (
                ("Session", row["id"]),
                ("Started (UTC)", row["started_at"]),
                ("Ended (UTC)", row["ended_at"] or "still running"),
                ("Status", row["status"]),
                ("Clock", row["clock_kind"]),
            ):
                text(f"{label}: {value}")
            scene = json.loads(row["scene_json"])
            text(
                f"Scene revision {scene['revision']} | {len(scene['zones'])} zones | "
                f"{len(scene['lines'])} counting lines"
            )
            text(
                "Counts are observed crossing events per track lifecycle. Overlapping cameras "
                "are not deduplicated. Missing calibration means physical speed is unavailable."
            )
            text("Directional crossings", heading=True)
            if not scene["lines"]:
                text("Counting unavailable: no counting lines configured.")
            elif not data["counts"]:
                text("0 crossing events recorded.")
            for count in data["counts"]:
                text(
                    f"{count['object_id']} | {count['category']} | "
                    f"{count['direction']}: {count['count']}"
                )
            text("Traffic windows (latest 240)", heading=True)
            if not data["windows"]:
                text("No measured windows yet.")
            for window in data["windows"]:
                rates = ", ".join(
                    f"{k}: {v:.2f}/min" if v is not None else f"{k}: unavailable"
                    for k, v in window["flow_per_minute"].items()
                )
                text(
                    f"{window['start_time']:.1f}-{window['end_time']:.1f}s | "
                    f"observed {window['observed_seconds']:.1f}s | "
                    f"{'complete' if window['complete'] else 'partial'} | {rates or 'no flow data'}"
                )
                for zone, status in window["zones"].items():
                    text(f"Zone {zone}: {json.dumps(status, ensure_ascii=False, sort_keys=True)}")
            text(f"Events (latest 200 of {data['event_total']})", heading=True)
            for event in reversed(data["events"]):
                text(
                    f"{event['source_time']:.2f}s | {event['kind']} | "
                    f"{event['object_id'] or '-'} | {event['category'] or '-'} | "
                    f"{event['direction'] or '-'} | {event['details_json']}"
                )
            image, maximum = heatmap_image(data["heatmap"])
            if not image.isNull():
                new_page()
                text("Observed vehicle dwell", heading=True)
                text(
                    f"Relative color scale: dark = 0, bright = {maximum:.3f} "
                    "observed vehicle-seconds/cell. No background image is stored."
                )
                painter.drawImage(QRectF(20, y + 15, width - 40, (width - 40) * 0.5625), image)
                y += 30 + (width - 40) * 0.5625
            text("CSV/JSON exports contain all raw records; this PDF is a bounded summary.")
        finally:
            painter.end()
        writer = None
        if temporary.stat().st_size < 100:
            raise OSError("PDF output is empty")
        os.link(temporary, output)
        return output
    finally:
        temporary.unlink(missing_ok=True)


EVENT_TITLES = {
    "crossing": "Vehicle crossed",
    "queue_started": "Queue formed",
    "queue_cleared": "Queue cleared",
    "stalled": "Vehicle stopped",
    "stalled_cleared": "Vehicle moving again",
    "anomaly": "Unusual traffic",
    "observation_gap": "Observation gap",
}


def event_row(event):
    """Present saved event facts in plain language without changing exported records."""
    kind = event["kind"]
    try:
        details = json.loads(event["details_json"])
        if not isinstance(details, dict):
            raise ValueError("Event details must be an object")
    except (ValueError, TypeError):
        details = {}
        description = "Saved details could not be read"
    else:
        if kind == "crossing":
            description = (event["direction"] or "Direction unavailable").replace("_", " ")
        elif kind == "queue_started":
            description = f"{details.get('vehicles', 'Unknown')} vehicles in the queue"
        elif kind == "stalled":
            duration = details.get("stationary_seconds")
            description = (
                f"Stationary for {duration:.1f} s"
                if isinstance(duration, (int, float))
                else "Stationary vehicle"
            )
        elif kind == "observation_gap":
            duration = details.get("seconds")
            description = (
                f"No observations for {duration:.1f} s. Tracking restarted."
                if isinstance(duration, (int, float))
                else "Tracking restarted after missing observations"
            )
        elif kind == "anomaly":
            metric = str(details.get("metric", "Traffic measurement")).replace("_", " ")
            value, median = (
                details.get("value", "unavailable"),
                details.get("median", "unavailable"),
            )
            description = f"{metric}: {value}; prior median {median}"
        else:
            description = "; ".join(
                f"{key.replace('_', ' ')}: {value}" for key, value in details.items()
            )
    return (
        f"{event['source_time']:.2f}",
        EVENT_TITLES.get(kind, kind.replace("_", " ").title()),
        event["object_id"],
        event["category"].title() if event["category"] else None,
        description,
    )


def comparable_sessions(first, second):
    return bool(
        first
        and second
        and first["id"] != second["id"]
        and first["status"] != "running"
        and second["status"] != "running"
        and all(
            first[key] == second[key]
            for key in ("camera_id", "source_fingerprint", "analysis_key", "clock_kind")
        )
    )

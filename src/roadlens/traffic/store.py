"""SQLite migrations and atomic writes, with one connection per camera worker."""

import csv
import fcntl
import json
import os
import sqlite3
import uuid
from collections.abc import Iterator
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from roadlens.traffic.models import AnalysisUpdate, Measurement
from roadlens.traffic.statistics import metrics

MIGRATIONS = (
    (
        """CREATE TABLE cameras (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, settings_json TEXT NOT NULL,
            updated_at TEXT NOT NULL)""",
        """CREATE TABLE sessions (
            id TEXT PRIMARY KEY, camera_id TEXT NOT NULL REFERENCES cameras(id),
            started_at TEXT NOT NULL, ended_at TEXT, status TEXT NOT NULL,
            clock_kind TEXT NOT NULL, source_fingerprint TEXT NOT NULL,
            analysis_key TEXT NOT NULL, scene_json TEXT NOT NULL)""",
        """CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            event_key TEXT NOT NULL, kind TEXT NOT NULL,
            source_time REAL NOT NULL CHECK(source_time>=0),
            object_id TEXT, category TEXT, direction TEXT,
            track_key TEXT, details_json TEXT NOT NULL,
            UNIQUE(session_id,event_key))""",
        """CREATE TABLE measurements (
            id INTEGER PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            start_time REAL NOT NULL, end_time REAL NOT NULL, observed_seconds REAL NOT NULL,
            samples INTEGER NOT NULL, complete INTEGER NOT NULL, data_json TEXT NOT NULL,
            CHECK(end_time>=start_time), CHECK(observed_seconds>=0),
            UNIQUE(session_id,start_time,end_time))""",
        """CREATE TABLE trajectories (
            id INTEGER PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            track_key TEXT NOT NULL, source_time REAL NOT NULL, category TEXT NOT NULL,
            x REAL NOT NULL CHECK(x BETWEEN 0 AND 1), y REAL NOT NULL CHECK(y BETWEEN 0 AND 1),
            speed_mps REAL, UNIQUE(session_id,track_key,source_time))""",
        "CREATE INDEX sessions_camera ON sessions(camera_id,analysis_key,started_at)",
        "CREATE INDEX events_session_time ON events(session_id,source_time)",
        "CREATE INDEX measurements_session_time ON measurements(session_id,end_time)",
        "CREATE INDEX trajectories_session_time ON trajectories(session_id,source_time)",
    ),
    (
        """CREATE TABLE heatmaps (
            session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
            source_time REAL NOT NULL, units TEXT NOT NULL, grid_json TEXT NOT NULL)""",
    ),
    ("ALTER TABLE sessions ADD COLUMN settings_json TEXT NOT NULL DEFAULT '{}'",),
    ("ALTER TABLE trajectories ADD COLUMN speed_unavailable_reason TEXT",),
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def encode(value) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)


class TrafficStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.connection = sqlite3.connect(path, timeout=15)
        self.connection.row_factory = sqlite3.Row
        try:
            os.chmod(path, 0o600)
            self.connection.execute("PRAGMA busy_timeout=15000")
            self.connection.execute("PRAGMA foreign_keys=ON")
            lock_path = path.with_name(path.name + ".init.lock")
            with os.fdopen(os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600), "a+b") as lock:
                # WAL activation can return BUSY without honoring SQLite's busy timeout.
                fcntl.flock(lock, fcntl.LOCK_EX)
                self.connection.execute("PRAGMA journal_mode=WAL")
                self.connection.execute("PRAGMA synchronous=FULL")
                with self.connection:
                    self.connection.execute("BEGIN IMMEDIATE")
                    version = self.connection.execute("PRAGMA user_version").fetchone()[0]
                    if version > len(MIGRATIONS):
                        raise ValueError("Database was created by a newer ROADLENS version")
                    for index in range(version, len(MIGRATIONS)):
                        for statement in MIGRATIONS[index]:
                            self.connection.execute(statement)
                        self.connection.execute(f"PRAGMA user_version={index + 1}")
        except Exception:
            self.connection.close()
            raise

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "TrafficStore":
        return self

    def __exit__(self, *args):
        self.close()

    def start_session(
        self,
        camera_id: str,
        name: str,
        settings: dict,
        scene: dict,
        analysis_key: str,
        clock_kind: str,
        source_fingerprint: str,
    ) -> str:
        session = uuid.uuid4().hex
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            previous = self.connection.execute(
                "SELECT settings_json FROM cameras WHERE id=?", (camera_id,)
            ).fetchone()
            if previous is not None:
                old = json.loads(previous[0])
                # A camera alias must not silently combine histories from different live devices.
                if (
                    old.get("device_fingerprint")
                    and settings.get("device_fingerprint")
                    and old["device_fingerprint"] != settings["device_fingerprint"]
                ):
                    raise ValueError(f"Camera ID {camera_id!r} belongs to a different live device")
                if old.get("device_fingerprint") and not settings.get("device_fingerprint"):
                    settings = {**settings, "device_fingerprint": old["device_fingerprint"]}
            self.connection.execute(
                "INSERT INTO cameras VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "name=excluded.name,settings_json=excluded.settings_json,updated_at=excluded.updated_at",
                (camera_id, name, encode(settings), utc_now()),
            )
            self.connection.execute(
                "INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    session,
                    camera_id,
                    utc_now(),
                    None,
                    "running",
                    clock_kind,
                    source_fingerprint,
                    analysis_key,
                    encode(scene),
                    encode(settings),
                ),
            )
        return session

    def write(self, session: str, update: AnalysisUpdate) -> None:
        with self.connection:
            for event in update.events:
                self.connection.execute(
                    "INSERT INTO events(session_id,event_key,kind,source_time,object_id,category,"
                    "direction,track_key,details_json) VALUES(?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(session_id,event_key) DO NOTHING",
                    (
                        session,
                        event.key,
                        event.kind,
                        event.source_time,
                        event.object_id,
                        event.category,
                        event.direction,
                        event.track_key,
                        encode(event.details),
                    ),
                )
            for p in update.trajectories:
                self.connection.execute(
                    "INSERT INTO trajectories(session_id,track_key,source_time,"
                    "category,x,y,speed_mps,speed_unavailable_reason) VALUES(?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(session_id,track_key,source_time) DO NOTHING",
                    (
                        session,
                        p.track_key,
                        p.source_time,
                        p.category,
                        p.x,
                        p.y,
                        p.speed_mps,
                        p.speed_unavailable_reason,
                    ),
                )
            for measurement in update.measurements:
                self.connection.execute(
                    "INSERT INTO measurements(session_id,start_time,end_time,"
                    "observed_seconds,samples,complete,data_json) VALUES(?,?,?,?,?,?,?) "
                    "ON CONFLICT(session_id,start_time,end_time) DO NOTHING",
                    (
                        session,
                        measurement.start_time,
                        measurement.end_time,
                        measurement.observed_seconds,
                        measurement.samples,
                        int(measurement.complete),
                        encode(asdict(measurement)),
                    ),
                )
            if update.heatmap is not None:
                self.connection.execute(
                    "INSERT INTO heatmaps VALUES(?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET "
                    "source_time=excluded.source_time,grid_json=excluded.grid_json",
                    (
                        session,
                        update.snapshot.source_time,
                        "observed_vehicle_seconds",
                        encode(update.heatmap),
                    ),
                )

    def finish_session(self, session: str, status: str) -> None:
        if status not in {"completed", "stopped", "failed"}:
            raise ValueError("Invalid final session status")
        with self.connection:
            self.connection.execute(
                "UPDATE sessions SET status=?,ended_at=? WHERE id=?", (status, utc_now(), session)
            )

    def baseline_history(
        self, camera_id: str, analysis_key: str, limit: int
    ) -> list[dict[str, float]]:
        rows = self.connection.execute(
            "SELECT m.data_json FROM measurements m JOIN sessions s ON s.id=m.session_id "
            "WHERE s.camera_id=? AND s.analysis_key=? AND m.complete=1 "
            "ORDER BY s.started_at DESC,m.end_time DESC LIMIT ?",
            (camera_id, analysis_key, limit),
        ).fetchall()
        history = []
        for row in reversed(rows):
            data = json.loads(row[0])
            history.append(metrics(Measurement(**data)))
        return history

    def prune(self, retention_days: int) -> int:
        if type(retention_days) is not int or retention_days < 1:
            raise ValueError("Retention must be at least one day")
        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
        with self.connection:
            cursor = self.connection.execute(
                "DELETE FROM sessions WHERE ended_at IS NOT NULL AND ended_at<?", (cutoff,)
            )
        return cursor.rowcount

    def rows(
        self, table: str, camera_id: str | None = None, session_id: str | None = None
    ) -> list[dict]:
        return list(self.iter_rows(table, camera_id, session_id))

    def iter_rows(
        self, table: str, camera_id: str | None = None, session_id: str | None = None
    ) -> Iterator[dict]:
        if table not in {
            "cameras",
            "sessions",
            "events",
            "measurements",
            "trajectories",
            "heatmaps",
        }:
            raise ValueError("Unknown export table")
        if table == "cameras":
            query, params = "SELECT * FROM cameras", []
            if camera_id is not None:
                query += " WHERE id=?"
                params.append(camera_id)
            if session_id is not None:
                query += " AND" if params else " WHERE"
                query += " id IN (SELECT camera_id FROM sessions WHERE id=?)"
                params.append(session_id)
            query += " ORDER BY id"
        elif table == "sessions":
            query, params = "SELECT * FROM sessions WHERE 1=1", []
            if camera_id is not None:
                query += " AND camera_id=?"
                params.append(camera_id)
            if session_id is not None:
                query += " AND id=?"
                params.append(session_id)
            query += " ORDER BY started_at,id"
        else:
            query = (  # nosec B608  # table is restricted to the literal allowlist above.
                f"SELECT t.* FROM {table} t JOIN sessions s ON s.id=t.session_id WHERE 1=1"
            )
            params = []
            if camera_id is not None:
                query += " AND s.camera_id=?"
                params.append(camera_id)
            if session_id is not None:
                query += " AND s.id=?"
                params.append(session_id)
            query += " ORDER BY s.started_at,t.session_id"
            query += (
                ",t.source_time"
                if table in {"events", "trajectories"}
                else (",t.end_time" if table == "measurements" else "")
            )
        for row in self.connection.execute(query, params):
            yield dict(row)

    def report(self, camera_id: str | None = None) -> dict:
        cameras = []
        for camera in self.rows("cameras", camera_id):
            counts = self.connection.execute(
                "SELECT e.object_id AS line_id,e.category,e.direction,COUNT(*) AS count "
                "FROM events e JOIN sessions s ON s.id=e.session_id "
                "WHERE s.camera_id=? AND e.kind='crossing' "
                "GROUP BY e.object_id,e.category,e.direction ORDER BY 1,2,3",
                (camera["id"],),
            )
            cameras.append(
                {
                    "camera_id": camera["id"],
                    "name": camera["name"],
                    "overlap_group": json.loads(camera["settings_json"]).get("overlap_group"),
                    "sessions": [
                        {
                            key: row[key]
                            for key in ("id", "started_at", "ended_at", "status", "clock_kind")
                        }
                        for row in self.rows("sessions", camera["id"])
                    ],
                    "crossing_events": [dict(row) for row in counts],
                }
            )
        return {
            "cameras": cameras,
            "identity_scope": "per_camera_session_track_lifecycle",
            "cross_camera_unique_vehicles": None,
            "cross_camera_unavailable_reason": (
                "Feeds may overlap; cross-camera identities are not inferred"
            ),
        }

    def export(
        self,
        directory: Path,
        format: str,
        *,
        camera_id: str | None = None,
        session_id: str | None = None,
    ) -> list[Path]:
        if format not in {"csv", "json"}:
            raise ValueError("Export format must be csv or json")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        tables = ("cameras", "sessions", "events", "measurements", "trajectories", "heatmaps")
        for table in tables:
            if (directory / f"{table}.{format}").exists():
                raise FileExistsError(f"Export destination already exists: {directory / table}")
        paths = []
        # A single read transaction gives every exported table the same snapshot.
        self.connection.execute("BEGIN")
        try:
            for table in tables:
                rows = self.iter_rows(table, camera_id, session_id)
                path = directory / f"{table}.{format}"
                if path.exists():
                    raise FileExistsError(f"Export destination already exists: {path}")
                with path.open("x", newline="") as stream:
                    os.chmod(path, 0o600)
                    if format == "json":
                        stream.write("[\n")
                        for index, row in enumerate(rows):
                            if index:
                                stream.write(",\n")
                            decoded = {
                                key.removesuffix("_json"): json.loads(value)
                                if key.endswith("_json")
                                else value
                                for key, value in row.items()
                            }
                            json.dump(decoded, stream, allow_nan=False)
                        stream.write("\n]\n")
                    else:
                        columns = [
                            r[1] for r in self.connection.execute(f"PRAGMA table_info({table})")
                        ]
                        writer = csv.DictWriter(stream, fieldnames=columns)
                        writer.writeheader()
                        for row in rows:
                            writer.writerow(
                                {
                                    key: (
                                        "'" + value
                                        if isinstance(value, str)
                                        and value.startswith(("=", "+", "-", "@", "\t", "\r"))
                                        else value
                                    )
                                    for key, value in row.items()
                                }
                            )
                paths.append(path)
        finally:
            self.connection.rollback()
        return paths

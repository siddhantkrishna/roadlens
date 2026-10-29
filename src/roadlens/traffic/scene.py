"""Versioned, editable scene geometry in normalized image coordinates."""

import hashlib
import json
import math
import re
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Literal

import cv2
import numpy as np

Point = tuple[float, float]


def finite_number(value: float, name: str, minimum: float = 0) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    if not math.isfinite(value) or value < minimum:
        raise ValueError(f"{name} must be finite and >= {minimum}")


def point(value: Point, normalized: bool = True) -> Point:
    if len(value) != 2:
        raise ValueError("Points require two coordinates")
    for coordinate in value:
        finite_number(coordinate, "coordinate", 0 if normalized else -1e9)
        if normalized and coordinate > 1:
            raise ValueError("Image coordinates must be normalized to [0, 1]")
    return tuple(map(float, value))


def identifier(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise ValueError("Geometry IDs require 1–64 letters, digits, underscores or hyphens")


def cross(a: Point, b: Point, p: Point) -> float:
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def intersection(a: Point, b: Point, c: Point, d: Point) -> Point | None:
    denominator = cross((0, 0), (b[0] - a[0], b[1] - a[1]), (d[0] - c[0], d[1] - c[1]))
    if abs(denominator) < 1e-12:
        return None
    t = cross((0, 0), (c[0] - a[0], c[1] - a[1]), (d[0] - c[0], d[1] - c[1])) / denominator
    u = cross((0, 0), (c[0] - a[0], c[1] - a[1]), (b[0] - a[0], b[1] - a[1])) / denominator
    if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9:
        return a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
    return None


@dataclass(frozen=True)
class Zone:
    id: str
    name: str
    polygon: tuple[Point, ...]
    kind: Literal["road", "lane", "queue", "exclude"] = "road"

    def __post_init__(self):
        identifier(self.id)
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Zones require a name")
        if self.kind not in {"road", "lane", "queue", "exclude"}:
            raise ValueError("Unknown zone kind")
        vertices = tuple(point(p) for p in self.polygon)
        if len(vertices) < 3 or len(set(vertices)) != len(vertices):
            raise ValueError("A polygon requires at least three distinct vertices, without closure")
        edges = list(zip(vertices, vertices[1:] + vertices[:1], strict=True))
        area = abs(sum(a[0] * b[1] - a[1] * b[0] for a, b in edges)) / 2
        if area < 1e-6:
            raise ValueError("Polygon area is too small")
        for i, (a, b) in enumerate(edges):
            for j, (c, d) in enumerate(edges[i + 1 :], i + 1):
                if j == i + 1 or (i == 0 and j == len(edges) - 1):
                    continue
                if intersection(a, b, c, d) is not None:
                    raise ValueError("Polygon edges must not intersect")
                for p, start, end in ((a, c, d), (b, c, d), (c, a, b), (d, a, b)):
                    if (
                        abs(cross(start, end, p)) < 1e-12
                        and min(start[0], end[0]) <= p[0] <= max(start[0], end[0])
                        and min(start[1], end[1]) <= p[1] <= max(start[1], end[1])
                    ):
                        raise ValueError("Polygon edges must not touch or overlap")
        object.__setattr__(self, "polygon", vertices)

    def contains(self, p: Point) -> bool:
        return cv2.pointPolygonTest(np.asarray(self.polygon, np.float32), p, False) >= 0


@dataclass(frozen=True)
class CountingLine:
    id: str
    start: Point
    end: Point
    forward: str = "forward"
    reverse: str = "reverse"
    hysteresis: float = 0.005

    def __post_init__(self):
        identifier(self.id)
        object.__setattr__(self, "start", point(self.start))
        object.__setattr__(self, "end", point(self.end))
        if math.dist(self.start, self.end) < 1e-4:
            raise ValueError("Counting line is too short")
        if (
            not isinstance(self.forward, str)
            or not isinstance(self.reverse, str)
            or not self.forward.strip()
            or not self.reverse.strip()
            or self.forward == self.reverse
        ):
            raise ValueError("Line directions must be distinct nonempty names")
        finite_number(self.hysteresis, "hysteresis")
        if not 0 < self.hysteresis <= 0.05:
            raise ValueError("Line hysteresis must be > 0 and <= 0.05")

    def side(self, p: Point) -> int:
        distance = cross(self.start, self.end, p) / math.dist(self.start, self.end)
        return 1 if distance > self.hysteresis else -1 if distance < -self.hysteresis else 0


@dataclass(frozen=True)
class Calibration:
    image_points: tuple[Point, ...]
    ground_points_m: tuple[Point, ...]
    reference_size: tuple[int, int]
    verified: bool = False
    max_error_m: float = 0.5

    def __post_init__(self):
        image = tuple(point(p) for p in self.image_points)
        ground = tuple(point(p, False) for p in self.ground_points_m)
        if len(image) < 4 or len(image) != len(ground):
            raise ValueError("Calibration needs at least four paired image/ground points")
        if len(self.reference_size) != 2 or any(
            type(n) is not int or n <= 0 for n in self.reference_size
        ):
            raise ValueError("Calibration requires a positive reference width and height")
        if type(self.verified) is not bool:
            raise ValueError("Calibration verified must be boolean")
        finite_number(self.max_error_m, "max_error_m", 0.001)
        for points in (image, ground):
            if cv2.contourArea(cv2.convexHull(np.asarray(points, np.float32))) < 1e-6:
                raise ValueError("Calibration points cannot be collinear")
        object.__setattr__(self, "image_points", image)
        object.__setattr__(self, "ground_points_m", ground)
        object.__setattr__(self, "reference_size", tuple(self.reference_size))
        matrix, _ = cv2.findHomography(np.asarray(image), np.asarray(ground), method=0)
        if matrix is None or not np.isfinite(matrix).all() or np.linalg.cond(matrix) > 1e12:
            raise ValueError("Calibration homography is degenerate")
        denominators = np.asarray(image) @ matrix[2, :2] + matrix[2, 2]
        if np.any(np.abs(denominators) < 1e-8) or (denominators.min() < 0 < denominators.max()):
            raise ValueError("Calibration crosses a projection horizon inside the measured region")
        projected = cv2.perspectiveTransform(np.asarray([image]), matrix)[0]
        if np.max(np.linalg.norm(projected - np.asarray(ground), axis=1)) > self.max_error_m:
            raise ValueError("Calibration reprojection error exceeds max_error_m")

    def matrix_for(self, shape: tuple[int, ...]) -> tuple[np.ndarray | None, str | None]:
        if not self.verified:
            return None, "calibration has not been verified against scene measurements"
        if abs(shape[1] / shape[0] / (self.reference_size[0] / self.reference_size[1]) - 1) > 0.01:
            return None, "frame aspect ratio differs from calibration"
        matrix, _ = cv2.findHomography(
            np.asarray(self.image_points), np.asarray(self.ground_points_m), method=0
        )
        return matrix, None


@dataclass(frozen=True)
class Scene:
    version: int = 1
    revision: int = 1
    zones: tuple[Zone, ...] = ()
    lines: tuple[CountingLine, ...] = ()
    calibration: Calibration | None = None
    overlap_group: str | None = None

    def __post_init__(self):
        if self.version != 1 or type(self.version) is not int:
            raise ValueError("Unsupported scene version")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("Scene revision must be a positive integer")
        for objects in (self.zones, self.lines):
            if len({obj.id for obj in objects}) != len(objects):
                raise ValueError("Zone/line IDs must be unique within their collection")
        if self.overlap_group is not None:
            identifier(self.overlap_group)
        object.__setattr__(self, "zones", tuple(self.zones))
        object.__setattr__(self, "lines", tuple(self.lines))

    @classmethod
    def from_dict(cls, data: dict) -> "Scene":
        values = dict(data)
        values["zones"] = tuple(Zone(**z) for z in values.get("zones", []))
        values["lines"] = tuple(CountingLine(**line) for line in values.get("lines", []))
        if values.get("calibration") is not None:
            values["calibration"] = Calibration(**values["calibration"])
        return cls(**values)

    @classmethod
    def load(cls, path: Path) -> "Scene":
        return cls.from_dict(json.loads(path.read_text()))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(asdict(self), stream, indent=2, allow_nan=False)
                stream.write("\n")
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def with_zone(self, zone: Zone) -> "Scene":
        return replace(
            self,
            revision=self.revision + 1,
            zones=tuple(z for z in self.zones if z.id != zone.id) + (zone,),
        )

    def with_line(self, line: CountingLine) -> "Scene":
        return replace(
            self,
            revision=self.revision + 1,
            lines=tuple(item for item in self.lines if item.id != line.id) + (line,),
        )

    def without(self, identifier: str, *, collection: Literal["zones", "lines"]) -> "Scene":
        if collection not in {"zones", "lines"}:
            raise ValueError("Unknown scene collection")
        if identifier not in {item.id for item in getattr(self, collection)}:
            raise KeyError(identifier)
        return replace(
            self,
            revision=self.revision + 1,
            **{
                collection: tuple(
                    item for item in getattr(self, collection) if item.id != identifier
                )
            },
        )

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()

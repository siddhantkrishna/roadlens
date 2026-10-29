import json
from dataclasses import replace

import pytest

from roadlens.config import load_config
from roadlens.traffic.models import AnalyticsConfig
from roadlens.traffic.scene import Calibration, CountingLine, Scene, Zone

POLYGON = ((0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9))


def test_scene_roundtrip_and_edit_models(tmp_path):
    zone = Zone("lane", "Lane one", POLYGON, "lane")
    line = CountingLine("entry", (0.1, 0.5), (0.9, 0.5))
    original = Scene()
    edited = original.with_zone(zone).with_line(line)
    assert edited.revision == 3 and original.zones == ()
    replacement = edited.with_zone(replace(zone, name="Renamed"))
    assert len(replacement.zones) == 1
    assert replacement.zones[0].name == "Renamed"
    path = tmp_path / "scene.json"
    edited.save(path)
    restored = Scene.load(path)
    assert restored == edited
    assert restored.fingerprint == edited.fingerprint
    assert restored.without("lane", collection="zones").zones == ()
    assert zone.contains((0.5, 0.5)) and not zone.contains((0, 0))
    with pytest.raises(KeyError):
        restored.without("missing", collection="lines")


@pytest.mark.parametrize(
    "polygon",
    [
        ((0, 0), (0.5, 0.5)),
        ((0, 0), (0.5, 0.5), (1, 1)),
        ((0, 0), (1, 1), (0, 1), (1, 0)),
        ((0, 0), (1, 0), (1, 1), (0, 0)),
        ((0, 0), (2, 0), (1, 1)),
        ((0, 0), (1, 0), (float("nan"), 1)),
    ],
)
def test_invalid_polygons(polygon):
    with pytest.raises(ValueError):
        Zone("invalid", "Invalid", polygon)


def test_invalid_scene_and_calibration(tmp_path):
    with pytest.raises(ValueError):
        CountingLine("line", (0, 0), (0, 0))
    with pytest.raises(ValueError):
        CountingLine("line", (0, 0), (1, 1), "same", "same")
    with pytest.raises(ValueError):
        Calibration(((0, 0), (0.2, 0.2), (0.5, 0.5), (1, 1)), POLYGON, (1000, 1000))
    path = tmp_path / "scene.json"
    path.write_text(json.dumps({"version": 99}))
    with pytest.raises(ValueError):
        Scene.load(path)
    with pytest.raises(TypeError):
        Scene.from_dict({"unknown": 1})


def test_calibration_cannot_fold_ground_plane_and_roundtrips(tmp_path):
    image = ((0, 0), (1, 0), (1, 1), (0, 1))
    with pytest.raises(ValueError, match="horizon"):
        Calibration(image, ((0, 0), (10, 0), (0, 10), (10, 10)), (1000, 1000), True)
    calibration = Calibration(image, ((0, 0), (10, 0), (10, 10), (0, 10)), (1000, 1000), True)
    scene = Scene(calibration=calibration)
    path = tmp_path / "calibrated.json"
    scene.save(path)
    assert Scene.load(path) == scene


def test_nested_analytics_config_and_validation(tmp_path):
    path = tmp_path / "app.toml"
    path.write_text(
        '[analytics]\ndatabase="local.sqlite3"\nwindow_seconds=5.0\n'
        '[[sources]]\nname="road"\nkind="camera"\nvalue="default"\n'
        'scene="road.json"\ncamera_id="fixed-camera"\n'
    )
    config = load_config(path)
    assert config.analytics.window_seconds == 5
    assert config.sources[0].scene == "road.json"
    assert config.sources[0].camera_id == "fixed-camera"
    for parameters in (
        {"window_seconds": 0},
        {"grid_width": 1000},
        {"retention_days": 0},
        {"baseline_min_windows": 2},
        {"congestion_occupancy": 2},
        {"stationary_seconds": float("nan")},
    ):
        with pytest.raises(ValueError):
            AnalyticsConfig(**parameters)

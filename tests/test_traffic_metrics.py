from dataclasses import replace

import pytest
from test_traffic_counting import SHAPE, vehicle

from roadlens.traffic.analyzer import TrafficAnalyzer
from roadlens.traffic.models import AnalyticsConfig
from roadlens.traffic.scene import Calibration, Scene, Zone
from roadlens.traffic.statistics import Baselines

POLYGON = ((0, 0), (1, 0), (1, 1), (0, 1))
ROAD = Zone("road", "Road", POLYGON)
QUEUE = Zone("waiting", "Queue region", POLYGON, "queue")


def test_occupancy_union_time_weights_and_dwell_heatmap():
    service = TrafficAnalyzer(Scene(zones=(ROAD,)), AnalyticsConfig(window_seconds=2))
    tracks = [vehicle(0.5), vehicle(0.5, identity=2)]
    first = service.update(tracks, 0, 1, SHAPE)
    occupancy = first.snapshot.zones[0].image_occupancy
    assert 0 < occupancy < 0.02
    one = TrafficAnalyzer(Scene(zones=(ROAD,)), AnalyticsConfig())
    assert one.update(tracks[:1], 0, 1, SHAPE).snapshot.zones[0].image_occupancy == occupancy
    assert first.snapshot.zones[0].vehicles == 2
    service.update(tracks, 0.5, 1, SHAPE)
    service.update(tracks, 1, 1, SHAPE)
    service.update([], 1.5, 1, SHAPE)
    measurement = service.update([], 2, 1, SHAPE).measurements[0]
    assert measurement.zones["road"]["mean_vehicles"] == 1.5
    assert measurement.zones["road"]["image_occupancy"] == pytest.approx(occupancy * 0.75)
    assert service.heatmap.sum() == pytest.approx(2)
    assert service.finish().heatmap is not None


def test_queue_requires_nearby_slow_vehicles_and_dwell_then_clears():
    service = TrafficAnalyzer(
        Scene(zones=(ROAD, QUEUE)),
        AnalyticsConfig(stationary_seconds=1, queue_seconds=1, stalled_seconds=3),
    )
    tracks = [vehicle(0.5, x=x, identity=i) for i, x in enumerate((0.4, 0.45, 0.5), 1)]
    events = []
    for i in range(7):
        update = service.update(tracks, i * 0.5, 1, SHAPE)
        events.extend(update.events)
    assert [e.kind for e in events].count("queue_started") == 1
    assert not any(e.kind == "stalled" for e in events)
    status = next(z for z in update.snapshot.zones if z.zone_id == "waiting")
    assert status.queue_active and status.queued_vehicles == 3
    assert status.congestion == "congested"
    moving = [vehicle(0.7, x=x, identity=i) for i, x in enumerate((0.4, 0.45, 0.5), 1)]
    clear = service.update(moving, 3.5, 1, SHAPE)
    assert [e.kind for e in clear.events] == ["queue_cleared"]


def test_separated_stationary_vehicles_are_not_a_queue_and_stalls_are_deduplicated():
    service = TrafficAnalyzer(
        Scene(zones=(ROAD, QUEUE)),
        AnalyticsConfig(stationary_seconds=1, stalled_seconds=2, queue_seconds=1),
    )
    tracks = [vehicle(0.5, x=x, identity=i) for i, x in enumerate((0.1, 0.5, 0.9), 1)]
    events = []
    for i in range(7):
        events.extend(service.update(tracks, i * 0.5, 1, SHAPE).events)
    assert not any(e.kind == "queue_started" for e in events)
    assert [e.kind for e in events].count("stalled") == 3
    clear = service.update(
        [vehicle(0.7, x=x, identity=i) for i, x in enumerate((0.1, 0.5, 0.9), 1)], 3.5, 1, SHAPE
    )
    assert [e.kind for e in clear.events].count("stalled_cleared") == 3


def test_missing_observations_do_not_establish_a_stall():
    service = TrafficAnalyzer(
        Scene(zones=(ROAD,)), AnalyticsConfig(stationary_seconds=1, stalled_seconds=2)
    )
    service.update([vehicle(0.5)], 0, 1, SHAPE)
    service.update([], 0.5, 1, SHAPE)
    service.update([], 1, 1, SHAPE)
    update = service.update([vehicle(0.5)], 1.5, 1, SHAPE)
    assert not any(e.kind == "stalled" for e in update.events)
    assert service.states[1].slow_since is None


def test_speed_requires_verified_geometry_valid_aspect_and_observations():
    calibration = Calibration(
        POLYGON, ((0, 0), (10, 0), (10, 20), (0, 20)), (1000, 1000), verified=True
    )
    service = TrafficAnalyzer(Scene(calibration=calibration), AnalyticsConfig())
    first = service.update([vehicle(0.5, x=0.2)], 0, 1, SHAPE)
    assert first.snapshot.speeds[0].mps is None
    service.update([vehicle(0.5, x=0.25)], 0.5, 1, SHAPE)
    speed = service.update([vehicle(0.5, x=0.3)], 1, 1, SHAPE).snapshot.speeds[0]
    assert speed.mps == pytest.approx(1)
    assert speed.unavailable_reason is None
    unverified = TrafficAnalyzer(
        Scene(calibration=replace(calibration, verified=False)), AnalyticsConfig()
    )
    assert "verified" in unverified.update([], 0, 1, SHAPE).snapshot.speed_unavailable_reason
    mismatch = service.update([vehicle(0.5, x=0.4)], 1.5, 1, (500, 1000, 3))
    assert mismatch.snapshot.speeds[0].mps is None
    assert "aspect" in mismatch.snapshot.speed_unavailable_reason
    absent = TrafficAnalyzer(Scene(), AnalyticsConfig()).update([vehicle(0.5)], 0, 1, SHAPE)
    assert absent.snapshot.speeds[0].mps is None
    assert not absent.snapshot.counting_available


def test_anomaly_baselines_are_prior_observations_not_seeded_values():
    baseline = Baselines(AnalyticsConfig(baseline_min_windows=5))
    assert baseline.windows == 0
    for value in (10, 11, 10, 9):
        assert baseline.observe({"flow/gate/down/car": value}) == []
    assert baseline.observe({"flow/gate/down/car": 10}) == []
    anomaly = baseline.observe({"flow/gate/down/car": 100})[0]
    assert anomaly.median == 10
    assert anomaly.prior_windows == 5
    assert anomaly.value == 100
    assert anomaly.robust_z > 3.5


def test_partial_or_single_sample_windows_do_not_train_baselines():
    service = TrafficAnalyzer(Scene(zones=(ROAD,)), AnalyticsConfig(window_seconds=2))
    service.update([], 0, 1, SHAPE)
    service.update([], 0.5, 1, SHAPE)
    service.finish()
    assert service.baselines.windows == 0

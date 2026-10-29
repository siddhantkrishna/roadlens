from dataclasses import replace

import pytest

from roadlens.tracking import Track
from roadlens.traffic.analyzer import TrafficAnalyzer
from roadlens.traffic.models import AnalyticsConfig
from roadlens.traffic.scene import CountingLine, Scene, Zone

SHAPE = (1000, 1000, 3)
LINE = CountingLine("gate", (0.2, 0.5), (0.8, 0.5), "down", "up", 0.01)


def vehicle(y, *, x=0.5, identity=1, category=2):
    return Track(
        identity,
        category,
        0.9,
        (x * 1000 - 20, y * 1000 - 60, x * 1000 + 20, y * 1000),
        (0, 0),
        (0, 0),
        (),
    )


def crossings(update):
    return [event for event in update.events if event.kind == "crossing"]


def analyzer(**parameters):
    return TrafficAnalyzer(Scene(lines=(LINE,)), AnalyticsConfig(**parameters))


def test_real_transition_direction_dedup_and_categories():
    service = analyzer()
    assert not crossings(service.update([vehicle(0.4)], 0, 1, SHAPE))
    down = crossings(service.update([vehicle(0.6)], 0.5, 1, SHAPE))
    assert len(down) == 1 and down[0].direction == "down" and down[0].category == "car"
    assert down[0].details["intersection"] == pytest.approx((0.5, 0.5))
    assert crossings(service.update([vehicle(0.4)], 1, 1, SHAPE))[0].direction == "up"
    assert not crossings(service.update([vehicle(0.6)], 1.5, 1, SHAPE))
    assert not crossings(service.update([vehicle(0.4, identity=2, category=7)], 2, 1, SHAPE))
    truck = crossings(service.update([vehicle(0.6, identity=2, category=7)], 2.5, 1, SHAPE))
    assert truck[0].category == "truck"
    assert sum(row.count for row in service.snapshot.counts) == 3


def test_hysteresis_deadband_and_finite_line():
    service = analyzer()
    service.update([vehicle(0.48)], 0, 1, SHAPE)
    for i, y in enumerate((0.499, 0.501, 0.495, 0.505), 1):
        assert not crossings(service.update([vehicle(y)], i * 0.1, 1, SHAPE))
    assert len(crossings(service.update([vehicle(0.53)], 0.5, 1, SHAPE))) == 1
    outside = analyzer()
    outside.update([vehicle(0.4, x=0.9)], 0, 1, SHAPE)
    assert not crossings(outside.update([vehicle(0.6, x=0.9)], 1, 1, SHAPE))


def test_epoch_reset_id_reuse_and_gap_never_bridge_a_crossing():
    service = analyzer(max_gap=1)
    service.update([vehicle(0.4)], 0, 1, SHAPE)
    assert not crossings(service.update([vehicle(0.6)], 0.5, 2, SHAPE))
    reset = service.update([vehicle(0.4)], 5, 2, SHAPE)
    assert not crossings(reset)
    assert any(event.kind == "observation_gap" for event in reset.events)
    event = crossings(service.update([vehicle(0.6)], 5.5, 2, SHAPE))[0]
    assert event.track_key.startswith("2:")
    assert event.track_key != "1:1:1"


def test_lost_track_expiry_recycled_id_and_duplicate_frame():
    service = analyzer(max_gap=1)
    service.update([vehicle(0.4)], 0, 1, SHAPE)
    first = crossings(service.update([vehicle(0.6)], 0.5, 1, SHAPE))[0]
    assert not service.update([vehicle(0.6)], 0.5, 1, SHAPE).events
    for t in (1, 1.5, 2):
        service.update([], t, 1, SHAPE)
    assert not service.states
    service.update([vehicle(0.4)], 2.5, 1, SHAPE)
    second = crossings(service.update([vehicle(0.6)], 3, 1, SHAPE))[0]
    assert first.key != second.key
    with pytest.raises(ValueError, match="rewound"):
        service.update([], 0, 1, SHAPE)


def test_camera_instances_and_exclusion_are_independent():
    a, b = analyzer(), analyzer()
    a.update([vehicle(0.4)], 0, 1, SHAPE)
    a.update([vehicle(0.6)], 1, 1, SHAPE)
    assert sum(row.count for row in b.snapshot.counts) == 0
    excluded = Zone(
        "ignore", "Privacy exclusion", ((0.3, 0.3), (0.7, 0.3), (0.7, 0.7), (0.3, 0.7)), "exclude"
    )
    service = TrafficAnalyzer(Scene(lines=(LINE,), zones=(excluded,)), AnalyticsConfig())
    service.update([vehicle(0.4)], 0, 1, SHAPE)
    update = service.update([vehicle(0.6)], 1, 1, SHAPE)
    assert not update.events and not update.trajectories and not service.states
    assert service.heatmap.sum() == 0


def test_flow_uses_observed_seconds_and_does_not_fill_disconnects():
    service = analyzer(window_seconds=2, max_gap=1)
    service.update([vehicle(0.4)], 0, 1, SHAPE)
    service.update([vehicle(0.6)], 0.5, 1, SHAPE)
    service.update([], 1, 1, SHAPE)
    service.update([], 1.5, 1, SHAPE)
    update = service.update([], 2, 1, SHAPE)
    measurement = update.measurements[0]
    assert measurement.complete
    assert measurement.observed_seconds == 2
    assert measurement.flow_per_minute["gate/down/car"] == 30
    gap = service.update([], 20, 1, SHAPE)
    assert sum(m.observed_seconds for m in gap.measurements) == 0
    assert all(not m.complete for m in gap.measurements)
    assert service.observed_total == 2


def test_bad_duplicate_ids_rejected():
    service = analyzer()
    with pytest.raises(ValueError, match="Duplicate"):
        service.update([vehicle(0.4), replace(vehicle(0.5), class_id=7)], 0, 1, SHAPE)

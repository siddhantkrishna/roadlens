import numpy as np
from supervision import Detections

from roadlens.config import Config
from roadlens.pipeline import annotate
from roadlens.tracking import VehicleTracker


def detection(x=10, score=0.9, class_id=2):
    return Detections(
        xyxy=np.array([[x, 10, x + 100, 110]], np.float32),
        confidence=np.array([score], np.float32),
        class_id=np.array([class_id]),
    )


def test_bytetrack_continuity_low_score_recovery_and_direction():
    tracker = VehicleTracker(Config())
    initial = tracker.update(detection(), 0.0)[0]
    second = tracker.update(detection(13), 0.1)[0]
    assert initial.id == second.id
    assert second.direction == (1.0, 0.0)
    assert second.velocity == (30.0, 0.0)
    assert tracker.update(detection(16, score=0.2), 0.2) == []
    recovered = tracker.update(detection(19), 0.3)[0]
    assert recovered.id == initial.id
    assert len(recovered.trail) == 4


def test_class_and_camera_identity_isolation():
    a, b = VehicleTracker(Config()), VehicleTracker(Config())
    car = detection()
    bus = detection(class_id=5)
    both = Detections.merge([car, bus])
    tracks = a.update(both, 1)
    assert len({t.id for t in tracks}) == 2
    assert len(b.update(car, 1)) == 1
    a.reset()
    assert b.epoch == 1
    assert b.update(detection(13), 1.1)[0].id == 1


def test_gap_reset_and_bounded_history():
    tracker = VehicleTracker(Config(track_buffer=2))
    for i in range(40):
        tracks = tracker.update(detection(10 + i), i * 0.1)
    assert len(tracks[0].trail) == 6
    epoch = tracker.epoch
    assert tracker.update(detection(), 10)[0].direction == (0.0, 0.0)
    assert tracker.epoch == epoch + 1
    for i in range(6):
        tracker.update(Detections.empty(), 10.1 + i * 0.1)
    assert not tracker.history
    assert not tracker.identities


def test_annotation_does_not_mutate_input():
    image = np.zeros((200, 400, 3), np.uint8)
    tracks = VehicleTracker(Config()).update(detection(), 1)
    result = annotate(image, tracks, "camera", 1, "diagnostics")
    assert image.max() == 0
    assert result.max() > 0

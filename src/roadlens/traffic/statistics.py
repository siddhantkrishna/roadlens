"""Rolling robust baselines learned only from completed observation windows."""

from collections import defaultdict, deque
from dataclasses import dataclass
from statistics import median

from roadlens.traffic.models import AnalyticsConfig, Measurement


@dataclass(frozen=True)
class Deviation:
    metric: str
    value: float
    median: float
    robust_z: float
    prior_windows: int


def metrics(measurement: Measurement) -> dict[str, float]:
    values = {
        f"flow/{key}": value
        for key, value in measurement.flow_per_minute.items()
        if value is not None
    }
    for zone, data in measurement.zones.items():
        for key in ("image_occupancy", "mean_queued_vehicles"):
            if data[key] is not None:
                values[f"{key}/{zone}"] = data[key]
    return values


class Baselines:
    def __init__(self, config: AnalyticsConfig):
        self.config = config
        self.windows = 0
        self.series: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=config.baseline_max_windows)
        )

    def observe(self, values: dict[str, float], *, detect: bool = True) -> list[Deviation]:
        deviations = []
        if not values:
            return deviations
        for key, value in values.items():
            history = self.series[key]
            if detect and len(history) >= self.config.baseline_min_windows:
                center = median(history)
                mad = median(abs(previous - center) for previous in history)
                minimum = (
                    0.1
                    if key.startswith("image_occupancy/")
                    else (2.0 if key.startswith("mean_queued_vehicles/") else 5.0)
                )
                scale = max(1.4826 * mad, minimum / self.config.anomaly_z)
                z = abs(value - center) / scale
                if abs(value - center) >= minimum and z >= self.config.anomaly_z:
                    deviations.append(Deviation(key, value, center, z, len(history)))
            history.append(value)
        self.windows = min(self.windows + 1, self.config.baseline_max_windows)
        return deviations

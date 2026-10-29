"""OpenCV HighGUI stays on the macOS main thread."""

import logging
import time
from pathlib import Path

import cv2
import numpy as np

from roadlens.pipeline import Pipeline

LOG = logging.getLogger(__name__)


def run_preview(
    pipelines: list[Pipeline],
    *,
    headless: bool = False,
    output_dir: Path | None = None,
    duration: float | None = None,
) -> int:
    latest = {}
    received = {}
    started = time.monotonic()
    try:
        if not headless:
            for pipeline in pipelines:
                title = f"ROADLENS - {pipeline.source.name}"
                cv2.namedWindow(title, cv2.WINDOW_NORMAL)
                cv2.resizeWindow(title, 960, 540)
        for pipeline in pipelines:
            pipeline.start()
        while True:
            for pipeline in pipelines:
                result = pipeline.results.get(timeout=0)
                if result is not None:
                    latest[pipeline.source.name] = result.image
                    received[pipeline.source.name] = time.monotonic()
                if not headless:
                    image = latest.get(pipeline.source.name)
                    if image is None:
                        image = np.zeros((540, 960, 3), np.uint8)
                    # Redraw status during disconnects so an old frame is visibly stale.
                    display = image.copy()
                    state = (
                        "failed"
                        if pipeline.error
                        else ("finished" if pipeline.done.is_set() else pipeline.capture.state)
                    )
                    age = time.monotonic() - received.get(pipeline.source.name, started)
                    cv2.putText(
                        display,
                        f"{state} | last update {age:.1f}s ago | Q / Esc quits",
                        (8, display.shape[0] - 15),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        (0, 220, 255),
                        1,
                        cv2.LINE_AA,
                    )
                    title = f"ROADLENS - {pipeline.source.name}"
                    cv2.imshow(title, display)
                    if cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                        return 0
            if all(p.done.is_set() for p in pipelines):
                return int(any(p.error is not None or p.processed == 0 for p in pipelines))
            if duration is not None and time.monotonic() - started >= duration:
                return int(any(p.error is not None or p.processed == 0 for p in pipelines))
            if headless:
                time.sleep(0.01)
            elif cv2.waitKey(30) & 0xFF in (27, ord("q"), ord("Q")):
                return 0
    except KeyboardInterrupt:
        return 130
    finally:
        for pipeline in pipelines:
            pipeline.stop()
        for pipeline in pipelines:
            if pipeline.ident is not None:
                pipeline.join(
                    timeout=None
                    if pipeline.source.kind == "camera"
                    else pipeline.config.read_timeout + 5
                )
                result = pipeline.results.get(timeout=0)
                if result is not None:
                    latest[pipeline.source.name] = result.image
                LOG.info(
                    "[%s] stopped: processed=%d dropped=%d reconnects=%d",
                    pipeline.source.name,
                    pipeline.processed,
                    pipeline.capture.frames.dropped,
                    pipeline.capture.reconnects,
                )
        if not headless:
            cv2.destroyAllWindows()
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
            for index, pipeline in enumerate(pipelines):
                image = latest.get(pipeline.source.name)
                if image is not None:
                    path = output_dir / f"source-{index + 1}.jpg"
                    if not cv2.imwrite(str(path), image):
                        raise OSError(f"Failed to save annotated frame: {path}")
                    LOG.info("[%s] saved %s", pipeline.source.name, path)

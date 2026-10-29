"""ROADLENS command line interface."""

import argparse
import json
import logging
import math
import platform
import sqlite3
import subprocess
import sys
from dataclasses import replace
from logging.handlers import RotatingFileHandler
from pathlib import Path

import cv2

from roadlens.cameras import build_bridge, list_cameras
from roadlens.config import Config, SourceConfig, load_config
from roadlens.detection import download_model
from roadlens.pipeline import Pipeline
from roadlens.preview import run_preview
from roadlens.traffic.scene import Scene
from roadlens.traffic.service import render_heatmap
from roadlens.traffic.store import TrafficStore


def configure_logging(level: str, path: Path | None):
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(path, maxBytes=5_000_000, backupCount=3))
    logging.basicConfig(
        level=level,
        handlers=handlers,
        force=True,
        format="%(asctime)s %(levelname)s %(threadName)s %(message)s",
    )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="ROADLENS local vehicle vision")
    root.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO")
    root.add_argument("--log-file", type=Path)
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "cameras", help="List AVFoundation IDs, including available Continuity Cameras"
    )
    commands.add_parser("doctor", help="Print runtime, camera and GUI diagnostics")
    fetch = commands.add_parser(
        "fetch-model", help="Download pinned, checksum-verified YOLOv8n ONNX"
    )
    fetch.add_argument("--output", type=Path, default=Path(Config.model))
    run = commands.add_parser("run", help="Run independent pipelines and local preview")
    run.add_argument("--config", type=Path)
    run.add_argument("--camera", action="append", default=[], metavar="ID_OR_NAME")
    run.add_argument("--opencv-index", action="append", type=int, default=[])
    run.add_argument("--video", action="append", type=Path, default=[])
    run.add_argument(
        "--offline", action="store_true", help="Process every recorded frame without pacing"
    )
    run.add_argument("--model", type=Path)
    run.add_argument("--headless", action="store_true")
    run.add_argument("--max-frames", type=int, help="Limit inference frames per source")
    run.add_argument("--duration", type=float, help="Stop after this many wall-clock seconds")
    run.add_argument("--output-dir", type=Path, help="Save the last annotated JPEG per source")
    run.add_argument("--scene", type=Path, help="Scene geometry for a single source")
    run.add_argument("--database", type=Path, help="Persist analytics to local SQLite")
    scene = commands.add_parser("scene", help="Create or validate editable scene JSON")
    actions = scene.add_subparsers(dest="action", required=True)
    init = actions.add_parser("init", help="Create an empty scene; no road geometry is inferred")
    init.add_argument("output", type=Path)
    check = actions.add_parser("check", help="Validate geometry and calibration data")
    check.add_argument("path", type=Path)
    report = commands.add_parser("report", help="Per-camera event counts and session history")
    report.add_argument("--database", type=Path, required=True)
    report.add_argument("--camera")
    export = commands.add_parser("export", help="Export actual collected records")
    export.add_argument("--database", type=Path, required=True)
    export.add_argument("--format", choices=["csv", "json"], required=True)
    export.add_argument("--output-dir", type=Path, required=True)
    export.add_argument("--camera")
    export.add_argument("--session")
    heatmap = commands.add_parser(
        "heatmap", help="Render observed vehicle dwell, with no camera image"
    )
    heatmap.add_argument("--database", type=Path, required=True)
    heatmap.add_argument("--session", required=True)
    heatmap.add_argument("--output", type=Path, required=True)
    validate = commands.add_parser(
        "validate-footage", help="Compare real inference to reviewed crossing labels"
    )
    validate.add_argument("--video", type=Path, required=True)
    validate.add_argument("--scene", type=Path, required=True)
    validate.add_argument("--annotations", type=Path, required=True)
    validate.add_argument("--output", type=Path, required=True)
    validate.add_argument("--model", type=Path, default=Path(Config.model))
    return root


def run_config(args) -> Config:
    config = load_config(args.config)
    sources = list(config.sources)
    for camera in args.camera:
        sources.append(SourceConfig(f"camera-{len(sources) + 1}", "camera", camera))
    for index in args.opencv_index:
        sources.append(SourceConfig(f"camera-{len(sources) + 1}", "opencv", str(index)))
    for video in args.video:
        sources.append(SourceConfig(f"video-{len(sources) + 1}", "video", str(video)))
    if not sources:
        sources = [SourceConfig("webcam", "camera", "default")]
    if args.offline:
        sources = [replace(s, realtime=False) if s.kind == "video" else s for s in sources]
    if args.scene:
        if len(sources) != 1:
            raise ValueError(
                "--scene requires one source; use per-source scenes in TOML for multiple cameras"
            )
        sources = [replace(sources[0], scene=str(args.scene))]
    analytics = (
        replace(config.analytics, database=str(args.database))
        if args.database
        else config.analytics
    )
    if args.max_frames is not None and args.max_frames <= 0:
        raise ValueError("--max-frames must be positive")
    if args.duration is not None and (not math.isfinite(args.duration) or args.duration <= 0):
        raise ValueError("--duration must be finite and positive")
    return replace(
        config,
        sources=tuple(sources),
        model=str(args.model) if args.model else config.model,
        analytics=analytics,
    )


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    configure_logging(args.log_level, args.log_file)
    try:
        if args.command == "fetch-model":
            print(download_model(args.output))
        elif args.command == "cameras":
            print(json.dumps(list_cameras(), indent=2, ensure_ascii=False))
        elif args.command == "doctor":
            print(
                json.dumps(
                    {
                        "python": sys.version,
                        "platform": platform.platform(),
                        "architecture": platform.machine(),
                        "opencv": cv2.__version__,
                        "gui": next(
                            (
                                s.strip()
                                for s in cv2.getBuildInformation().splitlines()
                                if s.strip().startswith("GUI:")
                            ),
                            "unknown",
                        ),
                        "model_present": Path(Config.model).is_file(),
                        "cameras": list_cameras(),
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
        elif args.command == "scene":
            if args.action == "init":
                if args.output.exists():
                    raise FileExistsError(args.output)
                Scene().save(args.output)
                print(args.output)
            else:
                scene = Scene.load(args.path)
                print(
                    json.dumps(
                        {
                            "valid": True,
                            "revision": scene.revision,
                            "zones": len(scene.zones),
                            "lines": len(scene.lines),
                            "fingerprint": scene.fingerprint,
                            "calibration_verified_by_user": bool(
                                scene.calibration and scene.calibration.verified
                            ),
                        },
                        indent=2,
                    )
                )
        elif args.command in {"report", "export", "heatmap"}:
            if not args.database.is_file():
                raise FileNotFoundError(f"Database does not exist: {args.database}")
            with TrafficStore(args.database) as store:
                if args.command == "report":
                    print(json.dumps(store.report(args.camera), indent=2))
                elif args.command == "export":
                    for path in store.export(
                        args.output_dir, args.format, camera_id=args.camera, session_id=args.session
                    ):
                        print(path)
                else:
                    render_heatmap(store, args.session, args.output)
                    print(args.output)
        elif args.command == "validate-footage":
            from roadlens.traffic.validation import validate_footage

            report = validate_footage(
                args.video, args.scene, args.annotations, args.model, args.output
            )
            print(json.dumps(report, indent=2))
            return 0 if report["false_positives"] == report["false_negatives"] == 0 else 2
        elif args.command == "run":
            config = run_config(args)
            if not Path(config.model).is_file():
                raise FileNotFoundError(
                    f"Model missing: {config.model}; run `roadlens fetch-model`"
                )
            if any(s.kind == "camera" for s in config.sources):
                build_bridge()
            cv2.setNumThreads(config.threads)
            logging.info(
                "CPU inference: %d sources, %d OpenCV threads, input=%d, limit=%.1ffps/source",
                len(config.sources),
                config.threads,
                config.input_size,
                config.inference_fps,
            )
            return run_preview(
                [Pipeline(s, config, args.max_frames) for s in config.sources],
                headless=args.headless,
                output_dir=args.output_dir,
                duration=args.duration,
            )
        return 0
    except (
        OSError,
        ValueError,
        TypeError,
        RuntimeError,
        subprocess.SubprocessError,
        cv2.error,
        sqlite3.Error,
    ) as error:
        logging.error("%s", error)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            logging.error("%s", error.stderr)
        return 1

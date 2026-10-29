"""Build the small native capture helper; select devices by identity, never index."""

import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def bridge_path() -> Path:
    if getattr(sys, "frozen", False):
        return (
            Path(sys.executable).parent.parent
            / "Helpers/ROADLENS Camera.app/Contents/MacOS/roadlens-camera"
        )
    return Path.cwd() / ".cache/roadlens/ROADLENS Camera.app/Contents/MacOS/roadlens-camera"


def build_bridge() -> Path:
    if platform.system() != "Darwin":
        raise RuntimeError("AVFoundation capture is only available on macOS")
    source = Path(__file__).with_name("native")
    binary = bridge_path()
    if getattr(sys, "frozen", False):
        if not binary.is_file():
            raise FileNotFoundError(f"Bundled camera helper is missing: {binary}")
        return binary
    if binary.exists() and binary.stat().st_mtime >= max(
        (source / name).stat().st_mtime for name in ("camera.m", "Info.plist")
    ):
        return binary
    if not shutil.which("clang"):
        raise RuntimeError("Install Apple Command Line Tools with: xcode-select --install")
    binary.parent.mkdir(parents=True, exist_ok=True)
    plist = binary.parent.parent / "Info.plist"
    shutil.copyfile(source / "Info.plist", plist)
    command = [
        "clang",
        "-fobjc-arc",
        "-O2",
        "-Wall",
        "-Wextra",
        "-Wno-unused-parameter",
        "-mmacosx-version-min=13.0",
        str(source / "camera.m"),
        "-framework",
        "Foundation",
        "-framework",
        "AVFoundation",
        "-framework",
        "CoreMedia",
        "-framework",
        "CoreVideo",
        "-Xlinker",
        "-sectcreate",
        "-Xlinker",
        "__TEXT",
        "-Xlinker",
        "__info_plist",
        "-Xlinker",
        str(plist),
        "-o",
        str(binary),
    ]
    subprocess.run(command, check=True, capture_output=True, text=True, timeout=120)
    subprocess.run(
        ["codesign", "--force", "--sign", "-", str(binary.parent.parent.parent)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return binary


def list_cameras() -> list[dict[str, str]]:
    result = subprocess.run(
        [str(build_bridge()), "list"], check=True, capture_output=True, text=True, timeout=20
    )
    return json.loads(result.stdout)


def select_camera(value: str, devices: list[dict[str, str]]) -> dict[str, str]:
    if value == "default":
        built_in = [d for d in devices if "BuiltIn" in d["type"]]
        matches = built_in or devices[:1]
    else:
        exact = [d for d in devices if d["id"] == value]
        matches = exact or [d for d in devices if value.casefold() in d["name"].casefold()]
    if not matches:
        raise RuntimeError(f"Camera {value!r} is unavailable; run `roadlens cameras`")
    if len(matches) > 1:
        raise RuntimeError(f"Camera name {value!r} is ambiguous; use its device ID")
    return matches[0]

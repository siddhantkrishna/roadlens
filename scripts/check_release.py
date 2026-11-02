"""Fail closed on private files/secrets; optionally create a reviewed source archive."""

import argparse
import gzip
import hashlib
import json
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT_FILES = {
    ".gitignore",
    ".gitattributes",
    "LICENSE",
    "NOTICE",
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "THIRD_PARTY.md",
    "TRAFFIC.md",
    "DESKTOP.md",
    "VERIFICATION.md",
    "ROADLENS.spec",
    "MANIFEST.in",
    "pyproject.toml",
    "requirements-macos-intel.lock",
    "requirements-security.lock",
    "roadlens.example.toml",
}
SOURCE_TYPES = {
    "src": {".py", ".m", ".plist"},
    "tests": {".py"},
    "scripts": {".py"},
    ".github": {".yml", ".yaml", ".md"},
    "docs": {".md", ".json"},
    "assets": {".md", ".txt", ".json"},
}
PUBLIC_ASSETS = {
    "assets/bus.jpg",
    "assets/traffic.avi",
    "docs/images/monitor.png",
    "docs/images/history.png",
    "docs/images/scene-editor.png",
    "docs/images/settings.png",
    "docs/images/monitor-dark.png",
    "docs/images/monitor-before.png",
    "docs/images/history-before.png",
    "docs/images/scene-editor-before.png",
}
PUBLIC_DIGESTS = {
    "190ba5f1e61411a001683e349d6b2cdb0804c0dc67a5e34cd8ff6fd00ee54b4d",
    "6c94e5d44f5770db95dd82f5bfaa041120b7f4b7bc586ea23fad465ed0780ec5",
    "27afd8f803e710cf2b5c1c8b62f4a465ad8bd7512dabfb92fc4348377cfbb867",
}
HOME_PATH = re.compile(rb"/(?:Users|home)/[^/\s]+/")


def candidates(root: Path) -> list[str]:
    changed = subprocess.run(
        ["git", "diff", "--name-only", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    if changed.stdout:
        raise ValueError(
            "Tracked files differ from the index; stage or restore changes before release"
        )
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return sorted(set(result.stdout.decode().strip("\0").split("\0")) - {""})


def inspect_files(root: Path, paths: list[str], assets: dict) -> list[str]:
    issues = []
    for name in paths:
        path = root / name
        parts = Path(name).parts
        if path.is_symlink() or not path.is_file() or ".." in parts or Path(name).is_absolute():
            issues.append(f"{name}: not a regular repository file")
            continue
        if name in assets:
            expected = assets[name]
            if not expected.get("source") or not expected.get("license"):
                issues.append(f"{name}: missing public provenance/license")
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected.get("sha256"):
                issues.append(f"{name}: public asset changed; review its provenance and hash")
            continue
        if name not in ROOT_FILES and not (
            len(parts) > 1 and path.suffix in SOURCE_TYPES.get(parts[0], set())
        ):
            issues.append(f"{name}: outside the public source allowlist")
            continue
        if any(part.startswith(".") for part in parts[1:]) or path.stat().st_size > 1_000_000:
            issues.append(f"{name}: hidden or oversized source file")
            continue
        content = path.read_bytes()
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            issues.append(f"{name}: unreviewed binary file")
        if b"\0" in content:
            issues.append(f"{name}: binary content in a source file")
        if HOME_PATH.search(content):
            issues.append(f"{name}: contains a personal home-directory path")
    for name in assets:
        if name not in paths:
            issues.append(f"{name}: required reviewed public asset is absent/ignored")
    return issues


def scan_secrets(root: Path, paths: list[str]) -> list[str]:
    # A clean tree prevents scanning private ignored files or uploading their contents.
    with tempfile.TemporaryDirectory(prefix="roadlens-release-scan-") as directory:
        clean = Path(directory)
        for name in paths:
            target = clean / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((root / name).read_bytes())
        result = subprocess.run(
            [sys.executable, "-m", "detect_secrets", "scan", "--no-verify", "--all-files", "."],
            cwd=clean,
            check=True,
            capture_output=True,
            text=True,
        )
        report = json.loads(result.stdout)
        manifest_path = root / "docs/public-assets.json"
        public = set(PUBLIC_DIGESTS)
        if manifest_path.is_file():
            public.update(row["sha256"] for row in json.loads(manifest_path.read_text()).values())
        # Exclude exact reviewed public checksums, not arbitrary entropy findings or whole lines.
        checksums = {
            hashlib.sha1(value.encode(), usedforsecurity=False).hexdigest() for value in public
        }
        return [
            f"{name}:{entry['line_number']}: {entry['type']} (value redacted)"
            for name, entries in report["results"].items()
            for entry in entries
            if not (
                entry["type"] == "Hex High Entropy String" and entry["hashed_secret"] in checksums
            )
        ]


def archive(root: Path, paths: list[str], output: Path):
    output.parent.mkdir(parents=True, exist_ok=True)
    with (
        output.open("xb") as stream,
        gzip.GzipFile(fileobj=stream, mode="wb", filename="", mtime=0) as zipped,
    ):
        with tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as bundle:
            for name in paths:
                path = root / name
                info = tarfile.TarInfo("roadlens/" + name)
                info.size = path.stat().st_size
                info.mode = 0o644
                with path.open("rb") as content:
                    bundle.addfile(info, content)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--archive", type=Path, help="Create a new source .tar.gz only after passing"
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        paths = candidates(root)
        manifest = json.loads((root / "docs/public-assets.json").read_text())
        if set(manifest) != PUBLIC_ASSETS:
            raise ValueError("Public asset paths must be explicitly reviewed in the release policy")
        issues = inspect_files(root, paths, manifest)
        if not issues:
            issues = scan_secrets(root, paths)
        if issues:
            print("Release blocked:\n" + "\n".join(issues), file=sys.stderr)
            return 1
        print(f"Public source/privacy and offline secret checks passed: {len(paths)} files.")
        if args.archive:
            archive(root, paths, args.archive)
            digest = hashlib.sha256(args.archive.read_bytes()).hexdigest()
            print(f"Source archive: {args.archive}\nSHA-256: {digest}")
        return 0
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as error:
        print(
            f"Release check failed: {type(error).__name__}; no release approved.", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

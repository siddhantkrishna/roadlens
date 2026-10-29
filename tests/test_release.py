"""Public-release gates operate on local test fixtures, never real credentials."""

import hashlib
import runpy
import subprocess
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
POLICY = runpy.run_path(str(ROOT / "scripts/check_release.py"))


@pytest.mark.parametrize(
    "name",
    [
        ".env",
        "recordings/private.mp4",
        "data/traffic.sqlite3",
        "dist/ROADLENS.app/binary",
        "docs/images/private.png",
        "src/roadlens/.credentials.py",
    ],
)
def test_private_or_unreviewed_files_block_release(tmp_path, name):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("test fixture")
    assert POLICY["inspect_files"](tmp_path, [name], {})


def test_public_assets_require_exact_bytes_and_provenance(tmp_path):
    name = "docs/images/monitor.png"
    path = tmp_path / name
    path.parent.mkdir(parents=True)
    path.write_bytes(b"public asset fixture")
    manifest = {
        name: {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "source": "test fixture",
            "license": "AGPL-3.0-only",
        }
    }
    assert not POLICY["inspect_files"](tmp_path, [name], manifest)
    path.write_bytes(b"changed unreviewed bytes")
    assert "changed" in POLICY["inspect_files"](tmp_path, [name], manifest)[0]
    assert "absent" in POLICY["inspect_files"](tmp_path, [], manifest)[0]


def test_personal_paths_and_symlinks_block_release(tmp_path):
    path = tmp_path / "README.md"
    path.write_text("/" + "Users" + "/test-person/private/video.mp4")
    assert "personal" in POLICY["inspect_files"](tmp_path, ["README.md"], {})[0]
    path.unlink()
    path.symlink_to(ROOT / "README.md")
    assert "regular" in POLICY["inspect_files"](tmp_path, ["README.md"], {})[0]


def test_git_candidates_include_forced_ignored_files(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text(".env\n*.mp4\n")
    (tmp_path / "README.md").write_text("Public source")
    (tmp_path / ".env").write_text("non-secret test fixture")
    (tmp_path / "private.mp4").write_bytes(b"not a real video")
    assert POLICY["candidates"](tmp_path) == [".gitignore", "README.md"]
    subprocess.run(["git", "add", "-f", ".env"], cwd=tmp_path, check=True)
    assert ".env" in POLICY["candidates"](tmp_path)
    assert POLICY["inspect_files"](tmp_path, POLICY["candidates"](tmp_path), {})


def test_secret_scanning_rejects_key_headers_without_exposing_values(tmp_path):
    pytest.importorskip("detect_secrets")
    path = tmp_path / "README.md"
    path.write_text("-----BEGIN " + "RSA PRIVATE KEY-----\nnon-secret test fixture\n")
    findings = POLICY["scan_secrets"](tmp_path, ["README.md"])
    assert findings and all("value redacted" in item for item in findings)
    assert all("BEGIN" not in item for item in findings)
    path.write_text("Public source with no credentials.")
    assert not POLICY["scan_secrets"](tmp_path, ["README.md"])


def test_source_archive_has_only_selected_files_and_no_local_owner_metadata(tmp_path):
    (tmp_path / "README.md").write_text("public source")
    (tmp_path / ".env").write_text("private test fixture")
    output = tmp_path / "source.tar.gz"
    POLICY["archive"](tmp_path, ["README.md"], output)
    with tarfile.open(output, "r:gz") as archive:
        assert archive.getnames() == ["roadlens/README.md"]
        info = archive.getmembers()[0]
        assert info.uid == info.gid == info.mtime == 0
        assert not info.uname and not info.gname
    with pytest.raises(FileExistsError):
        POLICY["archive"](tmp_path, ["README.md"], output)


def test_staged_content_cannot_be_hidden_by_a_clean_working_copy(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    path = tmp_path / "README.md"
    path.write_text("unreviewed staged fixture")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    path.write_text("sanitized working copy")
    with pytest.raises(ValueError, match="differ from the index"):
        POLICY["candidates"](tmp_path)

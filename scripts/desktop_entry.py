"""PyInstaller entry point; imports the same desktop used by roadlens-desktop."""

import os
from pathlib import Path

# PyInstaller's temporary matplotlib cache otherwise rescans every Mac font on every launch.
cache = Path.home() / "Library/Caches/ROADLENS/matplotlib"
try:
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
except OSError:
    pass  # Matplotlib retains the bundler's writable temporary cache.
else:
    os.environ["MPLCONFIGDIR"] = str(cache)

from roadlens.desktop import main  # noqa: E402

raise SystemExit(main())

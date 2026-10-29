"""ROADLENS: local vehicle vision; no network services or persistent identities."""

import os
import tempfile
from pathlib import Path

# Supervision imports matplotlib, even though ROADLENS never plots with it.
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "roadlens-matplotlib"))
os.environ.setdefault("MPLBACKEND", "Agg")

__version__ = "0.1.0"

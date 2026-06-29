"""Vercel entrypoint for the Meta Ads performance dashboard."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

if os.getenv("VERCEL"):
    os.environ.setdefault("ADINTEL_DB_PATH", "/tmp/adintel.db")

from adintel import db  # noqa: E402
from adintel.performance.dashboard import app  # noqa: E402,F401

db.init_db()

"""Vercel Python Function entrypoint.

Git-connected Vercel projects reliably detect Python functions under api/.
The root app.py remains the single application bootstrap for local/CLI usage.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402,F401

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
from adintel.performance.store import upsert_ad_account  # noqa: E402

db.init_db()


def _seed_meta_accounts_from_env() -> None:
    """Seed ephemeral Vercel SQLite with registered Meta ad accounts."""
    account_specs = os.getenv("META_AD_ACCOUNTS", "").strip()
    single_account = os.getenv("META_AD_ACCOUNT_ID", "").strip()
    if single_account and not account_specs:
        name = os.getenv("META_AD_ACCOUNT_NAME", single_account).strip()
        account_specs = f"{single_account}|{name}"
    if not account_specs:
        return

    conn = db.connect()
    try:
        for spec in account_specs.split(","):
            parts = [part.strip() for part in spec.split("|")]
            if not parts or not parts[0]:
                continue
            upsert_ad_account(
                conn,
                parts[0],
                account_name=parts[1] if len(parts) > 1 and parts[1] else parts[0],
                currency=parts[2] if len(parts) > 2 and parts[2] else None,
                timezone_name=parts[3] if len(parts) > 3 and parts[3] else None,
                target_action=parts[4] if len(parts) > 4 and parts[4] else "landing_click",
            )
        conn.commit()
    finally:
        conn.close()


_seed_meta_accounts_from_env()

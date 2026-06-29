"""Sync Meta Marketing API Insights into the local dashboard store.

usage:
  python3 scripts/sync_meta_insights.py --all --lookback-days 2
  python3 scripts/sync_meta_insights.py --account-id 123 --lookback-days 7
"""
from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse

from adintel import db
from adintel.performance import alerts, store
from adintel.performance.meta_api import MetaInsightsClient
from adintel.performance.sync import (
    DEFAULT_LEVELS,
    ensure_account_for_sync,
    sync_account,
    sync_all_accounts,
)


def _levels(value: str | None) -> tuple[str, ...]:
    if not value:
        return DEFAULT_LEVELS
    levels = tuple(v.strip() for v in value.split(",") if v.strip())
    allowed = set(DEFAULT_LEVELS)
    bad = [v for v in levels if v not in allowed]
    if bad:
        raise SystemExit(f"unsupported levels: {', '.join(bad)}")
    return levels


def main() -> None:
    ap = argparse.ArgumentParser()
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="sync all active registered accounts")
    group.add_argument("--account-id", help="sync one account; act_ prefix is optional")
    ap.add_argument("--account-name", help="name to use when --account-id is not registered yet")
    ap.add_argument("--lookback-days", type=int, default=2)
    ap.add_argument("--levels", help="comma-separated subset: account,campaign,adset,ad")
    ap.add_argument("--skip-alerts", action="store_true")
    args = ap.parse_args()

    db.init_db()
    conn = db.connect()
    try:
        client = MetaInsightsClient()
        levels = _levels(args.levels)
        if args.all:
            accounts = store.list_active_ad_accounts(conn)
            if not accounts:
                raise SystemExit("No active meta_ad_accounts. Use scripts/add_meta_account.py first.")
            results = sync_all_accounts(
                conn, client, lookback_days=args.lookback_days, levels=levels
            )
        else:
            account = ensure_account_for_sync(
                conn, args.account_id, account_name=args.account_name
            )
            results = [
                sync_account(
                    conn,
                    client,
                    account,
                    lookback_days=args.lookback_days,
                    levels=levels,
                )
            ]

        for r in results:
            print(
                f"[{r.status}] {r.ad_account_id} rows={r.rows_upserted} "
                f"finished_at={r.finished_at} {r.error}"
            )

        if not args.skip_alerts:
            current_alerts = alerts.compute_current_alerts(conn)
            notified = alerts.notify_slack(conn, current_alerts)
            print(f"[alerts] detected={len(current_alerts)} notified={notified}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

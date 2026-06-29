"""Register a Meta ad account for dashboard sync.

usage:
  python3 scripts/add_meta_account.py --account-id 123 --name "Brand KR"
"""
import _bootstrap  # noqa: F401
import argparse

from adintel import db
from adintel.performance.store import upsert_ad_account


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account-id", required=True, help="Meta ad account id; act_ prefix is optional")
    ap.add_argument("--name", required=True)
    ap.add_argument("--currency", default="KRW")
    ap.add_argument("--timezone", default="Asia/Seoul")
    ap.add_argument("--target-action", default="purchase")
    ap.add_argument("--min-alert-spend", type=float, default=50000)
    ap.add_argument("--inactive", action="store_true")
    ap.add_argument("--note", default="")
    args = ap.parse_args()

    db.init_db()
    conn = db.connect()
    try:
        upsert_ad_account(
            conn,
            args.account_id,
            account_name=args.name,
            currency=args.currency,
            timezone_name=args.timezone,
            active=not args.inactive,
            target_action=args.target_action,
            min_alert_spend=args.min_alert_spend,
            note=args.note,
        )
        conn.commit()
        print(f"[meta account] registered {args.account_id} ({args.name})")
    finally:
        conn.close()


if __name__ == "__main__":
    main()


"""DB/export/Notion 광고 행의 미디어링크·미디어타입을 점검.

usage:
  python3 scripts/audit_media.py
  python3 scripts/audit_media.py --notion --limit 100
"""
import _bootstrap  # noqa: F401
import argparse

from adintel import db
from adintel.media_audit import audit_db, audit_rows, print_issues
from adintel.reporting import notion_ads
from adintel.reporting.notion_ads import build_rows


def _run_section(name: str, issues: list) -> int:
    print(f"[audit:{name}]")
    print_issues(issues)
    return len(issues)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--active-only", action="store_true", help="export row는 활성 광고만 점검")
    ap.add_argument("--all", action="store_true", help="export row의 위너 후보 게이트를 끄고 전체 점검")
    ap.add_argument("--notion", action="store_true", help="Notion 광고 추적 DB도 조회해 점검")
    ap.add_argument("--limit", type=int, default=None, help="export/Notion 점검 행 수 제한")
    args = ap.parse_args()

    db.init_db()
    conn = db.connect()
    failures = 0
    try:
        failures += _run_section("db", audit_db(conn))

        export_rows = build_rows(
            conn,
            active_only=args.active_only,
            winners_only=not args.all,
        )
        if args.limit:
            export_rows = export_rows[: args.limit]
        failures += _run_section("export", audit_rows(export_rows, source="export"))

        if args.notion:
            if not notion_ads._enabled():
                print("[audit:notion] NOTION_TOKEN/NOTION_ADS_DATABASE_ID 미설정 → 건너뜀")
            else:
                notion_rows = notion_ads.fetch_ad_rows(limit=args.limit)
                failures += _run_section("notion", audit_rows(notion_rows, source="notion"))
    finally:
        conn.close()

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

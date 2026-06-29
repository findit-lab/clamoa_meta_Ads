"""ads 상태 테이블 → 노션 '광고 추적 DB'(per-ad) 적재.

usage:
  python scripts/export_ads.py [--active-only] [--limit N] [--csv PATH]

NOTION_TOKEN + NOTION_ADS_DATABASE_ID 있으면 REST 적재, 없으면 콘솔 미리보기.
--csv PATH 를 주면 노션과 동일한 컬럼으로 CSV를 함께 저장(노션 임포트/오프라인 확인용).
실 운영에서는 run_daily 직후 호출하거나 별도 스케줄로 돌린다.
"""
import _bootstrap  # noqa: F401
import argparse
import csv

from adintel import db
from adintel.reporting.notion_ads import build_rows, report_ads


def _write_csv(rows: list, path: str) -> None:
    if not rows:
        print("  CSV: 행 없음")
        return
    cols = list(rows[0].keys())
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"  📄 CSV 저장: {path} ({len(rows)}행)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--active-only", action="store_true", help="활성 광고만 적재")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--csv", help="노션 컬럼과 동일한 CSV 저장 경로")
    ap.add_argument("--no-upsert", action="store_true",
                    help="광고ID 갱신 대신 무조건 새 행 생성(중복 가능)")
    ap.add_argument("--all", action="store_true",
                    help="위너 후보 게이트를 끄고 전체 광고 적재(기본은 위너 후보만)")
    args = ap.parse_args()

    db.init_db()
    conn = db.connect()
    if args.csv:
        rows = build_rows(conn, active_only=args.active_only, winners_only=not args.all)
        rows.sort(key=lambda r: r.get("위너점수", 0), reverse=True)
        if args.limit:
            rows = rows[: args.limit]
        _write_csv(rows, args.csv)
    else:
        report_ads(conn, active_only=args.active_only, limit=args.limit,
                   upsert=not args.no_upsert, winners_only=not args.all)
    conn.close()


if __name__ == "__main__":
    main()

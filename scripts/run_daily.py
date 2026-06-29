"""일일 진입점: collect → diff → cluster (단일 날짜).

usage: python scripts/run_daily.py [--date 2026-01-15] [--start 2026-01-01]

Collector 선택: APIFY_TOKEN 있으면 Apify, 없으면 Mock.
실 운영에서는 Cloud Scheduler가 매일 이 스크립트(또는 등가 Job)를 트리거.
"""
import _bootstrap  # noqa: F401
import argparse
import datetime as dt

import config
from adintel import db, targets
from adintel.collectors.mock import MockCollector
from adintel.pipeline import run_daily


def _make_collector(start: str):
    if config.APIFY_TOKEN:
        from adintel.collectors.apify import ApifyCollector
        print("[collector] Apify")
        return ApifyCollector()
    print("[collector] Mock (APIFY_TOKEN 미설정)")
    return MockCollector(start_date=start)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--start", default="2026-01-01", help="mock 수집기 기준 시작일")
    args = ap.parse_args()

    db.init_db()
    conn = db.connect()
    if not targets.list_active(conn):
        print("⚠️  타겟이 없습니다. 먼저 `python scripts/seed_targets.py` 실행.")
        return

    collector = _make_collector(args.start)
    r = run_daily(conn, collector, args.date)
    print(f"[{args.date}] APPEARED {r.appeared} / STILL {r.still_active} / "
          f"MISSING {r.missing} / DISAPPEARED {r.disappeared}")
    conn.close()


if __name__ == "__main__":
    main()

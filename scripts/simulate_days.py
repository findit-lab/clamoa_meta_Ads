"""mock 수집기를 N일 전진시켜 Diff/longevity 시연 (2주차 게이트 검증).

usage: python scripts/simulate_days.py --days 30 [--start 2026-01-01]
"""
import _bootstrap  # noqa: F401
import argparse
import datetime as dt

from adintel import db, targets
from adintel.collectors.mock import MockCollector
from adintel.pipeline import run_daily


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--start", default="2026-01-01")
    args = ap.parse_args()

    db.init_db()
    conn = db.connect()
    if not targets.list_active(conn):
        print("⚠️  타겟이 없습니다. 먼저 `python scripts/seed_targets.py` 실행.")
        return

    collector = MockCollector(start_date=args.start)
    start = dt.date.fromisoformat(args.start)
    agg = {"appeared": 0, "still": 0, "disappeared": 0}

    for d in range(args.days):
        day = (start + dt.timedelta(days=d)).isoformat()
        r = run_daily(conn, collector, day)
        agg["appeared"] += r.appeared
        agg["still"] += r.still_active
        agg["disappeared"] += r.disappeared
        if d % 5 == 0 or d == args.days - 1:
            print(f"  day {d:2d} ({day}): +{r.appeared} ~{r.still_active} -{r.disappeared}")

    # 결과 요약
    ended = conn.execute(
        "SELECT COUNT(*), AVG(observed_active_days), MAX(observed_active_days) "
        "FROM ads WHERE status='ended'"
    ).fetchone()
    active = conn.execute("SELECT COUNT(*) FROM ads WHERE status='active'").fetchone()[0]
    clusters = conn.execute("SELECT COUNT(*) FROM concept_clusters").fetchone()[0]
    events = conn.execute("SELECT COUNT(*) FROM ad_events").fetchone()[0]

    print("\n=== 시뮬레이션 결과 ===")
    print(f"이벤트(append-only) 총 {events}건")
    print(f"누적: APPEARED {agg['appeared']} / STILL {agg['still']} / DISAPPEARED {agg['disappeared']}")
    print(f"종료 광고 {ended[0]}건 — observed_active_days 평균 "
          f"{(ended[1] or 0):.1f}일, 최대 {ended[2] or 0}일  ← ★2주차 게이트")
    print(f"현존 활성 광고 {active}건, 컨셉 클러스터 {clusters}개")
    conn.close()


if __name__ == "__main__":
    main()

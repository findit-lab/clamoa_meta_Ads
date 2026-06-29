"""주간 진입점: tag → analyze → report. 기획서 v2 §6 6~8단계.

usage: python scripts/run_weekly.py [--dry-run]

--dry-run: 외부 전송 없이 콘솔 미리보기만(키 없으면 어차피 콘솔).
"""
import _bootstrap  # noqa: F401
import argparse

from adintel import db
from adintel.analysis.patterns import compute_patterns, low_confidence, winner_concepts
from adintel.reporting import notion, slack
from adintel.tagging.vision import run_tagging


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db.init_db()
    conn = db.connect()

    # 6) 선별 LLM 비전 태깅 (+ 클러스터 전파)
    stats = run_tagging(conn)
    print(f"[tagging] model={stats['model']} "
          f"직접태깅 {stats['directly_tagged']} / 전파 {stats['propagated']}")

    # 7) 패턴 분석 (컨셉 × longevity lift)
    patterns = compute_patterns(conn)
    print("\n[patterns] 상위 lift:")
    for p in patterns[:8]:
        warn = " ⚠️저신뢰" if low_confidence(p) else ""
        print(f"  {p.key:28s} lift {p.lift:>5} (코호트{p.cohort_share}/전체{p.total_share}, n={p.sample_n}){warn}")

    winners = winner_concepts(conn, limit=10)

    # 8) 리포트 (Notion DB + Slack)
    if args.dry_run:
        print("\n[dry-run] 외부 전송 생략, 콘솔 미리보기만")
    notion.report_winners(winners, patterns)
    slack.report_weekly(winners, patterns)

    conn.close()


if __name__ == "__main__":
    main()

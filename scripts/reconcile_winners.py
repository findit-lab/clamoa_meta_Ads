"""노션 '광고 추적 DB'에 이미 적재된 행 중 현재 위너 게이트 미통과 광고를 정리.

게이트(config.WINNER_MIN_DAYS / WINNER_MIN_VARIANTS)가 강화/변경된 뒤, 과거에
게이트 없이 올라간 행을 소급 정리하는 용도. report_ads의 upsert는 신규 적재만 막지
이미 올라간 탈락 행은 건드리지 않으므로 이 스크립트로 별도 정리한다.

usage:
  python scripts/reconcile_winners.py                 # dry-run(기본): 대상만 출력
  python scripts/reconcile_winners.py --apply          # 검토상태='기각' 마킹(되돌림 가능)
  python scripts/reconcile_winners.py --mode archive --apply   # 페이지를 휴지통으로 보관

사람이 검토상태를 검토중/채택/기각으로 바꾼 행은 보존한다(휴먼 게이트).
로컬 ads 테이블에 없는 [샘플] 행은 평가 대상이 아니다.
"""
import _bootstrap  # noqa: F401
import argparse

from adintel import db
from adintel.reporting.notion_ads import reconcile_winners


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["mark", "archive"], default="mark",
                    help="mark=검토상태 '기각' 마킹(기본), archive=휴지통 이동")
    ap.add_argument("--apply", action="store_true",
                    help="실제 적용(미지정 시 dry-run)")
    args = ap.parse_args()

    db.init_db()
    conn = db.connect()
    reconcile_winners(conn, mode=args.mode, apply=args.apply)
    conn.close()


if __name__ == "__main__":
    main()

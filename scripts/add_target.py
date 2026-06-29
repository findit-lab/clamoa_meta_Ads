"""경쟁사 1곳을 레지스트리에 추가/갱신. URL·핸들·숫자 ID 모두 지원.

예시:
  python scripts/add_target.py --url https://www.facebook.com/ZapierApp --name "Zapier" --category 마케팅SaaS
  python scripts/add_target.py --url HubSpot --name "HubSpot" --category 마케팅SaaS
  python scripts/add_target.py --url 1234567890 --name "어떤 PR사" --category PR대행사

여러 곳을 한 번에:
  python scripts/add_target.py --bulk competitors.txt   # 각 줄: url|name|category
"""
import _bootstrap  # noqa: F401
import argparse
import datetime as dt

from adintel import db, targets
from adintel.models import TargetPage


def _add(conn, raw_url: str, name: str, category: str) -> None:
    page_id, page_url = targets.parse_competitor(raw_url)
    targets.upsert_target(
        conn,
        TargetPage(
            page_id=page_id,
            page_name=name or page_id,
            category=category or "미분류",
            page_url=page_url,
            active=True,
            added_at=dt.date.today().isoformat(),
            note="manual",
        ),
    )
    print(f"  ✅ {name or page_id}  (key={page_id}, url={page_url or '[id로 자동생성]'})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="FB 페이지 URL / 핸들 / 숫자 page_id")
    ap.add_argument("--name", default="")
    ap.add_argument("--category", default="미분류")
    ap.add_argument("--bulk", help="파일 경로. 각 줄: url|name|category")
    ap.add_argument("--purge-seed", action="store_true",
                    help="mock 시드(note='seed') 타겟을 먼저 모두 삭제")
    args = ap.parse_args()

    db.init_db()
    conn = db.connect()

    if args.purge_seed:
        n = targets.purge_by_note(conn, "seed")
        print(f"🧹 mock 시드 {n}곳 삭제")

    if args.bulk:
        with open(args.bulk, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = [p.strip() for p in line.split("|")]
                url = parts[0]
                name = parts[1] if len(parts) > 1 else ""
                cat = parts[2] if len(parts) > 2 else "미분류"
                _add(conn, url, name, cat)
    elif args.url:
        _add(conn, args.url, args.name, args.category)
    else:
        ap.error("--url 또는 --bulk 중 하나는 필요합니다.")

    total = len(targets.list_active(conn))
    print(f"현재 활성 타겟 {total}곳")
    conn.close()


if __name__ == "__main__":
    main()

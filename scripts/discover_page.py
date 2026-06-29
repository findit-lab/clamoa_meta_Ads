"""단일 광고(Ad Library id) → 광고주 페이지 식별 + (선택) 추적 등록.

Facebook Ad Library의 `?id=...` 는 페이지가 아니라 개별 광고다. 이 스크립트는 그
광고를 Apify 액터로 한 건 긁어 광고주 page_id/page_name 을 알아낸다. APIFY_TOKEN 필요.

예시:
  python scripts/discover_page.py --id 2873251402881995
  python scripts/discover_page.py --id 2873251402881995 --track --category 마케팅SaaS
  python scripts/discover_page.py --url "https://www.facebook.com/ads/library/?id=2873251402881995"
"""
import _bootstrap  # noqa: F401
import argparse
import datetime as dt

import config
from adintel import db, targets
from adintel.collectors.apify import ApifyCollector, page_ad_library_url
from adintel.models import TargetPage


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", help="광고 아카이브 ID (?id= 값)")
    ap.add_argument("--url", help="Ad Library 단일 광고 URL")
    ap.add_argument("--track", action="store_true", help="식별된 페이지를 추적 대상으로 등록")
    ap.add_argument("--category", default="미분류")
    ap.add_argument("--name", default="", help="페이지 이름 수동 지정(미지정 시 액터 결과 사용)")
    args = ap.parse_args()

    if not args.id and not args.url:
        ap.error("--id 또는 --url 필요")
    if not config.APIFY_TOKEN:
        ap.error("APIFY_TOKEN 미설정. .env에 토큰을 넣어주세요.")

    ad_url = args.url or f"https://www.facebook.com/ads/library/?id={args.id}"
    print(f"[discover] 액터 실행: {ad_url}")
    info = ApifyCollector().discover(ad_url)

    if info.get("error"):
        print(f"⚠️  액터 에러: {info['error']} ({info.get('errorCode','')})")
        return
    if not info or not info.get("page_id"):
        print("⚠️  이 액터(curious_coder/facebook-ads-library-scraper)는 단일 광고 id로")
        print("    광고주 페이지를 역추적하지 못합니다 (페이지/검색 URL 전용).")
        print("    → FB Ad Library에서 그 광고 카드의 '광고주(페이지)' 링크를 열어 페이지를")
        print("      확인한 뒤, 다음처럼 페이지로 등록하세요:")
        print("      python scripts/add_target.py --url <페이지URL 또는 핸들> --name <이름> --category <분류>")
        return

    pid, pname = info["page_id"], info["page_name"] or "(이름 미상)"
    print(f"\n✅ 광고주 식별:")
    print(f"   page_id   : {pid}")
    print(f"   page_name : {pname}")
    print(f"   ad_id     : {info['ad_archive_id']}")
    print(f"   페이지 광고 전체 보기: {page_ad_library_url(pid, config.APIFY_AD_COUNTRY, 'all')}")

    if args.track:
        db.init_db()
        conn = db.connect()
        targets.upsert_target(
            conn,
            TargetPage(
                page_id=pid,
                page_name=args.name or pname,
                category=args.category,
                page_url=page_ad_library_url(pid, config.APIFY_AD_COUNTRY, config.APIFY_ACTIVE_STATUS),
                active=True,
                added_at=dt.date.today().isoformat(),
                note="discovered",
            ),
        )
        conn.close()
        print(f"\n📌 추적 등록 완료: {args.name or pname} (page_id={pid})")
        print("   이후 `python scripts/run_daily.py` 가 이 페이지를 매일 수집합니다.")


if __name__ == "__main__":
    main()

"""캐러셀 소재 → Cloudinary 업로드 → Meta 캐러셀 광고용 카드 스펙(JSON) 생성.

자동화 루프의 '업로드' 단계. 로컬 소재(data/ad_creatives/meta_ads_260623/*.png)를
Cloudinary에 올려 공개 URL을 확보하고, Meta object_story_spec.link_data.child_attachments
형태의 카드 배열을 stdout(JSON)으로 출력한다.

Meta 광고 생성(child_attachments picture=공개URL)은 현재 meta-ads MCP를 통해 수행한다.
완전 무인화 시에는 Meta 시스템 유저 토큰으로 Graph API 직접 호출이 필요(TODO).

전제: .env에 CLOUDINARY_URL=cloudinary://<api_key>:<api_secret>@<cloud_name>
usage:
  python3 scripts/publish_carousel.py                 # meta_ads_260623 폴더 5장 업로드
  python3 scripts/publish_carousel.py --dir <폴더>     # 다른 소재 폴더
  python3 scripts/publish_carousel.py --landing https://clamoa.com
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = ROOT / "data/ad_creatives/meta_ads_260623"
LANDING = "https://clamoa.com"

# 슬라이드 파일명 → 카드 헤드라인/설명 (캐러셀 카피와 동일 매핑)
CARDS = [
    ("bf_0_cover.png",   "아무 셀럽에게나 협찬하고 계신가요?", "패션 브랜드 협찬 마케팅"),
    ("bf_1_problem.png", "유명하다고 다 어울리진 않습니다",   "노출만 남고 매출은 안 남습니다"),
    ("bf_2_fit.png",     "셀럽보다 중요한 건 ‘결’입니다",      "무드·타깃·가격대까지"),
    ("bf_3_match.png",   "브랜드에 맞는 셀럽을 찾아냅니다",     "셀럽 데이터 기반 매칭"),
    ("bf_4_cta.png",     "지금 무료로 셀럽 추천받으세요",       "clamoa 무료 상담"),
]


def _load_cloudinary():
    # .env에서 CLOUDINARY_URL 주입 (없으면 안내 후 종료)
    env = ROOT / ".env"
    if env.exists() and "CLOUDINARY_URL" not in os.environ:
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("CLOUDINARY_URL="):
                os.environ["CLOUDINARY_URL"] = line.split("=", 1)[1].strip()
    if not os.environ.get("CLOUDINARY_URL"):
        sys.exit(
            "CLOUDINARY_URL 미설정. .env에 다음을 추가하세요:\n"
            "  CLOUDINARY_URL=cloudinary://<api_key>:<api_secret>@<cloud_name>\n"
            "(Cloudinary 콘솔 > Settings > API Keys 에서 확인)"
        )
    try:
        import cloudinary
        import cloudinary.uploader
    except ImportError:
        sys.exit("cloudinary 미설치: ./.venv/bin/pip install cloudinary")
    cloudinary.config(secure=True)  # CLOUDINARY_URL 자동 사용
    return cloudinary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(DEFAULT_DIR))
    ap.add_argument("--landing", default=LANDING)
    ap.add_argument("--folder", default="clamoa/brandfit", help="Cloudinary 폴더(public_id prefix)")
    args = ap.parse_args()

    cloudinary = _load_cloudinary()
    src = Path(args.dir)
    cards = []
    for fname, name, desc in CARDS:
        fpath = src / fname
        if not fpath.exists():
            sys.exit(f"파일 없음: {fpath}")
        res = cloudinary.uploader.upload(
            str(fpath),
            public_id=f"{args.folder}/{fpath.stem}",
            overwrite=True,
            resource_type="image",
        )
        url = res["secure_url"]
        print(f"[uploaded] {fname} -> {url}", file=sys.stderr)
        cards.append({
            "link": args.landing,
            "picture": url,
            "name": name,
            "description": desc,
        })

    # Meta object_story_spec (페이지 ID는 MCP 생성 시점에 주입)
    out = {
        "landing": args.landing,
        "child_attachments": cards,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

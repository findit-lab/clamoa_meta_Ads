"""C2 — ApifyCollector: curious_coder/facebook-ads-library-scraper 액터.

액터: curious_coder/facebook-ads-library-scraper (ID: XtaWFhbtfxyzqrFmd)
- 입력은 URL 기반(Ad Library 검색 URL 또는 페이지 URL). pageIds가 아님.
- 우리는 page_id 레지스트리를 쓰므로 `view_all_page_id` Ad Library URL을 만들어 넘긴다.
- 과금: $0.75 / 1,000 ads.

확인된 입력 스키마(2026-06 기준):
    urls: [{"url": "..."}]            (required)
    count: int                         (총 레코드 수)
    scrapeAdDetails: bool
    limitPerSource: int
    scrapePageAds.activeStatus: "all"|"active"|"inactive"
    scrapePageAds.countryCode: "ALL"|"KR"|...
    scrapePageAds.sortBy / .period

인터페이스는 MockCollector와 동일하므로 파이프라인 코드 변경 없이 교체된다(기획서 §C2).

⚠️ 출력 필드 nesting은 공개 문서에 없음. _normalize()는 snapshot 중첩/평면 키를
   모두 방어적으로 처리한다. **첫 실제 run 후 dataset을 보고 키를 확정·조정할 것.**
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

import config
from ..models import RawAd, TargetPage
from .base import Collector


def page_ad_library_url(page_id: str, country: str, active_status: str) -> str:
    """page_id로 '해당 페이지의 광고 전체' Ad Library URL 생성."""
    q = urllib.parse.urlencode(
        {
            "active_status": active_status,  # active | all | inactive
            "ad_type": "all",
            "country": country,              # ALL | KR | US | ...
            "view_all_page_id": page_id,
        }
    )
    return f"https://www.facebook.com/ads/library/?{q}"


class ApifyCollector(Collector):
    def __init__(self, token: str | None = None, actor_id: str | None = None,
                 country: str | None = None, active_status: str | None = None,
                 count: int | None = None, download_media: bool = True):
        self.token = (token or config.APIFY_TOKEN).strip()
        self.actor_id = (actor_id or config.APIFY_ACTOR_ID).strip()
        self.country = (country or config.APIFY_AD_COUNTRY).strip()
        self.active_status = (active_status or config.APIFY_ACTIVE_STATUS).strip()
        self.count = count if count is not None else config.APIFY_COUNT
        self.download_media = download_media
        if not self.token:
            raise RuntimeError(
                "APIFY_TOKEN 미설정. .env에 토큰을 넣거나 MockCollector를 사용하세요."
            )
        config.ensure_dirs()

    # ── Collector 인터페이스 ─────────────────────────────────────────
    def collect(self, target: TargetPage, observed_at: str) -> list[RawAd]:
        # page_url이 있으면 그대로 사용(페이지 URL 또는 Ad Library URL),
        # 없으면 숫자 page_id로 view_all_page_id URL 생성.
        url = target.page_url or page_ad_library_url(
            target.page_id, self.country, self.active_status
        )
        items = self._run_actor([url])
        out = [self._normalize(it, target.page_id) for it in items]
        if self.download_media:
            for ad in out:
                ad.media_path = self._localize_media(ad.media_path, ad.ad_archive_id)
        return out

    # ── 단일 광고 → 광고주 페이지 식별 (discovery) ──────────────────
    def discover(self, ad_url: str) -> dict:
        """단일 광고 URL을 scrapeAdDetails로 긁어 광고주 page_id/page_name을 반환.

        광고가 비활성일 수 있으므로 activeStatus='all' 로 조회한다.
        """
        items = self._run_actor([ad_url], active_status="all", count=10)
        if not items:
            return {}
        it = items[0]
        if it.get("error"):  # 액터가 에러 레코드를 반환한 경우
            return {"error": it.get("error"), "errorCode": it.get("errorCode", ""), "raw": it}
        snap = it.get("snapshot") or {}
        return {
            "page_id": str(it.get("page_id") or it.get("pageID")
                           or snap.get("page_id") or ""),
            "page_name": (it.get("page_name") or snap.get("page_name")
                          or it.get("pageName") or ""),
            "ad_archive_id": str(it.get("ad_archive_id") or it.get("adArchiveID")
                                 or it.get("id") or ""),
            "raw": it,
        }

    # ── 액터 실행 (run-sync → dataset items) ─────────────────────────
    def _run_actor(self, urls: list[str], active_status: str | None = None,
                   count: int | None = None) -> list[dict]:
        endpoint = (
            f"https://api.apify.com/v2/acts/{self.actor_id.replace('/', '~')}"
            f"/run-sync-get-dataset-items?token={self.token}"
        )
        # 이 액터는 count(Maximum charged results) 최소 10 요구.
        eff_count = count if count is not None else self.count
        payload = {
            "urls": [{"url": u} for u in urls],
            "count": max(10, eff_count),
            "scrapeAdDetails": True,
            "scrapePageAds.activeStatus": active_status or self.active_status,
            "scrapePageAds.countryCode": self.country,
            "scrapePageAds.sortBy": "impressions_desc",
        }
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.loads(resp.read().decode())

    # ── 출력 정규화 ─────────────────────────────────────────────────
    # 실제 스키마(curious_coder, 2026-06 확인):
    #   item.{ad_archive_id, page_id, page_name, is_active, start_date, ...}
    #   item.snapshot.{body:{text}, title, cta_type, cta_text, link_url, images[], videos[], cards[]}
    # DCO 광고는 콘텐츠가 snapshot.cards[0]에 있고 루트 body/title은 {{템플릿}} 변수다.
    # → card 우선, 템플릿/빈값이면 snapshot 폴백.
    @staticmethod
    def _normalize(item: dict, page_id: str) -> RawAd:
        snap = item.get("snapshot") or {}
        cards = snap.get("cards") or []
        card = cards[0] if cards and isinstance(cards[0], dict) else {}

        def text_of(v):
            if isinstance(v, dict):
                return v.get("text", "")
            return v or ""

        def field(*keys):
            # 1순위: 템플릿이 아닌 실제 값(card → snapshot → item)
            for src in (card, snap, item):
                for k in keys:
                    v = text_of(src.get(k))
                    if v and "{{" not in str(v):
                        return v
            # 2순위: 템플릿이라도 비어있는 것보단 낫다
            for src in (card, snap, item):
                for k in keys:
                    v = text_of(src.get(k))
                    if v:
                        return v
            return ""

        media_url = ApifyCollector._extract_media(card) or ApifyCollector._extract_media(snap)
        return RawAd(
            ad_archive_id=str(item.get("ad_archive_id") or item.get("adArchiveID")
                              or item.get("ad_id") or item.get("id") or ""),
            page_id=str(item.get("page_id") or item.get("pageID") or page_id),
            headline=field("title"),
            ad_copy=field("body"),
            cta_type=field("cta_type", "cta_text"),
            link_url=field("link_url", "caption"),
            media_path=media_url,           # collect()에서 로컬로 다운로드됨
            media_url=media_url,             # 원본 fbcdn URL (노션 미디어링크)
            fb_start_date=ApifyCollector._fb_start(item),
            media_type=ApifyCollector._media_type(card, snap),
            # 변형수 = 묶인 광고 수(collation_count) 또는 DCO 카드 수. item.total은
            # 페이지 전체 광고수라 변형수가 아니므로 쓰지 않는다.
            variant_count=max(int(item.get("collation_count") or 0), len(cards), 1),
            display_format=str(snap.get("display_format") or ""),
            targeting=ApifyCollector._targeting(item),
        )

    @staticmethod
    def _fb_start(item: dict) -> str:
        """FB 라이브러리 시작일 → YYYY-MM-DD. start_date(epoch) 또는 *_formatted."""
        import datetime as _dt
        v = item.get("start_date")
        if isinstance(v, (int, float)) and v > 0:
            try:
                return _dt.datetime.utcfromtimestamp(int(v)).date().isoformat()
            except Exception:
                pass
        sf = item.get("start_date_formatted") or ""
        return str(sf)[:10] if sf else ""

    @staticmethod
    def _media_type(card: dict, snap: dict) -> str:
        for src in (card, snap):
            if not isinstance(src, dict):
                continue
            if src.get("video_hd_url") or src.get("video_sd_url") or (src.get("videos") or []):
                return "video"
        for src in (card, snap):
            if not isinstance(src, dict):
                continue
            if src.get("original_image_url") or (src.get("images") or []):
                return "image"
        return "unknown"

    @staticmethod
    def _targeting(item: dict) -> str:
        countries = item.get("targeted_or_reached_countries") or []
        if isinstance(countries, list) and countries:
            return "mixed" if len(countries) > 1 else str(countries[0])
        return ""

    @staticmethod
    def _extract_media(src: dict) -> str:
        """card 또는 snapshot에서 대표 '이미지' URL 1개 추출 (phash용 정지 이미지 우선)."""
        if not isinstance(src, dict):
            return ""
        # 직접 이미지 키 (정지 이미지 → 영상 썸네일 순)
        for k in ("original_image_url", "resized_image_url",
                  "watermarked_resized_image_url", "video_preview_image_url"):
            if src.get(k):
                return src[k]
        # 중첩 images[]
        imgs = src.get("images") or []
        if imgs and isinstance(imgs[0], dict):
            return (imgs[0].get("original_image_url") or imgs[0].get("resized_image_url")
                    or imgs[0].get("url", ""))
        # 중첩 videos[] (썸네일)
        vids = src.get("videos") or []
        if vids and isinstance(vids[0], dict):
            return vids[0].get("video_preview_image_url", "")
        return ""

    # ── 미디어 로컬 다운로드 (phash·vision이 로컬 파일을 요구) ───────
    def _localize_media(self, media_url: str, ad_id: str) -> str:
        if not media_url or not media_url.startswith("http"):
            return media_url
        ext = ".jpg"
        dest = config.MEDIA_DIR / f"{ad_id}{ext}"
        if dest.exists() and dest.stat().st_size > 0:
            return str(dest)
        try:
            with urllib.request.urlopen(media_url, timeout=60) as r:
                dest.write_bytes(r.read())
            return str(dest)
        except Exception:
            return media_url  # 실패 시 원격 URL 유지(phash는 스킵됨)

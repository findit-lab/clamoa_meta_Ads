"""C2 — MockCollector: 결정적 합성 수집기.

실데이터 없이 Diff 엔진(★핵심①)·클러스터링(★핵심②)·태깅(★핵심③)을 증명하기 위한
합성 데이터 생성기. 핵심 설계:

- 각 페이지는 고정된 "캠페인 로스터"를 가진다. 캠페인 = (concept, variant, start_day, duration).
- duration이 길수록 longevity 위너. 일부 concept에 긴 duration을 편향 → C6 lift 신호가 발생.
- concept별로 합성 크리에이티브 이미지를 생성: 같은 concept = 유사 픽셀(pHash 근접),
  다른 concept = 먼 픽셀. → "같은 컨셉 다른 픽셀" 클러스터링이 실제로 동작.

모두 hashlib 시드 기반이라 재현 가능(같은 날짜·페이지 → 같은 결과).
"""
from __future__ import annotations

import datetime as dt
import hashlib

import config
from ..models import RawAd, TargetPage
from .base import Collector


# 합성 크리에이티브 컨셉. 기획서 §C5 택사노미 값을 라벨로 부여 → 태깅·lift 검증에 사용.
# winner_bias가 클수록 캠페인 duration이 길어진다(= 장수 위너).
CONCEPTS = [
    # id, hue, offer_type,         hook_type,      angle,      winner_bias
    (0, 10,  "무료 진단·감사",     "비포애프터",   "성과향상", 1.0),  # 강한 위너
    (1, 45,  "무료 진단·감사",     "숫자·통계",    "비용절감", 0.9),  # 위너
    (2, 90,  "웨비나",             "권위·실적",    "성과향상", 0.5),
    (3, 140, "데모",               "질문",         "시간절감", 0.4),
    (4, 200, "자료 다운로드",      "문제제기",     "리스크감소", 0.2),
    (5, 280, "무료 상담",          "긴급성",       "시간절감", 0.1),  # 단명
]

_OFFER_TO_CTA = {
    "무료 진단·감사": "지금 신청",
    "웨비나": "지금 신청",
    "데모": "문의하기",
    "자료 다운로드": "다운로드",
    "무료 상담": "메시지 보내기",
}


def _h(*parts: str) -> int:
    """문자열들로부터 결정적 정수 시드."""
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest(), 16)


class MockCollector(Collector):
    """start_date 기준 day-index로 캠페인 활성 여부를 계산하는 합성 수집기."""

    def __init__(self, start_date: str, campaigns_per_page: int = 24, window_days: int = 45):
        self.start = dt.date.fromisoformat(start_date)
        self.campaigns_per_page = campaigns_per_page
        self.window_days = window_days
        config.ensure_dirs()

    # ── 캠페인 로스터 (페이지별 결정적) ──────────────────────────────
    def _roster(self, page_id: str) -> list[dict]:
        roster = []
        for i in range(self.campaigns_per_page):
            seed = _h(page_id, str(i))
            concept = CONCEPTS[seed % len(CONCEPTS)]
            _, _, offer, hook, angle, bias = concept
            # duration: winner_bias가 클수록 길다 (3~38일).
            base = 3 + int(bias * 32)
            duration = base + (seed >> 8) % 6
            # start_day: 윈도우 전체에 분산.
            start_day = (seed >> 16) % self.window_days
            variant = (seed >> 24) % 3  # 같은 concept의 픽셀 변형
            ad_id = f"{page_id}-ad-{i:03d}"
            roster.append(
                {
                    "ad_id": ad_id,
                    "concept": concept,
                    "offer": offer,
                    "hook": hook,
                    "angle": angle,
                    "start_day": start_day,
                    "duration": duration,
                    "variant": variant,
                    "seed": seed,
                    "bias": bias,
                }
            )
        return roster

    # ── Collector 인터페이스 ─────────────────────────────────────────
    def collect(self, target: TargetPage, observed_at: str) -> list[RawAd]:
        page_id = target.page_id
        day = (dt.date.fromisoformat(observed_at) - self.start).days
        out: list[RawAd] = []
        for c in self._roster(page_id):
            if c["start_day"] <= day < c["start_day"] + c["duration"]:
                media = self._ensure_image(c["concept"][0], c["variant"])
                concept_id = c["concept"][0]
                # winner_bias가 클수록 더 오래된 FB 시작일 → 게재일수 큼
                fb_start = (self.start - dt.timedelta(days=int(c["bias"] * 180) + 15)).isoformat()
                out.append(
                    RawAd(
                        ad_archive_id=c["ad_id"],
                        page_id=page_id,
                        headline=f'{c["offer"]} — {c["hook"]}',
                        ad_copy=f'{c["angle"]} 중심 카피 ({c["hook"]})',
                        cta_type=_OFFER_TO_CTA.get(c["offer"], "더 알아보기"),
                        link_url=f"https://example.com/{page_id}/{c['ad_id']}",
                        media_path=str(media),
                        media_url=f"https://mock.cdn/{concept_id}_{c['variant']}.png",
                        fb_start_date=fb_start,
                        media_type="image" if concept_id % 2 == 0 else "video",
                        variant_count=10 + (c["seed"] >> 4) % 55,
                        display_format="DCO" if c["bias"] >= 0.9 else "",
                        targeting="mixed" if concept_id % 2 == 0 else "KR",
                    )
                )
        return out

    # ── 합성 크리에이티브 이미지 ─────────────────────────────────────
    def _ensure_image(self, concept_id: int, variant: int):
        """concept별 유사 이미지 + 미세 variant 노이즈. pHash 근접중복/클러스터용."""
        path = config.MEDIA_DIR / f"concept{concept_id}_v{variant}.png"
        if path.exists():
            return path
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            # Pillow 미설치 시: 빈 파일만 만들어 파이프라인은 계속 동작(phash는 스킵).
            path.write_bytes(b"")
            return path

        hue = CONCEPTS[concept_id][1]
        img = Image.new("HSV", (64, 64), (hue, 180, 200)).convert("RGB")
        d = ImageDraw.Draw(img)
        # concept 식별용 큰 블록 (동일 concept = 동일)
        d.rectangle([12, 12, 52, 52], fill=((hue * 7) % 256, 120, 200))
        # variant 노이즈 (작아서 pHash 해밍거리 소폭만 증가)
        vx = 4 + variant * 6
        d.rectangle([vx, 4, vx + 4, 8], fill=(255, 255, 255))
        img.save(path)
        return path

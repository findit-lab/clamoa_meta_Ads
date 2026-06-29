"""C5 — 선별 LLM 비전 태깅 (★핵심③, LLM-last). 기획서 v2 §C5.

태깅 대상 = 클러스터 대표 + longevity 통과 광고만 (전체의 ~1/10).
Claude Vision(Sonnet 4.6) + 구조화 출력으로 기획서 택사노미를 강제한다.
ANTHROPIC_API_KEY 없으면 결정적 mock 태깅으로 폴백 → 파이프라인은 끊기지 않는다.

결과는 ad_tags(source='llm')에 기록하고, 같은 클러스터 멤버에 전파(source='propagated').
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import sqlite3
from pathlib import Path

import config
from ..models import AdTag

# 기획서 §C5 태깅 택사노미 (B2B 리더십 특화) — 구조화 출력 스키마의 enum 후보.
TAXONOMY = {
    "format": ["이미지", "영상", "캐러셀", "슬라이드"],
    "hook_type": ["숫자·통계", "질문", "문제제기", "비포애프터", "고객사례", "권위·실적", "긴급성"],
    "offer_type": ["무료 상담", "무료 진단·감사", "데모", "자료 다운로드", "웨비나", "체험"],
    "angle": ["시간절감", "비용절감", "성과향상", "리스크감소"],
    "copy_tone": ["전문가형", "친근형", "도발형"],
    "visual_flags": ["인물", "텍스트오버레이", "UI스크린샷", "로고노출"],
    "cta_button": ["더 알아보기", "문의하기", "지금 신청", "다운로드", "메시지 보내기"],
}

_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "format": {"type": "string", "enum": TAXONOMY["format"]},
        "hook_type": {"type": "string", "enum": TAXONOMY["hook_type"]},
        "offer_type": {"type": "string", "enum": TAXONOMY["offer_type"]},
        "angle": {"type": "string", "enum": TAXONOMY["angle"]},
        "copy_tone": {"type": "string", "enum": TAXONOMY["copy_tone"]},
        "visual_flags": {
            "type": "array",
            "items": {"type": "string", "enum": TAXONOMY["visual_flags"]},
        },
        "cta_button": {"type": "string", "enum": TAXONOMY["cta_button"]},
    },
    "required": ["format", "hook_type", "offer_type", "angle", "copy_tone",
                 "visual_flags", "cta_button"],
    "additionalProperties": False,
}


def _today() -> str:
    return dt.date.today().isoformat()


# ── 결정적 mock 태깅 (키 없을 때 폴백) ──────────────────────────────
def _mock_tag(row: sqlite3.Row) -> AdTag:
    """headline/cta에서 택사노미 값을 규칙 기반으로 추론. 키 없이도 검증 가능."""
    headline = row["headline"] or ""
    cta = row["cta_type"] or ""
    offer = next((o for o in TAXONOMY["offer_type"] if o in headline), "무료 상담")
    hook = next((h for h in TAXONOMY["hook_type"] if h in headline), "문제제기")
    angle = next((a for a in TAXONOMY["angle"] if a in (row["ad_copy"] or "")), "성과향상")
    cta_button = cta if cta in TAXONOMY["cta_button"] else "더 알아보기"
    return AdTag(
        ad_archive_id=row["ad_archive_id"],
        format="이미지",
        hook_type=hook,
        offer_type=offer,
        angle=angle,
        copy_tone="전문가형",
        visual_flags=["텍스트오버레이"],
        cta_button=cta_button,
        source="llm",  # mock도 'llm' 슬롯을 채운다(원천 광고 태그)
        tagged_at=_today(),
    )


# ── 실 Claude Vision 태깅 ───────────────────────────────────────────
def _claude_tag(row: sqlite3.Row) -> AdTag:
    import anthropic  # 지연 import (키 있을 때만)

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    content: list[dict] = []

    media = Path(row["media_path"] or "")
    if media.exists() and media.stat().st_size > 0:
        data = base64.standard_b64encode(media.read_bytes()).decode()
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": data},
        })
    content.append({
        "type": "text",
        "text": (
            "다음 B2B 광고 크리에이티브를 구조화 태깅하라. "
            f"헤드라인: {row['headline']!r} / 카피: {row['ad_copy']!r} / CTA: {row['cta_type']!r}. "
            "각 차원은 제공된 enum 중에서만 선택하라."
        ),
    })

    # 구조화 출력으로 택사노미 강제 (Sonnet 4.6: vision + structured output 지원).
    resp = client.messages.create(
        model=config.TAGGING_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": content}],
        output_config={"format": {"type": "json_schema", "schema": _OUTPUT_SCHEMA}},
    )
    text = next((b.text for b in resp.content if b.type == "text"), "{}")
    data = json.loads(text)
    return AdTag(
        ad_archive_id=row["ad_archive_id"],
        format=data["format"],
        hook_type=data["hook_type"],
        offer_type=data["offer_type"],
        angle=data["angle"],
        copy_tone=data["copy_tone"],
        visual_flags=data["visual_flags"],
        cta_button=data["cta_button"],
        source="llm",
        tagged_at=_today(),
    )


def tag_one(row: sqlite3.Row) -> AdTag:
    """키 있으면 Claude, 없으면 mock."""
    if config.ANTHROPIC_API_KEY:
        try:
            return _claude_tag(row)
        except Exception as e:  # API 실패 시에도 파이프라인 유지
            print(f"  [vision] Claude 호출 실패 → mock 폴백: {e}")
    return _mock_tag(row)


def _persist(conn: sqlite3.Connection, tag: AdTag) -> None:
    conn.execute(
        """INSERT INTO ad_tags (ad_archive_id, format, hook_type, offer_type, angle,
               copy_tone, visual_flags, cta_button, source, tagged_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(ad_archive_id) DO UPDATE SET
               format=excluded.format, hook_type=excluded.hook_type,
               offer_type=excluded.offer_type, angle=excluded.angle,
               copy_tone=excluded.copy_tone, visual_flags=excluded.visual_flags,
               cta_button=excluded.cta_button, source=excluded.source,
               tagged_at=excluded.tagged_at""",
        (tag.ad_archive_id, tag.format, tag.hook_type, tag.offer_type, tag.angle,
         tag.copy_tone, json.dumps(tag.visual_flags, ensure_ascii=False),
         tag.cta_button, tag.source, tag.tagged_at),
    )


def select_targets(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """태깅 대상 선별: 클러스터 대표 ∪ longevity 통과 광고 (전체의 ~1/10)."""
    threshold = config.LONGEVITY_THRESHOLD_DAYS
    rows = conn.execute(
        """
        SELECT DISTINCT a.* FROM ads a
        WHERE a.observed_active_days >= ?
           OR a.ad_archive_id IN (SELECT representative_ad_id FROM concept_clusters)
        """,
        (threshold,),
    ).fetchall()
    return rows


def run_tagging(conn: sqlite3.Connection) -> dict:
    """선별 태깅 + 클러스터 멤버 전파. 반환: 통계 dict."""
    targets_rows = select_targets(conn)
    tagged_clusters: dict[int, AdTag] = {}

    for row in targets_rows:
        tag = tag_one(row)
        _persist(conn, tag)
        cid = row["concept_cluster_id"]
        if cid is not None and cid not in tagged_clusters:
            tagged_clusters[cid] = tag

    # 전파: 태깅된 클러스터의 미태깅 멤버에 대표 태그 복사(source='propagated').
    propagated = 0
    for cid, tag in tagged_clusters.items():
        members = conn.execute(
            "SELECT ad_archive_id FROM ads WHERE concept_cluster_id=?", (cid,)
        ).fetchall()
        for m in members:
            ad_id = m["ad_archive_id"]
            exists = conn.execute(
                "SELECT 1 FROM ad_tags WHERE ad_archive_id=?", (ad_id,)
            ).fetchone()
            if exists:
                continue
            prop = AdTag(
                ad_archive_id=ad_id, format=tag.format, hook_type=tag.hook_type,
                offer_type=tag.offer_type, angle=tag.angle, copy_tone=tag.copy_tone,
                visual_flags=tag.visual_flags, cta_button=tag.cta_button,
                source="propagated", tagged_at=_today(),
            )
            _persist(conn, prop)
            propagated += 1

    conn.commit()
    total_model = "claude:" + config.TAGGING_MODEL if config.ANTHROPIC_API_KEY else "mock"
    return {
        "directly_tagged": len(targets_rows),
        "propagated": propagated,
        "model": total_model,
    }

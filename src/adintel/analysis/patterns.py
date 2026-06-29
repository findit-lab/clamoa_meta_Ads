"""C6 — 패턴 분석 (컨셉 × longevity). 기획서 v2 §C6.

lift = P(태그·컨셉 | 장수 코호트) ÷ P(태그·컨셉 | 전체)

장수 코호트 = observed_active_days ≥ LONGEVITY_THRESHOLD_DAYS 인 광고.
태그 차원별로 코호트 점유율 ÷ 전체 점유율을 계산해 '잘 사는' 패턴을 식별한다.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from collections import Counter

import config
from ..models import WinnerPattern

# 단일값 차원 (visual_flags는 배열이라 별도 처리).
_SCALAR_DIMS = ["format", "hook_type", "offer_type", "angle", "copy_tone", "cta_button"]


def _today() -> str:
    return dt.date.today().isoformat()


def _counts(conn: sqlite3.Connection, cohort_only: bool) -> tuple[dict[str, Counter], int]:
    """차원별 값 카운터 + 표본 수. cohort_only=True 면 장수 코호트로 제한."""
    q = """
        SELECT t.format, t.hook_type, t.offer_type, t.angle, t.copy_tone,
               t.cta_button, t.visual_flags, a.observed_active_days
        FROM ad_tags t JOIN ads a ON a.ad_archive_id = t.ad_archive_id
    """
    rows = conn.execute(q).fetchall()
    dims: dict[str, Counter] = {d: Counter() for d in _SCALAR_DIMS}
    dims["visual_flags"] = Counter()
    n = 0
    for r in rows:
        if cohort_only and r["observed_active_days"] < config.LONGEVITY_THRESHOLD_DAYS:
            continue
        n += 1
        for d in _SCALAR_DIMS:
            if r[d]:
                dims[d][r[d]] += 1
        for f in json.loads(r["visual_flags"] or "[]"):
            dims["visual_flags"][f] += 1
    return dims, n


def compute_patterns(conn: sqlite3.Connection) -> list[WinnerPattern]:
    """태그 차원별 lift 계산 + winner_patterns 테이블 기록. lift 내림차순 반환."""
    total_dims, total_n = _counts(conn, cohort_only=False)
    cohort_dims, cohort_n = _counts(conn, cohort_only=True)

    conn.execute("DELETE FROM winner_patterns")
    patterns: list[WinnerPattern] = []
    if total_n == 0 or cohort_n == 0:
        conn.commit()
        return patterns

    for dim, cohort_counter in cohort_dims.items():
        for value, cohort_cnt in cohort_counter.items():
            total_cnt = total_dims[dim].get(value, 0)
            if total_cnt == 0:
                continue
            cohort_share = cohort_cnt / cohort_n
            total_share = total_cnt / total_n
            lift = cohort_share / total_share if total_share else 0.0
            p = WinnerPattern(
                scope="tag",
                key=f"{dim}={value}",
                lift=round(lift, 3),
                cohort_share=round(cohort_share, 3),
                total_share=round(total_share, 3),
                sample_n=cohort_cnt,
                computed_at=_today(),
            )
            patterns.append(p)
            conn.execute(
                """INSERT INTO winner_patterns
                       (scope, key, lift, cohort_share, total_share, sample_n, computed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (p.scope, p.key, p.lift, p.cohort_share, p.total_share, p.sample_n, p.computed_at),
            )
    conn.commit()
    patterns.sort(key=lambda x: x.lift, reverse=True)
    return patterns


def low_confidence(p: WinnerPattern) -> bool:
    """표본수가 작으면 저신뢰 (기획서 §C6 신뢰도 경고)."""
    return p.sample_n < config.MIN_COHORT_SAMPLE


def winner_concepts(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    """위너 컨셉 클러스터 랭킹(노션 적재용 풍부한 행).

    대표 광고의 태그(Offer/Hook/Angle/CTA/Format) + 광고주 카테고리 + 대표 lift +
    Ad Library 링크까지 조인. max_observed_days·광고주 수 기준 정렬.
    """
    rows = conn.execute(
        """SELECT c.cluster_id, c.representative_ad_id, c.member_count,
                  c.advertiser_count, c.max_observed_days,
                  a.headline, a.media_path, a.page_id,
                  t.format, t.hook_type, t.offer_type, t.angle, t.cta_button,
                  p.page_name, p.category
           FROM concept_clusters c
           LEFT JOIN ads a       ON a.ad_archive_id = c.representative_ad_id
           LEFT JOIN ad_tags t   ON t.ad_archive_id = c.representative_ad_id
           LEFT JOIN target_pages p ON p.page_id = a.page_id
           ORDER BY c.max_observed_days DESC, c.advertiser_count DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()

    # 대표 태그값별 lift 빠른 조회 (winner_patterns 에서).
    lift_by_key = {
        r["key"]: r["lift"]
        for r in conn.execute("SELECT key, lift FROM winner_patterns").fetchall()
    }

    out = []
    for r in rows:
        d = dict(r)
        # 대표 컨셉의 대표 lift = offer/hook 패턴 lift 중 최대.
        cand = []
        for dim, val in (("offer_type", d.get("offer_type")), ("hook_type", d.get("hook_type")),
                         ("angle", d.get("angle"))):
            if val:
                cand.append(lift_by_key.get(f"{dim}={val}", 0.0))
        d["lift"] = round(max(cand), 3) if cand else 0.0
        d["confidence"] = "높음" if d["max_observed_days"] >= config.LONGEVITY_THRESHOLD_DAYS else "낮음"
        d["ad_library_url"] = (
            "https://www.facebook.com/ads/library/?active_status=all&ad_type=all"
            f"&country=ALL&view_all_page_id={d.get('page_id') or ''}"
            if d.get("page_id") else ""
        )
        out.append(d)
    return out

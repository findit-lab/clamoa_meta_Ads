"""일일 오케스트레이션: collect → diff → materialize → phash → cluster.

기획서 v2 §6 일일 처리 흐름의 1~4단계.
"""
from __future__ import annotations

import sqlite3

from . import targets
from .collectors.base import Collector
from .diff import DiffResult, process_day
from .embedding import phash as phash_mod
from .embedding.cluster import cluster_ads


def run_daily(conn: sqlite3.Connection, collector: Collector, observed_at: str) -> DiffResult:
    """단일 날짜의 전체 파이프라인 실행. 누적 DiffResult 반환."""
    total = DiffResult()

    # 1) 수집 + 2) Diff (페이지별)
    for page in targets.list_active(conn):
        raw = collector.collect(page, observed_at)
        r = process_day(conn, page.page_id, raw, observed_at)
        total.appeared += r.appeared
        total.still_active += r.still_active
        total.disappeared += r.disappeared

    # 3) pHash: 아직 해시 없는 신규 크리에이티브만 계산.
    for row in conn.execute(
        "SELECT ad_archive_id, media_path FROM ads WHERE phash='' OR phash IS NULL"
    ).fetchall():
        h = phash_mod.compute_phash(row["media_path"])
        if h:
            conn.execute(
                "UPDATE ads SET phash=? WHERE ad_archive_id=?", (h, row["ad_archive_id"])
            )
    conn.commit()

    # 4) 컨셉 클러스터 갱신.
    cluster_ads(conn, observed_at=observed_at)

    return total

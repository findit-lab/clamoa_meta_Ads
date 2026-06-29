"""C4 — 컨셉 클러스터링 (★핵심② 2단계). 기획서 v2 §C4.

"같은 컨셉, 다른 픽셀"을 한 묶음으로 모은다.

MVP는 pHash 해밍거리 기반 그리디 클러스터링(경량 구현). 인터페이스를 추상화해
추후 CLIP/멀티모달 임베딩 + HDBSCAN/코사인으로 교체 가능하게 둔다.

TODO(확장): VisionEmbeddingBackend 구현 — sentence-transformers CLIP로 이미지 임베딩 →
            코사인 유사도 또는 HDBSCAN. extras 의존성(requirements.txt 참고).
"""
from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod

import config
from . import phash


class ClusterBackend(ABC):
    @abstractmethod
    def assign(self, items: list[dict]) -> dict[str, int]:
        """items: [{ad_archive_id, phash, ...}] → {ad_archive_id: cluster_index}."""
        raise NotImplementedError


class PHashClusterBackend(ClusterBackend):
    """pHash 해밍거리 ≤ threshold 면 같은 클러스터 (그리디)."""

    def __init__(self, threshold: int | None = None):
        self.threshold = threshold if threshold is not None else config.PHASH_HAMMING_THRESHOLD

    def assign(self, items: list[dict]) -> dict[str, int]:
        assignment: dict[str, int] = {}
        reps: list[tuple[int, str]] = []  # (cluster_index, representative phash)
        for it in items:
            ad_id, h = it["ad_archive_id"], it.get("phash", "")
            placed = False
            if h:
                for idx, rep_h in reps:
                    if phash.is_near_duplicate(h, rep_h, self.threshold):
                        assignment[ad_id] = idx
                        placed = True
                        break
            if not placed:
                idx = len(reps)
                reps.append((idx, h))
                assignment[ad_id] = idx
        return assignment


def cluster_ads(conn: sqlite3.Connection, backend: ClusterBackend | None = None,
                observed_at: str = "") -> int:
    """전체 ads를 클러스터링하고 concept_cluster_id + concept_clusters 갱신.

    반환: 생성된 클러스터 수.
    """
    backend = backend or PHashClusterBackend()
    rows = conn.execute(
        "SELECT ad_archive_id, page_id, phash, observed_active_days FROM ads"
    ).fetchall()
    items = [dict(r) for r in rows]
    if not items:
        return 0

    assignment = backend.assign(items)

    # ad 행에 클러스터 id 기록.
    for ad_id, idx in assignment.items():
        conn.execute(
            "UPDATE ads SET concept_cluster_id=? WHERE ad_archive_id=?", (idx, ad_id)
        )

    # 클러스터 집계 테이블 재구축.
    conn.execute("DELETE FROM concept_clusters")
    by_cluster: dict[int, list[dict]] = {}
    for it in items:
        by_cluster.setdefault(assignment[it["ad_archive_id"]], []).append(it)

    for idx, members in by_cluster.items():
        rep = max(members, key=lambda m: m["observed_active_days"])
        advertisers = {m["page_id"] for m in members}
        conn.execute(
            """INSERT INTO concept_clusters
                   (cluster_id, label, representative_ad_id, member_count,
                    advertiser_count, max_observed_days, updated_at)
               VALUES (?, '', ?, ?, ?, ?, ?)""",
            (idx, rep["ad_archive_id"], len(members), len(advertisers),
             rep["observed_active_days"], observed_at),
        )
    conn.commit()
    return len(by_cluster)

"""C2 — Collector 인터페이스. 기획서 v2 §C2 "Collector 인터페이스".

수집 구현체(Apify/Mock/SerpApi 등)를 교체 가능하게 추상화한다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import RawAd, TargetPage


class Collector(ABC):
    """페이지별 '현재 활성 광고 집합 + 크리에이티브'를 반환."""

    @abstractmethod
    def collect(self, target: TargetPage, observed_at: str) -> list[RawAd]:
        """observed_at(YYYY-MM-DD) 시점에 target 페이지의 활성 광고 목록 반환."""
        raise NotImplementedError

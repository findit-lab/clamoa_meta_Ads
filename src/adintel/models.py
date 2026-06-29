"""도메인 모델 (dataclass). 기획서 v2 §5 데이터 모델과 1:1 대응."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# C2 수집기가 반환하는 원본 단위. 아직 DB에 들어가기 전.
@dataclass
class RawAd:
    ad_archive_id: str
    page_id: str
    ad_copy: str = ""
    headline: str = ""
    cta_type: str = ""
    link_url: str = ""
    media_path: str = ""  # 로컬 크리에이티브 경로 (mock은 합성 이미지)
    # 노션 광고추적 DB용 메타데이터 (FB Ad Library 출처)
    fb_start_date: str = ""      # FB 라이브러리 시작일 (YYYY-MM-DD)
    media_url: str = ""          # 원본 미디어 URL (fbcdn)
    media_type: str = "unknown"  # image | video | unknown
    variant_count: int = 0       # 변형/collation 수
    display_format: str = ""     # DCO 등 (운영모드 매핑용)
    targeting: str = ""          # 타깃 국가 요약 (mixed | KR | ...)


# C1 타겟 페이지 레지스트리
@dataclass
class TargetPage:
    page_id: str
    page_name: str
    category: str  # PR대행사 | 마케팅SaaS | ...
    page_url: str = ""  # FB 페이지/Ad Library URL (있으면 수집기가 직접 사용)
    active: bool = True
    added_at: str = ""
    note: str = ""


# 상태 테이블 (이벤트에서 materialize) — 기획서 §5 ads
@dataclass
class Ad:
    ad_archive_id: str
    page_id: str
    first_seen: str
    last_seen_active: str
    status: str  # active | ended
    observed_active_days: int = 0  # ★핵심: 실측 longevity
    ad_copy: str = ""
    headline: str = ""
    cta_type: str = ""
    link_url: str = ""
    media_path: str = ""
    phash: str = ""
    concept_cluster_id: Optional[int] = None
    updated_at: str = ""
    # 노션 광고추적 DB용 메타데이터
    fb_start_date: str = ""
    media_url: str = ""
    media_type: str = "unknown"
    variant_count: int = 0
    display_format: str = ""
    targeting: str = ""


# C4 컨셉 클러스터
@dataclass
class ConceptCluster:
    cluster_id: int
    label: str
    representative_ad_id: str
    member_count: int = 0
    advertiser_count: int = 0
    max_observed_days: int = 0
    updated_at: str = ""


# C5 선별 태그 (기획서 §C5 택사노미)
@dataclass
class AdTag:
    ad_archive_id: str
    format: str = ""          # 이미지 | 영상 | 캐러셀 | 슬라이드
    hook_type: str = ""       # 숫자·통계 | 질문 | 문제제기 | 비포애프터 | 고객사례 | 권위·실적 | 긴급성
    offer_type: str = ""      # 무료 상담 | 무료 진단·감사 | 데모 | 자료 다운로드 | 웨비나 | 체험
    angle: str = ""           # 시간절감 | 비용절감 | 성과향상 | 리스크감소
    copy_tone: str = ""       # 전문가형 | 친근형 | 도발형
    visual_flags: list[str] = field(default_factory=list)  # 인물 | 텍스트오버레이 | UI스크린샷 | 로고노출
    cta_button: str = ""      # 더 알아보기 | 문의하기 | 지금 신청 | 다운로드 | 메시지 보내기
    source: str = "llm"       # llm | propagated
    tagged_at: str = ""


# C6 패턴 분석 결과
@dataclass
class WinnerPattern:
    scope: str   # tag | concept_cluster
    key: str     # 예: "offer_type=무료 진단·감사"
    lift: float
    cohort_share: float
    total_share: float
    sample_n: int
    computed_at: str = ""
    pattern_id: Optional[int] = None

"""중앙 설정: .env 로드 + 경로 + 임계값.

기획서 v2 §C3~C6의 임계값을 한 곳에서 관리한다.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv 미설치 시에도 동작 (환경변수만 사용)
    pass


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


# ── 경로 ───────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATABASE_URL = (
    os.getenv("ADINTEL_DATABASE_URL")
    or os.getenv("SUPABASE_DATABASE_URL")
    or os.getenv("DATABASE_URL")
    or ""
).strip()
DB_PATH = Path(os.getenv("ADINTEL_DB_PATH", DATA_DIR / "adintel.db"))
MEDIA_DIR = DATA_DIR / "media"
MOCK_DIR = DATA_DIR / "mock"
GENERATED_DIR = DATA_DIR / "generated"

# ── 수집기 (C2) ────────────────────────────────────────────────────
APIFY_TOKEN = os.getenv("APIFY_TOKEN", "").strip()
# 사용 액터: curious_coder/facebook-ads-library-scraper (ID: XtaWFhbtfxyzqrFmd)
APIFY_ACTOR_ID = os.getenv("APIFY_ACTOR_ID", "curious_coder/facebook-ads-library-scraper").strip()
# Ad Library 국가 코드 (URL country + scrapePageAds.countryCode). ALL=전체.
APIFY_AD_COUNTRY = os.getenv("ADINTEL_AD_COUNTRY", "ALL").strip()
# 일일 스냅샷은 '현재 활성' 광고 집합이 필요 → active 권장. (all|active|inactive)
APIFY_ACTIVE_STATUS = os.getenv("ADINTEL_ACTIVE_STATUS", "active").strip()
# 페이지당 가져올 최대 레코드 수 (count).
APIFY_COUNT = _env_int("ADINTEL_APIFY_COUNT", 200)

# ── LLM 비전 태깅 (C5) ─────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
# 비용 우선: Sonnet 4.6 (vision + 구조화 출력 지원). 키 없으면 mock 폴백.
TAGGING_MODEL = os.getenv("ADINTEL_TAGGING_MODEL", "claude-sonnet-4-6").strip()

# ── 리포팅 (C7) ────────────────────────────────────────────────────
NOTION_TOKEN = os.getenv("NOTION_TOKEN", "").strip()
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID", "").strip()          # 위너 컨셉 DB
NOTION_ADS_DATABASE_ID = os.getenv("NOTION_ADS_DATABASE_ID", "").strip()  # 광고 추적 DB(per-ad)
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "").strip()

# ── Meta Ads 성과 대시보드 (v1) ────────────────────────────────────
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "").strip()
META_GRAPH_API_VERSION = os.getenv("META_GRAPH_API_VERSION", "v25.0").strip()
META_SYNC_INTERVAL_MINUTES = _env_int("META_SYNC_INTERVAL_MINUTES", 30)
META_DEFAULT_TIMEZONE = os.getenv("META_DEFAULT_TIMEZONE", "Asia/Seoul").strip()
META_DEFAULT_CURRENCY = os.getenv("META_DEFAULT_CURRENCY", "KRW").strip()
META_ALERT_MIN_SPEND = _env_float("META_ALERT_MIN_SPEND", 50000)
META_DASHBOARD_HOST = os.getenv("META_DASHBOARD_HOST", "127.0.0.1").strip()
META_DASHBOARD_PORT = _env_int("META_DASHBOARD_PORT", 8000)

# ── Meta Pixel + Conversions API (Clamoa 랜딩 기본) ─────────────────
META_PIXEL_ID = (
    os.getenv("CLAMOA_META_PIXEL_ID")
    or os.getenv("META_PIXEL_ID")
    or ""
).strip()
META_CAPI_ACCESS_TOKEN = (
    os.getenv("CLAMOA_META_CAPI_ACCESS_TOKEN")
    or os.getenv("META_CAPI_ACCESS_TOKEN")
    or META_ACCESS_TOKEN
    or ""
).strip()
META_CAPI_TEST_EVENT_CODE = os.getenv("META_CAPI_TEST_EVENT_CODE", "").strip()
META_CAPI_TIMEOUT_SECONDS = _env_int("META_CAPI_TIMEOUT_SECONDS", 10)
META_CAPI_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("META_CAPI_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]

# ── 광고 소재 생성 (GPT Image) ─────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
IMAGE_MODEL = os.getenv("ADINTEL_IMAGE_MODEL", "gpt-image-2").strip()
IMAGE_SIZE = os.getenv("ADINTEL_IMAGE_SIZE", "1024x1024").strip()
IMAGE_QUALITY = os.getenv("ADINTEL_IMAGE_QUALITY", "high").strip()

# ── 임계값 ─────────────────────────────────────────────────────────
# C5: 이 일수 이상 관측된 광고 = "장수(longevity) 위너 후보" → LLM 태깅 대상.
LONGEVITY_THRESHOLD_DAYS = _env_int("ADINTEL_LONGEVITY_THRESHOLD_DAYS", 14)
# C4: pHash 해밍거리 ≤ 이 값이면 근접중복으로 간주.
PHASH_HAMMING_THRESHOLD = _env_int("ADINTEL_PHASH_HAMMING_THRESHOLD", 6)
# C6: 패턴 lift 신뢰도 경고 기준 (코호트 표본수가 이보다 작으면 저신뢰).
MIN_COHORT_SAMPLE = _env_int("ADINTEL_MIN_COHORT_SAMPLE", 5)
# C7: 위너 후보 게이트 (노션 '광고 추적 DB' 적재 조건). OR 로직 —
#   (게재일수 ≥ WINNER_MIN_DAYS) 이거나 (변형수 ≥ WINNER_MIN_VARIANTS) 이면 후보.
#   둘 다 미달인 광고는 노션에 올리지 않는다. 광고를 오래 돌리거나(longevity 검증)
#   유사 컨셉을 여러 버전으로 운영(성공 공식)하는 소재만 위너 후보로 아카이브.
WINNER_MIN_DAYS = _env_int("ADINTEL_WINNER_MIN_DAYS", 30)
WINNER_MIN_VARIANTS = _env_int("ADINTEL_WINNER_MIN_VARIANTS", 3)
# C3: Diff grace-period. 광고가 안 보여도 곧장 종료하지 않고, 연속 이 횟수만큼
# 미관측돼야 'ended' 확정. 액터가 호출마다 반환 광고수가 출렁이는(109→30) 특성으로
# 인한 false DISAPPEARED를 흡수. 1=즉시 종료(grace 없음), 2=1회 누락 허용.
DISAPPEAR_GRACE_RUNS = _env_int("ADINTEL_DISAPPEAR_GRACE_RUNS", 2)


def ensure_dirs() -> None:
    """런타임 디렉터리 보장."""
    if DATABASE_URL:
        return
    if os.getenv("VERCEL"):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    MOCK_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)

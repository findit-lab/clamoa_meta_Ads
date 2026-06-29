"""Database schema + connection helpers.

- ad_events: append-only 이벤트 스토어 (★핵심①)
- ads: 이벤트에서 materialize 되는 상태 테이블
- 로컬 기본값은 SQLite, 운영에서는 Supabase/Postgres DATABASE_URL을 지원.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

import config

try:
    import psycopg
except ImportError:  # pragma: no cover - exercised only when Postgres is configured.
    psycopg = None  # type: ignore[assignment]

SCHEMA = """
PRAGMA journal_mode=WAL;

-- C1 타겟 광고주
CREATE TABLE IF NOT EXISTS target_pages (
    page_id    TEXT PRIMARY KEY,   -- 레지스트리 키 (숫자 page_id 또는 핸들)
    page_name  TEXT NOT NULL,
    category   TEXT NOT NULL,
    page_url   TEXT DEFAULT '',    -- FB 페이지/Ad Library URL (있으면 수집기가 직접 사용)
    active     INTEGER NOT NULL DEFAULT 1,
    added_at   TEXT NOT NULL,
    note       TEXT DEFAULT ''
);

-- 이벤트 스토어 (append-only) ★핵심①
CREATE TABLE IF NOT EXISTS ad_events (
    event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ad_archive_id   TEXT NOT NULL,
    page_id         TEXT NOT NULL,
    event_type      TEXT NOT NULL,   -- AD_APPEARED | AD_STILL_ACTIVE | AD_MISSING | AD_DISAPPEARED
    observed_at     TEXT NOT NULL,   -- ISO date (YYYY-MM-DD)
    payload_ref     TEXT DEFAULT ''  -- 원본 페이로드/미디어 경로
);
CREATE INDEX IF NOT EXISTS idx_events_ad ON ad_events(ad_archive_id);
CREATE INDEX IF NOT EXISTS idx_events_page ON ad_events(page_id);

-- 상태 테이블 (이벤트에서 materialize)
CREATE TABLE IF NOT EXISTS ads (
    ad_archive_id        TEXT PRIMARY KEY,
    page_id              TEXT NOT NULL,
    first_seen           TEXT NOT NULL,
    last_seen_active     TEXT NOT NULL,
    status               TEXT NOT NULL,   -- active | ended
    observed_active_days INTEGER NOT NULL DEFAULT 0,  -- ★ 실측 longevity
    miss_streak          INTEGER NOT NULL DEFAULT 0,  -- C3 grace: 연속 미관측 횟수
    ad_copy              TEXT DEFAULT '',
    headline             TEXT DEFAULT '',
    cta_type             TEXT DEFAULT '',
    link_url             TEXT DEFAULT '',
    media_path           TEXT DEFAULT '',
    phash                TEXT DEFAULT '',
    concept_cluster_id   INTEGER,
    updated_at           TEXT NOT NULL,
    -- 노션 광고추적 DB용 메타데이터 (FB Ad Library 출처)
    fb_start_date        TEXT DEFAULT '',
    media_url            TEXT DEFAULT '',
    media_type           TEXT DEFAULT 'unknown',
    variant_count        INTEGER DEFAULT 0,
    display_format       TEXT DEFAULT '',
    targeting            TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ads_page ON ads(page_id);
CREATE INDEX IF NOT EXISTS idx_ads_status ON ads(status);
CREATE INDEX IF NOT EXISTS idx_ads_cluster ON ads(concept_cluster_id);

-- C4 컨셉 클러스터
CREATE TABLE IF NOT EXISTS concept_clusters (
    cluster_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    label               TEXT DEFAULT '',
    representative_ad_id TEXT,
    member_count        INTEGER DEFAULT 0,
    advertiser_count    INTEGER DEFAULT 0,
    max_observed_days   INTEGER DEFAULT 0,
    updated_at          TEXT NOT NULL
);

-- C5 선별 태그
CREATE TABLE IF NOT EXISTS ad_tags (
    ad_archive_id TEXT PRIMARY KEY,
    format        TEXT DEFAULT '',
    hook_type     TEXT DEFAULT '',
    offer_type    TEXT DEFAULT '',
    angle         TEXT DEFAULT '',
    copy_tone     TEXT DEFAULT '',
    visual_flags  TEXT DEFAULT '[]',  -- JSON 배열
    cta_button    TEXT DEFAULT '',
    source        TEXT DEFAULT 'llm', -- llm | propagated
    tagged_at     TEXT NOT NULL
);

-- C6 패턴 분석 결과
CREATE TABLE IF NOT EXISTS winner_patterns (
    pattern_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    scope        TEXT NOT NULL,   -- tag | concept_cluster
    key          TEXT NOT NULL,
    lift         REAL NOT NULL,
    cohort_share REAL NOT NULL,
    total_share  REAL NOT NULL,
    sample_n     INTEGER NOT NULL,
    computed_at  TEXT NOT NULL
);

-- Meta Ads 성과 대시보드: 다중 광고계정 레지스트리
CREATE TABLE IF NOT EXISTS meta_ad_accounts (
    ad_account_id   TEXT PRIMARY KEY, -- act_ prefix 없는 숫자/문자 ID
    account_name    TEXT NOT NULL,
    currency        TEXT DEFAULT 'KRW',
    timezone_name   TEXT DEFAULT 'Asia/Seoul',
    active          INTEGER NOT NULL DEFAULT 1,
    target_action   TEXT DEFAULT 'purchase',
    min_alert_spend REAL NOT NULL DEFAULT 50000,
    note            TEXT DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_meta_ad_accounts_active
ON meta_ad_accounts(active);

-- Meta Ads Insights 최신 일자별 fact.
CREATE TABLE IF NOT EXISTS meta_insights (
    ad_account_id                  TEXT NOT NULL,
    level                          TEXT NOT NULL, -- account | campaign | adset | ad
    date_start                     TEXT NOT NULL,
    date_stop                      TEXT NOT NULL,
    object_id                      TEXT NOT NULL,
    object_name                    TEXT DEFAULT '',
    campaign_id                    TEXT DEFAULT '',
    campaign_name                  TEXT DEFAULT '',
    adset_id                       TEXT DEFAULT '',
    adset_name                     TEXT DEFAULT '',
    ad_id                          TEXT DEFAULT '',
    ad_name                        TEXT DEFAULT '',
    spend                          REAL NOT NULL DEFAULT 0,
    impressions                    INTEGER NOT NULL DEFAULT 0,
    reach                          INTEGER NOT NULL DEFAULT 0,
    frequency                      REAL NOT NULL DEFAULT 0,
    clicks                         INTEGER NOT NULL DEFAULT 0,
    inline_link_clicks             INTEGER NOT NULL DEFAULT 0,
    cpc                            REAL NOT NULL DEFAULT 0,
    cpm                            REAL NOT NULL DEFAULT 0,
    ctr                            REAL NOT NULL DEFAULT 0,
    conversions                    REAL NOT NULL DEFAULT 0,
    conversion_value               REAL NOT NULL DEFAULT 0,
    purchase_roas                  REAL NOT NULL DEFAULT 0,
    cpa                            REAL NOT NULL DEFAULT 0,
    actions_json                   TEXT DEFAULT '[]',
    action_values_json             TEXT DEFAULT '[]',
    cost_per_action_type_json      TEXT DEFAULT '[]',
    raw_json                       TEXT DEFAULT '{}',
    synced_at                      TEXT NOT NULL,
    PRIMARY KEY (ad_account_id, level, date_start, object_id)
);
CREATE INDEX IF NOT EXISTS idx_meta_insights_account_date
ON meta_insights(ad_account_id, date_start);
CREATE INDEX IF NOT EXISTS idx_meta_insights_level_date
ON meta_insights(level, date_start);
CREATE INDEX IF NOT EXISTS idx_meta_insights_campaign
ON meta_insights(ad_account_id, campaign_id, date_start);

-- Meta Ads Insights 플랫폼/노출 위치별 breakdown fact.
CREATE TABLE IF NOT EXISTS meta_insight_breakdowns (
    ad_account_id                  TEXT NOT NULL,
    level                          TEXT NOT NULL, -- account | campaign | adset | ad
    date_start                     TEXT NOT NULL,
    date_stop                      TEXT NOT NULL,
    object_id                      TEXT NOT NULL,
    object_name                    TEXT DEFAULT '',
    campaign_id                    TEXT DEFAULT '',
    campaign_name                  TEXT DEFAULT '',
    adset_id                       TEXT DEFAULT '',
    adset_name                     TEXT DEFAULT '',
    ad_id                          TEXT DEFAULT '',
    ad_name                        TEXT DEFAULT '',
    publisher_platform             TEXT NOT NULL DEFAULT '',
    platform_position              TEXT NOT NULL DEFAULT '',
    spend                          REAL NOT NULL DEFAULT 0,
    impressions                    INTEGER NOT NULL DEFAULT 0,
    reach                          INTEGER NOT NULL DEFAULT 0,
    frequency                      REAL NOT NULL DEFAULT 0,
    clicks                         INTEGER NOT NULL DEFAULT 0,
    inline_link_clicks             INTEGER NOT NULL DEFAULT 0,
    cpc                            REAL NOT NULL DEFAULT 0,
    cpm                            REAL NOT NULL DEFAULT 0,
    ctr                            REAL NOT NULL DEFAULT 0,
    conversions                    REAL NOT NULL DEFAULT 0,
    conversion_value               REAL NOT NULL DEFAULT 0,
    purchase_roas                  REAL NOT NULL DEFAULT 0,
    cpa                            REAL NOT NULL DEFAULT 0,
    actions_json                   TEXT DEFAULT '[]',
    action_values_json             TEXT DEFAULT '[]',
    cost_per_action_type_json      TEXT DEFAULT '[]',
    raw_json                       TEXT DEFAULT '{}',
    synced_at                      TEXT NOT NULL,
    PRIMARY KEY (
        ad_account_id, level, date_start, object_id,
        publisher_platform, platform_position
    )
);
CREATE INDEX IF NOT EXISTS idx_meta_breakdowns_platform
ON meta_insight_breakdowns(ad_account_id, publisher_platform, date_start);
CREATE INDEX IF NOT EXISTS idx_meta_breakdowns_campaign
ON meta_insight_breakdowns(ad_account_id, campaign_id, date_start);

-- Meta Ads 운영 광고 소재 미리보기 메타데이터.
CREATE TABLE IF NOT EXISTS meta_ad_creatives (
    ad_account_id    TEXT NOT NULL,
    ad_id            TEXT NOT NULL,
    creative_id      TEXT DEFAULT '',
    thumbnail_url    TEXT DEFAULT '',
    image_url        TEXT DEFAULT '',
    effective_status TEXT DEFAULT '',
    raw_json         TEXT DEFAULT '{}',
    synced_at        TEXT NOT NULL,
    PRIMARY KEY (ad_account_id, ad_id)
);
CREATE INDEX IF NOT EXISTS idx_meta_ad_creatives_status
ON meta_ad_creatives(ad_account_id, effective_status);

-- 당일 누적값 스냅샷. 15-30분 단위 추이 표시용.
CREATE TABLE IF NOT EXISTS meta_insight_snapshots (
    snapshot_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at       TEXT NOT NULL,
    ad_account_id     TEXT NOT NULL,
    level             TEXT NOT NULL,
    date_start        TEXT NOT NULL,
    object_id         TEXT NOT NULL,
    object_name       TEXT DEFAULT '',
    campaign_id       TEXT DEFAULT '',
    campaign_name     TEXT DEFAULT '',
    spend             REAL NOT NULL DEFAULT 0,
    impressions       INTEGER NOT NULL DEFAULT 0,
    clicks            INTEGER NOT NULL DEFAULT 0,
    conversions       REAL NOT NULL DEFAULT 0,
    conversion_value  REAL NOT NULL DEFAULT 0,
    purchase_roas     REAL NOT NULL DEFAULT 0,
    cpa               REAL NOT NULL DEFAULT 0,
    frequency         REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_meta_snapshots_captured
ON meta_insight_snapshots(captured_at);
CREATE INDEX IF NOT EXISTS idx_meta_snapshots_account_level
ON meta_insight_snapshots(ad_account_id, level, date_start);

-- 계정별 동기화 실행 이력.
CREATE TABLE IF NOT EXISTS meta_sync_runs (
    run_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ad_account_id TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    finished_at   TEXT DEFAULT '',
    status        TEXT NOT NULL, -- running | success | failed
    lookback_days INTEGER NOT NULL DEFAULT 0,
    levels_json   TEXT DEFAULT '[]',
    rows_upserted INTEGER NOT NULL DEFAULT 0,
    api_version   TEXT DEFAULT '',
    error         TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_meta_sync_runs_account
ON meta_sync_runs(ad_account_id, started_at);
CREATE INDEX IF NOT EXISTS idx_meta_sync_runs_status
ON meta_sync_runs(status);

-- Slack 중복 알림 방지용 ledger.
CREATE TABLE IF NOT EXISTS meta_alert_events (
    alert_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint   TEXT NOT NULL UNIQUE,
    alert_type    TEXT NOT NULL,
    severity      TEXT NOT NULL,
    ad_account_id TEXT NOT NULL,
    level         TEXT DEFAULT '',
    object_id     TEXT DEFAULT '',
    object_name   TEXT DEFAULT '',
    message       TEXT NOT NULL,
    metric_value  REAL NOT NULL DEFAULT 0,
    threshold     REAL NOT NULL DEFAULT 0,
    detected_at   TEXT NOT NULL,
    sent_at       TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_meta_alert_events_account
ON meta_alert_events(ad_account_id, detected_at);

-- Notion 제작요청 → OpenAI 이미지 생성 작업 ledger
CREATE TABLE IF NOT EXISTS creative_jobs (
    job_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    notion_page_id  TEXT NOT NULL,
    ad_archive_id   TEXT NOT NULL,
    status          TEXT NOT NULL,  -- running | done | error | skipped
    source_media_url TEXT DEFAULT '',
    output_path     TEXT DEFAULT '',
    prompt          TEXT DEFAULT '',
    model           TEXT DEFAULT '',
    error           TEXT DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE(notion_page_id, ad_archive_id)
);
CREATE INDEX IF NOT EXISTS idx_creative_jobs_ad ON creative_jobs(ad_archive_id);
CREATE INDEX IF NOT EXISTS idx_creative_jobs_status ON creative_jobs(status);
"""

POSTGRES_SCHEMA = (
    SCHEMA.replace("PRAGMA journal_mode=WAL;", "")
    .replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
    .replace("REAL", "DOUBLE PRECISION")
)


class DbRow(Mapping[str, Any]):
    """Small row object compatible with sqlite3.Row's common access patterns."""

    def __init__(self, columns: Sequence[str], values: Sequence[Any]):
        self._columns = tuple(columns)
        self._values = tuple(values)
        self._by_name = dict(zip(self._columns, self._values))

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return self._values[key]
        return self._by_name[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._columns)

    def __len__(self) -> int:
        return len(self._columns)

    def keys(self):  # sqlite3.Row compatibility.
        return self._by_name.keys()

    def get(self, key: str, default: Any = None) -> Any:
        return self._by_name.get(key, default)


class PostgresCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    @property
    def lastrowid(self) -> None:
        return None

    def fetchone(self) -> DbRow | None:
        row = self._cursor.fetchone()
        if row is None:
            return None
        return self._row(row)

    def fetchall(self) -> list[DbRow]:
        return [self._row(row) for row in self._cursor.fetchall()]

    def _row(self, row: Sequence[Any]) -> DbRow:
        columns = [col.name for col in self._cursor.description or []]
        return DbRow(columns, row)


class PostgresConnection:
    """Tiny adapter that lets existing sqlite-style code talk to Postgres."""

    dialect = "postgres"

    def __init__(self, database_url: str):
        if psycopg is None:
            raise RuntimeError(
                "Postgres DATABASE_URL is configured but psycopg is not installed. "
                "Run `pip install -r requirements.txt`."
            )
        self._conn = psycopg.connect(
            database_url,
            connect_timeout=10,
            prepare_threshold=None,
        )

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> PostgresCursor:
        cursor = self._conn.execute(_postgres_sql(sql), params or ())
        return PostgresCursor(cursor)

    def executemany(self, sql: str, seq_of_params: Iterable[Sequence[Any]]) -> PostgresCursor:
        cursor = self._conn.cursor()
        cursor.executemany(_postgres_sql(sql), list(seq_of_params))
        return PostgresCursor(cursor)

    def executescript(self, script: str) -> None:
        with self._conn.cursor() as cursor:
            for statement in _split_sql_statements(script):
                cursor.execute(_postgres_sql(statement))

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


def _postgres_sql(sql: str) -> str:
    return sql.replace("?", "%s")


def _split_sql_statements(script: str) -> list[str]:
    return [stmt.strip() for stmt in script.split(";") if stmt.strip()]


def is_postgres_connection(conn: object) -> bool:
    return isinstance(conn, PostgresConnection)


def is_integrity_error(exc: BaseException) -> bool:
    if isinstance(exc, sqlite3.IntegrityError):
        return True
    return bool(psycopg is not None and isinstance(exc, psycopg.IntegrityError))


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    """커넥션 반환. Row 팩토리로 dict 유사 접근 가능."""
    config.ensure_dirs()
    if db_path is None and config.DATABASE_URL:
        return PostgresConnection(config.DATABASE_URL)  # type: ignore[return-value]
    conn = sqlite3.connect(str(db_path or config.DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(db_path: Path | None = None) -> None:
    """스키마 생성 (멱등) + 경량 마이그레이션."""
    conn = connect(db_path)
    try:
        conn.executescript(POSTGRES_SCHEMA if is_postgres_connection(conn) else SCHEMA)
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """기존 DB에 누락된 컬럼을 추가 (SQLite는 ADD COLUMN IF NOT EXISTS 미지원)."""
    if is_postgres_connection(conn):
        _migrate_postgres(conn)
        return

    cols = {r["name"] for r in conn.execute("PRAGMA table_info(target_pages)").fetchall()}
    if "page_url" not in cols:
        conn.execute("ALTER TABLE target_pages ADD COLUMN page_url TEXT DEFAULT ''")

    # ads 테이블: 노션 광고추적 DB용 메타데이터 컬럼.
    ad_cols = {r["name"] for r in conn.execute("PRAGMA table_info(ads)").fetchall()}
    for col, ddl in (
        ("fb_start_date", "TEXT DEFAULT ''"),
        ("media_url", "TEXT DEFAULT ''"),
        ("media_type", "TEXT DEFAULT 'unknown'"),
        ("variant_count", "INTEGER DEFAULT 0"),
        ("display_format", "TEXT DEFAULT ''"),
        ("targeting", "TEXT DEFAULT ''"),
        ("miss_streak", "INTEGER NOT NULL DEFAULT 0"),
    ):
        if col not in ad_cols:
            conn.execute(f"ALTER TABLE ads ADD COLUMN {col} {ddl}")


def _migrate_postgres(conn) -> None:
    target_cols = _postgres_columns(conn, "target_pages")
    if "page_url" not in target_cols:
        conn.execute("ALTER TABLE target_pages ADD COLUMN page_url TEXT DEFAULT ''")

    ad_cols = _postgres_columns(conn, "ads")
    for col, ddl in (
        ("fb_start_date", "TEXT DEFAULT ''"),
        ("media_url", "TEXT DEFAULT ''"),
        ("media_type", "TEXT DEFAULT 'unknown'"),
        ("variant_count", "INTEGER DEFAULT 0"),
        ("display_format", "TEXT DEFAULT ''"),
        ("targeting", "TEXT DEFAULT ''"),
        ("miss_streak", "INTEGER NOT NULL DEFAULT 0"),
    ):
        if col not in ad_cols:
            conn.execute(f"ALTER TABLE ads ADD COLUMN {col} {ddl}")


def _postgres_columns(conn, table_name: str) -> set[str]:
    rows = conn.execute(
        """SELECT column_name
           FROM information_schema.columns
           WHERE table_schema='public' AND table_name=?""",
        (table_name,),
    ).fetchall()
    return {r["column_name"] for r in rows}

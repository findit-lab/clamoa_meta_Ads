import sqlite3

from adintel import db


def test_postgres_schema_is_compatible():
    assert "PRAGMA" not in db.POSTGRES_SCHEMA
    assert "AUTOINCREMENT" not in db.POSTGRES_SCHEMA
    assert "BIGSERIAL PRIMARY KEY" in db.POSTGRES_SCHEMA


def test_postgres_placeholder_translation():
    sql = "SELECT * FROM meta_insights WHERE level=? AND ad_account_id=?"
    assert db._postgres_sql(sql) == (
        "SELECT * FROM meta_insights WHERE level=%s AND ad_account_id=%s"
    )


def test_postgres_sql_escapes_literal_percent_patterns():
    sql = (
        "UPDATE landing_utm_events SET landing_key='clamoa' "
        "WHERE lower(event_source_url) LIKE '%clamoa%' AND browser_event_id=?"
    )
    assert db._postgres_sql(sql) == (
        "UPDATE landing_utm_events SET landing_key='clamoa' "
        "WHERE lower(event_source_url) LIKE '%%clamoa%%' AND browser_event_id=%s"
    )


def test_postgres_sql_keeps_question_marks_inside_literals():
    sql = "SELECT 'https://clamoa.com/?utm_source=meta' AS url, ? AS source"
    assert db._postgres_sql(sql) == (
        "SELECT 'https://clamoa.com/?utm_source=meta' AS url, %s AS source"
    )


def test_db_row_supports_sqlite_row_access_patterns():
    row = db.DbRow(["count", "name"], [2, "clamoa"])
    assert row[0] == 2
    assert row["name"] == "clamoa"
    assert row.get("missing", "fallback") == "fallback"
    assert set(row.keys()) == {"count", "name"}


def test_init_db_migrates_legacy_landing_events_before_index_creation(tmp_path):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """CREATE TABLE landing_utm_events (
                landing_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                captured_at TEXT NOT NULL,
                event_name TEXT NOT NULL,
                browser_event_id TEXT DEFAULT '',
                event_source_url TEXT DEFAULT ''
            )"""
        )
        conn.execute(
            """INSERT INTO landing_utm_events
               (captured_at, event_name, browser_event_id, event_source_url)
               VALUES ('2026-06-30T00:00:00+09:00', 'PageView', 'legacy-1', 'https://clamoa.com/')"""
        )
        conn.commit()
    finally:
        conn.close()

    db.init_db(db_path)

    conn = db.connect(db_path)
    try:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(landing_utm_events)")}
        indexes = {row["name"] for row in conn.execute("PRAGMA index_list('landing_utm_events')")}
        landing_key = conn.execute(
            "SELECT landing_key FROM landing_utm_events WHERE browser_event_id='legacy-1'"
        ).fetchone()["landing_key"]
    finally:
        conn.close()

    assert "landing_key" in cols
    assert "idx_landing_utm_events_landing" in indexes
    assert landing_key == "clamoa"

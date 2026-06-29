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


def test_db_row_supports_sqlite_row_access_patterns():
    row = db.DbRow(["count", "name"], [2, "clamoa"])
    assert row[0] == 2
    assert row["name"] == "clamoa"
    assert row.get("missing", "fallback") == "fallback"
    assert set(row.keys()) == {"count", "name"}

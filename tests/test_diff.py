"""C3 Diff 엔진 정확성 — ★핵심①. APPEARED/DISAPPEARED/observed_active_days."""
from adintel.diff import process_day
from adintel.models import RawAd


def _ad(ad_id="ad-1", page="p1"):
    return RawAd(ad_archive_id=ad_id, page_id=page, headline="h", media_path="")


def test_appeared_creates_active_row(conn):
    r = process_day(conn, "p1", [_ad()], "2026-01-01")
    assert r.appeared == 1 and r.still_active == 0 and r.disappeared == 0
    row = conn.execute("SELECT * FROM ads WHERE ad_archive_id='ad-1'").fetchone()
    assert row["status"] == "active"
    assert row["first_seen"] == "2026-01-01"
    assert row["observed_active_days"] == 0


def test_still_active_updates_last_seen(conn):
    process_day(conn, "p1", [_ad()], "2026-01-01")
    r = process_day(conn, "p1", [_ad()], "2026-01-03")
    assert r.still_active == 1 and r.appeared == 0
    row = conn.execute("SELECT * FROM ads WHERE ad_archive_id='ad-1'").fetchone()
    assert row["last_seen_active"] == "2026-01-03"
    assert row["observed_active_days"] == 2  # 1/3 − 1/1


def test_disappeared_finalizes_longevity(conn):
    # 1/1 등장 → 1/3 까지 지속 → 1/4 사라짐. grace=1(즉시 종료)로 확정 동작 검증.
    process_day(conn, "p1", [_ad()], "2026-01-01")
    process_day(conn, "p1", [_ad()], "2026-01-03")
    r = process_day(conn, "p1", [], "2026-01-04", grace=1)
    assert r.disappeared == 1
    row = conn.execute("SELECT * FROM ads WHERE ad_archive_id='ad-1'").fetchone()
    assert row["status"] == "ended"
    assert row["observed_active_days"] == 2  # last_seen(1/3) − first_seen(1/1)


def test_events_are_append_only(conn):
    process_day(conn, "p1", [_ad()], "2026-01-01")
    process_day(conn, "p1", [_ad()], "2026-01-02")
    process_day(conn, "p1", [], "2026-01-03", grace=1)
    types = [r["event_type"] for r in conn.execute(
        "SELECT event_type FROM ad_events ORDER BY event_id").fetchall()]
    assert types == ["AD_APPEARED", "AD_STILL_ACTIVE", "AD_DISAPPEARED"]


def test_reappearance_resets_first_seen(conn):
    process_day(conn, "p1", [_ad()], "2026-01-01")
    process_day(conn, "p1", [], "2026-01-02", grace=1)  # ended
    r = process_day(conn, "p1", [_ad()], "2026-01-10")  # 재등장
    assert r.appeared == 1
    row = conn.execute("SELECT * FROM ads WHERE ad_archive_id='ad-1'").fetchone()
    assert row["status"] == "active"
    assert row["first_seen"] == "2026-01-10"
    assert row["observed_active_days"] == 0


def test_two_pages_isolated(conn):
    process_day(conn, "p1", [_ad("a", "p1")], "2026-01-01")
    process_day(conn, "p2", [_ad("b", "p2")], "2026-01-01")
    # p1 에서 빈 집합을 줘도 p2 광고는 영향 없음.
    process_day(conn, "p1", [], "2026-01-02", grace=1)
    p2 = conn.execute("SELECT status FROM ads WHERE ad_archive_id='b'").fetchone()
    assert p2["status"] == "active"


# ── grace-period (액터 비결정성 흡수) ────────────────────────────────
def test_grace_tolerates_single_miss(conn):
    # grace=2: 1회 누락은 active 유지(AD_MISSING), 종료 아님.
    process_day(conn, "p1", [_ad()], "2026-01-01")
    process_day(conn, "p1", [_ad()], "2026-01-03")
    r = process_day(conn, "p1", [], "2026-01-04", grace=2)
    assert r.disappeared == 0 and r.missing == 1
    row = conn.execute("SELECT * FROM ads WHERE ad_archive_id='ad-1'").fetchone()
    assert row["status"] == "active"
    assert row["miss_streak"] == 1
    assert row["last_seen_active"] == "2026-01-03"   # 동결
    assert row["observed_active_days"] == 2          # 동결


def test_grace_reappearance_continues_longevity(conn):
    # 누락 후 다시 등장 → 종료 없이 longevity 이어서 카운트, miss_streak 리셋.
    process_day(conn, "p1", [_ad()], "2026-01-01")
    process_day(conn, "p1", [], "2026-01-02", grace=2)   # 누락(유예)
    r = process_day(conn, "p1", [_ad()], "2026-01-05")   # 재관측
    assert r.still_active == 1 and r.appeared == 0
    row = conn.execute("SELECT * FROM ads WHERE ad_archive_id='ad-1'").fetchone()
    assert row["status"] == "active"
    assert row["miss_streak"] == 0
    assert row["first_seen"] == "2026-01-01"             # 종료 안 됐으므로 유지
    assert row["observed_active_days"] == 4              # 1/5 − 1/1 (누락 구간 포함)


def test_grace_ends_after_consecutive_misses(conn):
    # grace=2: 연속 2회 누락 시 종료. longevity는 마지막 실관측일 기준.
    process_day(conn, "p1", [_ad()], "2026-01-01")
    process_day(conn, "p1", [_ad()], "2026-01-03")       # last_seen=1/3
    process_day(conn, "p1", [], "2026-01-04", grace=2)   # 1회 누락 → 유예
    r = process_day(conn, "p1", [], "2026-01-05", grace=2)  # 2회 누락 → 종료
    assert r.disappeared == 1
    row = conn.execute("SELECT * FROM ads WHERE ad_archive_id='ad-1'").fetchone()
    assert row["status"] == "ended"
    assert row["observed_active_days"] == 2              # 1/3 − 1/1
    types = [r["event_type"] for r in conn.execute(
        "SELECT event_type FROM ad_events ORDER BY event_id").fetchall()]
    assert types == ["AD_APPEARED", "AD_STILL_ACTIVE", "AD_MISSING", "AD_DISAPPEARED"]

"""C7 광고추적 리포터 — 밴딩/tier/위너점수."""
from adintel.reporting import notion_ads as na


def test_band_longevity():
    assert na.band_longevity(217) == "90일+"
    assert na.band_longevity(90) == "90일+"
    assert na.band_longevity(75) == "60–90일"
    assert na.band_longevity(45) == "30–60일"
    assert na.band_longevity(20) == "14–30일"
    assert na.band_longevity(5) == "14일 미만"


def test_advertiser_tier():
    assert na.advertiser_tier(150) == "top"
    assert na.advertiser_tier(50) == "high"
    assert na.advertiser_tier(15) == "mid"
    assert na.advertiser_tier(3) == "low"


def test_winner_score_reproduces_cheongwoldang_example():
    # 청월당: 217일 + 50변형 + mid → 4.5 (이미지와 일치)
    assert na.winner_score(217, 50, "mid") == 4.5


def test_winner_score_components():
    # 14일미만(0.4) + 변형0(0) + low(0.2) = 0.6
    assert na.winner_score(5, 0, "low") == 0.6
    # 90일+(3.0) + 변형100→cap1.0 + top(1.0) = 5.0
    assert na.winner_score(120, 100, "top") == 5.0


def test_op_mode():
    assert na.op_mode("DCO") == "DCO"
    assert na.op_mode("IMAGE") == "단일"
    assert na.op_mode("") == "기타"


def test_creative_status_props_done_with_file_upload():
    props = na._creative_status_props(
        na.GEN_STATUS_DONE,
        prompt="prompt",
        model="gpt-image-2",
        error="",
        generated_at="2026-06-22T00:00:00+00:00",
        file_upload_id="file123",
        filename="out.png",
    )
    assert props["제작상태"]["select"]["name"] == "완료"
    assert props["생성프롬프트"]["rich_text"][0]["text"]["content"] == "prompt"
    assert props["생성모델"]["rich_text"][0]["text"]["content"] == "gpt-image-2"
    assert props["생성결과"]["files"][0]["type"] == "file_upload"
    assert props["생성결과"]["files"][0]["file_upload"]["id"] == "file123"


def test_pending_creative_requests_parses_notion_rows(monkeypatch):
    page = {
        "id": "pg1",
        "properties": {
            "광고ID": {"rich_text": [{"plain_text": "A1"}]},
            "미디어링크": {"url": "https://cdn/a.png"},
            "미디어타입": {"select": {"name": "image"}},
            "제작상태": {"select": {"name": "생성요청"}},
            "제작브리프": {"rich_text": [{"plain_text": "새로운 SaaS 톤"}]},
        },
    }
    monkeypatch.setattr(na, "_query_ads_database", lambda filter_payload=None, limit=None: [page])
    reqs = na.pending_creative_requests()
    assert len(reqs) == 1
    assert reqs[0].page_id == "pg1"
    assert reqs[0].ad_id == "A1"
    assert reqs[0].media_type == "image"
    assert reqs[0].brief == "새로운 SaaS 톤"


def test_is_winner_candidate_or_gate():
    # 기본 임계값: 게재 ≥30일 OR 변형 ≥3개 (OR 로직)
    assert na.is_winner_candidate(30, 0) is True       # 장수만으로 통과
    assert na.is_winner_candidate(0, 3) is True        # 변형만으로 통과
    assert na.is_winner_candidate(45, 5) is True        # 둘 다
    assert na.is_winner_candidate(29, 2) is False       # 둘 다 미달
    assert na.is_winner_candidate(10, None) is False    # 변형수 None 안전


def test_build_rows_winners_only_filters(conn):
    conn.execute("INSERT INTO target_pages (page_id, page_name, category, added_at) "
                 "VALUES ('p1','브랜드','x','2026-01-01')")
    # 위너(217일) 1건 + 비후보(5일·변형1) 1건
    conn.execute(
        """INSERT INTO ads (ad_archive_id, page_id, first_seen, last_seen_active, status,
               observed_active_days, ad_copy, updated_at, fb_start_date, media_url,
               media_type, variant_count, display_format, targeting)
           VALUES ('WIN','p1','2026-06-10','2026-06-10','active',0,'a',
                   '2026-06-10','2025-11-05','','image',50,'','')""")
    conn.execute(
        """INSERT INTO ads (ad_archive_id, page_id, first_seen, last_seen_active, status,
               observed_active_days, ad_copy, updated_at, fb_start_date, media_url,
               media_type, variant_count, display_format, targeting)
           VALUES ('LOSE','p1','2026-06-08','2026-06-10','active',2,'b',
                   '2026-06-10','2026-06-05','','image',1,'','')""")
    conn.commit()
    winners = na.build_rows(conn, ref_date="2026-06-10")               # 기본 winners_only=True
    assert {r["광고ID"] for r in winners} == {"WIN"}
    allrows = na.build_rows(conn, ref_date="2026-06-10", winners_only=False)
    assert {r["광고ID"] for r in allrows} == {"WIN", "LOSE"}


def _seed_two_ads(conn):
    conn.execute("INSERT INTO target_pages (page_id, page_name, category, added_at) "
                 "VALUES ('p1','브랜드','x','2026-01-01')")
    conn.execute(
        """INSERT INTO ads (ad_archive_id, page_id, first_seen, last_seen_active, status,
               observed_active_days, ad_copy, updated_at, fb_start_date, media_url,
               media_type, variant_count, display_format, targeting)
           VALUES ('WIN','p1','2026-06-10','2026-06-10','active',0,'a',
                   '2026-06-10','2025-11-05','','image',50,'','')""")
    conn.execute(
        """INSERT INTO ads (ad_archive_id, page_id, first_seen, last_seen_active, status,
               observed_active_days, ad_copy, updated_at, fb_start_date, media_url,
               media_type, variant_count, display_format, targeting)
           VALUES ('LOSE','p1','2026-06-08','2026-06-10','active',2,'b',
                   '2026-06-10','2026-06-05','','image',1,'','')""")
    conn.commit()


def test_winner_fail_ids(conn):
    _seed_two_ads(conn)
    fail = na.winner_fail_ids(conn, ref_date="2026-06-10")
    assert fail == {"LOSE"}          # WIN(217일)은 통과, LOSE(5일/1변형)만 미통과


def test_reconcile_marks_only_new_status(conn, monkeypatch):
    _seed_two_ads(conn)
    # 노션에 4행: LOSE(신규)·LOSE2(검토중·보존)·WIN(신규,게이트통과→대상아님)·[샘플](로컬無)
    existing = {
        "LOSE":   {"page_id": "pgLOSE", "review": "신규"},
        "WIN":    {"page_id": "pgWIN",  "review": "신규"},
        "SAMPLE": {"page_id": "pgSMP",  "review": "신규"},
    }
    monkeypatch.setattr(na, "_enabled", lambda: True)
    monkeypatch.setattr(na, "_existing_pages_detailed", lambda: existing)
    calls = []
    monkeypatch.setattr(na, "_set_review", lambda pid, v: calls.append(("mark", pid, v)))
    monkeypatch.setattr(na, "_archive_page", lambda pid: calls.append(("archive", pid)))

    # dry-run: 변경 없음
    s = na.reconcile_winners(conn, mode="mark", apply=False, ref_date="2026-06-10")
    assert s["targets"] == ["LOSE"] and calls == []

    # apply: LOSE만 기각 마킹 (WIN=게이트통과 제외, SAMPLE=로컬無 제외)
    s = na.reconcile_winners(conn, mode="mark", apply=True, ref_date="2026-06-10")
    assert calls == [("mark", "pgLOSE", "기각")]
    assert s["done"] == 1


def test_reconcile_preserves_human_review(conn, monkeypatch):
    _seed_two_ads(conn)
    existing = {"LOSE": {"page_id": "pgLOSE", "review": "채택"}}  # 사람이 채택 → 보존
    monkeypatch.setattr(na, "_enabled", lambda: True)
    monkeypatch.setattr(na, "_existing_pages_detailed", lambda: existing)
    calls = []
    monkeypatch.setattr(na, "_set_review", lambda pid, v: calls.append(pid))
    s = na.reconcile_winners(conn, mode="mark", apply=True, ref_date="2026-06-10")
    assert calls == [] and s["skipped_human"] == 1 and s["targets"] == []


def test_reconcile_archive_mode(conn, monkeypatch):
    _seed_two_ads(conn)
    existing = {"LOSE": {"page_id": "pgLOSE", "review": "신규"}}
    monkeypatch.setattr(na, "_enabled", lambda: True)
    monkeypatch.setattr(na, "_existing_pages_detailed", lambda: existing)
    arch = []
    monkeypatch.setattr(na, "_archive_page", lambda pid: arch.append(pid))
    s = na.reconcile_winners(conn, mode="archive", apply=True, ref_date="2026-06-10")
    assert arch == ["pgLOSE"] and s["done"] == 1


def test_build_rows_end_to_end(conn):
    # ads 한 건 직접 삽입 → build_rows 검증
    conn.execute("INSERT INTO target_pages (page_id, page_name, category, added_at) "
                 "VALUES ('p1','청월당','마케팅SaaS','2026-01-01')")
    conn.execute(
        """INSERT INTO ads (ad_archive_id, page_id, first_seen, last_seen_active, status,
               observed_active_days, ad_copy, updated_at, fb_start_date, media_url,
               media_type, variant_count, display_format, targeting)
           VALUES ('A1','p1','2026-06-10','2026-06-10','active',0,'다들 사주 보신 적 있으신가요?',
                   '2026-06-10','2025-11-05','https://cdn/x.mp4','video',50,'','mixed')""")
    conn.commit()
    rows = na.build_rows(conn, ref_date="2026-06-10")
    assert len(rows) == 1
    r = rows[0]
    assert r["광고주"] == "청월당"
    assert r["게재일수"] == 217          # 2026-06-10 − 2025-11-05
    assert r["Longevity밴드"] == "90일+"
    assert r["미디어타입"] == "video"
    assert r["변형수"] == 50
    assert r["광고링크"].endswith("id=A1")
    assert r["카피발췌"].startswith("다들 사주")

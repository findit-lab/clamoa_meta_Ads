"""C1 — 경쟁사 입력 파싱 + Apify URL 라우팅."""
import pytest

from adintel import targets
from adintel.models import TargetPage


@pytest.mark.parametrize("raw, exp_id, exp_url", [
    ("https://www.facebook.com/ZapierApp", "ZapierApp", "https://www.facebook.com/ZapierApp"),
    ("ZapierApp", "ZapierApp", "https://www.facebook.com/ZapierApp"),
    ("@HubSpot", "HubSpot", "https://www.facebook.com/HubSpot"),
    ("1234567890", "1234567890", ""),
    ("https://www.facebook.com/ads/library/?active_status=all&view_all_page_id=999",
     "999", "https://www.facebook.com/ads/library/?active_status=all&view_all_page_id=999"),
])
def test_parse_competitor(raw, exp_id, exp_url):
    pid, url = targets.parse_competitor(raw)
    assert pid == exp_id
    assert url == exp_url


def test_parse_competitor_rejects_garbage():
    with pytest.raises(ValueError):
        targets.parse_competitor("   ")


def test_upsert_and_purge_seed(conn):
    targets.upsert_target(conn, TargetPage("h1", "A", "PR대행사", page_url="u1",
                                           added_at="2026-01-01", note="seed"))
    targets.upsert_target(conn, TargetPage("h2", "B", "마케팅SaaS", page_url="u2",
                                           added_at="2026-01-01", note="manual"))
    assert len(targets.list_active(conn)) == 2
    removed = targets.purge_by_note(conn, "seed")
    assert removed == 1
    remaining = targets.list_active(conn)
    assert [t.page_id for t in remaining] == ["h2"]
    assert remaining[0].page_url == "u2"


def test_apify_url_routing(conn):
    """page_url 있으면 그대로, 없으면 view_all_page_id URL 생성."""
    from adintel.collectors.apify import page_ad_library_url
    # page_url 있는 타겟 → 그 URL 사용
    t1 = TargetPage("ZapierApp", "Zapier", "마케팅SaaS",
                    page_url="https://www.facebook.com/ZapierApp")
    chosen = t1.page_url or page_ad_library_url(t1.page_id, "ALL", "active")
    assert chosen == "https://www.facebook.com/ZapierApp"
    # page_url 없는 숫자 id → 생성된 Ad Library URL
    t2 = TargetPage("999", "X", "PR대행사", page_url="")
    chosen2 = t2.page_url or page_ad_library_url(t2.page_id, "ALL", "active")
    assert "view_all_page_id=999" in chosen2

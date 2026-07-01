from adintel.performance import store
from adintel.performance.meta_api import friendly_error_message, is_access_token_expired
from adintel.performance.models import AdCreative
from adintel.performance.sync import sync_all_accounts


class FakeClient:
    api_version = "v25.0"

    def __init__(self, fail_accounts=None):
        self.fail_accounts = set(fail_accounts or [])

    def fetch_insights(
        self,
        ad_account_id,
        level,
        since,
        until,
        fields,
        breakdowns=None,
        time_increment=1,
    ):
        if ad_account_id in self.fail_accounts:
            raise RuntimeError("permission error")
        object_fields = {
            "account": {"account_id": ad_account_id, "account_name": f"Account {ad_account_id}"},
            "campaign": {"campaign_id": "camp-1", "campaign_name": "Campaign 1"},
            "adset": {
                "campaign_id": "camp-1",
                "campaign_name": "Campaign 1",
                "adset_id": "set-1",
                "adset_name": "Set 1",
            },
            "ad": {
                "campaign_id": "camp-1",
                "campaign_name": "Campaign 1",
                "adset_id": "set-1",
                "adset_name": "Set 1",
                "ad_id": "ad-1",
                "ad_name": "Ad 1",
            },
        }[level]
        base = {
            **object_fields,
            "date_start": since,
            "date_stop": since,
            "spend": "100000",
            "impressions": "10000",
            "reach": "4000",
            "frequency": "2.5",
            "clicks": "200",
            "inline_link_clicks": "180",
            "actions": [{"action_type": "purchase", "value": "4"}],
            "action_values": [{"action_type": "purchase", "value": "240000"}],
        }
        if breakdowns:
            return [
                {
                    **base,
                    "publisher_platform": "facebook",
                    "platform_position": "feed",
                    "spend": "80000",
                    "impressions": "8000",
                    "clicks": "160",
                },
                {
                    **base,
                    "publisher_platform": "instagram",
                    "platform_position": "feed",
                    "spend": "20000",
                    "impressions": "2000",
                    "clicks": "40",
                },
            ]
        return [base]

    def fetch_ad_creatives(self, ad_account_id, ad_ids, synced_at="", chunk_size=50):
        return [
            AdCreative(
                ad_account_id=ad_account_id,
                ad_id=ad_id,
                creative_id=f"creative-{ad_id}",
                thumbnail_url=f"https://cdn.example/{ad_id}.jpg",
                image_url=f"https://cdn.example/{ad_id}-full.jpg",
                effective_status="ACTIVE",
                url_tags="utm_source=meta&utm_medium=paid_social&utm_campaign=test",
                raw_json="{}",
                synced_at=synced_at,
            )
            for ad_id in ad_ids
        ]


def test_meta_insights_are_scoped_by_account_and_upserted(conn):
    store.upsert_ad_account(conn, "111", "A")
    store.upsert_ad_account(conn, "222", "B")
    conn.commit()

    results = sync_all_accounts(
        conn,
        FakeClient(),
        lookback_days=1,
        levels=("campaign",),
    )
    assert [r.status for r in results] == ["success", "success"]
    assert conn.execute("SELECT COUNT(*) FROM meta_insights").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM meta_insight_breakdowns").fetchone()[0] == 4

    # Same account/campaign/date is replaced, not duplicated.
    results = sync_all_accounts(
        conn,
        FakeClient(),
        lookback_days=1,
        levels=("campaign",),
    )
    assert [r.status for r in results] == ["success", "success"]
    assert conn.execute("SELECT COUNT(*) FROM meta_insights").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM meta_insight_breakdowns").fetchone()[0] == 4
    accounts = {
        r["ad_account_id"]
        for r in conn.execute("SELECT ad_account_id FROM meta_insights").fetchall()
    }
    assert accounts == {"111", "222"}


def test_sync_all_isolates_failed_accounts(conn):
    store.upsert_ad_account(conn, "111", "A")
    store.upsert_ad_account(conn, "222", "B")
    conn.commit()

    results = sync_all_accounts(
        conn,
        FakeClient(fail_accounts={"222"}),
        lookback_days=1,
        levels=("campaign",),
    )
    assert {r.ad_account_id: r.status for r in results} == {
        "111": "success",
        "222": "failed",
    }
    assert conn.execute("SELECT COUNT(*) FROM meta_insights").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM meta_insight_breakdowns").fetchone()[0] == 2
    failed = conn.execute(
        "SELECT status, error FROM meta_sync_runs WHERE ad_account_id='222'"
    ).fetchone()
    assert failed["status"] == "failed"
    assert "permission error" in failed["error"]


def test_meta_token_expiry_errors_are_user_friendly():
    raw = (
        'HTTP 400: {"error":{"message":"Error validating access token: '
        'Session has expired on Sunday, 28-Jun-26 20:00:00 PDT.",'
        '"type":"OAuthException","code":190,"error_subcode":463}}'
    )
    assert is_access_token_expired(raw)
    assert friendly_error_message(raw).startswith("Meta 액세스 토큰이 만료")


def test_upsert_ad_creatives_replaces_preview(conn):
    first = AdCreative(
        ad_account_id="111",
        ad_id="ad-1",
        creative_id="creative-1",
        thumbnail_url="https://cdn.example/old.jpg",
        image_url="https://cdn.example/old-full.jpg",
        effective_status="ACTIVE",
        url_tags="utm_source=meta&utm_campaign=old",
        raw_json="{}",
        synced_at="2026-06-25T00:00:00+00:00",
    )
    second = AdCreative(
        ad_account_id="111",
        ad_id="ad-1",
        creative_id="creative-2",
        thumbnail_url="",
        image_url="https://cdn.example/new-full.jpg",
        effective_status="PAUSED",
        url_tags="utm_source=meta&utm_campaign=new",
        raw_json="{}",
        synced_at="2026-06-26T00:00:00+00:00",
    )
    assert store.upsert_ad_creatives(conn, [first]) == 1
    assert store.upsert_ad_creatives(conn, [second]) == 1

    row = conn.execute("SELECT * FROM meta_ad_creatives WHERE ad_id='ad-1'").fetchone()
    assert row["creative_id"] == "creative-2"
    assert row["thumbnail_url"] == ""
    assert row["image_url"] == "https://cdn.example/new-full.jpg"
    assert row["effective_status"] == "PAUSED"
    assert row["url_tags"] == "utm_source=meta&utm_campaign=new"


def test_ad_level_sync_stores_creative_preview(conn):
    store.upsert_ad_account(conn, "111", "A")
    conn.commit()

    results = sync_all_accounts(
        conn,
        FakeClient(),
        lookback_days=1,
        levels=("ad",),
    )
    assert results[0].status == "success"
    row = conn.execute("SELECT * FROM meta_ad_creatives WHERE ad_id='ad-1'").fetchone()
    assert row["creative_id"] == "creative-ad-1"
    assert row["thumbnail_url"] == "https://cdn.example/ad-1.jpg"
    assert row["url_tags"] == "utm_source=meta&utm_medium=paid_social&utm_campaign=test"

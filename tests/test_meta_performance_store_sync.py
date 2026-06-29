from adintel.performance import store
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

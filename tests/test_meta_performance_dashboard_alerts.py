import datetime as dt

from adintel.performance import alerts, dashboard_data, store
from adintel.performance.normalizer import normalize_breakdown_insight, normalize_insight


def _insert_campaign(
    conn,
    account_id="111",
    campaign_id="camp-1",
    date_start="2026-06-25",
    spend="100000",
    purchases="4",
    value="240000",
    frequency="2.0",
):
    row = normalize_insight(
        {
            "date_start": date_start,
            "date_stop": date_start,
            "campaign_id": campaign_id,
            "campaign_name": f"Campaign {campaign_id}",
            "spend": spend,
            "impressions": "10000",
            "reach": "5000",
            "frequency": frequency,
            "clicks": "200",
            "inline_link_clicks": "150",
            "actions": [{"action_type": "purchase", "value": purchases}],
            "action_values": [{"action_type": "purchase", "value": value}],
        },
        account_id,
        level="campaign",
        synced_at="2026-06-25T00:00:00+00:00",
    )
    account_row = normalize_insight(
        {
            "date_start": date_start,
            "date_stop": date_start,
            "account_id": account_id,
            "account_name": f"Account {account_id}",
            "spend": spend,
            "impressions": "10000",
            "reach": "5000",
            "frequency": frequency,
            "clicks": "200",
            "inline_link_clicks": "150",
            "actions": [{"action_type": "purchase", "value": purchases}],
            "action_values": [{"action_type": "purchase", "value": value}],
        },
        account_id,
        level="account",
        synced_at="2026-06-25T00:00:00+00:00",
    )
    ad_row = normalize_insight(
        {
            "date_start": date_start,
            "date_stop": date_start,
            "campaign_id": campaign_id,
            "campaign_name": f"Campaign {campaign_id}",
            "ad_id": "ad-1",
            "ad_name": "Ad 1",
            "spend": spend,
            "impressions": "10000",
            "reach": "5000",
            "frequency": frequency,
            "clicks": "200",
            "inline_link_clicks": "150",
            "actions": [{"action_type": "purchase", "value": purchases}],
            "action_values": [{"action_type": "purchase", "value": value}],
        },
        account_id,
        level="ad",
        synced_at="2026-06-25T00:00:00+00:00",
    )
    store.upsert_insight_rows(conn, [row, account_row, ad_row], captured_at="2026-06-25T01:00:00+00:00")
    breakdowns = [
        normalize_breakdown_insight(
            {
                "date_start": date_start,
                "date_stop": date_start,
                "campaign_id": campaign_id,
                "campaign_name": f"Campaign {campaign_id}",
                "ad_id": "ad-1",
                "ad_name": "Ad 1",
                "publisher_platform": "facebook",
                "platform_position": "feed",
                "spend": str(float(spend) * 0.8),
                "impressions": "8000",
                "reach": "4000",
                "frequency": frequency,
                "clicks": "160",
                "actions": [{"action_type": "purchase", "value": purchases}],
                "action_values": [{"action_type": "purchase", "value": value}],
            },
            account_id,
            level="ad",
            synced_at="2026-06-25T00:00:00+00:00",
        ),
        normalize_breakdown_insight(
            {
                "date_start": date_start,
                "date_stop": date_start,
                "campaign_id": campaign_id,
                "campaign_name": f"Campaign {campaign_id}",
                "ad_id": "ad-1",
                "ad_name": "Ad 1",
                "publisher_platform": "instagram",
                "platform_position": "feed",
                "spend": str(float(spend) * 0.2),
                "impressions": "2000",
                "reach": "1000",
                "frequency": frequency,
                "clicks": "40",
                "actions": [{"action_type": "purchase", "value": "0"}],
                "action_values": [{"action_type": "purchase", "value": "0"}],
            },
            account_id,
            level="ad",
            synced_at="2026-06-25T00:00:00+00:00",
        ),
    ]
    store.upsert_breakdown_rows(conn, breakdowns)
    conn.commit()


def test_dashboard_summary_and_rankings(conn):
    store.upsert_ad_account(conn, "111", "Account 111")
    _insert_campaign(conn)

    summary = dashboard_data.get_summary(
        conn,
        start="2026-06-25",
        end="2026-06-25",
        target_action="purchase",
    )
    assert summary["spend"] == 100000
    assert summary["conversions"] == 4
    assert summary["cpa"] == 25000
    assert summary["purchase_roas"] == 2.4

    click_summary = dashboard_data.get_summary(
        conn,
        start="2026-06-25",
        end="2026-06-25",
        target_action="landing_click",
    )
    assert click_summary["conversions"] == 150
    assert round(click_summary["cpa"], 2) == 666.67

    insights = dashboard_data.get_insights(
        conn,
        start="2026-06-25",
        end="2026-06-25",
        target_action="purchase",
    )
    assert insights["campaigns"][0]["id"] == "camp-1"
    assert insights["campaigns"][0]["spend"] == 100000
    assert insights["trend"][0]["spend"] == 100000
    assert {r["name"] for r in insights["platforms"]} == {"Facebook", "Instagram"}

    ad_scoped = dashboard_data.get_insights(
        conn,
        start="2026-06-25",
        end="2026-06-25",
        ad_id="ad-1",
        target_action="purchase",
    )
    assert len(ad_scoped["platforms"]) == 2
    assert ad_scoped["trend"][0]["spend"] == 100000

    weekly = dashboard_data.get_trend(
        conn,
        start="2026-06-25",
        end="2026-06-25",
        target_action="purchase",
        grain="weekly",
    )
    monthly = dashboard_data.get_trend(
        conn,
        start="2026-06-25",
        end="2026-06-25",
        target_action="purchase",
        grain="monthly",
    )
    assert weekly[0]["bucket"].startswith("2026-W")
    assert monthly[0]["bucket"] == "2026-06"


def test_alerts_trigger_and_dedupe(conn):
    store.upsert_ad_account(conn, "111", "Account 111", min_alert_spend=50000)
    _insert_campaign(
        conn,
        spend="70000",
        purchases="0",
        value="0",
        frequency="4.5",
    )

    current = alerts.compute_current_alerts(conn, today=dt.date(2026, 6, 25))
    types = {a.alert_type for a in current}
    assert "no_conversion_spend" in types
    assert "high_frequency" in types

    first = alerts.notify_slack(conn, current)
    second = alerts.notify_slack(conn, current)
    assert first == len(current)
    assert second == 0

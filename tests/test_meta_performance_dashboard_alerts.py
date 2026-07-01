import datetime as dt

from adintel.performance import alerts, dashboard_data, store
from adintel.performance.dashboard import _sync_response
from adintel.performance.models import AdCreative
from adintel.performance.models import SyncResult
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


def test_dashboard_ads_include_creative_preview(conn):
    store.upsert_ad_account(conn, "111", "Account 111")
    _insert_campaign(conn)
    store.upsert_ad_creatives(
        conn,
        [
            AdCreative(
                ad_account_id="111",
                ad_id="ad-1",
                creative_id="creative-1",
                thumbnail_url="",
                image_url="https://cdn.example/ad-1-full.jpg",
                effective_status="ACTIVE",
                raw_json="{}",
                synced_at="2026-06-25T00:00:00+00:00",
            )
        ],
    )

    insights = dashboard_data.get_insights(
        conn,
        start="2026-06-25",
        end="2026-06-25",
        target_action="purchase",
    )
    assert insights["ads"][0]["creative_id"] == "creative-1"
    assert insights["ads"][0]["thumbnail_url"] == "https://cdn.example/ad-1-full.jpg"
    assert insights["ads"][0]["effective_status"] == "ACTIVE"


def test_dashboard_utm_filter_uses_ad_level_rows(conn):
    store.upsert_ad_account(conn, "111", "Account 111")
    _insert_campaign(conn)
    utm_row = normalize_insight(
        {
            "date_start": "2026-06-25",
            "date_stop": "2026-06-25",
            "campaign_id": "camp-1",
            "campaign_name": "Campaign camp-1",
            "adset_id": "set-utm",
            "adset_name": "Set UTM",
            "ad_id": "ad-utm",
            "ad_name": "Ad UTM",
            "spend": "2500",
            "impressions": "1000",
            "reach": "800",
            "frequency": "1.25",
            "clicks": "20",
            "inline_link_clicks": "10",
            "actions": [],
            "action_values": [],
        },
        "111",
        level="ad",
        synced_at="2026-06-25T00:00:00+00:00",
    )
    store.upsert_insight_rows(conn, [utm_row], take_snapshot=False)
    store.upsert_ad_creatives(
        conn,
        [
            AdCreative(
                ad_account_id="111",
                ad_id="ad-utm",
                creative_id="creative-utm",
                effective_status="ACTIVE",
                url_tags=(
                    "utm_source=meta&utm_medium=paid_social"
                    "&utm_campaign=clamoa_brandfit&utm_content=fb_feed"
                ),
                raw_json="{}",
                synced_at="2026-06-25T00:00:00+00:00",
            )
        ],
    )

    summary = dashboard_data.get_summary(
        conn,
        start="2026-06-25",
        end="2026-06-25",
        target_action="landing_click",
        utm_filter="utm",
    )
    assert summary["level"] == "ad"
    assert summary["spend"] == 2500
    assert summary["conversions"] == 10
    assert summary["utm_ad_count"] == 1

    insights = dashboard_data.get_insights(
        conn,
        start="2026-06-25",
        end="2026-06-25",
        target_action="landing_click",
        utm_filter="utm",
    )
    assert [row["id"] for row in insights["ads"]] == ["ad-utm"]
    assert insights["campaigns"][0]["spend"] == 2500
    assert insights["utms"][0]["utm_campaign"] == "clamoa_brandfit"
    assert insights["utms"][0]["ad_count"] == 1


def test_landing_utm_events_group_traffic_sources(conn):
    store.record_landing_utm_event(
        conn,
        event_name="PageView",
        browser_event_id="pv-naver",
        event_source_url=(
            "https://clamoa.com/?utm_source=naver"
            "&utm_medium=paid_search&utm_campaign=brandfit"
        ),
        session_id="s-naver",
        captured_at="2026-06-25T00:00:00+00:00",
    )
    store.record_landing_utm_event(
        conn,
        event_name="Lead",
        browser_event_id="lead-naver",
        event_source_url="https://clamoa.com/#consult",
        session_id="s-naver",
        utm={
            "utm_source": "naver",
            "utm_medium": "paid_search",
            "utm_campaign": "brandfit",
        },
        captured_at="2026-06-25T00:02:00+00:00",
    )
    store.record_landing_utm_event(
        conn,
        event_name="PageView",
        browser_event_id="pv-google",
        event_source_url="https://clamoa.com/?gclid=test-click",
        session_id="s-google",
        captured_at="2026-06-25T00:03:00+00:00",
    )
    store.record_landing_utm_event(
        conn,
        event_name="PageView",
        browser_event_id="pv-meta",
        event_source_url="https://clamoa.com/?fbclid=test-click",
        session_id="s-meta",
        captured_at="2026-06-25T00:04:00+00:00",
    )
    store.record_landing_utm_event(
        conn,
        event_name="PageView",
        browser_event_id="pv-asinayo",
        event_source_url="https://asinayo.example/?utm_source=naver",
        session_id="s-asinayo",
        captured_at="2026-06-25T00:05:00+00:00",
    )

    rows = {
        row["traffic_source"]: row
        for row in dashboard_data.get_traffic_sources(
            conn,
            start="2026-06-25",
            end="2026-06-25",
        )
    }
    assert rows["naver"]["clicks"] == 1
    assert rows["naver"]["conversions"] == 1
    assert rows["naver"]["conversion_rate"] == 100
    assert rows["google"]["clicks"] == 1
    assert rows["meta"]["clicks"] == 1

    asinayo_rows = {
        row["traffic_source"]: row
        for row in dashboard_data.get_traffic_sources(
            conn,
            start="2026-06-25",
            end="2026-06-25",
            landing_key="asinayo",
        )
    }
    assert asinayo_rows["naver"]["clicks"] == 1


def test_sync_response_marks_expired_token():
    response = _sync_response(
        [
            SyncResult(
                ad_account_id="111",
                status="failed",
                rows_upserted=0,
                started_at="",
                finished_at="2026-06-29T00:00:00+00:00",
                error=(
                    'HTTP 400: {"error":{"message":"Error validating access token: '
                    'Session has expired.","code":190,"error_subcode":463}}'
                ),
            )
        ],
        alerts_detected=0,
        alerts_notified=0,
    )
    assert response["ok"] is False
    assert response["needs_token_refresh"] is True
    assert response["message"].startswith("Meta 액세스 토큰이 만료")
    assert response["results"][0]["friendly_error"].startswith("Meta 액세스 토큰이 만료")


def test_sync_failure_alert_uses_friendly_token_message(conn):
    store.upsert_ad_account(conn, "111", "Account 111")
    conn.execute(
        """INSERT INTO meta_sync_runs
             (ad_account_id, started_at, finished_at, status, lookback_days,
              levels_json, rows_upserted, api_version, error)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "111",
            "2026-06-25T00:00:00+00:00",
            "2026-06-25T00:01:00+00:00",
            "failed",
            7,
            "[]",
            0,
            "v25.0",
            (
                'HTTP 400: {"error":{"message":"Error validating access token: '
                'Session has expired.","code":190,"error_subcode":463}}'
            ),
        ),
    )
    current = alerts.compute_current_alerts(conn, today=dt.date(2026, 6, 25))
    sync_alert = next(a for a in current if a.alert_type == "sync_failure")
    assert "Meta 액세스 토큰이 만료" in sync_alert.message
    assert "HTTP 400" not in sync_alert.message


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

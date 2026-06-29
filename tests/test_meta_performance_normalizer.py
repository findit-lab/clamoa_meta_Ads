from adintel.performance.normalizer import (
    metrics_from_action_json,
    normalize_account_id,
    normalize_insight,
)


def test_normalize_account_id_strips_act_prefix():
    assert normalize_account_id("act_123") == "123"
    assert normalize_account_id("123") == "123"


def test_normalize_insight_extracts_purchase_metrics():
    raw = {
        "date_start": "2026-06-25",
        "date_stop": "2026-06-25",
        "campaign_id": "c1",
        "campaign_name": "Campaign",
        "spend": "120000",
        "impressions": "10000",
        "reach": "5000",
        "frequency": "2",
        "clicks": "300",
        "inline_link_clicks": "220",
        "cpc": "400",
        "cpm": "12000",
        "ctr": "3",
        "actions": [
            {"action_type": "link_click", "value": "220"},
            {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "6"},
        ],
        "action_values": [
            {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "360000"}
        ],
        "purchase_roas": [{"action_type": "omni_purchase", "value": "3"}],
        "cost_per_action_type": [
            {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "20000"}
        ],
    }
    row = normalize_insight(raw, "act_999", level="campaign", synced_at="now")
    assert row.ad_account_id == "999"
    assert row.object_id == "c1"
    assert row.conversions == 6
    assert row.conversion_value == 360000
    assert row.purchase_roas == 3
    assert row.cpa == 20000


def test_metrics_from_action_json_supports_non_purchase_target():
    conversions, value, roas, cpa = metrics_from_action_json(
        50000,
        '[{"action_type":"lead","value":"5"}]',
        '[{"action_type":"lead","value":"250000"}]',
        '[{"action_type":"lead","value":"10000"}]',
        target_action="lead",
    )
    assert conversions == 5
    assert value == 250000
    assert roas == 5
    assert cpa == 10000


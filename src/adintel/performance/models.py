"""Small value objects for Meta Ads performance monitoring."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AdAccount:
    ad_account_id: str
    account_name: str
    currency: str = "KRW"
    timezone_name: str = "Asia/Seoul"
    active: bool = True
    target_action: str = "purchase"
    min_alert_spend: float = 50000.0


@dataclass(frozen=True)
class InsightRow:
    ad_account_id: str
    level: str
    date_start: str
    date_stop: str
    object_id: str
    object_name: str
    campaign_id: str
    campaign_name: str
    adset_id: str
    adset_name: str
    ad_id: str
    ad_name: str
    spend: float
    impressions: int
    reach: int
    frequency: float
    clicks: int
    inline_link_clicks: int
    cpc: float
    cpm: float
    ctr: float
    conversions: float
    conversion_value: float
    purchase_roas: float
    cpa: float
    actions_json: str
    action_values_json: str
    cost_per_action_type_json: str
    raw_json: str
    synced_at: str


@dataclass(frozen=True)
class InsightBreakdownRow(InsightRow):
    publisher_platform: str = ""
    platform_position: str = ""


@dataclass(frozen=True)
class AdCreative:
    ad_account_id: str
    ad_id: str
    creative_id: str = ""
    thumbnail_url: str = ""
    image_url: str = ""
    effective_status: str = ""
    url_tags: str = ""
    raw_json: str = "{}"
    synced_at: str = ""


@dataclass(frozen=True)
class SyncResult:
    ad_account_id: str
    status: str
    rows_upserted: int
    started_at: str
    finished_at: str
    error: str = ""


@dataclass(frozen=True)
class Alert:
    fingerprint: str
    alert_type: str
    severity: str
    ad_account_id: str
    level: str
    object_id: str
    object_name: str
    message: str
    metric_value: float
    threshold: float
    detected_at: str

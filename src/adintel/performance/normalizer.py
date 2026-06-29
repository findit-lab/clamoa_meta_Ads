"""Normalize Meta Marketing API Insights rows into dashboard facts."""
from __future__ import annotations

import json
from typing import Any

from .models import InsightBreakdownRow, InsightRow


ACTION_SYNONYMS = {
    "purchase": {
        "purchase",
        "omni_purchase",
        "offsite_conversion.fb_pixel_purchase",
        "onsite_conversion.purchase",
        "web_in_store_purchase",
    },
    "lead": {
        "lead",
        "omni_lead",
        "offsite_conversion.fb_pixel_lead",
        "onsite_conversion.lead",
    },
    "complete_registration": {
        "complete_registration",
        "omni_complete_registration",
        "offsite_conversion.fb_pixel_complete_registration",
    },
    "contact": {
        "contact",
        "omni_contact",
        "onsite_conversion.messaging_conversation_started_7d",
    },
}


def normalize_account_id(ad_account_id: str) -> str:
    value = str(ad_account_id or "").strip()
    return value[4:] if value.startswith("act_") else value


def _as_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    return int(_as_float(value, float(default)))


def _json_list(value: Any) -> list[dict[str, Any]]:
    return value if isinstance(value, list) else []


def _dump(value: Any) -> str:
    return json.dumps(value if value is not None else [], ensure_ascii=False, sort_keys=True)


def _action_matches(action_type: str, target_action: str) -> bool:
    action = (action_type or "").lower()
    target = (target_action or "purchase").lower()
    if not action:
        return False
    if action == target:
        return True
    if action in ACTION_SYNONYMS.get(target, set()):
        return True
    normalized = action.replace(".", "_").replace(":", "_")
    return normalized.endswith("_" + target)


def metric_for_action(items: Any, target_action: str = "purchase") -> float:
    rows = _json_list(items)
    for item in rows:
        if _action_matches(str(item.get("action_type", "")), target_action):
            return _as_float(item.get("value"))
    return 0.0


def roas_for_action(items: Any, target_action: str = "purchase") -> float:
    rows = _json_list(items)
    for item in rows:
        if _action_matches(str(item.get("action_type", "")), target_action):
            return _as_float(item.get("value"))
    if rows:
        return _as_float(rows[0].get("value"))
    return 0.0


def metrics_from_action_json(
    spend: float,
    actions_json: str,
    action_values_json: str,
    cost_per_action_type_json: str,
    target_action: str = "purchase",
) -> tuple[float, float, float, float]:
    try:
        actions = json.loads(actions_json or "[]")
    except json.JSONDecodeError:
        actions = []
    try:
        values = json.loads(action_values_json or "[]")
    except json.JSONDecodeError:
        values = []
    try:
        costs = json.loads(cost_per_action_type_json or "[]")
    except json.JSONDecodeError:
        costs = []

    conversions = metric_for_action(actions, target_action)
    conversion_value = metric_for_action(values, target_action)
    cpa = metric_for_action(costs, target_action)
    if cpa <= 0 and conversions > 0:
        cpa = spend / conversions
    roas = conversion_value / spend if spend > 0 and conversion_value > 0 else 0.0
    return conversions, conversion_value, roas, cpa


def _object_identity(raw: dict[str, Any], ad_account_id: str, level: str) -> tuple[str, str]:
    if level == "account":
        return (
            normalize_account_id(str(raw.get("account_id") or ad_account_id)),
            str(raw.get("account_name") or raw.get("account_id") or ad_account_id),
        )
    if level == "campaign":
        return str(raw.get("campaign_id") or ""), str(raw.get("campaign_name") or "")
    if level == "adset":
        return str(raw.get("adset_id") or ""), str(raw.get("adset_name") or "")
    if level == "ad":
        return str(raw.get("ad_id") or ""), str(raw.get("ad_name") or "")
    raise ValueError(f"unsupported insight level: {level}")


def normalize_insight(
    raw: dict[str, Any],
    ad_account_id: str,
    level: str,
    synced_at: str,
    target_action: str = "purchase",
) -> InsightRow:
    account_id = normalize_account_id(ad_account_id)
    object_id, object_name = _object_identity(raw, account_id, level)
    if not object_id:
        object_id = account_id

    spend = _as_float(raw.get("spend"))
    actions = _json_list(raw.get("actions"))
    action_values = _json_list(raw.get("action_values"))
    cost_per_action_type = _json_list(raw.get("cost_per_action_type"))
    conversions = metric_for_action(actions, target_action)
    conversion_value = metric_for_action(action_values, target_action)
    purchase_roas = roas_for_action(raw.get("purchase_roas"), target_action)
    if purchase_roas <= 0 and spend > 0 and conversion_value > 0:
        purchase_roas = conversion_value / spend
    cpa = metric_for_action(cost_per_action_type, target_action)
    if cpa <= 0 and conversions > 0:
        cpa = spend / conversions

    return InsightRow(
        ad_account_id=account_id,
        level=level,
        date_start=str(raw.get("date_start") or ""),
        date_stop=str(raw.get("date_stop") or raw.get("date_start") or ""),
        object_id=object_id,
        object_name=object_name,
        campaign_id=str(raw.get("campaign_id") or ""),
        campaign_name=str(raw.get("campaign_name") or ""),
        adset_id=str(raw.get("adset_id") or ""),
        adset_name=str(raw.get("adset_name") or ""),
        ad_id=str(raw.get("ad_id") or ""),
        ad_name=str(raw.get("ad_name") or ""),
        spend=spend,
        impressions=_as_int(raw.get("impressions")),
        reach=_as_int(raw.get("reach")),
        frequency=_as_float(raw.get("frequency")),
        clicks=_as_int(raw.get("clicks")),
        inline_link_clicks=_as_int(raw.get("inline_link_clicks")),
        cpc=_as_float(raw.get("cpc")),
        cpm=_as_float(raw.get("cpm")),
        ctr=_as_float(raw.get("ctr")),
        conversions=conversions,
        conversion_value=conversion_value,
        purchase_roas=purchase_roas,
        cpa=cpa,
        actions_json=_dump(actions),
        action_values_json=_dump(action_values),
        cost_per_action_type_json=_dump(cost_per_action_type),
        raw_json=json.dumps(raw, ensure_ascii=False, sort_keys=True),
        synced_at=synced_at,
    )


def normalize_breakdown_insight(
    raw: dict[str, Any],
    ad_account_id: str,
    level: str,
    synced_at: str,
    target_action: str = "purchase",
) -> InsightBreakdownRow:
    base = normalize_insight(
        raw,
        ad_account_id=ad_account_id,
        level=level,
        synced_at=synced_at,
        target_action=target_action,
    )
    return InsightBreakdownRow(
        **base.__dict__,
        publisher_platform=str(raw.get("publisher_platform") or ""),
        platform_position=str(raw.get("platform_position") or ""),
    )

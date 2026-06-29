"""Query helpers for the Meta Ads monitoring dashboard."""
from __future__ import annotations

import datetime as dt
import sqlite3
from typing import Any

from . import alerts
from .normalizer import metrics_from_action_json, normalize_account_id


def default_range(days: int = 7, today: dt.date | None = None) -> tuple[str, str]:
    end = today or dt.date.today()
    start = end - dt.timedelta(days=max(1, days) - 1)
    return start.isoformat(), end.isoformat()


def get_accounts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT a.*,
                  (SELECT status FROM meta_sync_runs r
                    WHERE r.ad_account_id=a.ad_account_id
                    ORDER BY r.started_at DESC LIMIT 1) AS sync_status,
                  (SELECT COALESCE(NULLIF(finished_at, ''), started_at)
                    FROM meta_sync_runs r
                    WHERE r.ad_account_id=a.ad_account_id
                    ORDER BY r.started_at DESC LIMIT 1) AS last_sync_at
           FROM meta_ad_accounts a
           ORDER BY a.account_name"""
    ).fetchall()
    return [
        {
            "ad_account_id": r["ad_account_id"],
            "account_name": r["account_name"],
            "currency": r["currency"],
            "timezone_name": r["timezone_name"],
            "active": bool(r["active"]),
            "target_action": r["target_action"],
            "min_alert_spend": r["min_alert_spend"],
            "sync_status": r["sync_status"] or "never",
            "last_sync_at": r["last_sync_at"] or "",
        }
        for r in rows
    ]


def get_campaign_options(conn: sqlite3.Connection, account_id: str | None = None) -> list[dict[str, str]]:
    sql = (
        "SELECT campaign_id, MAX(campaign_name) AS campaign_name "
        "FROM meta_insights WHERE campaign_id<>''"
    )
    params: list[Any] = []
    if account_id:
        sql += " AND ad_account_id=?"
        params.append(normalize_account_id(account_id))
    sql += " GROUP BY campaign_id ORDER BY campaign_name"
    rows = conn.execute(sql, params).fetchall()
    return [
        {"campaign_id": r["campaign_id"], "campaign_name": r["campaign_name"] or r["campaign_id"]}
        for r in rows
    ]


def get_ad_options(
    conn: sqlite3.Connection,
    account_id: str | None = None,
    campaign_id: str | None = None,
) -> list[dict[str, str]]:
    sql = (
        "SELECT ad_id, MAX(ad_name) AS ad_name, MAX(campaign_id) AS campaign_id, "
        "MAX(ad_account_id) AS ad_account_id "
        "FROM meta_insights WHERE ad_id<>''"
    )
    params: list[Any] = []
    if account_id:
        sql += " AND ad_account_id=?"
        params.append(normalize_account_id(account_id))
    if campaign_id:
        sql += " AND campaign_id=?"
        params.append(campaign_id)
    sql += " GROUP BY ad_id ORDER BY ad_name"
    rows = conn.execute(sql, params).fetchall()
    return [
        {
            "ad_id": r["ad_id"],
            "ad_name": r["ad_name"] or r["ad_id"],
            "campaign_id": r["campaign_id"] or "",
            "ad_account_id": r["ad_account_id"] or "",
        }
        for r in rows
    ]


def get_summary(
    conn: sqlite3.Connection,
    start: str,
    end: str,
    account_id: str | None = None,
    campaign_id: str | None = None,
    ad_id: str | None = None,
    target_action: str = "landing_click",
) -> dict[str, Any]:
    level = "ad" if ad_id else "campaign" if campaign_id else "account"
    rows = _fetch_rows(
        conn,
        level,
        start,
        end,
        account_id=account_id,
        campaign_id=campaign_id,
        ad_id=ad_id,
    )
    summary = _aggregate(rows, target_action=target_action)
    latest = _latest_sync(conn, account_id=account_id)
    summary.update(
        {
            "start": start,
            "end": end,
            "level": level,
            "last_sync_at": latest["last_sync_at"],
            "error_accounts": latest["error_accounts"],
            "account_count": latest["account_count"],
        }
    )
    return summary


def get_insights(
    conn: sqlite3.Connection,
    start: str,
    end: str,
    account_id: str | None = None,
    campaign_id: str | None = None,
    ad_id: str | None = None,
    target_action: str = "landing_click",
    trend_grain: str = "daily",
) -> dict[str, Any]:
    account_rows = _fetch_rows(conn, "account", start, end, account_id=account_id)
    campaign_rows = _fetch_rows(
        conn, "campaign", start, end, account_id=account_id, campaign_id=campaign_id
    )
    adset_rows = _fetch_rows(
        conn, "adset", start, end, account_id=account_id, campaign_id=campaign_id
    )
    ad_rows = _fetch_rows(
        conn, "ad", start, end, account_id=account_id, campaign_id=campaign_id, ad_id=ad_id
    )
    if ad_id:
        account_rows = ad_rows
        campaign_rows = ad_rows
        adset_rows = ad_rows
        account_label_field = "ad_account_id"
    else:
        account_label_field = "object_name"
    account_groups = _group_rows(
        account_rows,
        key_field="ad_account_id",
        label_field=account_label_field,
        target_action=target_action,
        limit=100,
    )
    account_names = {a["ad_account_id"]: a["account_name"] for a in get_accounts(conn)}
    for account in account_groups:
        account["name"] = account_names.get(account["id"], account["name"])

    return {
        "accounts": account_groups,
        "campaigns": _group_rows(
            campaign_rows,
            key_field="campaign_id",
            label_field="campaign_name",
            target_action=target_action,
            limit=25,
        ),
        "adsets": _group_rows(
            adset_rows,
            key_field="adset_id",
            label_field="adset_name",
            target_action=target_action,
            limit=25,
        ),
        "ads": _group_rows(
            ad_rows,
            key_field="ad_id",
            label_field="ad_name",
            target_action=target_action,
            limit=25,
        ),
        "platforms": get_platform_breakdown(
            conn,
            start=start,
            end=end,
            account_id=account_id,
            campaign_id=campaign_id,
            ad_id=ad_id,
            target_action=target_action,
        ),
        "trend": get_trend(
            conn,
            start=start,
            end=end,
            account_id=account_id,
            campaign_id=campaign_id,
            ad_id=ad_id,
            target_action=target_action,
            grain=trend_grain,
        ),
    }


def get_trend(
    conn: sqlite3.Connection,
    start: str,
    end: str,
    account_id: str | None = None,
    campaign_id: str | None = None,
    ad_id: str | None = None,
    target_action: str = "landing_click",
    grain: str = "daily",
) -> list[dict[str, Any]]:
    level = "ad" if ad_id else "campaign" if campaign_id else "account"
    fact_rows = _fetch_rows(
        conn,
        level,
        start,
        end,
        account_id=account_id,
        campaign_id=campaign_id,
        ad_id=ad_id,
    )
    by_bucket: dict[str, list[sqlite3.Row]] = {}
    for row in fact_rows:
        by_bucket.setdefault(_bucket_for_date(row["date_start"], grain), []).append(row)
    return [
        {"bucket": bucket, **_aggregate(bucket_rows, target_action=target_action)}
        for bucket, bucket_rows in sorted(by_bucket.items())
    ]


def get_platform_breakdown(
    conn: sqlite3.Connection,
    start: str,
    end: str,
    account_id: str | None = None,
    campaign_id: str | None = None,
    ad_id: str | None = None,
    target_action: str = "landing_click",
) -> list[dict[str, Any]]:
    rows = _fetch_breakdown_rows(
        conn,
        "ad",
        start,
        end,
        account_id=account_id,
        campaign_id=campaign_id,
        ad_id=ad_id,
    )
    if not rows:
        fallback_level = "ad" if ad_id else "campaign" if campaign_id else "account"
        rows = _fetch_breakdown_rows(
            conn,
            fallback_level,
            start,
            end,
            account_id=account_id,
            campaign_id=campaign_id,
            ad_id=ad_id,
        )
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        platform = row["publisher_platform"] or "unknown"
        group = groups.setdefault(
            platform,
            {
                "id": platform,
                "name": _platform_label(platform),
                "publisher_platform": platform,
                "rows": [],
            },
        )
        group["rows"].append(row)
    out = []
    for group in groups.values():
        metrics = _aggregate(group["rows"], target_action=target_action)
        out.append({k: v for k, v in group.items() if k != "rows"} | metrics)
    out.sort(key=lambda r: r["spend"], reverse=True)
    return out


def get_alerts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [a.__dict__ for a in alerts.compute_current_alerts(conn)]


def _fetch_rows(
    conn: sqlite3.Connection,
    level: str,
    start: str,
    end: str,
    account_id: str | None = None,
    campaign_id: str | None = None,
    ad_id: str | None = None,
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM meta_insights WHERE level=? AND date_start>=? AND date_start<=?"
    params: list[Any] = [level, start, end]
    if account_id:
        sql += " AND ad_account_id=?"
        params.append(normalize_account_id(account_id))
    if campaign_id:
        sql += " AND campaign_id=?"
        params.append(campaign_id)
    if ad_id:
        sql += " AND ad_id=?"
        params.append(ad_id)
    return conn.execute(sql, params).fetchall()


def _fetch_breakdown_rows(
    conn: sqlite3.Connection,
    level: str,
    start: str,
    end: str,
    account_id: str | None = None,
    campaign_id: str | None = None,
    ad_id: str | None = None,
) -> list[sqlite3.Row]:
    sql = (
        "SELECT * FROM meta_insight_breakdowns "
        "WHERE level=? AND date_start>=? AND date_start<=?"
    )
    params: list[Any] = [level, start, end]
    if account_id:
        sql += " AND ad_account_id=?"
        params.append(normalize_account_id(account_id))
    if campaign_id:
        sql += " AND campaign_id=?"
        params.append(campaign_id)
    if ad_id:
        sql += " AND ad_id=?"
        params.append(ad_id)
    return conn.execute(sql, params).fetchall()


def _row_metrics(row: sqlite3.Row, target_action: str) -> dict[str, float]:
    spend = float(row["spend"] or 0)
    if _is_homepage_click_target(target_action):
        return {
            "spend": spend,
            "impressions": float(row["impressions"] or 0),
            "reach": float(row["reach"] or 0),
            "clicks": float(row["clicks"] or 0),
            "inline_link_clicks": float(row["inline_link_clicks"] or 0),
            "conversions": float(row["inline_link_clicks"] or 0),
            "conversion_value": 0.0,
            "purchase_roas": 0.0,
            "cpa": 0.0,
        }
    conversions, value, roas, cpa = metrics_from_action_json(
        spend,
        row["actions_json"],
        row["action_values_json"],
        row["cost_per_action_type_json"],
        target_action=target_action,
    )
    if target_action == "purchase" and conversions <= 0 and value <= 0:
        conversions = float(row["conversions"] or 0)
        value = float(row["conversion_value"] or 0)
        roas = float(row["purchase_roas"] or 0)
        cpa = float(row["cpa"] or 0)
    return {
        "spend": spend,
        "impressions": float(row["impressions"] or 0),
        "reach": float(row["reach"] or 0),
        "clicks": float(row["clicks"] or 0),
        "inline_link_clicks": float(row["inline_link_clicks"] or 0),
        "conversions": conversions,
        "conversion_value": value,
        "purchase_roas": roas,
        "cpa": cpa,
    }


def _aggregate(rows: list[sqlite3.Row], target_action: str = "landing_click") -> dict[str, Any]:
    totals = {
        "spend": 0.0,
        "impressions": 0.0,
        "reach": 0.0,
        "clicks": 0.0,
        "inline_link_clicks": 0.0,
        "conversions": 0.0,
        "conversion_value": 0.0,
    }
    for row in rows:
        metrics = _row_metrics(row, target_action)
        for key in totals:
            totals[key] += metrics[key]

    spend = totals["spend"]
    impressions = totals["impressions"]
    reach = totals["reach"]
    clicks = totals["clicks"]
    conversions = totals["conversions"]
    value = totals["conversion_value"]
    return {
        "spend": spend,
        "impressions": int(impressions),
        "reach": int(reach),
        "clicks": int(clicks),
        "inline_link_clicks": int(totals["inline_link_clicks"]),
        "conversions": conversions,
        "conversion_value": value,
        "ctr": (clicks / impressions * 100) if impressions else 0.0,
        "cpm": (spend / impressions * 1000) if impressions else 0.0,
        "cpc": (spend / clicks) if clicks else 0.0,
        "cpa": (spend / conversions) if conversions else 0.0,
        "purchase_roas": (value / spend) if spend and value else 0.0,
        "frequency": (impressions / reach) if reach else 0.0,
        "row_count": len(rows),
    }


def _group_rows(
    rows: list[sqlite3.Row],
    key_field: str,
    label_field: str,
    target_action: str,
    limit: int,
) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row[key_field] if key_field in row.keys() else row["object_id"]
        if not key:
            key = row["object_id"]
        group = groups.setdefault(
            key,
            {
                "id": key,
                "name": row[label_field] if label_field in row.keys() else row["object_name"],
                "ad_account_id": row["ad_account_id"],
                "rows": [],
            },
        )
        group["rows"].append(row)
    out = []
    for group in groups.values():
        metrics = _aggregate(group["rows"], target_action=target_action)
        out.append({k: v for k, v in group.items() if k != "rows"} | metrics)
    out.sort(key=lambda r: (r["spend"], r["conversions"]), reverse=True)
    return out[:limit]


def _trend_row(row: sqlite3.Row) -> dict[str, Any]:
    spend = float(row["spend"] or 0)
    conversions = float(row["conversions"] or 0)
    value = float(row["conversion_value"] or 0)
    impressions = float(row["impressions"] or 0)
    clicks = float(row["clicks"] or 0)
    return {
        "bucket": row["bucket"],
        "spend": spend,
        "conversions": conversions,
        "conversion_value": value,
        "purchase_roas": (value / spend) if spend and value else 0.0,
        "cpa": (spend / conversions) if conversions else 0.0,
        "ctr": (clicks / impressions * 100) if impressions else 0.0,
    }


def _bucket_for_date(date_s: str, grain: str) -> str:
    d = dt.date.fromisoformat(date_s)
    if grain == "weekly":
        iso = d.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    if grain == "monthly":
        return d.strftime("%Y-%m")
    return d.isoformat()


def _platform_label(platform: str) -> str:
    labels = {
        "facebook": "Facebook",
        "instagram": "Instagram",
        "messenger": "Messenger",
        "audience_network": "Audience Network",
        "threads": "Threads",
    }
    return labels.get(platform, platform or "Unknown")


def _is_homepage_click_target(target_action: str) -> bool:
    return target_action in {"landing_click", "homepage_click", "inline_link_click"}


def _latest_sync(conn: sqlite3.Connection, account_id: str | None = None) -> dict[str, Any]:
    accounts = get_accounts(conn)
    if account_id:
        account_id = normalize_account_id(account_id)
        accounts = [a for a in accounts if a["ad_account_id"] == account_id]
    last_sync = max([a["last_sync_at"] for a in accounts if a["last_sync_at"]] or [""])
    error_accounts = sum(1 for a in accounts if a["sync_status"] == "failed")
    return {
        "last_sync_at": last_sync,
        "error_accounts": error_accounts,
        "account_count": len(accounts),
    }

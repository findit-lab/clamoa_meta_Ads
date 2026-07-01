"""Query helpers for the Meta Ads monitoring dashboard."""
from __future__ import annotations

import datetime as dt
import sqlite3
from typing import Any
from urllib.parse import parse_qsl

from . import alerts, landing_events
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
           WHERE a.active=1
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
) -> list[dict[str, Any]]:
    sql = (
        "SELECT i.ad_id, MAX(i.ad_name) AS ad_name, MAX(i.campaign_id) AS campaign_id, "
        "MAX(i.ad_account_id) AS ad_account_id, MAX(COALESCE(c.url_tags, '')) AS url_tags "
        "FROM meta_insights i "
        "LEFT JOIN meta_ad_creatives c "
        "ON c.ad_account_id=i.ad_account_id AND c.ad_id=i.ad_id "
        "WHERE i.ad_id<>''"
    )
    params: list[Any] = []
    if account_id:
        sql += " AND i.ad_account_id=?"
        params.append(normalize_account_id(account_id))
    if campaign_id:
        sql += " AND i.campaign_id=?"
        params.append(campaign_id)
    sql += " GROUP BY i.ad_id ORDER BY ad_name"
    rows = conn.execute(sql, params).fetchall()
    return [
        {
            "ad_id": r["ad_id"],
            "ad_name": r["ad_name"] or r["ad_id"],
            "campaign_id": r["campaign_id"] or "",
            "ad_account_id": r["ad_account_id"] or "",
            **_utm_fields(r["ad_name"] or "", r["url_tags"] or ""),
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
    utm_filter: str = "all",
) -> dict[str, Any]:
    level = "ad" if ad_id or _uses_ad_rows(utm_filter) else "campaign" if campaign_id else "account"
    rows = _fetch_rows(
        conn,
        level,
        start,
        end,
        account_id=account_id,
        campaign_id=campaign_id,
        ad_id=ad_id,
        utm_filter=utm_filter,
    )
    summary = _aggregate(rows, target_action=target_action)
    utm_rows = _fetch_rows(
        conn,
        "ad",
        start,
        end,
        account_id=account_id,
        campaign_id=campaign_id,
        ad_id=ad_id,
        utm_filter="utm",
    )
    utm_summary = _aggregate(utm_rows, target_action=target_action)
    latest = _latest_sync(conn, account_id=account_id)
    summary.update(
        {
            "start": start,
            "end": end,
            "level": level,
            "utm_filter": _clean_utm_filter(utm_filter),
            "utm_ad_count": len({r["ad_id"] for r in utm_rows if r["ad_id"]}),
            "utm_spend": utm_summary["spend"],
            "utm_conversions": utm_summary["conversions"],
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
    utm_filter: str = "all",
) -> dict[str, Any]:
    ad_rows = _fetch_rows(
        conn,
        "ad",
        start,
        end,
        account_id=account_id,
        campaign_id=campaign_id,
        ad_id=ad_id,
        utm_filter=utm_filter,
    )
    if ad_id or _uses_ad_rows(utm_filter):
        account_rows = ad_rows
        campaign_rows = ad_rows
        adset_rows = ad_rows
        account_label_field = "ad_account_id"
    else:
        account_rows = _fetch_rows(conn, "account", start, end, account_id=account_id)
        campaign_rows = _fetch_rows(
            conn, "campaign", start, end, account_id=account_id, campaign_id=campaign_id
        )
        adset_rows = _fetch_rows(
            conn, "adset", start, end, account_id=account_id, campaign_id=campaign_id
        )
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

    ad_groups = _group_rows(
        ad_rows,
        key_field="ad_id",
        label_field="ad_name",
        target_action=target_action,
        limit=25,
    )
    _attach_creatives(conn, ad_groups)

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
        "ads": ad_groups,
        "utms": _group_utm_rows(ad_rows, target_action=target_action, limit=25),
        "traffic_sources": get_traffic_sources(conn, start=start, end=end, landing_key="clamoa"),
        "platforms": get_platform_breakdown(
            conn,
            start=start,
            end=end,
            account_id=account_id,
            campaign_id=campaign_id,
            ad_id=ad_id,
            target_action=target_action,
            utm_filter=utm_filter,
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
            utm_filter=utm_filter,
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
    utm_filter: str = "all",
) -> list[dict[str, Any]]:
    level = "ad" if ad_id or _uses_ad_rows(utm_filter) else "campaign" if campaign_id else "account"
    fact_rows = _fetch_rows(
        conn,
        level,
        start,
        end,
        account_id=account_id,
        campaign_id=campaign_id,
        ad_id=ad_id,
        utm_filter=utm_filter,
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
    utm_filter: str = "all",
) -> list[dict[str, Any]]:
    rows = _fetch_breakdown_rows(
        conn,
        "ad",
        start,
        end,
        account_id=account_id,
        campaign_id=campaign_id,
        ad_id=ad_id,
        utm_filter=utm_filter,
    )
    if not rows and not _uses_ad_rows(utm_filter):
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


def get_traffic_sources(
    conn: sqlite3.Connection,
    start: str,
    end: str,
    landing_key: str = "clamoa",
    limit: int = 20,
) -> list[dict[str, Any]]:
    landing = _clean_landing_key(landing_key)
    durable_rows = landing_events.fetch(start=start, end=end, landing_key=landing, limit=5000)
    if durable_rows:
        return _traffic_sources_from_landing_rows(durable_rows, landing=landing, limit=limit)

    rows = conn.execute(
        """SELECT
             COALESCE(NULLIF(traffic_source, ''), 'direct') AS traffic_source,
             MAX(landing_key) AS landing_key,
             SUM(CASE WHEN event_name='PageView' THEN 1 ELSE 0 END) AS clicks,
             COUNT(DISTINCT CASE
               WHEN event_name='PageView' AND session_id<>'' THEN session_id
               ELSE NULL END) AS sessions,
             SUM(CASE WHEN event_name='Lead' THEN 1 ELSE 0 END) AS conversions,
             COUNT(*) AS events,
             MAX(traffic_medium) AS traffic_medium,
             MAX(traffic_campaign) AS traffic_campaign
           FROM landing_utm_events
           WHERE substr(captured_at, 1, 10)>=?
             AND substr(captured_at, 1, 10)<=?
             AND (?='all' OR landing_key=?)
           GROUP BY COALESCE(NULLIF(traffic_source, ''), 'direct')
           ORDER BY clicks DESC, conversions DESC, traffic_source
           LIMIT ?""",
        (start, end, landing, landing, int(limit)),
    ).fetchall()
    out = []
    for row in rows:
        clicks = int(row["clicks"] or 0)
        conversions = int(row["conversions"] or 0)
        out.append(
            {
                "id": row["traffic_source"] or "direct",
                "name": _traffic_source_label(row["traffic_source"] or "direct"),
                "landing_key": row["landing_key"] or landing,
                "traffic_source": row["traffic_source"] or "direct",
                "traffic_medium": row["traffic_medium"] or "",
                "traffic_campaign": row["traffic_campaign"] or "",
                "clicks": clicks,
                "sessions": int(row["sessions"] or 0),
                "conversions": conversions,
                "events": int(row["events"] or 0),
                "conversion_rate": (conversions / clicks * 100) if clicks else 0.0,
            }
        )
    return out


def _traffic_sources_from_landing_rows(
    rows: list[dict[str, Any]],
    *,
    landing: str,
    limit: int,
) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        if landing != "all" and row.get("landing_key") != landing:
            continue
        source = str(row.get("traffic_source") or "direct")
        group = groups.setdefault(
            source,
            {
                "id": source,
                "name": _traffic_source_label(source),
                "landing_key": row.get("landing_key") or landing,
                "traffic_source": source,
                "traffic_medium": "",
                "traffic_campaign": "",
                "clicks": 0,
                "sessions": set(),
                "conversions": 0,
                "events": 0,
            },
        )
        group["events"] += 1
        if row.get("traffic_medium"):
            group["traffic_medium"] = row["traffic_medium"]
        if row.get("traffic_campaign"):
            group["traffic_campaign"] = row["traffic_campaign"]
        if row.get("event_name") == "PageView":
            group["clicks"] += 1
            session_id = str(row.get("session_id") or "")
            if session_id:
                group["sessions"].add(session_id)
        if row.get("event_name") == "Lead":
            group["conversions"] += 1

    out = []
    for group in groups.values():
        clicks = int(group["clicks"] or 0)
        conversions = int(group["conversions"] or 0)
        out.append(
            {
                **group,
                "sessions": len(group["sessions"]),
                "conversion_rate": (conversions / clicks * 100) if clicks else 0.0,
            }
        )
    out.sort(key=lambda row: (-row["clicks"], -row["conversions"], row["traffic_source"]))
    return out[: int(limit)]


def _fetch_rows(
    conn: sqlite3.Connection,
    level: str,
    start: str,
    end: str,
    account_id: str | None = None,
    campaign_id: str | None = None,
    ad_id: str | None = None,
    utm_filter: str = "all",
) -> list[sqlite3.Row]:
    table_alias = "i"
    if level == "ad":
        sql = (
            "SELECT i.*, COALESCE(c.url_tags, '') AS creative_url_tags "
            "FROM meta_insights i "
            "LEFT JOIN meta_ad_creatives c "
            "ON c.ad_account_id=i.ad_account_id AND c.ad_id=i.ad_id "
            "WHERE i.level=? AND i.date_start>=? AND i.date_start<=?"
        )
    else:
        sql = "SELECT * FROM meta_insights WHERE level=? AND date_start>=? AND date_start<=?"
        table_alias = ""
    params: list[Any] = [level, start, end]
    if account_id:
        sql += f" AND {_qualify(table_alias, 'ad_account_id')}=?"
        params.append(normalize_account_id(account_id))
    if campaign_id:
        sql += f" AND {_qualify(table_alias, 'campaign_id')}=?"
        params.append(campaign_id)
    if ad_id:
        sql += f" AND {_qualify(table_alias, 'ad_id')}=?"
        params.append(ad_id)
    if level == "ad":
        sql = _append_utm_filter(sql, "i", _clean_utm_filter(utm_filter))
    return conn.execute(sql, params).fetchall()


def _fetch_breakdown_rows(
    conn: sqlite3.Connection,
    level: str,
    start: str,
    end: str,
    account_id: str | None = None,
    campaign_id: str | None = None,
    ad_id: str | None = None,
    utm_filter: str = "all",
) -> list[sqlite3.Row]:
    table_alias = "b"
    if level == "ad":
        sql = (
            "SELECT b.*, COALESCE(c.url_tags, '') AS creative_url_tags "
            "FROM meta_insight_breakdowns b "
            "LEFT JOIN meta_ad_creatives c "
            "ON c.ad_account_id=b.ad_account_id AND c.ad_id=b.ad_id "
            "WHERE b.level=? AND b.date_start>=? AND b.date_start<=?"
        )
    else:
        sql = (
            "SELECT * FROM meta_insight_breakdowns "
            "WHERE level=? AND date_start>=? AND date_start<=?"
        )
        table_alias = ""
    params: list[Any] = [level, start, end]
    if account_id:
        sql += f" AND {_qualify(table_alias, 'ad_account_id')}=?"
        params.append(normalize_account_id(account_id))
    if campaign_id:
        sql += f" AND {_qualify(table_alias, 'campaign_id')}=?"
        params.append(campaign_id)
    if ad_id:
        sql += f" AND {_qualify(table_alias, 'ad_id')}=?"
        params.append(ad_id)
    if level == "ad":
        sql = _append_utm_filter(sql, "b", _clean_utm_filter(utm_filter))
    return conn.execute(sql, params).fetchall()


def _qualify(table_alias: str, column: str) -> str:
    return f"{table_alias}.{column}" if table_alias else column


def _append_utm_filter(sql: str, table_alias: str, utm_filter: str) -> str:
    condition = (
        "(LOWER(COALESCE(c.url_tags, '')) LIKE '%utm_%' "
        f"OR LOWER(COALESCE({table_alias}.ad_name, '')) LIKE '%utm%' "
        f"OR LOWER(COALESCE({table_alias}.adset_name, '')) LIKE '%utm%' "
        f"OR LOWER(COALESCE({table_alias}.campaign_name, '')) LIKE '%utm%')"
    )
    if utm_filter == "utm":
        return f"{sql} AND {condition}"
    if utm_filter == "non_utm":
        return f"{sql} AND NOT {condition}"
    return sql


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


def _group_utm_rows(
    rows: list[sqlite3.Row],
    target_action: str,
    limit: int,
) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        utm = _utm_from_row(row)
        if not utm["is_utm"]:
            continue
        key_parts = [
            utm["utm_source"],
            utm["utm_medium"],
            utm["utm_campaign"],
            utm["utm_content"],
            utm["utm_term"],
        ]
        key = "|".join(key_parts) if any(key_parts) else "utm_named_ads"
        group = groups.setdefault(
            key,
            {
                "id": key,
                "name": _utm_label(utm),
                "utm_source": utm["utm_source"],
                "utm_medium": utm["utm_medium"],
                "utm_campaign": utm["utm_campaign"],
                "utm_content": utm["utm_content"],
                "utm_term": utm["utm_term"],
                "url_tags": utm["url_tags"],
                "ad_ids": set(),
                "rows": [],
            },
        )
        if row["ad_id"]:
            group["ad_ids"].add(row["ad_id"])
        group["rows"].append(row)

    out = []
    for group in groups.values():
        metrics = _aggregate(group["rows"], target_action=target_action)
        ad_count = len(group["ad_ids"])
        out.append(
            {
                k: v
                for k, v in group.items()
                if k not in {"rows", "ad_ids"}
            }
            | {"ad_count": ad_count}
            | metrics
        )
    out.sort(key=lambda r: (r["spend"], r["conversions"]), reverse=True)
    return out[:limit]


def _attach_creatives(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    ad_ids = sorted({str(row.get("id") or "") for row in rows if row.get("id")})
    if not ad_ids:
        return
    placeholders = ",".join("?" for _ in ad_ids)
    creative_rows = conn.execute(
        f"""SELECT ad_account_id, ad_id, creative_id, thumbnail_url, image_url,
                   effective_status, url_tags
            FROM meta_ad_creatives
            WHERE ad_id IN ({placeholders})""",
        ad_ids,
    ).fetchall()
    by_account_ad = {
        (r["ad_account_id"], r["ad_id"]): r
        for r in creative_rows
    }
    by_ad: dict[str, sqlite3.Row] = {}
    for r in creative_rows:
        by_ad.setdefault(r["ad_id"], r)
    for row in rows:
        creative = by_account_ad.get((row.get("ad_account_id"), row.get("id"))) or by_ad.get(row.get("id"))
        if not creative:
            row.update(_utm_fields(str(row.get("name") or ""), ""))
            row.update(
                {
                    "creative_id": "",
                    "thumbnail_url": "",
                    "image_url": "",
                    "effective_status": "",
                    "url_tags": "",
                }
            )
            continue
        url_tags = creative["url_tags"] or ""
        row.update(_utm_fields(str(row.get("name") or ""), url_tags))
        row.update(
            {
                "creative_id": creative["creative_id"] or "",
                "thumbnail_url": creative["thumbnail_url"] or creative["image_url"] or "",
                "image_url": creative["image_url"] or "",
                "effective_status": creative["effective_status"] or "",
                "url_tags": url_tags,
            }
        )


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


def _traffic_source_label(source: str) -> str:
    labels = {
        "meta": "Meta",
        "naver": "Naver",
        "google": "Google",
        "direct": "Direct",
    }
    return labels.get(source, source or "Unknown")


def _clean_landing_key(value: str) -> str:
    value = str(value or "clamoa").strip().lower()
    return value if value in {"clamoa", "asinayo", "all"} else "clamoa"


def _is_homepage_click_target(target_action: str) -> bool:
    return target_action in {"landing_click", "homepage_click", "inline_link_click"}


def _clean_utm_filter(value: str) -> str:
    value = str(value or "all").strip().lower()
    return value if value in {"all", "utm", "non_utm"} else "all"


def _uses_ad_rows(utm_filter: str) -> bool:
    return _clean_utm_filter(utm_filter) != "all"


def _row_value(row: sqlite3.Row | dict[str, Any], key: str, default: str = "") -> str:
    if isinstance(row, dict):
        return str(row.get(key) or default)
    return str(row[key] if key in row.keys() and row[key] is not None else default)


def _utm_from_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    url_tags = _row_value(row, "creative_url_tags") or _row_value(row, "url_tags")
    name = " ".join(
        _row_value(row, field)
        for field in ("ad_name", "adset_name", "campaign_name", "object_name", "name")
    )
    return _utm_fields(name, url_tags)


def _utm_fields(name: str, url_tags: str) -> dict[str, Any]:
    params = _parse_url_tags(url_tags)
    has_utm_params = any(key.startswith("utm_") for key in params)
    named_utm = "utm" in str(name or "").lower()
    return {
        "is_utm": has_utm_params or named_utm,
        "utm_source": params.get("utm_source", ""),
        "utm_medium": params.get("utm_medium", ""),
        "utm_campaign": params.get("utm_campaign", ""),
        "utm_content": params.get("utm_content", ""),
        "utm_term": params.get("utm_term", ""),
        "url_tags": url_tags or "",
    }


def _parse_url_tags(url_tags: str) -> dict[str, str]:
    raw = str(url_tags or "").strip().lstrip("?")
    if not raw:
        return {}
    return {
        str(key).lower(): str(value)
        for key, value in parse_qsl(raw, keep_blank_values=True)
    }


def _utm_label(utm: dict[str, Any]) -> str:
    parts = [
        str(utm.get("utm_source") or ""),
        str(utm.get("utm_campaign") or ""),
        str(utm.get("utm_content") or ""),
    ]
    label = " / ".join(part for part in parts if part)
    return label or "UTM 이름 표기 광고"


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

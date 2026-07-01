"""SQLite persistence helpers for Meta Ads performance data."""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import urllib.parse
from typing import Any, Iterable, Mapping

import config
from adintel import db as db_module
from .models import AdAccount, AdCreative, Alert, InsightBreakdownRow, InsightRow
from .normalizer import normalize_account_id


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def upsert_ad_account(
    conn: sqlite3.Connection,
    ad_account_id: str,
    account_name: str | None = None,
    currency: str | None = None,
    timezone_name: str | None = None,
    active: bool = True,
    target_action: str = "purchase",
    min_alert_spend: float | None = None,
    note: str = "",
    now: str | None = None,
) -> None:
    account_id = normalize_account_id(ad_account_id)
    ts = now or now_iso()
    conn.execute(
        """INSERT INTO meta_ad_accounts
             (ad_account_id, account_name, currency, timezone_name, active,
              target_action, min_alert_spend, note, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(ad_account_id) DO UPDATE SET
             account_name=excluded.account_name,
             currency=excluded.currency,
             timezone_name=excluded.timezone_name,
             active=excluded.active,
             target_action=excluded.target_action,
             min_alert_spend=excluded.min_alert_spend,
             note=excluded.note,
             updated_at=excluded.updated_at""",
        (
            account_id,
            account_name or account_id,
            currency or config.META_DEFAULT_CURRENCY,
            timezone_name or config.META_DEFAULT_TIMEZONE,
            1 if active else 0,
            target_action or "purchase",
            config.META_ALERT_MIN_SPEND if min_alert_spend is None else float(min_alert_spend),
            note,
            ts,
            ts,
        ),
    )


def row_to_account(row: sqlite3.Row) -> AdAccount:
    return AdAccount(
        ad_account_id=row["ad_account_id"],
        account_name=row["account_name"],
        currency=row["currency"] or "KRW",
        timezone_name=row["timezone_name"] or config.META_DEFAULT_TIMEZONE,
        active=bool(row["active"]),
        target_action=row["target_action"] or "purchase",
        min_alert_spend=float(row["min_alert_spend"] or config.META_ALERT_MIN_SPEND),
    )


def get_ad_account(conn: sqlite3.Connection, ad_account_id: str) -> AdAccount | None:
    row = conn.execute(
        "SELECT * FROM meta_ad_accounts WHERE ad_account_id=?",
        (normalize_account_id(ad_account_id),),
    ).fetchone()
    return row_to_account(row) if row else None


def list_active_ad_accounts(conn: sqlite3.Connection) -> list[AdAccount]:
    rows = conn.execute(
        "SELECT * FROM meta_ad_accounts WHERE active=1 ORDER BY account_name"
    ).fetchall()
    return [row_to_account(r) for r in rows]


def record_sync_start(
    conn: sqlite3.Connection,
    ad_account_id: str,
    lookback_days: int,
    levels: Iterable[str],
    api_version: str,
    started_at: str | None = None,
) -> tuple[int, str]:
    ts = started_at or now_iso()
    if db_module.is_postgres_connection(conn):
        cur = conn.execute(
            """INSERT INTO meta_sync_runs
                 (ad_account_id, started_at, status, lookback_days, levels_json, api_version)
               VALUES (?, ?, 'running', ?, ?, ?)
               RETURNING run_id""",
            (
                normalize_account_id(ad_account_id),
                ts,
                int(lookback_days),
                json.dumps(list(levels), ensure_ascii=False),
                api_version,
            ),
        )
        return int(cur.fetchone()["run_id"]), ts

    cur = conn.execute(
        """INSERT INTO meta_sync_runs
             (ad_account_id, started_at, status, lookback_days, levels_json, api_version)
           VALUES (?, ?, 'running', ?, ?, ?)""",
        (
            normalize_account_id(ad_account_id),
            ts,
            int(lookback_days),
            json.dumps(list(levels), ensure_ascii=False),
            api_version,
        ),
    )
    return int(cur.lastrowid), ts


def record_sync_finish(
    conn: sqlite3.Connection,
    run_id: int,
    status: str,
    rows_upserted: int = 0,
    error: str = "",
    finished_at: str | None = None,
) -> str:
    ts = finished_at or now_iso()
    conn.execute(
        """UPDATE meta_sync_runs
           SET finished_at=?, status=?, rows_upserted=?, error=?
           WHERE run_id=?""",
        (ts, status, int(rows_upserted), error, run_id),
    )
    return ts


def upsert_insight_rows(
    conn: sqlite3.Connection,
    rows: list[InsightRow],
    captured_at: str | None = None,
    take_snapshot: bool = True,
) -> int:
    if not rows:
        return 0
    conn.executemany(
        """INSERT INTO meta_insights
             (ad_account_id, level, date_start, date_stop, object_id, object_name,
              campaign_id, campaign_name, adset_id, adset_name, ad_id, ad_name,
              spend, impressions, reach, frequency, clicks, inline_link_clicks,
              cpc, cpm, ctr, conversions, conversion_value, purchase_roas, cpa,
              actions_json, action_values_json, cost_per_action_type_json, raw_json,
              synced_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                   ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(ad_account_id, level, date_start, object_id) DO UPDATE SET
              date_stop=excluded.date_stop,
              object_name=excluded.object_name,
              campaign_id=excluded.campaign_id,
              campaign_name=excluded.campaign_name,
              adset_id=excluded.adset_id,
              adset_name=excluded.adset_name,
              ad_id=excluded.ad_id,
              ad_name=excluded.ad_name,
              spend=excluded.spend,
              impressions=excluded.impressions,
              reach=excluded.reach,
              frequency=excluded.frequency,
              clicks=excluded.clicks,
              inline_link_clicks=excluded.inline_link_clicks,
              cpc=excluded.cpc,
              cpm=excluded.cpm,
              ctr=excluded.ctr,
              conversions=excluded.conversions,
              conversion_value=excluded.conversion_value,
              purchase_roas=excluded.purchase_roas,
              cpa=excluded.cpa,
              actions_json=excluded.actions_json,
              action_values_json=excluded.action_values_json,
              cost_per_action_type_json=excluded.cost_per_action_type_json,
              raw_json=excluded.raw_json,
              synced_at=excluded.synced_at""",
        [_insight_tuple(r) for r in rows],
    )
    if take_snapshot:
        snapshot_time = captured_at or now_iso()
        conn.executemany(
            """INSERT INTO meta_insight_snapshots
                 (captured_at, ad_account_id, level, date_start, object_id,
                  object_name, campaign_id, campaign_name, spend, impressions,
                  clicks, conversions, conversion_value, purchase_roas, cpa,
                  frequency)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    snapshot_time,
                    r.ad_account_id,
                    r.level,
                    r.date_start,
                    r.object_id,
                    r.object_name,
                    r.campaign_id,
                    r.campaign_name,
                    r.spend,
                    r.impressions,
                    r.clicks,
                    r.conversions,
                    r.conversion_value,
                    r.purchase_roas,
                    r.cpa,
                    r.frequency,
                )
                for r in rows
            ],
        )
    return len(rows)


def _insight_tuple(r: InsightRow) -> tuple:
    return (
        r.ad_account_id,
        r.level,
        r.date_start,
        r.date_stop,
        r.object_id,
        r.object_name,
        r.campaign_id,
        r.campaign_name,
        r.adset_id,
        r.adset_name,
        r.ad_id,
        r.ad_name,
        r.spend,
        r.impressions,
        r.reach,
        r.frequency,
        r.clicks,
        r.inline_link_clicks,
        r.cpc,
        r.cpm,
        r.ctr,
        r.conversions,
        r.conversion_value,
        r.purchase_roas,
        r.cpa,
        r.actions_json,
        r.action_values_json,
        r.cost_per_action_type_json,
        r.raw_json,
        r.synced_at,
    )


def upsert_breakdown_rows(
    conn: sqlite3.Connection,
    rows: list[InsightBreakdownRow],
) -> int:
    if not rows:
        return 0
    conn.executemany(
        """INSERT INTO meta_insight_breakdowns
             (ad_account_id, level, date_start, date_stop, object_id, object_name,
              campaign_id, campaign_name, adset_id, adset_name, ad_id, ad_name,
              publisher_platform, platform_position,
              spend, impressions, reach, frequency, clicks, inline_link_clicks,
              cpc, cpm, ctr, conversions, conversion_value, purchase_roas, cpa,
              actions_json, action_values_json, cost_per_action_type_json, raw_json,
              synced_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                   ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(ad_account_id, level, date_start, object_id,
                       publisher_platform, platform_position) DO UPDATE SET
              date_stop=excluded.date_stop,
              object_name=excluded.object_name,
              campaign_id=excluded.campaign_id,
              campaign_name=excluded.campaign_name,
              adset_id=excluded.adset_id,
              adset_name=excluded.adset_name,
              ad_id=excluded.ad_id,
              ad_name=excluded.ad_name,
              spend=excluded.spend,
              impressions=excluded.impressions,
              reach=excluded.reach,
              frequency=excluded.frequency,
              clicks=excluded.clicks,
              inline_link_clicks=excluded.inline_link_clicks,
              cpc=excluded.cpc,
              cpm=excluded.cpm,
              ctr=excluded.ctr,
              conversions=excluded.conversions,
              conversion_value=excluded.conversion_value,
              purchase_roas=excluded.purchase_roas,
              cpa=excluded.cpa,
              actions_json=excluded.actions_json,
              action_values_json=excluded.action_values_json,
              cost_per_action_type_json=excluded.cost_per_action_type_json,
              raw_json=excluded.raw_json,
              synced_at=excluded.synced_at""",
        [_breakdown_tuple(r) for r in rows],
    )
    return len(rows)


def _breakdown_tuple(r: InsightBreakdownRow) -> tuple:
    return (
        r.ad_account_id,
        r.level,
        r.date_start,
        r.date_stop,
        r.object_id,
        r.object_name,
        r.campaign_id,
        r.campaign_name,
        r.adset_id,
        r.adset_name,
        r.ad_id,
        r.ad_name,
        r.publisher_platform,
        r.platform_position,
        r.spend,
        r.impressions,
        r.reach,
        r.frequency,
        r.clicks,
        r.inline_link_clicks,
        r.cpc,
        r.cpm,
        r.ctr,
        r.conversions,
        r.conversion_value,
        r.purchase_roas,
        r.cpa,
        r.actions_json,
        r.action_values_json,
        r.cost_per_action_type_json,
        r.raw_json,
        r.synced_at,
    )


def upsert_ad_creatives(conn: sqlite3.Connection, rows: list[AdCreative]) -> int:
    if not rows:
        return 0
    conn.executemany(
        """INSERT INTO meta_ad_creatives
             (ad_account_id, ad_id, creative_id, thumbnail_url, image_url,
              effective_status, url_tags, raw_json, synced_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(ad_account_id, ad_id) DO UPDATE SET
              creative_id=excluded.creative_id,
              thumbnail_url=excluded.thumbnail_url,
              image_url=excluded.image_url,
              effective_status=excluded.effective_status,
              url_tags=excluded.url_tags,
              raw_json=excluded.raw_json,
              synced_at=excluded.synced_at""",
        [_ad_creative_tuple(r) for r in rows],
    )
    return len(rows)


def _ad_creative_tuple(r: AdCreative) -> tuple:
    return (
        r.ad_account_id,
        r.ad_id,
        r.creative_id,
        r.thumbnail_url,
        r.image_url,
        r.effective_status,
        r.url_tags,
        r.raw_json,
        r.synced_at,
    )


def record_landing_utm_event(
    conn: sqlite3.Connection,
    *,
    event_name: str,
    event_source_url: str,
    referrer: str = "",
    session_id: str = "",
    landing_key: str = "",
    browser_event_id: str = "",
    utm: Mapping[str, Any] | None = None,
    custom_data: Mapping[str, Any] | None = None,
    captured_at: str | None = None,
) -> int | None:
    row = landing_utm_event_row(
        event_name=event_name,
        event_source_url=event_source_url,
        referrer=referrer,
        session_id=session_id,
        landing_key=landing_key,
        browser_event_id=browser_event_id,
        utm=utm,
        custom_data=custom_data,
        captured_at=captured_at,
    )
    return insert_landing_utm_event_row(conn, row)


def insert_landing_utm_event_row(conn: sqlite3.Connection, row: Mapping[str, Any]) -> int | None:
    cur = conn.execute(
        """INSERT INTO landing_utm_events
             (captured_at, event_name, browser_event_id, event_source_url,
              page_path, referrer, session_id, landing_key, utm_source, utm_medium,
              utm_campaign, utm_content, utm_term, traffic_source,
              traffic_medium, traffic_campaign, raw_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            row["captured_at"],
            row["event_name"],
            row["browser_event_id"],
            row["event_source_url"],
            row["page_path"],
            row["referrer"],
            row["session_id"],
            row["landing_key"],
            row["utm_source"],
            row["utm_medium"],
            row["utm_campaign"],
            row["utm_content"],
            row["utm_term"],
            row["traffic_source"],
            row["traffic_medium"],
            row["traffic_campaign"],
            row["raw_json"],
        ),
    )
    return getattr(cur, "lastrowid", None)


def landing_utm_event_row(
    *,
    event_name: str,
    event_source_url: str,
    referrer: str = "",
    session_id: str = "",
    landing_key: str = "",
    browser_event_id: str = "",
    utm: Mapping[str, Any] | None = None,
    custom_data: Mapping[str, Any] | None = None,
    captured_at: str | None = None,
) -> dict[str, Any]:
    ts = captured_at or now_iso()
    parsed = _parse_url(event_source_url)
    params = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    utm_values = _utm_values(params, utm or {})
    traffic_source = _traffic_source(
        utm_values["utm_source"],
        params=params,
        referrer=referrer,
    )
    traffic_medium = _clip(utm_values["utm_medium"] or _default_medium(traffic_source))
    traffic_campaign = _clip(utm_values["utm_campaign"])
    landing = _landing_key(landing_key, event_source_url)
    raw = {
        "event_source_url": event_source_url,
        "referrer": referrer,
        "landing_key": landing,
        "utm": dict(utm or {}),
        "custom_data": dict(custom_data or {}),
    }
    return {
        "captured_at": ts,
        "event_name": _clip(event_name, 64),
        "browser_event_id": _clip(browser_event_id, 200),
        "event_source_url": _clip(event_source_url, 2000),
        "page_path": _clip(parsed.path or "/", 500),
        "referrer": _clip(referrer, 2000),
        "session_id": _clip(session_id, 200),
        "landing_key": landing,
        "utm_source": _clip(utm_values["utm_source"]),
        "utm_medium": _clip(utm_values["utm_medium"]),
        "utm_campaign": _clip(utm_values["utm_campaign"]),
        "utm_content": _clip(utm_values["utm_content"]),
        "utm_term": _clip(utm_values["utm_term"]),
        "traffic_source": _clip(traffic_source, 100),
        "traffic_medium": traffic_medium,
        "traffic_campaign": traffic_campaign,
        "raw_json": json.dumps(raw, ensure_ascii=False, sort_keys=True),
    }


def _landing_key(value: str, event_source_url: str) -> str:
    explicit = _source_slug(value)
    if explicit:
        return explicit
    host = _parse_url(event_source_url).netloc.lower()
    if "clamoa" in host:
        return "clamoa"
    if "asinayo" in host:
        return "asinayo"
    return "unknown"


def _parse_url(url: str) -> urllib.parse.ParseResult:
    try:
        return urllib.parse.urlparse(str(url or ""))
    except ValueError:
        return urllib.parse.urlparse("")


def _utm_values(
    query_params: Mapping[str, Any],
    payload_utm: Mapping[str, Any],
) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"):
        value = payload_utm.get(key) or query_params.get(key) or ""
        out[key] = str(value).strip()
    if not out["utm_source"]:
        if query_params.get("gclid") or query_params.get("gad_source"):
            out["utm_source"] = "google"
        elif query_params.get("fbclid"):
            out["utm_source"] = "meta"
        elif any(str(k).startswith("n_") for k in query_params):
            out["utm_source"] = "naver"
    return out


def _traffic_source(
    utm_source: str,
    *,
    params: Mapping[str, Any],
    referrer: str,
) -> str:
    source = _source_slug(utm_source)
    if source:
        return source
    if params.get("gclid") or params.get("gad_source"):
        return "google"
    if params.get("fbclid"):
        return "meta"
    if any(str(k).startswith("n_") for k in params):
        return "naver"
    host = _parse_url(referrer).netloc.lower()
    if not host:
        return "direct"
    if "naver." in host:
        return "naver"
    if "google." in host or "youtube." in host:
        return "google"
    if any(token in host for token in ("facebook.", "instagram.", "threads.", "meta.")):
        return "meta"
    return _clip(host.replace("www.", ""), 100)


def _source_slug(value: str) -> str:
    source = str(value or "").strip().lower()
    if not source:
        return ""
    if source in {"fb", "ig", "facebook", "instagram", "threads"} or "facebook" in source:
        return "meta"
    if "instagram" in source or "meta" in source:
        return "meta"
    if "naver" in source or "네이버" in source:
        return "naver"
    if "google" in source or "youtube" in source:
        return "google"
    return _clip(source.replace(" ", "_"), 100)


def _default_medium(source: str) -> str:
    if source in {"meta", "naver", "google"}:
        return "paid"
    if source == "direct":
        return "none"
    return "referral"


def _clip(value: Any, limit: int = 500) -> str:
    return str(value or "")[:limit]


def create_alert_event(conn: sqlite3.Connection, alert: Alert) -> bool:
    if db_module.is_postgres_connection(conn):
        cur = conn.execute(
            """INSERT INTO meta_alert_events
                 (fingerprint, alert_type, severity, ad_account_id, level,
                  object_id, object_name, message, metric_value, threshold,
                  detected_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(fingerprint) DO NOTHING
               RETURNING alert_id""",
            (
                alert.fingerprint,
                alert.alert_type,
                alert.severity,
                alert.ad_account_id,
                alert.level,
                alert.object_id,
                alert.object_name,
                alert.message,
                alert.metric_value,
                alert.threshold,
                alert.detected_at,
            ),
        )
        return cur.fetchone() is not None

    try:
        conn.execute(
            """INSERT INTO meta_alert_events
                 (fingerprint, alert_type, severity, ad_account_id, level,
                  object_id, object_name, message, metric_value, threshold,
                  detected_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                alert.fingerprint,
                alert.alert_type,
                alert.severity,
                alert.ad_account_id,
                alert.level,
                alert.object_id,
                alert.object_name,
                alert.message,
                alert.metric_value,
                alert.threshold,
                alert.detected_at,
            ),
        )
    except sqlite3.IntegrityError:
        return False
    return True


def mark_alerts_sent(conn: sqlite3.Connection, fingerprints: Iterable[str], sent_at: str | None = None) -> None:
    ts = sent_at or now_iso()
    conn.executemany(
        "UPDATE meta_alert_events SET sent_at=? WHERE fingerprint=?",
        [(ts, fp) for fp in fingerprints],
    )

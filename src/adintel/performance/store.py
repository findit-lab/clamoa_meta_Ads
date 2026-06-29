"""SQLite persistence helpers for Meta Ads performance data."""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from typing import Iterable

import config
from .models import AdAccount, Alert, InsightBreakdownRow, InsightRow
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


def create_alert_event(conn: sqlite3.Connection, alert: Alert) -> bool:
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

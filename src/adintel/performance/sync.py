"""Meta Ads Insights sync orchestration."""
from __future__ import annotations

import datetime as dt
import sqlite3

import config
from . import store
from .meta_api import MetaInsightsClient, fields_for_level
from .models import AdAccount, SyncResult
from .normalizer import normalize_account_id, normalize_breakdown_insight, normalize_insight

DEFAULT_LEVELS = ("account", "campaign", "adset", "ad")
DEFAULT_BREAKDOWNS = ("publisher_platform", "platform_position")


def date_window(lookback_days: int, today: dt.date | None = None) -> tuple[str, str]:
    anchor = today or dt.date.today()
    days = max(1, int(lookback_days))
    since = anchor - dt.timedelta(days=days - 1)
    return since.isoformat(), anchor.isoformat()


def sync_account(
    conn: sqlite3.Connection,
    client: MetaInsightsClient,
    account: AdAccount,
    lookback_days: int = 2,
    levels: tuple[str, ...] = DEFAULT_LEVELS,
    breakdowns: tuple[str, ...] = DEFAULT_BREAKDOWNS,
    today: dt.date | None = None,
    captured_at: str | None = None,
) -> SyncResult:
    started_at = captured_at or store.now_iso()
    run_id, started_at = store.record_sync_start(
        conn,
        account.ad_account_id,
        lookback_days=lookback_days,
        levels=levels,
        api_version=client.api_version,
        started_at=started_at,
    )
    since, until = date_window(lookback_days, today=today)
    rows = []
    breakdown_rows = []
    ad_ids: set[str] = set()
    try:
        for level in levels:
            raw_rows = client.fetch_insights(
                account.ad_account_id,
                level=level,
                since=since,
                until=until,
                fields=fields_for_level(level),
                time_increment=1,
            )
            rows.extend(
                normalize_insight(
                    raw,
                    ad_account_id=account.ad_account_id,
                    level=level,
                    synced_at=started_at,
                    target_action=account.target_action,
                )
                for raw in raw_rows
            )
            if level == "ad":
                ad_ids.update(str(raw.get("ad_id") or "").strip() for raw in raw_rows)
            if breakdowns:
                raw_breakdown_rows = client.fetch_insights(
                    account.ad_account_id,
                    level=level,
                    since=since,
                    until=until,
                    fields=fields_for_level(level),
                    breakdowns=list(breakdowns),
                    time_increment=1,
                )
                breakdown_rows.extend(
                    normalize_breakdown_insight(
                        raw,
                        ad_account_id=account.ad_account_id,
                        level=level,
                        synced_at=started_at,
                        target_action=account.target_action,
                    )
                    for raw in raw_breakdown_rows
                )
        inserted = store.upsert_insight_rows(conn, rows, captured_at=started_at)
        inserted += store.upsert_breakdown_rows(conn, breakdown_rows)
        inserted += _sync_ad_creatives(conn, client, account, ad_ids, started_at)
        finished_at = store.record_sync_finish(
            conn, run_id, "success", rows_upserted=inserted
        )
        conn.commit()
        return SyncResult(
            ad_account_id=account.ad_account_id,
            status="success",
            rows_upserted=inserted,
            started_at=started_at,
            finished_at=finished_at,
        )
    except Exception as e:
        finished_at = store.record_sync_finish(
            conn, run_id, "failed", rows_upserted=0, error=str(e)
        )
        conn.commit()
        raise RuntimeError(f"Meta sync failed for {account.ad_account_id}: {e}") from e


def sync_all_accounts(
    conn: sqlite3.Connection,
    client: MetaInsightsClient,
    lookback_days: int = 2,
    levels: tuple[str, ...] = DEFAULT_LEVELS,
    breakdowns: tuple[str, ...] = DEFAULT_BREAKDOWNS,
    today: dt.date | None = None,
) -> list[SyncResult]:
    results: list[SyncResult] = []
    for account in store.list_active_ad_accounts(conn):
        try:
            results.append(
                sync_account(
                    conn,
                    client,
                    account,
                    lookback_days=lookback_days,
                    levels=levels,
                    breakdowns=breakdowns,
                    today=today,
                )
            )
        except Exception as e:
            results.append(
                SyncResult(
                    ad_account_id=account.ad_account_id,
                    status="failed",
                    rows_upserted=0,
                    started_at="",
                    finished_at=store.now_iso(),
                    error=str(e),
                )
            )
    return results


def ensure_account_for_sync(
    conn: sqlite3.Connection,
    ad_account_id: str,
    account_name: str | None = None,
) -> AdAccount:
    account_id = normalize_account_id(ad_account_id)
    account = store.get_ad_account(conn, account_id)
    if account:
        return account
    store.upsert_ad_account(
        conn,
        account_id,
        account_name=account_name or account_id,
        currency=config.META_DEFAULT_CURRENCY,
        timezone_name=config.META_DEFAULT_TIMEZONE,
    )
    conn.commit()
    created = store.get_ad_account(conn, account_id)
    assert created is not None
    return created


def _sync_ad_creatives(
    conn: sqlite3.Connection,
    client: MetaInsightsClient,
    account: AdAccount,
    ad_ids: set[str],
    synced_at: str,
) -> int:
    fetch = getattr(client, "fetch_ad_creatives", None)
    clean_ids = sorted(ad_id for ad_id in ad_ids if ad_id)
    if not clean_ids or fetch is None:
        return 0
    try:
        previews = fetch(account.ad_account_id, clean_ids, synced_at=synced_at)
    except Exception as e:
        print(f"[creative-sync] skipped {account.ad_account_id}: {e}")
        return 0
    return store.upsert_ad_creatives(conn, previews)

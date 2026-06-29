"""FastAPI dashboard for Meta Ads performance monitoring."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

import config
from adintel import db
from . import alerts, dashboard_data
from .meta_api import MetaInsightsClient
from .sync import DEFAULT_LEVELS, ensure_account_for_sync, sync_account, sync_all_accounts

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

app = FastAPI(title="Meta Ads Performance Dashboard")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/api/accounts")
def api_accounts():
    conn = db.connect()
    try:
        return {
            "accounts": dashboard_data.get_accounts(conn),
            "campaigns": dashboard_data.get_campaign_options(conn),
            "ads": dashboard_data.get_ad_options(conn),
        }
    finally:
        conn.close()


@app.get("/api/summary")
def api_summary(
    start: Optional[str] = None,
    end: Optional[str] = None,
    account_id: Optional[str] = None,
    campaign_id: Optional[str] = None,
    ad_id: Optional[str] = None,
    target_action: str = "landing_click",
):
    start, end = _range(start, end)
    conn = db.connect()
    try:
        return dashboard_data.get_summary(
            conn,
            start=start,
            end=end,
            account_id=account_id,
            campaign_id=campaign_id,
            ad_id=ad_id,
            target_action=target_action,
        )
    finally:
        conn.close()


@app.get("/api/insights")
def api_insights(
    start: Optional[str] = None,
    end: Optional[str] = None,
    account_id: Optional[str] = None,
    campaign_id: Optional[str] = None,
    ad_id: Optional[str] = None,
    target_action: str = "landing_click",
    trend_grain: str = "daily",
):
    start, end = _range(start, end)
    conn = db.connect()
    try:
        return dashboard_data.get_insights(
            conn,
            start=start,
            end=end,
            account_id=account_id,
            campaign_id=campaign_id,
            ad_id=ad_id,
            target_action=target_action,
            trend_grain=trend_grain,
        )
    finally:
        conn.close()


@app.get("/api/alerts")
def api_alerts():
    conn = db.connect()
    try:
        return {"alerts": dashboard_data.get_alerts(conn)}
    finally:
        conn.close()


@app.post("/api/sync")
def api_sync(
    account_id: Optional[str] = Query(default=None),
    lookback_days: int = Query(default=2, ge=1, le=90),
):
    db.init_db()
    conn = db.connect()
    try:
        client = MetaInsightsClient()
        if account_id:
            account = ensure_account_for_sync(conn, account_id)
            results = [
                sync_account(
                    conn,
                    client,
                    account,
                    lookback_days=lookback_days,
                    levels=DEFAULT_LEVELS,
                )
            ]
        else:
            results = sync_all_accounts(conn, client, lookback_days=lookback_days)
        current_alerts = alerts.compute_current_alerts(conn)
        notified = alerts.notify_slack(conn, current_alerts)
        return {
            "results": [r.__dict__ for r in results],
            "alerts_detected": len(current_alerts),
            "alerts_notified": notified,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    finally:
        conn.close()


def _range(start: str | None, end: str | None) -> tuple[str, str]:
    default_start, default_end = dashboard_data.default_range(days=7)
    return start or default_start, end or default_end

"""FastAPI dashboard for Meta Ads performance monitoring."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

import config
from adintel import db
from . import alerts, dashboard_data
from .capi import ALLOWED_EVENT_NAMES, MetaCapiError, MetaConversionsClient, build_event_payload
from .meta_api import MetaApiError, MetaInsightsClient, friendly_error_message, is_access_token_expired
from .models import SyncResult
from . import store
from .sync import DEFAULT_LEVELS, ensure_account_for_sync, sync_account, sync_all_accounts

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

app = FastAPI(title="Meta Ads Performance Dashboard")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

if config.META_CAPI_ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.META_CAPI_ALLOWED_ORIGINS,
        allow_methods=["POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )


class CapiBrowserEvent(BaseModel):
    event_name: str
    event_id: str = ""
    event_source_url: str = ""
    fbp: str = ""
    fbc: str = ""
    custom_data: dict[str, Any] = Field(default_factory=dict)


class LandingUtmEvent(BaseModel):
    event_name: str = "PageView"
    event_id: str = ""
    event_source_url: str = ""
    referrer: str = ""
    session_id: str = ""
    landing_key: str = ""
    utm: dict[str, Any] = Field(default_factory=dict)
    custom_data: dict[str, Any] = Field(default_factory=dict)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={},
    )


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
    utm_filter: str = "all",
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
            utm_filter=utm_filter,
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
    utm_filter: str = "all",
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
            utm_filter=utm_filter,
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


@app.post("/api/utm/event")
def api_utm_event(payload: LandingUtmEvent, request: Request):
    if payload.event_name not in ALLOWED_EVENT_NAMES:
        raise HTTPException(status_code=400, detail=f"unsupported event: {payload.event_name}")
    conn = db.connect()
    try:
        store.record_landing_utm_event(
            conn,
            event_name=payload.event_name,
            browser_event_id=payload.event_id,
            event_source_url=payload.event_source_url or str(request.headers.get("referer") or request.url),
            referrer=payload.referrer,
            session_id=payload.session_id,
            landing_key=payload.landing_key,
            utm=payload.utm,
            custom_data=payload.custom_data,
        )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.post("/api/meta/capi")
def api_meta_capi(payload: CapiBrowserEvent, request: Request):
    try:
        event = build_event_payload(
            event_name=payload.event_name,
            event_id=payload.event_id or f"server-{store.now_iso()}",
            event_source_url=payload.event_source_url or str(request.url),
            client_ip_address=_client_ip(request),
            client_user_agent=request.headers.get("user-agent", ""),
            fbp=payload.fbp,
            fbc=payload.fbc,
            custom_data=payload.custom_data,
        )
        response = MetaConversionsClient().send_event(event)
        return {
            "ok": True,
            "events_received": response.get("events_received", 0),
            "fbtrace_id": response.get("fbtrace_id", ""),
            "messages": response.get("messages", []),
        }
    except MetaCapiError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@app.post("/api/sync")
def api_sync(
    account_id: Optional[str] = Query(default=None),
    lookback_days: int = Query(default=2, ge=1, le=90),
):
    db.init_db()
    conn = db.connect()
    try:
        try:
            client = MetaInsightsClient()
        except MetaApiError as e:
            return _sync_response(
                [
                    SyncResult(
                        ad_account_id=account_id or "",
                        status="failed",
                        rows_upserted=0,
                        started_at="",
                        finished_at=store.now_iso(),
                        error=str(e),
                    )
                ],
                alerts_detected=0,
                alerts_notified=0,
            )
        if account_id:
            account = ensure_account_for_sync(conn, account_id)
            try:
                results = [
                    sync_account(
                        conn,
                        client,
                        account,
                        lookback_days=lookback_days,
                        levels=DEFAULT_LEVELS,
                    )
                ]
            except Exception as e:
                results = [
                    SyncResult(
                        ad_account_id=account.ad_account_id,
                        status="failed",
                        rows_upserted=0,
                        started_at="",
                        finished_at=store.now_iso(),
                        error=str(e),
                    )
                ]
        else:
            results = sync_all_accounts(conn, client, lookback_days=lookback_days)
        current_alerts = alerts.compute_current_alerts(conn)
        notified = alerts.notify_slack(conn, current_alerts)
        return _sync_response(
            results,
            alerts_detected=len(current_alerts),
            alerts_notified=notified,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=friendly_error_message(str(e))) from e
    finally:
        conn.close()


def _sync_response(
    results: list[SyncResult],
    alerts_detected: int,
    alerts_notified: int,
) -> dict:
    failed = [r for r in results if r.status != "success"]
    token_expired = any(is_access_token_expired(r.error) for r in failed)
    message = ""
    if failed:
        if token_expired:
            message = friendly_error_message(failed[0].error)
        else:
            message = "일부 계정 동기화에 실패했습니다: " + "; ".join(
                f"{r.ad_account_id or 'unknown'} - {friendly_error_message(r.error)}"
                for r in failed
            )
    return {
        "ok": not failed,
        "needs_token_refresh": token_expired,
        "message": message,
        "results": [
            {
                **r.__dict__,
                "friendly_error": friendly_error_message(r.error) if r.error else "",
            }
            for r in results
        ],
        "alerts_detected": alerts_detected,
        "alerts_notified": alerts_notified,
    }


def _range(start: str | None, end: str | None) -> tuple[str, str]:
    default_start, default_end = dashboard_data.default_range(days=7)
    return start or default_start, end or default_end


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.client.host if request.client else ""

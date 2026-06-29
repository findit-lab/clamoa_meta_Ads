"""Operational alert rules and Slack delivery for Meta Ads monitoring."""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import statistics
import urllib.request

import config
from .models import Alert
from . import store


CPA_SPIKE_MULTIPLIER = 1.5
ROAS_DROP_MULTIPLIER = 0.5
SPEND_PACING_MULTIPLIER = 1.5
HIGH_FREQUENCY_THRESHOLD = 4.0


def compute_current_alerts(
    conn: sqlite3.Connection,
    today: dt.date | None = None,
    level: str = "campaign",
) -> list[Alert]:
    anchor = today or dt.date.today()
    today_s = anchor.isoformat()
    start_s = (anchor - dt.timedelta(days=7)).isoformat()
    detected_at = store.now_iso()
    alerts: list[Alert] = []
    accounts = {a.ad_account_id: a for a in store.list_active_ad_accounts(conn)}

    alerts.extend(_sync_failure_alerts(conn, accounts, detected_at, today_s))

    today_rows = conn.execute(
        """SELECT * FROM meta_insights
           WHERE level=? AND date_start=?""",
        (level, today_s),
    ).fetchall()
    history_rows = conn.execute(
        """SELECT * FROM meta_insights
           WHERE level=? AND date_start>=? AND date_start<?""",
        (level, start_s, today_s),
    ).fetchall()
    history = _history_by_object(history_rows)

    for row in today_rows:
        account = accounts.get(row["ad_account_id"])
        if not account:
            continue
        spend = float(row["spend"] or 0)
        if spend < account.min_alert_spend:
            continue
        object_id = row["object_id"]
        object_name = row["object_name"] or object_id

        if float(row["conversions"] or 0) <= 0:
            alerts.append(
                _alert(
                    "no_conversion_spend",
                    "critical",
                    row,
                    today_s,
                    detected_at,
                    f"{object_name}: spend is running with 0 target conversions",
                    spend,
                    account.min_alert_spend,
                )
            )

        if float(row["frequency"] or 0) >= HIGH_FREQUENCY_THRESHOLD:
            alerts.append(
                _alert(
                    "high_frequency",
                    "warning",
                    row,
                    today_s,
                    detected_at,
                    f"{object_name}: frequency is high",
                    float(row["frequency"] or 0),
                    HIGH_FREQUENCY_THRESHOLD,
                )
            )

        prior = history.get((row["ad_account_id"], object_id), [])
        cpas = [float(r["cpa"] or 0) for r in prior if float(r["cpa"] or 0) > 0]
        roas_values = [
            float(r["purchase_roas"] or 0)
            for r in prior
            if float(r["purchase_roas"] or 0) > 0
        ]
        spends = [float(r["spend"] or 0) for r in prior if float(r["spend"] or 0) > 0]

        current_cpa = float(row["cpa"] or 0)
        if cpas and current_cpa > statistics.median(cpas) * CPA_SPIKE_MULTIPLIER:
            threshold = statistics.median(cpas) * CPA_SPIKE_MULTIPLIER
            alerts.append(
                _alert(
                    "cpa_spike",
                    "critical",
                    row,
                    today_s,
                    detected_at,
                    f"{object_name}: CPA is above the 7-day median band",
                    current_cpa,
                    threshold,
                )
            )

        current_roas = float(row["purchase_roas"] or 0)
        if roas_values and current_roas < statistics.median(roas_values) * ROAS_DROP_MULTIPLIER:
            threshold = statistics.median(roas_values) * ROAS_DROP_MULTIPLIER
            alerts.append(
                _alert(
                    "roas_drop",
                    "warning",
                    row,
                    today_s,
                    detected_at,
                    f"{object_name}: ROAS is below the 7-day median band",
                    current_roas,
                    threshold,
                )
            )

        if spends and spend > statistics.median(spends) * SPEND_PACING_MULTIPLIER:
            threshold = statistics.median(spends) * SPEND_PACING_MULTIPLIER
            alerts.append(
                _alert(
                    "spend_pacing",
                    "warning",
                    row,
                    today_s,
                    detected_at,
                    f"{object_name}: spend is pacing above the recent median",
                    spend,
                    threshold,
                )
            )

    return alerts


def _sync_failure_alerts(
    conn: sqlite3.Connection,
    accounts: dict[str, object],
    detected_at: str,
    today_s: str,
) -> list[Alert]:
    rows = conn.execute(
        """SELECT r.* FROM meta_sync_runs r
           JOIN (
             SELECT ad_account_id, MAX(started_at) AS started_at
             FROM meta_sync_runs
             GROUP BY ad_account_id
           ) latest
           ON latest.ad_account_id=r.ad_account_id
          AND latest.started_at=r.started_at
           WHERE r.status='failed'"""
    ).fetchall()
    alerts = []
    for row in rows:
        if row["ad_account_id"] not in accounts:
            continue
        message = f"{row['ad_account_id']}: latest Meta sync failed"
        if row["error"]:
            message += f" ({row['error'][:160]})"
        alerts.append(
            Alert(
                fingerprint=f"sync_failure:{row['ad_account_id']}:{today_s}",
                alert_type="sync_failure",
                severity="critical",
                ad_account_id=row["ad_account_id"],
                level="account",
                object_id=row["ad_account_id"],
                object_name=row["ad_account_id"],
                message=message,
                metric_value=0,
                threshold=0,
                detected_at=detected_at,
            )
        )
    return alerts


def _history_by_object(rows: list[sqlite3.Row]) -> dict[tuple[str, str], list[sqlite3.Row]]:
    out: dict[tuple[str, str], list[sqlite3.Row]] = {}
    for row in rows:
        out.setdefault((row["ad_account_id"], row["object_id"]), []).append(row)
    return out


def _alert(
    alert_type: str,
    severity: str,
    row: sqlite3.Row,
    date_key: str,
    detected_at: str,
    message: str,
    metric_value: float,
    threshold: float,
) -> Alert:
    fingerprint = (
        f"{alert_type}:{row['ad_account_id']}:{row['level']}:"
        f"{row['object_id']}:{date_key}"
    )
    return Alert(
        fingerprint=fingerprint,
        alert_type=alert_type,
        severity=severity,
        ad_account_id=row["ad_account_id"],
        level=row["level"],
        object_id=row["object_id"],
        object_name=row["object_name"] or row["object_id"],
        message=message,
        metric_value=float(metric_value),
        threshold=float(threshold),
        detected_at=detected_at,
    )


def build_slack_text(alerts: list[Alert]) -> str:
    lines = ["*Meta Ads efficiency alerts*"]
    for alert in alerts[:20]:
        lines.append(
            f"- [{alert.severity}] {alert.message} "
            f"(value={alert.metric_value:.2f}, threshold={alert.threshold:.2f})"
        )
    if len(alerts) > 20:
        lines.append(f"- ...and {len(alerts) - 20} more")
    return "\n".join(lines)


def notify_slack(conn: sqlite3.Connection, alerts: list[Alert]) -> int:
    new_alerts = [a for a in alerts if store.create_alert_event(conn, a)]
    if not new_alerts:
        conn.commit()
        return 0
    text = build_slack_text(new_alerts)
    if not config.SLACK_WEBHOOK_URL:
        print("\n[Meta Ads Alerts] SLACK_WEBHOOK_URL unset; console preview")
        print(text)
        conn.commit()
        return len(new_alerts)

    req = urllib.request.Request(
        config.SLACK_WEBHOOK_URL,
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()
    store.mark_alerts_sent(conn, [a.fingerprint for a in new_alerts])
    conn.commit()
    return len(new_alerts)


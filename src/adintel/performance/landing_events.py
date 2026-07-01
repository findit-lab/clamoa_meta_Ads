"""Durable landing event storage for serverless deployments.

SQLite remains useful locally, but Vercel functions cannot rely on /tmp SQLite
for cross-request persistence. When Upstash Redis env vars are present, this
module stores landing UTM events in a sorted set keyed by capture time.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import urllib.error
import urllib.request
from typing import Any, Iterable

EVENT_PREFIX = "adintel:landing_utm_event:v1:"
EVENT_INDEX = "adintel:landing_utm_events:v1"
MAX_FETCH_IDS = 5000


def enabled() -> bool:
    return bool(_rest_url() and _rest_token())


def record(row: dict[str, Any]) -> bool:
    if not enabled():
        return False
    event_id = _event_id(row)
    score = _score(row.get("captured_at", ""))
    payload = json.dumps(row, ensure_ascii=False, sort_keys=True)
    ok = _command(["SET", f"{EVENT_PREFIX}{event_id}", payload]) is not None
    ok = _command(["ZADD", EVENT_INDEX, score, event_id]) is not None and ok
    return ok


def fetch(start: str, end: str, landing_key: str = "clamoa", limit: int = MAX_FETCH_IDS) -> list[dict[str, Any]]:
    if not enabled():
        return []
    start_score = _date_score(start, end_of_day=False)
    end_score = _date_score(end, end_of_day=True)
    ids = _command(["ZRANGEBYSCORE", EVENT_INDEX, start_score, end_score])
    if not isinstance(ids, list) or not ids:
        return []
    ids = [str(event_id) for event_id in ids[-max(1, int(limit)):]]
    rows: list[dict[str, Any]] = []
    for chunk in _chunks(ids, 100):
        values = _command(["MGET", *[f"{EVENT_PREFIX}{event_id}" for event_id in chunk]])
        if not isinstance(values, list):
            continue
        for raw in values:
            if not isinstance(raw, str) or not raw:
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            if landing_key != "all" and row.get("landing_key") != landing_key:
                continue
            rows.append(row)
    rows.sort(key=lambda row: str(row.get("captured_at", "")))
    return rows


def _command(command: list[Any]) -> Any:
    url = _rest_url()
    token = _rest_token()
    if not url or not token:
        return None
    request = urllib.request.Request(
        url,
        data=json.dumps(command).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"landing event redis command failed: {type(exc).__name__}")
        return None
    return data.get("result") if isinstance(data, dict) else None


def _rest_url() -> str:
    return (
        os.getenv("KV_REST_API_URL")
        or os.getenv("UPSTASH_REDIS_REST_URL")
        or ""
    ).strip().rstrip("/")


def _rest_token() -> str:
    return (
        os.getenv("KV_REST_API_TOKEN")
        or os.getenv("UPSTASH_REDIS_REST_TOKEN")
        or ""
    ).strip()


def _event_id(row: dict[str, Any]) -> str:
    explicit = str(row.get("browser_event_id") or "").strip()
    if explicit:
        return explicit
    digest = hashlib.sha256(
        json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"generated:{digest}"


def _score(value: str) -> int:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        parsed = dt.datetime.now(dt.timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return int(parsed.timestamp() * 1000)


def _date_score(value: str, *, end_of_day: bool) -> int:
    parsed = dt.date.fromisoformat(value)
    timestamp = dt.datetime.combine(
        parsed,
        dt.time.max if end_of_day else dt.time.min,
        tzinfo=dt.timezone.utc,
    )
    return int(timestamp.timestamp() * 1000)


def _chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for idx in range(0, len(values), size):
        yield values[idx:idx + size]

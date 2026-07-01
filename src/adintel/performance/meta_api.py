"""Thin Meta Marketing API Insights client."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import config
from .models import AdCreative
from .normalizer import normalize_account_id


COMMON_FIELDS = [
    "date_start",
    "date_stop",
    "spend",
    "impressions",
    "reach",
    "frequency",
    "clicks",
    "inline_link_clicks",
    "cpc",
    "cpm",
    "ctr",
    "actions",
    "action_values",
    "purchase_roas",
    "cost_per_action_type",
]


LEVEL_FIELDS = {
    "account": ["account_id", "account_name"],
    "campaign": ["campaign_id", "campaign_name"],
    "adset": ["campaign_id", "campaign_name", "adset_id", "adset_name"],
    "ad": [
        "campaign_id",
        "campaign_name",
        "adset_id",
        "adset_name",
        "ad_id",
        "ad_name",
    ],
}


class MetaApiError(RuntimeError):
    pass


def is_access_token_expired(error: str) -> bool:
    text = str(error or "").lower()
    return (
        "session has expired" in text
        or "error validating access token" in text
        or '"code":190' in text
        or "code 190" in text
        or '"error_subcode":463' in text
        or "subcode 463" in text
    )


def friendly_error_message(error: str) -> str:
    if is_access_token_expired(error):
        return (
            "Meta 액세스 토큰이 만료되어 동기화할 수 없습니다. "
            "Vercel의 META_ACCESS_TOKEN을 새 장기 토큰으로 교체한 뒤 다시 Sync를 눌러주세요."
        )
    if "META_ACCESS_TOKEN is required" in str(error or ""):
        return "META_ACCESS_TOKEN 환경변수가 설정되어 있지 않습니다."
    return str(error or "Meta API 요청에 실패했습니다.")


def fields_for_level(level: str) -> list[str]:
    if level not in LEVEL_FIELDS:
        raise ValueError(f"unsupported insight level: {level}")
    return LEVEL_FIELDS[level] + COMMON_FIELDS


class MetaInsightsClient:
    def __init__(
        self,
        access_token: str | None = None,
        api_version: str | None = None,
        timeout: int = 60,
        max_retries: int = 3,
    ):
        self.access_token = access_token or config.META_ACCESS_TOKEN
        self.api_version = api_version or config.META_GRAPH_API_VERSION
        self.timeout = timeout
        self.max_retries = max_retries
        if not self.access_token:
            raise MetaApiError("META_ACCESS_TOKEN is required for Meta Ads Insights sync")

    def fetch_insights(
        self,
        ad_account_id: str,
        level: str,
        since: str,
        until: str,
        fields: list[str] | None = None,
        breakdowns: list[str] | None = None,
        time_increment: int = 1,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        account_id = normalize_account_id(ad_account_id)
        path = f"https://graph.facebook.com/{self.api_version}/act_{account_id}/insights"
        params = {
            "access_token": self.access_token,
            "level": level,
            "fields": ",".join(fields or fields_for_level(level)),
            "time_increment": str(time_increment),
            "time_range": json.dumps({"since": since, "until": until}),
            "limit": str(limit),
        }
        if breakdowns:
            params["breakdowns"] = ",".join(breakdowns)
        url = path + "?" + urllib.parse.urlencode(params)
        rows: list[dict[str, Any]] = []
        while url:
            payload = self._get_json(url)
            rows.extend(payload.get("data") or [])
            url = (payload.get("paging") or {}).get("next")
        return rows

    def fetch_ad_creatives(
        self,
        ad_account_id: str,
        ad_ids: list[str],
        synced_at: str = "",
        chunk_size: int = 50,
    ) -> list[AdCreative]:
        account_id = normalize_account_id(ad_account_id)
        unique_ids = sorted({str(ad_id).strip() for ad_id in ad_ids if str(ad_id).strip()})
        previews: list[AdCreative] = []
        for i in range(0, len(unique_ids), max(1, chunk_size)):
            chunk = unique_ids[i : i + chunk_size]
            params = {
                "access_token": self.access_token,
                "ids": ",".join(chunk),
                "fields": "effective_status,creative{id,thumbnail_url,image_url,url_tags}",
            }
            url = (
                f"https://graph.facebook.com/{self.api_version}/?"
                + urllib.parse.urlencode(params)
            )
            payload = self._get_json(url)
            for ad_id in chunk:
                raw = payload.get(ad_id)
                if not isinstance(raw, dict):
                    continue
                creative = raw.get("creative") if isinstance(raw.get("creative"), dict) else {}
                previews.append(
                    AdCreative(
                        ad_account_id=account_id,
                        ad_id=ad_id,
                        creative_id=str(creative.get("id") or ""),
                        thumbnail_url=str(creative.get("thumbnail_url") or ""),
                        image_url=str(creative.get("image_url") or ""),
                        effective_status=str(raw.get("effective_status") or ""),
                        url_tags=str(creative.get("url_tags") or raw.get("url_tags") or ""),
                        raw_json=json.dumps(raw, ensure_ascii=False, sort_keys=True),
                        synced_at=synced_at,
                    )
                )
        return previews

    def _get_json(self, url: str) -> dict[str, Any]:
        last_error = ""
        for attempt in range(self.max_retries + 1):
            try:
                req = urllib.request.Request(url, headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")
                last_error = f"HTTP {e.code}: {body}"
                if e.code not in {429, 500, 502, 503, 504} or attempt >= self.max_retries:
                    raise MetaApiError(last_error) from e
            except urllib.error.URLError as e:
                last_error = str(e)
                if attempt >= self.max_retries:
                    raise MetaApiError(last_error) from e
            time.sleep(min(2 ** attempt, 30))
        raise MetaApiError(last_error or "Meta API request failed")

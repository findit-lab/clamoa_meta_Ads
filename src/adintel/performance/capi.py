"""Meta Conversions API client for website events."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping

import config


ALLOWED_EVENT_NAMES = {"PageView", "ViewContent", "Lead"}


class MetaCapiError(RuntimeError):
    pass


def build_event_payload(
    *,
    event_name: str,
    event_id: str,
    event_source_url: str,
    client_ip_address: str = "",
    client_user_agent: str = "",
    fbp: str = "",
    fbc: str = "",
    custom_data: Mapping[str, Any] | None = None,
    event_time: int | None = None,
) -> dict[str, Any]:
    if event_name not in ALLOWED_EVENT_NAMES:
        raise MetaCapiError(f"unsupported Meta CAPI event: {event_name}")

    user_data = _clean_dict(
        {
            "client_ip_address": client_ip_address,
            "client_user_agent": client_user_agent,
            "fbp": fbp,
            "fbc": fbc,
        }
    )
    event = _clean_dict(
        {
            "event_name": event_name,
            "event_time": int(event_time or time.time()),
            "event_id": event_id,
            "action_source": "website",
            "event_source_url": event_source_url,
            "user_data": user_data,
            "custom_data": _clean_dict(dict(custom_data or {})),
        }
    )
    return event


class MetaConversionsClient:
    def __init__(
        self,
        pixel_id: str | None = None,
        access_token: str | None = None,
        api_version: str | None = None,
        timeout: int | None = None,
        test_event_code: str | None = None,
    ):
        self.pixel_id = pixel_id or config.META_PIXEL_ID
        self.access_token = access_token or config.META_CAPI_ACCESS_TOKEN
        self.api_version = api_version or config.META_GRAPH_API_VERSION
        self.timeout = timeout or config.META_CAPI_TIMEOUT_SECONDS
        self.test_event_code = test_event_code or config.META_CAPI_TEST_EVENT_CODE
        if not self.pixel_id:
            raise MetaCapiError("CLAMOA_META_PIXEL_ID or META_PIXEL_ID is required")
        if not self.access_token:
            raise MetaCapiError("META_CAPI_ACCESS_TOKEN is required")

    def send_event(self, event: Mapping[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {"data": [dict(event)]}
        if self.test_event_code:
            payload["test_event_code"] = self.test_event_code

        params = urllib.parse.urlencode({"access_token": self.access_token})
        url = f"https://graph.facebook.com/{self.api_version}/{self.pixel_id}/events?{params}"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise MetaCapiError(f"HTTP {e.code}: {body}") from e
        except urllib.error.URLError as e:
            raise MetaCapiError(str(e)) from e


def _clean_dict(values: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in values.items()
        if value not in ("", None, {}, [])
    }

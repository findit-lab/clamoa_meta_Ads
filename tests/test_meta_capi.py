import json
import urllib.request

import pytest

from adintel.performance.capi import (
    MetaCapiError,
    MetaConversionsClient,
    build_event_payload,
)


def test_build_event_payload_for_website_event():
    event = build_event_payload(
        event_name="Lead",
        event_id="lead-123",
        event_source_url="https://asinayo.example/#waitlist",
        client_ip_address="203.0.113.10",
        client_user_agent="pytest",
        fbp="fb.1.123.456",
        fbc="fb.1.123.fbclid",
        custom_data={"content_name": "asinayo_waitlist", "empty": ""},
        event_time=1_780_000_000,
    )

    assert event["event_name"] == "Lead"
    assert event["event_id"] == "lead-123"
    assert event["action_source"] == "website"
    assert event["user_data"]["client_user_agent"] == "pytest"
    assert event["custom_data"] == {"content_name": "asinayo_waitlist"}


def test_build_event_payload_rejects_unsupported_event():
    with pytest.raises(MetaCapiError):
        build_event_payload(
            event_name="Purchase",
            event_id="purchase-123",
            event_source_url="https://asinayo.example/",
        )


def test_meta_conversions_client_posts_expected_payload(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"events_received": 1, "fbtrace_id": "trace"}'

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    client = MetaConversionsClient(
        pixel_id="123456",
        access_token="token",
        api_version="v25.0",
        timeout=5,
        test_event_code="TEST123",
    )
    response = client.send_event({"event_name": "PageView", "event_time": 1})

    assert response["events_received"] == 1
    assert "123456/events" in captured["url"]
    assert "access_token=token" in captured["url"]
    assert captured["timeout"] == 5
    assert captured["body"]["test_event_code"] == "TEST123"
    assert captured["body"]["data"] == [{"event_name": "PageView", "event_time": 1}]

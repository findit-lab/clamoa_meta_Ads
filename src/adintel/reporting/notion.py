"""C7 — Notion DB 리포터. 기획서 v2 §C7/§C8.

위너 컨셉 1개 = 1 row. 노션 DB 스키마(컨셉/상태/카테고리/Offer/Hook/Angle/CTA/
Format/Lift/광고주 수/최대 관측일/멤버 수/표본 수/신뢰도/대표 이미지/광고 라이브러리/
광고주 페이지/Cluster ID/발견일)에 맞춰 적재한다.

NOTION_TOKEN(인테그레이션) + NOTION_DATABASE_ID 있을 때만 실 기록, 없으면 콘솔 미리보기.
표준 라이브러리 urllib만 사용. 인테그레이션은 해당 DB에 연결(공유)돼 있어야 한다.
"""
from __future__ import annotations

import datetime as dt
import json
import urllib.request

import config

_NOTION_API = "https://api.notion.com/v1/pages"
_NOTION_VERSION = "2022-06-28"


def _enabled() -> bool:
    return bool(config.NOTION_TOKEN and config.NOTION_DATABASE_ID)


def report_winners(winners: list[dict], patterns: list) -> None:
    """위너 컨셉 목록을 Notion DB에 적재(또는 콘솔 미리보기)."""
    if not _enabled():
        print("\n[Notion] 토큰/DB 미설정 → 콘솔 미리보기")
        for w in winners:
            print(f"  • #{w['cluster_id']} {w.get('headline','') or '(제목없음)'} | "
                  f"{w.get('offer_type','')}/{w.get('hook_type','')} | lift {w.get('lift',0)} | "
                  f"광고주 {w['advertiser_count']} | 최대 {w['max_observed_days']}일 | {w.get('confidence','')}")
        return

    ok = 0
    for w in winners:
        try:
            _create_page(w)
            ok += 1
        except Exception as e:
            print(f"  [Notion] 행 적재 실패 (#{w.get('cluster_id')}): {e}")
    print(f"[Notion] {ok}/{len(winners)}개 위너 컨셉 적재 완료")


def _select(value: str | None):
    return {"select": {"name": value}} if value else {"select": None}


def _number(value):
    return {"number": value if value is not None else None}


def _url(value: str | None):
    return {"url": value or None}


def _build_properties(w: dict) -> dict:
    title = w.get("headline") or f"Concept cluster #{w['cluster_id']}"
    return {
        "컨셉": {"title": [{"text": {"content": title[:200]}}]},
        "상태": _select("신규"),
        "카테고리": _select(w.get("category")),
        "Offer": _select(w.get("offer_type")),
        "Hook": _select(w.get("hook_type")),
        "Angle": _select(w.get("angle")),
        "CTA": _select(w.get("cta_button")),
        "Format": _select(w.get("format")),
        "Lift": _number(w.get("lift")),
        "광고주 수": _number(w.get("advertiser_count")),
        "최대 관측일": _number(w.get("max_observed_days")),
        "멤버 수": _number(w.get("member_count")),
        "신뢰도": _select(w.get("confidence")),
        "대표 이미지": _url(w.get("media_path") if str(w.get("media_path", "")).startswith("http") else None),
        "광고 라이브러리": _url(w.get("ad_library_url")),
        "광고주 페이지": {"rich_text": [{"text": {"content": str(w.get("page_name") or w.get("page_id") or "")}}]},
        "Cluster ID": _number(w.get("cluster_id")),
        "발견일": {"date": {"start": dt.date.today().isoformat()}},
    }


def _create_page(w: dict) -> None:
    payload = {
        "parent": {"database_id": config.NOTION_DATABASE_ID},
        "properties": _build_properties(w),
    }
    req = urllib.request.Request(
        _NOTION_API,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.NOTION_TOKEN}",
            "Content-Type": "application/json",
            "Notion-Version": _NOTION_VERSION,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()

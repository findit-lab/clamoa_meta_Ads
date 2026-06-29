"""C7 — 노션 '광고 추적 DB'(per-ad) 리포터. 첨부 이미지 스키마 대응.

ads 상태 테이블 1행 = 노션 1행. 밴딩/광고주tier/위너점수를 계산해 적재한다.

위너점수 공식(청월당 예시 재현: 217일·50변형·mid = 4.5):
  score = longevity_comp(0~3) + variant_comp(0~1) + tier_comp(0~1)

NOTION_TOKEN + NOTION_ADS_DATABASE_ID 있을 때 REST 적재, 없으면 콘솔 미리보기.
build_rows()는 노션 비종속 dict를 반환하므로 MCP 적재/검증에도 재사용 가능.
"""
from __future__ import annotations

import datetime as dt
import json
import mimetypes
import sqlite3
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import config

_NOTION_API = "https://api.notion.com/v1/pages"
_NOTION_VERSION = "2022-06-28"
_NOTION_UPLOAD_VERSION = "2026-03-11"

GEN_STATUS_WAITING = "대기"
GEN_STATUS_REQUESTED = "생성요청"
GEN_STATUS_RUNNING = "생성중"
GEN_STATUS_DONE = "완료"
GEN_STATUS_ERROR = "오류"
GEN_STATUS_SKIPPED = "스킵"
GEN_STATUS_VALUES = (
    GEN_STATUS_WAITING,
    GEN_STATUS_REQUESTED,
    GEN_STATUS_RUNNING,
    GEN_STATUS_DONE,
    GEN_STATUS_ERROR,
    GEN_STATUS_SKIPPED,
)


@dataclass
class CreativeRequest:
    page_id: str
    ad_id: str
    media_type: str = ""
    media_url: str = ""
    brief: str = ""
    status: str = ""


# ── 파생 계산 ───────────────────────────────────────────────────────
def band_longevity(days: int) -> str:
    if days >= 90:
        return "90일+"
    if days >= 60:
        return "60–90일"
    if days >= 30:
        return "30–60일"
    if days >= 14:
        return "14–30일"
    return "14일 미만"


def advertiser_tier(active_count: int) -> str:
    if active_count >= 100:
        return "top"
    if active_count >= 40:
        return "high"
    if active_count >= 10:
        return "mid"
    return "low"


_LONGEVITY_COMP = [(90, 3.0), (60, 2.4), (30, 1.8), (14, 1.0), (0, 0.4)]
_TIER_COMP = {"top": 1.0, "high": 0.7, "mid": 0.5, "low": 0.2}


def winner_score(days: int, variant_count: int, tier: str) -> float:
    longevity = next(c for thr, c in _LONGEVITY_COMP if days >= thr)
    variant = min((variant_count or 0) / 50.0, 1.0)
    return round(longevity + variant + _TIER_COMP.get(tier, 0.2), 1)


def is_winner_candidate(days: int, variant_count: int) -> bool:
    """위너 후보 게이트(OR): 오래 돌리거나(longevity 검증) 변형이 많으면(성공 공식) 후보.

    - 게재일수 ≥ WINNER_MIN_DAYS: 광고주가 오래 유지 → 효율 검증된 소재일 확률.
    - 변형수 ≥ WINNER_MIN_VARIANTS: 유사 컨셉을 여러 버전으로 운영 → 브랜드 성공 공식.
    둘 다 미달이면 노션에 적재하지 않는다.
    """
    return (days >= config.WINNER_MIN_DAYS) or ((variant_count or 0) >= config.WINNER_MIN_VARIANTS)


def op_mode(display_format: str) -> str:
    df = (display_format or "").upper()
    if df == "DCO":
        return "DCO"
    if df in ("IMAGE", "VIDEO", "SINGLE"):
        return "단일"
    return "기타"


def _days_running(fb_start: str, ref: str, observed_days: int) -> int:
    """게재일수 = 기준일 − FB시작일. FB시작일 없으면 관측 longevity로 폴백."""
    if fb_start:
        try:
            return max(0, (dt.date.fromisoformat(ref) - dt.date.fromisoformat(fb_start[:10])).days)
        except Exception:
            pass
    return observed_days or 0


# ── 행 생성 (노션 비종속) ───────────────────────────────────────────
def build_rows(conn: sqlite3.Connection, active_only: bool = False,
               ref_date: str | None = None, winners_only: bool = True) -> list[dict]:
    """ads → 노션 행. winners_only=True(기본)이면 위너 후보 게이트 미통과 광고는 제외.

    게이트는 is_winner_candidate(게재일수, 변형수)로 판정한다(OR 로직). 노션 '광고 추적
    DB'는 위너 후보만 아카이브하는 것이 설계이므로 기본값을 True로 둔다. 전체 광고를
    보려면 winners_only=False.
    """
    ref = ref_date or dt.date.today().isoformat()

    # 페이지별 활성 광고 수 → 광고주tier.
    tier_by_page = {}
    for r in conn.execute(
        "SELECT page_id, COUNT(*) n FROM ads WHERE status='active' GROUP BY page_id"
    ).fetchall():
        tier_by_page[r["page_id"]] = advertiser_tier(r["n"])

    names = {r["page_id"]: r["page_name"]
             for r in conn.execute("SELECT page_id, page_name FROM target_pages").fetchall()}

    q = "SELECT * FROM ads" + (" WHERE status='active'" if active_only else "")
    rows = []
    for a in conn.execute(q).fetchall():
        days = _days_running(a["fb_start_date"], ref, a["observed_active_days"])
        if winners_only and not is_winner_candidate(days, a["variant_count"]):
            continue
        tier = tier_by_page.get(a["page_id"], "low")
        rows.append({
            "광고주": names.get(a["page_id"], a["page_id"]),
            "Longevity밴드": band_longevity(days),
            "검토상태": "신규",
            "게재상태": "활성" if a["status"] == "active" else "종료",
            "게재일수": days,
            "광고ID": a["ad_archive_id"],
            "광고링크": f"https://www.facebook.com/ads/library/?id={a['ad_archive_id']}",
            "광고주tier": tier,
            "라이브러리시작일": a["fb_start_date"] or "",
            "미디어링크": a["media_url"] or "",
            "미디어타입": a["media_type"] or "unknown",
            "변형수": a["variant_count"] or 0,
            "운영모드": op_mode(a["display_format"]),
            "위너점수": winner_score(days, a["variant_count"], tier),
            "최종관측일": a["last_seen_active"],
            "최초관측일": a["first_seen"],
            "카피발췌": (a["ad_copy"] or a["headline"] or "")[:200],
            "타깃": a["targeting"] or "",
        })
    return rows


# ── REST 적재 ───────────────────────────────────────────────────────
def _enabled() -> bool:
    return bool(config.NOTION_TOKEN and config.NOTION_ADS_DATABASE_ID)


def _props(row: dict) -> dict:
    def sel(v):
        return {"select": {"name": v}} if v else {"select": None}

    def num(v):
        return {"number": v if v is not None else None}

    def url(v):
        return {"url": v or None}

    def date(v):
        return {"date": {"start": v}} if v else {"date": None}

    return {
        "광고주": {"title": [{"text": {"content": str(row["광고주"])[:200]}}]},
        "Longevity밴드": sel(row["Longevity밴드"]),
        "검토상태": sel(row["검토상태"]),
        "게재상태": sel(row["게재상태"]),
        "게재일수": num(row["게재일수"]),
        "광고ID": {"rich_text": [{"text": {"content": str(row["광고ID"])}}]},
        "광고링크": url(row["광고링크"]),
        "광고주tier": sel(row["광고주tier"]),
        "라이브러리시작일": date(row["라이브러리시작일"]),
        "미디어링크": url(row["미디어링크"] if str(row["미디어링크"]).startswith("http") else None),
        "미디어타입": sel(row["미디어타입"]),
        "변형수": num(row["변형수"]),
        "운영모드": sel(row["운영모드"]),
        "위너점수": num(row["위너점수"]),
        "최종관측일": date(row["최종관측일"]),
        "최초관측일": date(row["최초관측일"]),
        "카피발췌": {"rich_text": [{"text": {"content": row["카피발췌"]}}]},
        "타깃": {"rich_text": [{"text": {"content": row["타깃"]}}]},
    }


# 사람이 노션에서 직접 관리하는 컬럼 — upsert 갱신 시 덮어쓰지 않는다(휴먼 게이트 보존).
_HUMAN_OWNED = ("검토상태",)


def report_ads(conn: sqlite3.Connection, active_only: bool = False,
               limit: int | None = None, upsert: bool = True,
               winners_only: bool = True) -> None:
    """광고 추적 DB 적재.

    winners_only=True(기본): 위너 후보 게이트 통과 광고만 적재(설계상 기본). False면 전체.
    upsert=True(기본): 광고ID 기준으로 기존 행은 갱신, 없으면 생성 → 매일 재실행해도
      중복이 생기지 않는다. 사람이 설정한 검토상태(_HUMAN_OWNED)는 보존한다.
    upsert=False: 무조건 새 행 생성(과거 동작).
    """
    rows = build_rows(conn, active_only=active_only, winners_only=winners_only)
    if winners_only:
        total = len(build_rows(conn, active_only=active_only, winners_only=False))
        print(f"[Notion 광고추적] 위너 후보 게이트(게재 ≥{config.WINNER_MIN_DAYS}일 OR "
              f"변형 ≥{config.WINNER_MIN_VARIANTS}개): {len(rows)}/{total}건 통과")
    if limit:
        rows = rows[:limit]

    if not _enabled():
        print(f"\n[Notion 광고추적] 토큰/DB 미설정 → 콘솔 미리보기 ({len(rows)}행)")
        for r in rows[:10]:
            print(f"  {r['광고주']} | {r['광고ID']} | {r['Longevity밴드']} | 게재 {r['게재일수']}일 "
                  f"| {r['미디어타입']} | 변형 {r['변형수']} | {r['광고주tier']} | 점수 {r['위너점수']}")
        return

    if not upsert:
        ok = 0
        for r in rows:
            try:
                _create_page(r)
                ok += 1
            except Exception as e:
                print(f"  [Notion 광고추적] 적재 실패 ({r['광고ID']}): {e}")
        print(f"[Notion 광고추적] {ok}/{len(rows)}행 생성 완료")
        return

    existing = _existing_pages()  # 광고ID → page_id
    created = updated = failed = 0
    for r in rows:
        try:
            page_id = existing.get(str(r["광고ID"]))
            if page_id:
                _update_page(page_id, r)
                updated += 1
            else:
                _create_page(r)
                created += 1
        except Exception as e:
            failed += 1
            print(f"  [Notion 광고추적] 실패 ({r['광고ID']}): {e}")
    msg = f"[Notion 광고추적] upsert 완료 — 신규 {created} / 갱신 {updated} / 총 {len(rows)}"
    if failed:
        msg += f" / 실패 {failed}"
    print(msg)


# ── REST 저수준 ─────────────────────────────────────────────────────
def _headers(notion_version: str | None = None,
             content_type: str | None = "application/json") -> dict:
    headers = {
        "Authorization": f"Bearer {config.NOTION_TOKEN}",
        "Notion-Version": notion_version or _NOTION_VERSION,
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _api(url: str, payload: dict | None = None, method: str = "POST",
         notion_version: str | None = None) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=data, headers=_headers(notion_version=notion_version), method=method
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode()
    return json.loads(body) if body else {}


def _plain_text(prop: dict) -> str:
    chunks = prop.get("rich_text") or prop.get("title") or []
    return "".join(c.get("plain_text", "") for c in chunks).strip()


def _select_name(prop: dict) -> str:
    return ((prop.get("select") or {}).get("name") or "").strip()


def _url_value(prop: dict) -> str:
    return (prop.get("url") or "").strip()


def _rich_text(value: str) -> dict:
    return {"rich_text": [{"text": {"content": str(value or "")[:2000]}}]}


def _date_value(value: str) -> dict:
    return {"date": {"start": value}} if value else {"date": None}


def _creative_status_props(
    status: str,
    *,
    prompt: str | None = None,
    model: str | None = None,
    error: str | None = None,
    generated_at: str | None = None,
    file_upload_id: str | None = None,
    filename: str | None = None,
) -> dict:
    if status not in GEN_STATUS_VALUES:
        raise ValueError(f"unknown generation status: {status}")
    props = {"제작상태": {"select": {"name": status}}}
    if prompt is not None:
        props["생성프롬프트"] = _rich_text(prompt)
    if model is not None:
        props["생성모델"] = _rich_text(model)
    if error is not None:
        props["생성오류"] = _rich_text(error)
    if generated_at is not None:
        props["생성일시"] = _date_value(generated_at)
    if file_upload_id:
        props["생성결과"] = {
            "files": [
                {
                    "name": filename or "generated.png",
                    "type": "file_upload",
                    "file_upload": {"id": file_upload_id},
                }
            ]
        }
    return props


def _query_ads_database(filter_payload: dict | None = None,
                        limit: int | None = None) -> list[dict]:
    if not _enabled():
        return []
    out: list[dict] = []
    url = f"https://api.notion.com/v1/databases/{config.NOTION_ADS_DATABASE_ID}/query"
    cursor = None
    while True:
        page_size = min(100, max(1, (limit - len(out)) if limit else 100))
        payload: dict = {"page_size": page_size}
        if filter_payload:
            payload["filter"] = filter_payload
        if cursor:
            payload["start_cursor"] = cursor
        res = _api(url, payload)
        out.extend(res.get("results", []))
        if limit and len(out) >= limit:
            return out[:limit]
        if not res.get("has_more"):
            return out
        cursor = res.get("next_cursor")


def _page_to_ad_row(page: dict) -> dict:
    props = page.get("properties", {})
    return {
        "page_id": page.get("id", ""),
        "광고ID": _plain_text(props.get("광고ID", {}) or {}),
        "미디어링크": _url_value(props.get("미디어링크", {}) or {}),
        "미디어타입": _select_name(props.get("미디어타입", {}) or {}),
        "제작상태": _select_name(props.get("제작상태", {}) or {}),
        "제작브리프": _plain_text(props.get("제작브리프", {}) or {}),
        "카피발췌": _plain_text(props.get("카피발췌", {}) or {}),
    }


def fetch_ad_rows(limit: int | None = None) -> list[dict]:
    """노션 광고 추적 DB 행을 감사 가능한 dict로 조회."""
    return [_page_to_ad_row(p) for p in _query_ads_database(limit=limit)]


def pending_creative_requests(limit: int | None = None) -> list[CreativeRequest]:
    """Notion `제작상태=생성요청` 행을 이미지 생성 큐로 반환."""
    pages = _query_ads_database(
        {
            "property": "제작상태",
            "select": {"equals": GEN_STATUS_REQUESTED},
        },
        limit=limit,
    )
    requests: list[CreativeRequest] = []
    for page in pages:
        row = _page_to_ad_row(page)
        if not row["광고ID"]:
            continue
        requests.append(
            CreativeRequest(
                page_id=row["page_id"],
                ad_id=row["광고ID"],
                media_type=row["미디어타입"],
                media_url=row["미디어링크"],
                brief=row["제작브리프"] or row["카피발췌"],
                status=row["제작상태"],
            )
        )
    return requests


def update_creative_status(
    page_id: str,
    status: str,
    *,
    prompt: str | None = None,
    model: str | None = None,
    error: str | None = None,
    generated_at: str | None = None,
    file_upload_id: str | None = None,
    filename: str | None = None,
) -> None:
    """제작상태/생성 메타데이터를 Notion 페이지에 반영."""
    props = _creative_status_props(
        status,
        prompt=prompt,
        model=model,
        error=error,
        generated_at=generated_at,
        file_upload_id=file_upload_id,
        filename=filename,
    )
    _api(
        f"https://api.notion.com/v1/pages/{page_id}",
        {"properties": props},
        method="PATCH",
        notion_version=_NOTION_UPLOAD_VERSION if file_upload_id else None,
    )


def _multipart_file_body(path: Path, boundary: str) -> tuple[bytes, str]:
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8")
    footer = f"\r\n--{boundary}--\r\n".encode("utf-8")
    return header + path.read_bytes() + footer, content_type


def upload_file(path: str | Path) -> str:
    """Notion Direct Upload로 파일을 올리고 file_upload id를 반환."""
    if not _enabled():
        raise RuntimeError("NOTION_TOKEN/NOTION_ADS_DATABASE_ID 미설정")
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        raise FileNotFoundError(str(p))

    created = _api(
        "https://api.notion.com/v1/file_uploads",
        {},
        notion_version=_NOTION_UPLOAD_VERSION,
    )
    file_upload_id = created["id"]
    upload_url = created.get("upload_url") or (
        f"https://api.notion.com/v1/file_uploads/{file_upload_id}/send"
    )

    boundary = f"----adintel-{uuid4().hex}"
    body, _ = _multipart_file_body(p, boundary)
    headers = _headers(
        notion_version=_NOTION_UPLOAD_VERSION,
        content_type=f"multipart/form-data; boundary={boundary}",
    )
    req = urllib.request.Request(upload_url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        uploaded = json.loads(resp.read().decode())
    if uploaded.get("status") != "uploaded":
        raise RuntimeError(f"Notion file upload failed: {uploaded}")
    return file_upload_id


def attach_generation_result(page_id: str, path: str | Path,
                             *, prompt: str, model: str,
                             generated_at: str | None = None) -> str:
    """생성 이미지를 Notion에 업로드하고 `생성결과` 파일 속성에 첨부."""
    p = Path(path)
    upload_id = upload_file(p)
    update_creative_status(
        page_id,
        GEN_STATUS_DONE,
        prompt=prompt,
        model=model,
        error="",
        generated_at=generated_at or dt.datetime.now(dt.timezone.utc).isoformat(),
        file_upload_id=upload_id,
        filename=p.name,
    )
    return upload_id


def _existing_pages() -> dict:
    """광고 추적 DB의 광고ID → page_id 맵(페이지네이션 전체 조회).

    [샘플]행 등 다른 광고ID는 자연히 별개 키라 영향 없음.
    """
    out: dict[str, str] = {}
    url = f"https://api.notion.com/v1/databases/{config.NOTION_ADS_DATABASE_ID}/query"
    cursor = None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        res = _api(url, payload)
        for p in res.get("results", []):
            rt = (p.get("properties", {}).get("광고ID", {}) or {}).get("rich_text", [])
            if rt:
                out[rt[0].get("plain_text", "")] = p["id"]
        if not res.get("has_more"):
            break
        cursor = res.get("next_cursor")
    return out


def _existing_pages_detailed() -> dict:
    """광고ID → {page_id, review} 맵. 검토상태까지 포함(reconcile용)."""
    out: dict[str, dict] = {}
    url = f"https://api.notion.com/v1/databases/{config.NOTION_ADS_DATABASE_ID}/query"
    cursor = None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        res = _api(url, payload)
        for p in res.get("results", []):
            props = p.get("properties", {})
            rt = (props.get("광고ID", {}) or {}).get("rich_text", [])
            if not rt:
                continue
            review = ((props.get("검토상태", {}) or {}).get("select") or {}).get("name", "")
            out[rt[0].get("plain_text", "")] = {"page_id": p["id"], "review": review}
        if not res.get("has_more"):
            break
        cursor = res.get("next_cursor")
    return out


def _set_review(page_id: str, value: str) -> None:
    _api(f"https://api.notion.com/v1/pages/{page_id}",
         {"properties": {"검토상태": {"select": {"name": value}}}}, method="PATCH")


def _archive_page(page_id: str) -> None:
    _api(f"https://api.notion.com/v1/pages/{page_id}", {"archived": True}, method="PATCH")


def winner_fail_ids(conn: sqlite3.Connection, ref_date: str | None = None) -> set[str]:
    """로컬 ads 테이블에서 위너 게이트를 통과하지 못하는 광고ID 집합(순수 계산)."""
    ref = ref_date or dt.date.today().isoformat()
    fail: set[str] = set()
    for a in conn.execute(
        "SELECT ad_archive_id, fb_start_date, observed_active_days, variant_count FROM ads"
    ).fetchall():
        days = _days_running(a["fb_start_date"], ref, a["observed_active_days"])
        if not is_winner_candidate(days, a["variant_count"]):
            fail.add(a["ad_archive_id"])
    return fail


# reconcile 시 보존할 검토상태 — 사람이 손댄 행은 자동 정리하지 않는다.
_RECONCILE_SKIP_REVIEW = ("검토중", "채택", "기각")


def reconcile_winners(conn: sqlite3.Connection, mode: str = "mark",
                      apply: bool = False, ref_date: str | None = None) -> dict:
    """이미 노션에 적재된 행 중 현재 위너 게이트 미통과 광고를 정리.

    대상 = (로컬 게이트 미통과) ∩ (노션 적재됨) ∩ (검토상태='신규' 또는 빈값).
      사람이 검토중/채택/기각으로 바꾼 행은 보존(휴먼 게이트). 로컬에 없는 [샘플] 행은 제외.
    mode='mark'(기본): 검토상태='기각' 마킹(되돌릴 수 있음).
    mode='archive': 노션 페이지를 휴지통으로 보관(삭제, 복구 가능).
    apply=False(기본): dry-run — 대상만 집계/출력하고 변경하지 않는다.
    반환: {'targets': [광고ID...], 'skipped_human': n, 'done': n, 'failed': n}.
    """
    fail = winner_fail_ids(conn, ref_date=ref_date)
    summary = {"targets": [], "skipped_human": 0, "done": 0, "failed": 0}

    if not _enabled():
        print(f"[reconcile] 토큰/DB 미설정 → 로컬 게이트 미통과 {len(fail)}건(노션 조회 불가)")
        return summary

    existing = _existing_pages_detailed()  # 광고ID → {page_id, review}
    targets = []  # (광고ID, page_id)
    for ad_id, info in existing.items():
        if ad_id not in fail:
            continue
        if info["review"] in _RECONCILE_SKIP_REVIEW:
            summary["skipped_human"] += 1
            continue
        targets.append((ad_id, info["page_id"]))
    summary["targets"] = [t[0] for t in targets]

    action = "기각 마킹" if mode == "mark" else "아카이브(휴지통 이동)"
    head = (f"[reconcile] 게이트 미통과 & 노션 적재 & 검토상태=신규 → {action} 대상 {len(targets)}건")
    if summary["skipped_human"]:
        head += f" / 사람이 검토상태 변경해 보존 {summary['skipped_human']}건"
    print(head)

    if not apply:
        for ad_id in summary["targets"][:20]:
            print(f"    (dry-run) {ad_id}")
        if len(targets) > 20:
            print(f"    … 외 {len(targets) - 20}건")
        print("  실제 적용하려면 --apply 를 주세요.")
        return summary

    for ad_id, page_id in targets:
        try:
            if mode == "mark":
                _set_review(page_id, "기각")
            else:
                _archive_page(page_id)
            summary["done"] += 1
        except Exception as e:
            summary["failed"] += 1
            print(f"  실패 ({ad_id}): {e}")
    msg = f"[reconcile] 완료 — {action} {summary['done']}/{len(targets)}"
    if summary["failed"]:
        msg += f" / 실패 {summary['failed']}"
    print(msg)
    return summary


def _create_page(row: dict) -> None:
    _api(_NOTION_API, {
        "parent": {"database_id": config.NOTION_ADS_DATABASE_ID},
        "properties": _props(row),
    })


def _update_page(page_id: str, row: dict) -> None:
    props = _props(row)
    for k in _HUMAN_OWNED:
        props.pop(k, None)  # 사람이 설정한 값 보존
    _api(f"https://api.notion.com/v1/pages/{page_id}", {"properties": props}, method="PATCH")

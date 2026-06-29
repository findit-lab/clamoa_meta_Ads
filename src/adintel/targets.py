"""C1 — 타겟 광고주 레지스트리 CRUD + 경쟁사 URL/핸들 파싱. 기획서 v2 §C1.

경쟁사는 숫자 page_id를 몰라도 Facebook 페이지 URL/핸들만으로 등록 가능.
액터(curious_coder/facebook-ads-library-scraper)가 페이지 URL을 직접 받기 때문.
"""
from __future__ import annotations

import re
import sqlite3
import urllib.parse

from .models import TargetPage

# facebook.com 경로 중 페이지 핸들이 아닌 예약어 (잘못 핸들로 잡지 않도록).
_RESERVED = {"ads", "profile.php", "people", "pages", "groups", "watch", "marketplace"}


def parse_competitor(raw: str) -> tuple[str, str]:
    """경쟁사 입력(URL/핸들/숫자 ID) → (레지스트리 page_id 키, page_url).

    지원 형태:
      - "https://www.facebook.com/ZapierApp"            → ("ZapierApp", 그 URL)
      - "ZapierApp" 또는 "@ZapierApp"                    → ("ZapierApp", 페이지 URL)
      - "https://www.facebook.com/ads/library/?...view_all_page_id=123" → ("123", 그 URL)
      - "123456789" (숫자만)                              → ("123456789", "")  # 수집기가 view_all_page_id URL 생성
    """
    s = raw.strip()
    if not s:
        raise ValueError("빈 입력")

    # Ad Library URL: view_all_page_id = 페이지(추적 가능), id = 단일 광고(추적 불가).
    if "facebook.com/ads/library" in s:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(s).query)
        if qs.get("view_all_page_id"):
            pid = qs["view_all_page_id"][0]
            return (pid, s)
        if qs.get("id"):
            raise ValueError(
                "단일 광고 URL입니다 (id=광고 아카이브 ID, 페이지가 아님). "
                "광고주 페이지를 추적하려면 먼저 `python scripts/discover_page.py "
                f"--id {qs['id'][0]}` 로 page_id를 찾으세요."
            )
        # 키워드 검색 URL 등은 URL 그대로 사용.
        return (s, s)

    # 일반 페이지 URL → 첫 경로 세그먼트를 핸들로.
    if s.startswith("http"):
        path = urllib.parse.urlparse(s).path.strip("/")
        handle = path.split("/")[0] if path else ""
        if handle and handle not in _RESERVED:
            return (handle, f"https://www.facebook.com/{handle}")
        return (s, s)  # 예약어 경로 등은 URL 그대로 사용

    # 순수 숫자 → page_id (URL은 수집기가 view_all_page_id 로 생성)
    if s.isdigit():
        return (s, "")

    # 핸들 (@ 제거)
    handle = s.lstrip("@")
    if re.fullmatch(r"[A-Za-z0-9_.-]+", handle):
        return (handle, f"https://www.facebook.com/{handle}")

    raise ValueError(f"인식 불가한 경쟁사 입력: {raw!r}")


def upsert_target(conn: sqlite3.Connection, t: TargetPage) -> None:
    conn.execute(
        """
        INSERT INTO target_pages (page_id, page_name, category, page_url, active, added_at, note)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(page_id) DO UPDATE SET
            page_name=excluded.page_name,
            category=excluded.category,
            page_url=excluded.page_url,
            active=excluded.active,
            note=excluded.note
        """,
        (t.page_id, t.page_name, t.category, t.page_url, int(t.active), t.added_at, t.note),
    )
    conn.commit()


def list_active(conn: sqlite3.Connection) -> list[TargetPage]:
    rows = conn.execute(
        "SELECT * FROM target_pages WHERE active=1 ORDER BY page_id"
    ).fetchall()
    return [_row_to_target(r) for r in rows]


def list_all(conn: sqlite3.Connection) -> list[TargetPage]:
    rows = conn.execute("SELECT * FROM target_pages ORDER BY page_id").fetchall()
    return [_row_to_target(r) for r in rows]


def deactivate(conn: sqlite3.Connection, page_id: str) -> None:
    conn.execute("UPDATE target_pages SET active=0 WHERE page_id=?", (page_id,))
    conn.commit()


def purge_by_note(conn: sqlite3.Connection, note: str) -> int:
    """특정 note(예: 'seed') 타겟을 삭제. 반환: 삭제 건수."""
    cur = conn.execute("DELETE FROM target_pages WHERE note=?", (note,))
    conn.commit()
    return cur.rowcount


def _row_to_target(r: sqlite3.Row) -> TargetPage:
    keys = r.keys()
    return TargetPage(
        page_id=r["page_id"],
        page_name=r["page_name"],
        category=r["category"],
        page_url=r["page_url"] if "page_url" in keys else "",
        active=bool(r["active"]),
        added_at=r["added_at"],
        note=r["note"],
    )

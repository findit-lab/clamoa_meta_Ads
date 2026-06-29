"""미디어 링크/타입 품질 점검.

DB 행, export row, Notion row를 같은 규칙으로 검사한다. Notion row는 광고 제작
요청(`제작상태=생성요청`)까지 포함할 수 있으므로 이미지 생성 대상 검증도 여기서 한다.
"""
from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from typing import Iterable, Mapping, Any


VALID_MEDIA_TYPES = {"image", "video"}
GENERATION_REQUESTED = "생성요청"


@dataclass
class MediaIssue:
    source: str
    ad_id: str
    field: str
    value: str
    message: str
    severity: str = "error"

    def to_dict(self) -> dict:
        return asdict(self)


def _row_dict(row: Mapping[str, Any] | sqlite3.Row) -> dict:
    if isinstance(row, sqlite3.Row):
        return {k: row[k] for k in row.keys()}
    return dict(row)


def _first(row: dict, *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None:
            return str(value).strip()
    return ""


def audit_rows(rows: Iterable[Mapping[str, Any] | sqlite3.Row],
               source: str = "rows") -> list[MediaIssue]:
    """행 목록을 미디어 규칙으로 검사한다.

    지원 키:
      - DB: ad_archive_id, media_url, media_type
      - export/Notion: 광고ID, 미디어링크, 미디어타입, 제작상태
    """
    issues: list[MediaIssue] = []
    for idx, raw in enumerate(rows, start=1):
        row = _row_dict(raw)
        ad_id = _first(row, "광고ID", "ad_archive_id") or f"row-{idx}"
        link = _first(row, "미디어링크", "media_url")
        media_type = _first(row, "미디어타입", "media_type").lower()
        generation_status = _first(row, "제작상태", "generation_status")

        if not link:
            issues.append(MediaIssue(source, ad_id, "미디어링크", link, "미디어링크가 비어 있습니다."))
        elif not link.startswith(("http://", "https://")):
            issues.append(MediaIssue(source, ad_id, "미디어링크", link, "미디어링크가 http(s) URL이 아닙니다."))

        if media_type not in VALID_MEDIA_TYPES:
            issues.append(MediaIssue(source, ad_id, "미디어타입", media_type,
                                     "미디어타입은 image 또는 video여야 합니다."))

        if generation_status == GENERATION_REQUESTED and media_type != "image":
            issues.append(MediaIssue(source, ad_id, "제작상태", generation_status,
                                     "이미지 생성 요청은 미디어타입=image 행만 처리합니다."))

    return issues


def audit_db(conn: sqlite3.Connection, source: str = "db") -> list[MediaIssue]:
    rows = conn.execute(
        "SELECT ad_archive_id, media_url, media_type FROM ads ORDER BY ad_archive_id"
    ).fetchall()
    return audit_rows(rows, source=source)


def print_issues(issues: list[MediaIssue], limit: int = 50) -> None:
    if not issues:
        print("  issues: 0")
        return
    print(f"  issues: {len(issues)}")
    for issue in issues[:limit]:
        print(f"  [{issue.severity}] {issue.source} {issue.ad_id} "
              f"{issue.field}: {issue.message} ({issue.value})")
    if len(issues) > limit:
        print(f"  ... 외 {len(issues) - limit}건")

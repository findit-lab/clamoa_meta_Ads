"""C3 — Diff 엔진 (★핵심①). 기획서 v2 §C3.

매일 페이지별 '현재 활성 광고 집합' vs '이전 상태(ads where status=active)'를 비교해
이벤트를 발행하고 상태 테이블을 materialize 한다.

- 신규           → AD_APPEARED      (first_seen=today, status=active)
- 양쪽 존재      → AD_STILL_ACTIVE  (last_seen_active=today 갱신, miss_streak=0)
- 이전 active∖현재 → grace-period 적용:
    · 연속 미관측 < grace → AD_MISSING (status=active 유지, last_seen_active 동결)
    · 연속 미관측 ≥ grace → AD_DISAPPEARED (status=ended,
                     observed_active_days = last_seen_active − first_seen 확정)

grace-period 이유: 수집 액터가 동일 입력에도 호출마다 반환 광고수가 출렁여(109→30)
1회 누락이 false 종료를 만들 수 있다. 연속 N회 미관측 시에만 종료를 확정하고,
그 사이엔 active를 유지하되 last_seen_active를 마지막 실관측일로 동결해 longevity 정확도를 지킨다.

ad_events는 append-only, ads는 이벤트에서 materialize.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass

import config
from .models import RawAd


@dataclass
class DiffResult:
    appeared: int = 0
    still_active: int = 0
    disappeared: int = 0
    missing: int = 0  # grace-period 내 미관측(아직 종료 아님)


def _days(a: str, b: str) -> int:
    """(a − b).days, ISO 날짜 문자열."""
    return (dt.date.fromisoformat(a) - dt.date.fromisoformat(b)).days


def _emit(conn: sqlite3.Connection, ad_id: str, page_id: str, etype: str,
          observed_at: str, payload_ref: str = "") -> None:
    conn.execute(
        "INSERT INTO ad_events (ad_archive_id, page_id, event_type, observed_at, payload_ref)"
        " VALUES (?, ?, ?, ?, ?)",
        (ad_id, page_id, etype, observed_at, payload_ref),
    )


def process_day(
    conn: sqlite3.Connection,
    page_id: str,
    current_ads: list[RawAd],
    observed_at: str,
    grace: int | None = None,
) -> DiffResult:
    """단일 페이지·단일 날짜의 diff를 처리하고 이벤트+상태를 갱신.

    grace: 종료 확정까지 허용할 연속 미관측 횟수. None이면 config.DISAPPEAR_GRACE_RUNS.
           1이면 grace 없음(미관측 즉시 종료).
    """
    grace = config.DISAPPEAR_GRACE_RUNS if grace is None else grace
    res = DiffResult()
    current = {a.ad_archive_id: a for a in current_ads}

    # 이 페이지에서 직전 'active' 상태였던 광고들.
    prev_active = {
        r["ad_archive_id"]: r
        for r in conn.execute(
            "SELECT * FROM ads WHERE page_id=? AND status='active'", (page_id,)
        ).fetchall()
    }

    # 1) 현재 활성 광고 처리: 신규(APPEARED) 또는 지속(STILL_ACTIVE)
    for ad_id, ad in current.items():
        row = conn.execute(
            "SELECT * FROM ads WHERE ad_archive_id=?", (ad_id,)
        ).fetchone()

        if row is None:
            # 신규
            _emit(conn, ad_id, page_id, "AD_APPEARED", observed_at, ad.media_path)
            conn.execute(
                """INSERT INTO ads (ad_archive_id, page_id, first_seen, last_seen_active,
                       status, observed_active_days, ad_copy, headline, cta_type,
                       link_url, media_path, updated_at,
                       fb_start_date, media_url, media_type, variant_count,
                       display_format, targeting)
                   VALUES (?, ?, ?, ?, 'active', 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (ad_id, page_id, observed_at, observed_at, ad.ad_copy, ad.headline,
                 ad.cta_type, ad.link_url, ad.media_path, observed_at,
                 ad.fb_start_date, ad.media_url, ad.media_type, ad.variant_count,
                 ad.display_format, ad.targeting),
            )
            res.appeared += 1
        elif row["status"] == "ended":
            # 종료됐던 광고가 다시 등장 → 새 등장으로 취급, first_seen 재설정.
            _emit(conn, ad_id, page_id, "AD_APPEARED", observed_at, ad.media_path)
            conn.execute(
                """UPDATE ads SET status='active', first_seen=?, last_seen_active=?,
                       observed_active_days=0, miss_streak=0, media_path=?, updated_at=?,
                       media_url=?, media_type=?, variant_count=?, display_format=?,
                       targeting=?, fb_start_date=?
                   WHERE ad_archive_id=?""",
                (observed_at, observed_at, ad.media_path, observed_at,
                 ad.media_url, ad.media_type, ad.variant_count, ad.display_format,
                 ad.targeting, ad.fb_start_date, ad_id),
            )
            res.appeared += 1
        else:
            # 지속 — longevity 갱신 + 변동 가능한 메타데이터(미디어·변형수·타깃) 리프레시
            # grace 기간 중 다시 보였다면 miss_streak 리셋. 누락 구간도 실제로는
            # 계속 게재된 것이므로 span은 today−first_seen으로 이어서 센다.
            _emit(conn, ad_id, page_id, "AD_STILL_ACTIVE", observed_at, ad.media_path)
            span = _days(observed_at, row["first_seen"])
            conn.execute(
                """UPDATE ads SET last_seen_active=?, observed_active_days=?, miss_streak=0,
                       updated_at=?, media_url=?, media_type=?, variant_count=?, targeting=?
                   WHERE ad_archive_id=?""",
                (observed_at, span, observed_at, ad.media_url, ad.media_type,
                 ad.variant_count, ad.targeting, ad_id),
            )
            res.still_active += 1

    # 2) 사라진 광고 처리: 이전 active 였는데 오늘 없음.
    #    grace-period 내(연속 미관측 < grace)면 종료를 보류(AD_MISSING)하고 active 유지.
    #    연속 미관측이 grace 이상이면 종료 확정 → longevity = last_seen_active − first_seen.
    for ad_id, row in prev_active.items():
        if ad_id in current:
            continue
        streak = (row["miss_streak"] or 0) + 1
        if streak >= grace:
            _emit(conn, ad_id, page_id, "AD_DISAPPEARED", observed_at)
            span = _days(row["last_seen_active"], row["first_seen"])
            conn.execute(
                "UPDATE ads SET status='ended', observed_active_days=?, miss_streak=?,"
                " updated_at=? WHERE ad_archive_id=?",
                (span, streak, observed_at, ad_id),
            )
            res.disappeared += 1
        else:
            # 아직 유예 중: last_seen_active·observed_active_days는 건드리지 않고 동결.
            _emit(conn, ad_id, page_id, "AD_MISSING", observed_at)
            conn.execute(
                "UPDATE ads SET miss_streak=?, updated_at=? WHERE ad_archive_id=?",
                (streak, observed_at, ad_id),
            )
            res.missing += 1

    conn.commit()
    return res

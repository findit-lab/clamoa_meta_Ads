"""C6 패턴 분석 lift 계산."""
import json

import config
from adintel.analysis.patterns import compute_patterns


def _add_ad(conn, ad_id, days, offer):
    conn.execute(
        """INSERT INTO ads (ad_archive_id, page_id, first_seen, last_seen_active,
               status, observed_active_days, updated_at)
           VALUES (?, 'p1', '2026-01-01', '2026-01-01', 'ended', ?, '2026-01-01')""",
        (ad_id, days),
    )
    conn.execute(
        """INSERT INTO ad_tags (ad_archive_id, format, hook_type, offer_type, angle,
               copy_tone, visual_flags, cta_button, source, tagged_at)
           VALUES (?, '이미지', '문제제기', ?, '성과향상', '전문가형', '[]', '더 알아보기', 'llm', '2026-01-01')""",
        (ad_id, offer),
    )


def test_lift_for_longevity_correlated_tag(conn):
    thr = config.LONGEVITY_THRESHOLD_DAYS
    # 장수 4건 = 모두 "무료 진단·감사", 단명 6건 = 모두 "무료 상담".
    for i in range(4):
        _add_ad(conn, f"long-{i}", thr + 5, "무료 진단·감사")
    for i in range(6):
        _add_ad(conn, f"short-{i}", 2, "무료 상담")
    conn.commit()

    patterns = compute_patterns(conn)
    by_key = {p.key: p for p in patterns}

    win = by_key["offer_type=무료 진단·감사"]
    # cohort_share=4/4=1.0, total_share=4/10=0.4, lift=2.5
    assert win.cohort_share == 1.0
    assert win.total_share == 0.4
    assert abs(win.lift - 2.5) < 1e-6
    assert win.sample_n == 4

    # 단명 전용 태그는 코호트에 등장하지 않으므로 패턴에 없음.
    assert "offer_type=무료 상담" not in by_key


def test_empty_db_returns_no_patterns(conn):
    assert compute_patterns(conn) == []

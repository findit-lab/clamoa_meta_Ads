"""C7 — Slack 주간 요약. 기획서 v2 §C7.

"이번 주 신규 위너 컨셉 N개" 요약 + 상위 lift 패턴. SLACK_WEBHOOK_URL 있을 때만
전송, 없으면 콘솔. 표준 라이브러리 urllib만 사용.
"""
from __future__ import annotations

import json
import urllib.request

import config
from ..analysis.patterns import low_confidence


def _build_text(winners: list[dict], patterns: list) -> str:
    lines = [f"*Clamoa 경쟁 광고 인텔리전스 — 주간 요약*",
             f"신규/현존 위너 컨셉 {len(winners)}개"]
    if winners:
        lines.append("\n*Top 위너 컨셉*")
        for w in winners[:5]:
            lines.append(
                f"  • #{w['cluster_id']} {w.get('headline','')} "
                f"(광고주 {w['advertiser_count']}곳, 최대 {w['max_observed_days']}일)"
            )
    top = [p for p in patterns if p.lift > 1.2][:5]
    if top:
        lines.append("\n*강한 패턴 (lift>1.2)*")
        for p in top:
            warn = " ⚠️저신뢰" if low_confidence(p) else ""
            lines.append(f"  • {p.key} — lift {p.lift} (n={p.sample_n}){warn}")
    return "\n".join(lines)


def report_weekly(winners: list[dict], patterns: list) -> None:
    text = _build_text(winners, patterns)
    if not config.SLACK_WEBHOOK_URL:
        print("\n[Slack] 웹훅 미설정 → 콘솔 미리보기\n" + "-" * 50)
        print(text)
        print("-" * 50)
        return

    req = urllib.request.Request(
        config.SLACK_WEBHOOK_URL,
        data=json.dumps({"text": text}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()
    print("[Slack] 주간 요약 전송 완료")

"""C1 시드 — 타겟 광고주 10곳 (mock PR대행사 / 마케팅SaaS).

실제 운영 시 이 목록을 경쟁사 Facebook Page ID로 교체한다.
"""
import _bootstrap  # noqa: F401
import datetime as dt

from adintel import db, targets
from adintel.models import TargetPage

SEED = [
    ("100000000000001", "PR Partners A", "PR대행사"),
    ("100000000000002", "PR Studio B", "PR대행사"),
    ("100000000000003", "Comms Agency C", "PR대행사"),
    ("100000000000004", "Brand PR D", "PR대행사"),
    ("100000000000005", "Media Relations E", "PR대행사"),
    ("100000000000006", "GrowthSaaS F", "마케팅SaaS"),
    ("100000000000007", "MarTech G", "마케팅SaaS"),
    ("100000000000008", "AdOps H", "마케팅SaaS"),
    ("100000000000009", "Funnel I", "마케팅SaaS"),
    ("100000000000010", "CRM Suite J", "마케팅SaaS"),
]


def main() -> None:
    db.init_db()
    conn = db.connect()
    today = dt.date.today().isoformat()
    for pid, name, cat in SEED:
        targets.upsert_target(
            conn, TargetPage(page_id=pid, page_name=name, category=cat,
                             active=True, added_at=today, note="seed")
        )
    n = len(targets.list_active(conn))
    conn.close()
    print(f"✅ target_pages 시드 완료: {n}곳 활성")


if __name__ == "__main__":
    main()

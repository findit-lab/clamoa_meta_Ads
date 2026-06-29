"""Notion 제작요청(`제작상태=생성요청`)을 GPT Image로 처리.

usage:
  python3 scripts/process_creative_requests.py --dry-run
  python3 scripts/process_creative_requests.py --limit 5
"""
import _bootstrap  # noqa: F401
import argparse
import datetime as dt
from pathlib import Path

from adintel import db
from adintel.generation.openai_images import generate_from_ad
from adintel.reporting import notion_ads
from adintel.reporting.notion_ads import (
    GEN_STATUS_DONE,
    GEN_STATUS_ERROR,
    GEN_STATUS_RUNNING,
    GEN_STATUS_SKIPPED,
)


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _process_one(conn, req, dry_run: bool = False) -> str:
    if dry_run:
        print(f"  dry-run | {req.ad_id} | {req.media_type} | {req.page_id}")
        return "dry-run"

    if (req.media_type or "").lower() != "image":
        notion_ads.update_creative_status(
            req.page_id,
            GEN_STATUS_SKIPPED,
            error="이미지 생성은 미디어타입=image 광고만 처리합니다.",
        )
        print(f"  skipped | {req.ad_id} | media_type={req.media_type}")
        return "skipped"

    notion_ads.update_creative_status(req.page_id, GEN_STATUS_RUNNING, error="")
    result = generate_from_ad(conn, req.ad_id, req.brief, page_id=req.page_id)

    if result.status == "done":
        try:
            notion_ads.attach_generation_result(
                req.page_id,
                result.output_path,
                prompt=result.prompt,
                model=result.model,
                generated_at=_utc_now(),
            )
            print(f"  done | {req.ad_id} | {Path(result.output_path).name}")
            return "done"
        except Exception as e:
            notion_ads.update_creative_status(
                req.page_id,
                GEN_STATUS_ERROR,
                prompt=result.prompt,
                model=result.model,
                error=f"생성은 완료됐지만 Notion 업로드 실패: {e}",
            )
            print(f"  error | {req.ad_id} | upload failed: {e}")
            return "error"

    if result.status == "skipped" and result.output_path and Path(result.output_path).exists():
        try:
            notion_ads.attach_generation_result(
                req.page_id,
                result.output_path,
                prompt=result.prompt,
                model=result.model,
                generated_at=_utc_now(),
            )
            print(f"  done | {req.ad_id} | reused {Path(result.output_path).name}")
            return "done"
        except Exception as e:
            notion_ads.update_creative_status(
                req.page_id,
                GEN_STATUS_ERROR,
                prompt=result.prompt,
                model=result.model,
                error=f"기존 생성 파일 Notion 업로드 실패: {e}",
            )
            print(f"  error | {req.ad_id} | reuse upload failed: {e}")
            return "error"

    if result.status == "skipped":
        notion_ads.update_creative_status(
            req.page_id,
            GEN_STATUS_SKIPPED,
            prompt=result.prompt,
            model=result.model,
            error=result.error,
        )
        print(f"  skipped | {req.ad_id} | {result.error}")
        return "skipped"

    notion_ads.update_creative_status(
        req.page_id,
        GEN_STATUS_ERROR,
        prompt=result.prompt,
        model=result.model,
        error=result.error,
    )
    print(f"  error | {req.ad_id} | {result.error}")
    return "error"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not notion_ads._enabled():
        raise SystemExit("NOTION_TOKEN/NOTION_ADS_DATABASE_ID 미설정")

    db.init_db()
    conn = db.connect()
    try:
        requests = notion_ads.pending_creative_requests(limit=args.limit)
        print(f"[creative-requests] pending={len(requests)}")
        counts = {"done": 0, "error": 0, "skipped": 0, "dry-run": 0}
        for req in requests:
            status = _process_one(conn, req, dry_run=args.dry_run)
            counts[status] = counts.get(status, 0) + 1
        print("[creative-requests] " + " / ".join(f"{k} {v}" for k, v in counts.items() if v))
    finally:
        conn.close()


if __name__ == "__main__":
    main()

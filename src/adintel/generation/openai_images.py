"""OpenAI GPT Image 기반 광고 소재 생성.

Notion에서 승인한 이미지 광고를 참조해 새 Meta Radar/Findit 소재를 만든다. 참조 이미지는
구도와 메시지 패턴만 참고하고 경쟁사 로고/상표/동일 레이아웃 복제를 금지한다.
"""
from __future__ import annotations

import base64
import datetime as dt
import sqlite3
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import config


@dataclass
class GenerationResult:
    status: str
    output_path: str = ""
    prompt: str = ""
    model: str = ""
    error: str = ""


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _job(conn: sqlite3.Connection, page_id: str, ad_id: str) -> sqlite3.Row | None:
    if not page_id:
        return None
    return conn.execute(
        "SELECT * FROM creative_jobs WHERE notion_page_id=? AND ad_archive_id=?",
        (page_id, ad_id),
    ).fetchone()


def _upsert_job(
    conn: sqlite3.Connection,
    *,
    page_id: str,
    ad_id: str,
    status: str,
    source_media_url: str = "",
    output_path: str = "",
    prompt: str = "",
    model: str = "",
    error: str = "",
) -> None:
    if not page_id:
        return
    now = _now()
    conn.execute(
        """INSERT INTO creative_jobs
               (notion_page_id, ad_archive_id, status, source_media_url, output_path,
                prompt, model, error, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(notion_page_id, ad_archive_id) DO UPDATE SET
                status=excluded.status,
                source_media_url=excluded.source_media_url,
                output_path=excluded.output_path,
                prompt=excluded.prompt,
                model=excluded.model,
                error=excluded.error,
                updated_at=excluded.updated_at""",
        (page_id, ad_id, status, source_media_url, output_path, prompt, model, error, now, now),
    )
    conn.commit()


def _ad_row(conn: sqlite3.Connection, ad_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT a.*, t.page_name
        FROM ads a
        LEFT JOIN target_pages t ON t.page_id = a.page_id
        WHERE a.ad_archive_id=?
        """,
        (ad_id,),
    ).fetchone()


def _extension_from_url(url: str) -> str:
    path = urllib.parse.urlparse(url).path
    suffix = Path(path).suffix.lower()
    return suffix if suffix in (".png", ".jpg", ".jpeg", ".webp") else ".jpg"


def _download_reference(media_url: str, ad_id: str) -> str:
    if not media_url or not media_url.startswith("http"):
        return ""
    config.ensure_dirs()
    dest = config.GENERATED_DIR / f"reference_{ad_id}{_extension_from_url(media_url)}"
    if dest.exists() and dest.stat().st_size > 0:
        return str(dest)
    with urllib.request.urlopen(media_url, timeout=60) as resp:
        dest.write_bytes(resp.read())
    return str(dest)


def _resolve_reference(row: sqlite3.Row) -> str:
    media_path = Path(row["media_path"] or "")
    if media_path.exists() and media_path.stat().st_size > 0:
        return str(media_path)
    return _download_reference(row["media_url"] or "", row["ad_archive_id"])


def build_prompt(row: sqlite3.Row, brief: str = "") -> str:
    page_name = row["page_name"] or row["page_id"]
    source_copy = (row["ad_copy"] or row["headline"] or "")[:500]
    brief_text = (brief or "").strip()
    return (
        "Create one original Meta/Facebook ad image for Meta Radar / Findit.\n"
        "Use the attached reference image only to infer high-level composition, message hierarchy, "
        "visual density, and creative strategy. Do not copy the exact layout, pixels, logo, brand "
        "marks, trademarked elements, characters, or distinctive trade dress from the reference.\n"
        "Make the output clearly original and suitable for a B2B marketing intelligence / ad creative "
        "automation product. Favor a polished Korean SaaS ad style, crisp hierarchy, and enough "
        "negative space for platform-safe ad copy.\n"
        "Avoid competitor names and logos. If text appears, keep it short, generic, and legible.\n\n"
        f"Reference advertiser context: {page_name}\n"
        f"Reference ad copy pattern: {source_copy or 'N/A'}\n"
        f"User production brief: {brief_text or 'Create a fresh image ad variant inspired by the winning pattern.'}\n"
        "Output should be a finished square ad creative, not a mockup in a device frame."
    )


def _image_base64(result) -> str:
    item = result.data[0]
    if isinstance(item, dict):
        return item.get("b64_json", "")
    return getattr(item, "b64_json", "")


def _write_output(ad_id: str, image_base64: str) -> str:
    config.ensure_dirs()
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = config.GENERATED_DIR / f"{ad_id}_{stamp}.png"
    dest.write_bytes(base64.b64decode(image_base64))
    return str(dest)


def _call_openai_edit(client, reference_path: str, prompt: str):
    with open(reference_path, "rb") as image_file:
        return client.images.edit(
            model=config.IMAGE_MODEL,
            image=[image_file],
            prompt=prompt,
            size=config.IMAGE_SIZE,
            quality=config.IMAGE_QUALITY,
        )


def generate_from_ad(
    conn: sqlite3.Connection,
    ad_id: str,
    brief: str,
    page_id: str | None = None,
    *,
    client=None,
) -> GenerationResult:
    """광고 1건을 참조해 이미지 소재를 생성.

    page_id가 있으면 creative_jobs ledger로 중복 실행을 막는다.
    """
    notion_page_id = page_id or ""
    existing = _job(conn, notion_page_id, ad_id)
    if existing and existing["status"] in ("running", "done"):
        return GenerationResult(
            status="skipped",
            output_path=existing["output_path"] or "",
            prompt=existing["prompt"] or "",
            model=existing["model"] or config.IMAGE_MODEL,
            error=f"이미 처리 중이거나 완료된 요청입니다: {existing['status']}",
        )

    row = _ad_row(conn, ad_id)
    if row is None:
        err = f"광고ID를 로컬 DB에서 찾을 수 없습니다: {ad_id}"
        _upsert_job(conn, page_id=notion_page_id, ad_id=ad_id, status="error", error=err)
        return GenerationResult(status="error", model=config.IMAGE_MODEL, error=err)

    if (row["media_type"] or "").lower() != "image":
        err = "이미지 생성은 미디어타입=image 광고만 처리합니다."
        _upsert_job(
            conn,
            page_id=notion_page_id,
            ad_id=ad_id,
            status="skipped",
            source_media_url=row["media_url"] or "",
            model=config.IMAGE_MODEL,
            error=err,
        )
        return GenerationResult(status="skipped", model=config.IMAGE_MODEL, error=err)

    try:
        reference_path = _resolve_reference(row)
        if not reference_path:
            raise RuntimeError("참조 이미지를 찾거나 다운로드할 수 없습니다.")
        prompt = build_prompt(row, brief)
        _upsert_job(
            conn,
            page_id=notion_page_id,
            ad_id=ad_id,
            status="running",
            source_media_url=row["media_url"] or reference_path,
            prompt=prompt,
            model=config.IMAGE_MODEL,
        )

        if client is None:
            if not config.OPENAI_API_KEY:
                raise RuntimeError("OPENAI_API_KEY 미설정")
            from openai import OpenAI  # 지연 import: 테스트/감사 명령은 SDK 없이도 동작

            client = OpenAI(api_key=config.OPENAI_API_KEY)

        result = _call_openai_edit(client, reference_path, prompt)
        image_base64 = _image_base64(result)
        if not image_base64:
            raise RuntimeError("OpenAI 응답에 b64_json 이미지가 없습니다.")
        output_path = _write_output(ad_id, image_base64)
        _upsert_job(
            conn,
            page_id=notion_page_id,
            ad_id=ad_id,
            status="done",
            source_media_url=row["media_url"] or reference_path,
            output_path=output_path,
            prompt=prompt,
            model=config.IMAGE_MODEL,
        )
        return GenerationResult(
            status="done",
            output_path=output_path,
            prompt=prompt,
            model=config.IMAGE_MODEL,
        )
    except Exception as e:
        err = str(e)
        _upsert_job(
            conn,
            page_id=notion_page_id,
            ad_id=ad_id,
            status="error",
            source_media_url=row["media_url"] or "",
            prompt=build_prompt(row, brief),
            model=config.IMAGE_MODEL,
            error=err,
        )
        return GenerationResult(status="error", prompt=build_prompt(row, brief),
                                model=config.IMAGE_MODEL, error=err)

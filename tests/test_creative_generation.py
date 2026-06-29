import base64

import config
from adintel.generation.openai_images import generate_from_ad


class _ImageItem:
    b64_json = base64.b64encode(b"generated-image").decode("ascii")


class _ImageResult:
    data = [_ImageItem()]


class _FakeImages:
    def __init__(self):
        self.calls = []

    def edit(self, **kwargs):
        self.calls.append(kwargs)
        return _ImageResult()


class _FakeClient:
    def __init__(self):
        self.images = _FakeImages()


def _seed_ad(conn, media_path, media_type="image", ad_id="A1"):
    conn.execute(
        "INSERT INTO target_pages (page_id, page_name, category, added_at) "
        "VALUES ('P1','Cafe24','x','2026-01-01')"
    )
    conn.execute(
        """INSERT INTO ads (ad_archive_id, page_id, first_seen, last_seen_active, status,
               observed_active_days, ad_copy, headline, media_path, updated_at,
               media_url, media_type, variant_count, display_format, targeting)
           VALUES (?, 'P1','2026-06-10','2026-06-10','active',0,
                   '광고 자동화 카피','헤드라인', ?, '2026-06-10',
                   'https://cdn/source.jpg', ?, 3, 'DCO', 'KR')""",
        (ad_id, str(media_path), media_type),
    )
    conn.commit()


def test_generate_from_ad_writes_output_and_job(conn, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "GENERATED_DIR", tmp_path / "generated")
    src = tmp_path / "source.png"
    src.write_bytes(b"source-image")
    _seed_ad(conn, src)

    client = _FakeClient()
    result = generate_from_ad(conn, "A1", "새 소재", page_id="pg1", client=client)

    assert result.status == "done"
    assert result.model == config.IMAGE_MODEL
    assert "Do not copy" in result.prompt
    assert client.images.calls[0]["model"] == config.IMAGE_MODEL
    assert client.images.calls[0]["image"]
    assert (tmp_path / "generated").exists()
    assert open(result.output_path, "rb").read() == b"generated-image"

    job = conn.execute("SELECT * FROM creative_jobs WHERE ad_archive_id='A1'").fetchone()
    assert job["status"] == "done"
    assert job["output_path"] == result.output_path


def test_generate_from_ad_skips_duplicate_done_job(conn, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "GENERATED_DIR", tmp_path / "generated")
    src = tmp_path / "source.png"
    src.write_bytes(b"source-image")
    _seed_ad(conn, src)

    client = _FakeClient()
    first = generate_from_ad(conn, "A1", "새 소재", page_id="pg1", client=client)
    second = generate_from_ad(conn, "A1", "새 소재", page_id="pg1", client=client)

    assert first.status == "done"
    assert second.status == "skipped"
    assert len(client.images.calls) == 1


def test_generate_from_ad_skips_video(conn, tmp_path):
    src = tmp_path / "source.png"
    src.write_bytes(b"source-image")
    _seed_ad(conn, src, media_type="video")

    client = _FakeClient()
    result = generate_from_ad(conn, "A1", "새 소재", page_id="pg1", client=client)

    assert result.status == "skipped"
    assert "미디어타입=image" in result.error
    assert client.images.calls == []


def test_generate_from_ad_errors_without_openai_key(conn, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", "")
    src = tmp_path / "source.png"
    src.write_bytes(b"source-image")
    _seed_ad(conn, src)

    result = generate_from_ad(conn, "A1", "새 소재", page_id="pg1")

    assert result.status == "error"
    assert "OPENAI_API_KEY" in result.error
    job = conn.execute("SELECT status, error FROM creative_jobs WHERE ad_archive_id='A1'").fetchone()
    assert job["status"] == "error"
    assert "OPENAI_API_KEY" in job["error"]

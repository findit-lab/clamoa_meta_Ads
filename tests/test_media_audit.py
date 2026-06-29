from adintel.media_audit import audit_rows


def _messages(issues):
    return [i.message for i in issues]


def test_audit_accepts_valid_image_row():
    issues = audit_rows([
        {"광고ID": "A1", "미디어링크": "https://cdn/x.png", "미디어타입": "image"}
    ])
    assert issues == []


def test_audit_flags_missing_media_link():
    issues = audit_rows([
        {"광고ID": "A1", "미디어링크": "", "미디어타입": "image"}
    ])
    assert any("비어" in m for m in _messages(issues))


def test_audit_flags_unknown_media_type():
    issues = audit_rows([
        {"광고ID": "A1", "미디어링크": "https://cdn/x", "미디어타입": "unknown"}
    ])
    assert any("image 또는 video" in m for m in _messages(issues))


def test_audit_flags_generation_request_for_video():
    issues = audit_rows([
        {
            "광고ID": "A1",
            "미디어링크": "https://cdn/x.mp4",
            "미디어타입": "video",
            "제작상태": "생성요청",
        }
    ])
    assert any("미디어타입=image" in m for m in _messages(issues))


def test_audit_flags_non_http_url():
    issues = audit_rows([
        {"광고ID": "A1", "미디어링크": "/tmp/x.png", "미디어타입": "image"}
    ])
    assert any("http(s)" in m for m in _messages(issues))

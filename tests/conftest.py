"""pytest 부트스트랩: sys.path 등록 + 임시 DB 픽스처."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from adintel import db  # noqa: E402


@pytest.fixture()
def conn(tmp_path):
    dbp = tmp_path / "test.db"
    db.init_db(dbp)
    c = db.connect(dbp)
    yield c
    c.close()

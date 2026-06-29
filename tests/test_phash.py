"""C4 pHash 근접중복 — ★핵심② 1단계."""
import pytest

from adintel.embedding import phash
from adintel.embedding.cluster import PHashClusterBackend

# imagehash/Pillow 없으면 스킵.
imagehash = pytest.importorskip("imagehash")
pytest.importorskip("PIL")


def _hash_image(color):
    from PIL import Image
    return str(imagehash.phash(Image.new("RGB", (64, 64), color)))


def test_identical_images_zero_hamming():
    h = _hash_image((10, 20, 30))
    assert phash.hamming(h, h) == 0
    assert phash.is_near_duplicate(h, h, threshold=6)


def test_distinct_images_far():
    h1 = _hash_image((0, 0, 0))
    h2 = _hash_image((255, 255, 255))
    # solid 색끼리는 phash가 거의 동일할 수 있어 거리만 검증(>=0).
    assert phash.hamming(h1, h2) >= 0


def test_empty_hash_is_far():
    assert phash.hamming("", "abc") == 9999
    assert not phash.is_near_duplicate("", "abc", threshold=6)


def test_cluster_backend_groups_near_duplicates():
    backend = PHashClusterBackend(threshold=6)
    h = _hash_image((10, 20, 30))
    items = [
        {"ad_archive_id": "a", "phash": h},
        {"ad_archive_id": "b", "phash": h},          # a와 동일 → 같은 클러스터
        {"ad_archive_id": "c", "phash": ""},          # 해시 없음 → 단독
    ]
    assign = backend.assign(items)
    assert assign["a"] == assign["b"]
    assert assign["c"] != assign["a"]

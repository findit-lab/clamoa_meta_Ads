"""C4 — pHash 근접중복 제거 (★핵심② 1단계). 기획서 v2 §C4.

imagehash로 크리에이티브 perceptual hash를 계산하고, 해밍거리 ≤ 임계값이면
근접중복으로 간주한다. 같은 컨셉의 미세 변형을 1차로 묶는다.
"""
from __future__ import annotations

from pathlib import Path


def compute_phash(media_path: str) -> str:
    """이미지 경로 → pHash 16진 문자열. 실패 시 빈 문자열."""
    if not media_path:
        return ""
    p = Path(media_path)
    if not p.exists() or p.stat().st_size == 0:
        return ""
    try:
        import imagehash
        from PIL import Image
    except ImportError:
        return ""
    try:
        return str(imagehash.phash(Image.open(p)))
    except Exception:
        return ""


def hamming(h1: str, h2: str) -> int:
    """두 pHash 16진 문자열의 해밍거리. 비교 불가 시 큰 값."""
    if not h1 or not h2 or len(h1) != len(h2):
        return 9999
    try:
        import imagehash

        return imagehash.hex_to_hash(h1) - imagehash.hex_to_hash(h2)
    except ImportError:
        # imagehash 없으면 비트 단위 직접 비교.
        b1 = bin(int(h1, 16))[2:].zfill(len(h1) * 4)
        b2 = bin(int(h2, 16))[2:].zfill(len(h2) * 4)
        return sum(c1 != c2 for c1, c2 in zip(b1, b2))


def is_near_duplicate(h1: str, h2: str, threshold: int) -> bool:
    return hamming(h1, h2) <= threshold

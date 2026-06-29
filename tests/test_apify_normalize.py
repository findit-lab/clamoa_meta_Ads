from adintel.collectors.apify import ApifyCollector


def test_normalize_snapshot_image():
    raw = {
        "ad_archive_id": "A1",
        "page_id": "P1",
        "snapshot": {
            "body": {"text": "body"},
            "title": "headline",
            "images": [{"original_image_url": "https://cdn/image.jpg"}],
        },
    }
    ad = ApifyCollector._normalize(raw, "P1")
    assert ad.media_url == "https://cdn/image.jpg"
    assert ad.media_type == "image"


def test_normalize_snapshot_video_preview():
    raw = {
        "ad_archive_id": "A1",
        "page_id": "P1",
        "snapshot": {
            "videos": [{"video_preview_image_url": "https://cdn/preview.jpg"}],
        },
    }
    ad = ApifyCollector._normalize(raw, "P1")
    assert ad.media_url == "https://cdn/preview.jpg"
    assert ad.media_type == "video"


def test_normalize_card_takes_precedence_for_dco():
    raw = {
        "ad_archive_id": "A1",
        "page_id": "P1",
        "collation_count": 2,
        "snapshot": {
            "body": {"text": "{{product.description}}"},
            "title": "{{product.name}}",
            "display_format": "DCO",
            "cards": [
                {
                    "body": {"text": "real body"},
                    "title": "real title",
                    "original_image_url": "https://cdn/card.jpg",
                }
            ],
        },
    }
    ad = ApifyCollector._normalize(raw, "P1")
    assert ad.ad_copy == "real body"
    assert ad.headline == "real title"
    assert ad.media_url == "https://cdn/card.jpg"
    assert ad.media_type == "image"
    assert ad.variant_count == 2


def test_normalize_cards_count_as_variants_without_collation():
    raw = {
        "ad_archive_id": "A1",
        "page_id": "P1",
        "snapshot": {
            "display_format": "CAROUSEL",
            "cards": [
                {"original_image_url": "https://cdn/1.jpg"},
                {"original_image_url": "https://cdn/2.jpg"},
                {"original_image_url": "https://cdn/3.jpg"},
            ],
        },
    }
    ad = ApifyCollector._normalize(raw, "P1")
    assert ad.variant_count == 3
    assert ad.media_url == "https://cdn/1.jpg"
    assert ad.media_type == "image"

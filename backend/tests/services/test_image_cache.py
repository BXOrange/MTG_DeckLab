"""Tests for ImageCache: download-once, serve-from-disk-after.

Reference: docs/concepts/06_CARD_GRAPHICS_AND_LAZY_LOADING.md,
docs/Reference/08_CARD_CACHE_EXPORT_IMPORT.md.
"""

import httpx2 as httpx

from mtg_analyzer.services.image_cache import ImageCache


def make_cache(tmp_path, handler) -> ImageCache:
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://cards.scryfall.io")
    return ImageCache(cache_dir=tmp_path / "images", client=client)


class TestPathFor:
    def test_jpg_sizes(self, tmp_path):
        cache = ImageCache(cache_dir=tmp_path)
        for size in ("small", "normal", "large"):
            assert cache.path_for("card-1", size) == tmp_path / "card-1" / f"{size}.jpg"

    def test_png_size(self, tmp_path):
        cache = ImageCache(cache_dir=tmp_path)
        assert cache.path_for("card-1", "png") == tmp_path / "card-1" / "png.png"

    def test_back_face_gets_a_distinct_filename(self, tmp_path):
        # Both faces of a DFC share the card id, so the back face must not
        # clobber the front's cached file.
        cache = ImageCache(cache_dir=tmp_path)
        front = cache.path_for("card-1", "normal", "front")
        back = cache.path_for("card-1", "normal", "back")
        assert front == tmp_path / "card-1" / "normal.jpg"
        assert back == tmp_path / "card-1" / "normal_back.jpg"
        assert front != back


class TestGetOrFetch:
    def test_downloads_and_writes_file(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"fake-image-bytes")

        cache = make_cache(tmp_path, handler)
        path = cache.get_or_fetch("card-1", "normal", "https://cards.scryfall.io/normal/card-1.jpg")

        assert path.exists()
        assert path.read_bytes() == b"fake-image-bytes"

    def test_second_fetch_does_not_hit_network(self, tmp_path):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, content=b"fake-image-bytes")

        cache = make_cache(tmp_path, handler)
        cache.get_or_fetch("card-1", "normal", "https://cards.scryfall.io/normal/card-1.jpg")
        cache.get_or_fetch("card-1", "normal", "https://cards.scryfall.io/normal/card-1.jpg")

        assert len(calls) == 1

    def test_different_sizes_cached_independently(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"fake-image-bytes")

        cache = make_cache(tmp_path, handler)
        small_path = cache.get_or_fetch("card-1", "small", "https://cards.scryfall.io/small/card-1.jpg")
        normal_path = cache.get_or_fetch("card-1", "normal", "https://cards.scryfall.io/normal/card-1.jpg")

        assert small_path != normal_path
        assert small_path.exists() and normal_path.exists()

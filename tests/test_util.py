"""Tests for the util module."""

import pytest

from custom_components.denon_marantz_avr.util import sanitize_image_url


class TestSanitizeImageUrl:
    @pytest.mark.parametrize(
        "raw",
        [
            None,
            "",
            "   ",
            '""',
            '  ""  ',
            # The reported bug: empty art appended to an AIOS device URL.
            "http://192.168.1.200:60006/upnp/desc/aios_device/%22%22",
            'http://192.168.1.200:60006/upnp/desc/aios_device/""',
            "http://192.168.1.200:60006/upnp/desc/aios_device/",
        ],
    )
    def test_returns_none_for_no_artwork(self, raw: str | None) -> None:
        assert sanitize_image_url(raw) is None

    @pytest.mark.parametrize(
        "raw",
        [
            "http://host/art.jpg",
            "http://192.168.1.200/NetAudio/art.asp-jpg?-123456789",
            "http://192.168.1.200:60006/upnp/desc/aios_device/cover123.jpg",
        ],
    )
    def test_keeps_real_image_urls(self, raw: str) -> None:
        assert sanitize_image_url(raw) == raw

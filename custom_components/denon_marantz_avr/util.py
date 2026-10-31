"""Small shared helpers for the Denon & Marantz AVR integration."""

from __future__ import annotations

from urllib.parse import unquote, urlsplit


def sanitize_image_url(raw: str | None) -> str | None:
    """
    Return a usable cover-art URL, or ``None`` when there is no artwork.

    Some receivers report missing album art as an empty string, sometimes a
    JSON empty string (``""``). That value can still be appended to a device
    URL, leaving a final path segment of ``""`` or empty, e.g.
    ``http://host:60006/upnp/desc/aios_device/%22%22``. Home Assistant's image
    proxy then logs a warning for a URL that can never resolve. Treat such a
    value as "no image" so the media player reports no cover instead.
    """
    if not raw:
        return None
    url = raw.strip().strip('"').strip()
    if not url:
        return None
    last_segment = urlsplit(url).path.rsplit("/", 1)[-1]
    if not unquote(last_segment).strip().strip('"').strip():
        return None
    return url

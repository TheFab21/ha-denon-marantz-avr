"""
Client for the newer Denon/Marantz web control API (port 11080).

Recent Denon/Marantz receivers (HEOS era, e.g. the Marantz CINEMA / Denon
AVR-X series) serve an internal control API on port 11080 that the
``denonavr`` library does not use. Unlike ``denonavr``'s static
``SOUND_MODE_MAPPING``, this endpoint returns the *real* list of sound modes
the receiver currently offers for the active input/signal, and which one is
selected:

    GET http://<host>:11080/ajax/control/get_config?type=9
    -> <SoundModeSettings>
         <Genre>1</Genre>
         <SoundMode><List>
           <Item index="1" selected="2">Stereo</Item>
           <Item index="3" selected="1">DTS Neural:X</Item>   (selected="1" = active)
           ...
         </List></SoundMode>
       </SoundModeSettings>

Selecting a mode uses the item's index:

    GET http://<host>:11080/ajax/control/set_config?type=4&data=<SoundMode>3</SoundMode>

Older receivers do not serve this port; callers must treat a ``None`` result
as "not supported" and fall back to the library behaviour.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING
from xml.etree import ElementTree as ET

import httpx

if TYPE_CHECKING:
    from collections.abc import Sequence

_LOGGER = logging.getLogger(__name__)

WEBAPI_PORT = 11080
_TIMEOUT = 4.0
_GET_SOUND_MODE_TYPE = 9
_GET_AUDIO_TYPE = 1
_SET_TYPE = 4

# Channel index -> label, taken from the receiver's own web app (the
# ``InputSignal`` and ``ActiveSpeaker`` tables served on port 11080). Both
# share one index space; ActiveSpeaker covers more speaker positions (heights,
# tops, wides, ...) than the input-signal display.
INPUT_SIGNAL_CHANNELS: dict[int, str] = {
    0: "FL",
    1: "FR",
    2: "C",
    3: "LFE",
    5: "SL",
    6: "SR",
    7: "SBL",
    8: "SBR",
    9: "SB",
    10: "FWL",
    11: "FWR",
    12: "FHL",
    13: "FHR",
    24: "SHL",
    25: "SHR",
    30: "CH",
    31: "TS",
    35: "EXT",
}
ACTIVE_SPEAKER_CHANNELS: dict[int, str] = {
    0: "FL",
    1: "FR",
    2: "C",
    3: "SW",
    5: "SL",
    6: "SR",
    7: "SBL",
    8: "SBR",
    9: "SB",
    10: "FWL",
    11: "FWR",
    12: "FHL",
    13: "FHR",
    14: "FDL",
    15: "FDR",
    16: "TFL",
    17: "TFR",
    18: "TML",
    19: "TMR",
    20: "SDL",
    21: "SDR",
    22: "TRL",
    23: "TRR",
    24: "SHL",
    25: "SHR",
    26: "RHL",
    27: "RHR",
    28: "BDL",
    29: "BDR",
    30: "CH",
    31: "TS",
}

# Per-speaker value: "2" = active (present in the signal / speaker playing),
# "1" = available but idle, "0" = not present.
_CHANNEL_ACTIVE = "2"


@dataclass(frozen=True)
class SoundModeItem:
    """A single selectable sound mode reported by the receiver."""

    index: int
    name: str
    selected: bool


@dataclass(frozen=True)
class SoundModeSettings:
    """The receiver's current sound-mode list for the active input."""

    genre: int | None
    items: Sequence[SoundModeItem]

    @property
    def names(self) -> list[str]:
        """Return the selectable sound-mode names, in receiver order."""
        return [item.name for item in self.items]

    @property
    def current(self) -> str | None:
        """Return the name of the currently selected sound mode."""
        for item in self.items:
            if item.selected:
                return item.name
        return None

    def index_for(self, name: str) -> int | None:
        """Return the receiver index for a mode name, if present."""
        for item in self.items:
            if item.name == name:
                return item.index
        return None


def _base_url(host: str) -> str:
    return f"http://{host}:{WEBAPI_PORT}/ajax/control"


def _parse_sound_modes(text: str) -> SoundModeSettings | None:
    """Parse a get_config?type=9 XML body."""
    try:
        root = ET.fromstring(text)  # noqa: S314 - trusted local device
    except ET.ParseError:
        return None
    if root.tag != "SoundModeSettings":
        return None
    genre_text = root.findtext("Genre")
    genre = int(genre_text) if genre_text and genre_text.isdigit() else None
    items: list[SoundModeItem] = []
    for item in root.findall("./SoundMode/List/Item"):
        index_attr = item.get("index")
        name = (item.text or "").strip()
        if not index_attr or not index_attr.isdigit() or not name:
            continue
        items.append(
            SoundModeItem(
                index=int(index_attr),
                name=name,
                selected=item.get("selected") == "1",
            )
        )
    if not items:
        return None
    return SoundModeSettings(genre=genre, items=items)


async def async_get_sound_mode_settings(
    client: httpx.AsyncClient, host: str
) -> SoundModeSettings | None:
    """Fetch the real sound-mode list, or None if the API is unavailable."""
    try:
        response = await client.get(
            f"{_base_url(host)}/get_config",
            params={"type": _GET_SOUND_MODE_TYPE},
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
    except (httpx.HTTPError, OSError) as err:
        _LOGGER.debug("Web API sound-mode read failed for %s: %s", host, err)
        return None
    return _parse_sound_modes(response.text)


async def _async_set(
    client: httpx.AsyncClient, host: str, data: str, what: str
) -> bool:
    try:
        response = await client.get(
            f"{_base_url(host)}/set_config",
            params={"type": _SET_TYPE, "data": data},
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
    except (httpx.HTTPError, OSError) as err:
        _LOGGER.debug("Web API %s set failed for %s: %s", what, host, err)
        return False
    return True


async def async_select_sound_mode(
    client: httpx.AsyncClient, host: str, index: int
) -> bool:
    """Select a sound mode by its receiver index. Return True on success."""
    return await _async_set(
        client, host, f"<SoundMode>{index}</SoundMode>", "sound-mode"
    )


async def async_select_genre(client: httpx.AsyncClient, host: str, index: int) -> bool:
    """Select a sound category (genre) by its 1-based index."""
    return await _async_set(client, host, f"<Genre>{index}</Genre>", "genre")


@dataclass(frozen=True)
class AudioInfo:
    """Current audio status (active channels) from the port-11080 web API."""

    input_signal: list[str]
    active_speakers: list[str]

    @property
    def input_signal_text(self) -> str | None:
        """Return the input-signal channels as text, or None when empty."""
        return " ".join(self.input_signal) or None

    @property
    def active_speakers_text(self) -> str | None:
        """Return the active-speaker channels as text, or None when empty."""
        return " ".join(self.active_speakers) or None


def _active_channels(parent: ET.Element | None, names: dict[int, str]) -> list[str]:
    """Return the labels of the active (value "2") speakers in a section."""
    channels: list[str] = []
    if parent is None:
        return channels
    for item in parent.findall("./List/Speaker"):
        index_attr = item.get("index")
        if (
            index_attr
            and index_attr.isdigit()
            and (item.text or "").strip() == _CHANNEL_ACTIVE
        ):
            name = names.get(int(index_attr))
            if name:
                channels.append(name)
    return channels


def _parse_audio(text: str) -> AudioInfo | None:
    """Parse an audio get_config?type=1 XML body."""
    try:
        root = ET.fromstring(text)  # noqa: S314 - trusted local device
    except ET.ParseError:
        return None
    if root.tag != "Audio":
        return None
    return AudioInfo(
        input_signal=_active_channels(root.find("InputSignal"), INPUT_SIGNAL_CHANNELS),
        active_speakers=_active_channels(
            root.find("ActiveSpeaker"), ACTIVE_SPEAKER_CHANNELS
        ),
    )


async def async_get_audio_info(
    client: httpx.AsyncClient, host: str
) -> AudioInfo | None:
    """Fetch the active input-signal / speaker channels, or None if absent."""
    try:
        response = await client.get(
            f"http://{host}:{WEBAPI_PORT}/ajax/audio/get_config",
            params={"type": _GET_AUDIO_TYPE},
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
    except (httpx.HTTPError, OSError) as err:
        _LOGGER.debug("Web API audio read failed for %s: %s", host, err)
        return None
    return _parse_audio(response.text)

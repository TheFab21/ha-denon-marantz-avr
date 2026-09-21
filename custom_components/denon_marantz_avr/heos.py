"""
Optional HEOS (network streaming) support via pyheos.

Recent Denon/Marantz receivers include HEOS Built-in. This module opens an
optional connection to the receiver's own HEOS player (port 1255) and
resolves the :class:`pyheos.HeosPlayer` that matches this receiver's IP, so
a dedicated streaming media player can offer now-playing, transport,
favorites/inputs and media browsing.

Everything here is best-effort: if the receiver has no HEOS interface, or
pyheos cannot connect, the integration keeps working exactly as before and
no streaming entity is created.
"""

from __future__ import annotations

import logging
from contextlib import suppress
from typing import TYPE_CHECKING

from pyheos import Heos, HeosError, HeosOptions

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pyheos import HeosPlayer, MediaItem

_LOGGER = logging.getLogger(__name__)


class HeosStreaming:
    """Manage the optional HEOS connection for a single receiver."""

    def __init__(self, host: str) -> None:
        """Initialize the HEOS connection wrapper."""
        self._host = host
        self.heos = Heos(
            HeosOptions(
                host,
                all_progress_events=False,
                auto_reconnect=True,
                auto_failover=False,
            )
        )
        self.player: HeosPlayer | None = None
        self.favorites: dict[int, MediaItem] = {}
        self.inputs: Sequence[MediaItem] = []
        self.connected = False

    async def async_connect(self) -> bool:
        """
        Connect and resolve this receiver's HEOS player.

        Returns True when a matching player was found and the streaming
        entity should be created.
        """
        try:
            await self.heos.connect()
            await self.heos.get_players()
        except HeosError as err:
            _LOGGER.debug("HEOS unavailable for %s: %s", self._host, err)
            with suppress(HeosError):
                await self.heos.disconnect()
            return False

        self.player = next(
            (
                player
                for player in self.heos.players.values()
                if player.ip_address == self._host
            ),
            None,
        )
        if self.player is None:
            _LOGGER.debug("No HEOS player matches host %s", self._host)
            with suppress(HeosError):
                await self.heos.disconnect()
            return False

        self.connected = True
        self.heos.add_on_connected(self._on_connected)
        self.heos.add_on_disconnected(self._on_disconnected)
        await self.async_update_sources()
        return True

    async def _on_connected(self) -> None:
        self.connected = True
        await self.async_update_sources()

    async def _on_disconnected(self) -> None:
        self.connected = False

    async def async_update_sources(self) -> None:
        """Refresh favorites and input sources (best-effort)."""
        self.favorites = {}
        self.inputs = []
        if self.heos.is_signed_in:
            with suppress(HeosError):
                self.favorites = await self.heos.get_favorites()
        with suppress(HeosError):
            self.inputs = await self.heos.get_input_sources()

    def source_list(self) -> list[str]:
        """Return favorite + input source names."""
        names = [favorite.name for favorite in self.favorites.values()]
        names.extend(source.name for source in self.inputs)
        return names

    def favorite_index(self, name: str) -> int | None:
        """Return the preset index of a favorite by name."""
        for index, favorite in self.favorites.items():
            if favorite.name == name:
                return index
        return None

    async def async_disconnect(self) -> None:
        """Disconnect from HEOS."""
        with suppress(Exception):
            self.heos.dispatcher.disconnect_all()
        with suppress(Exception):
            await self.heos.disconnect()
        self.connected = False

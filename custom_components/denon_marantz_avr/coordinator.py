"""
Data coordinator for the native Audyssey/Eco controls.

This coordinator drives the extra receiver controls (Dynamic EQ, Dynamic
Volume, Reference Level Offset, MultiEQ, Eco mode and the Audyssey/recover
buttons) that the media player does not expose. It reuses the same
:class:`denonavr.DenonAVR` instance created for the media player, so no second
connection to the receiver is opened.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from denonavr.exceptions import DenonAvrError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONTROLS_SCAN_INTERVAL,
    DEFAULT_POWER_OFF_DELAY,
    DEFAULT_POWER_ON_DELAY,
    DOMAIN,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from denonavr import DenonAVR
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class DenonControlsCoordinator(DataUpdateCoordinator[None]):
    """Coordinate receiver control updates and serialize commands."""

    def __init__(
        self,
        hass: HomeAssistant,
        receiver: DenonAVR,
        device_id: str,
    ) -> None:
        """Initialize the coordinator around an existing receiver."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=CONTROLS_SCAN_INTERVAL,
        )
        self.receiver = receiver
        self.device_id = device_id
        self.command_lock = asyncio.Lock()

    async def _async_update_data(self) -> None:
        """
        Read current receiver and Audyssey settings.

        The plain receiver update must succeed for the controls to be
        available, but the Audyssey read is best-effort: some models or
        sound modes do not expose it, and a failure there should not take
        the whole integration down.
        """
        try:
            async with self.command_lock:
                await self.receiver.async_update()
                with contextlib.suppress(DenonAvrError):
                    await self.receiver.async_update_audyssey()
        except DenonAvrError as err:
            raise UpdateFailed from err

    async def async_run_command(self, command: Callable[[], Awaitable[None]]) -> None:
        """Run one command at a time and refresh Audyssey afterward."""
        async with self.command_lock:
            await command()
            with contextlib.suppress(DenonAvrError):
                await self.receiver.async_update_audyssey()
        self.async_set_updated_data(None)

    async def async_set_eco_mode(self, mode: str) -> None:
        """Set Eco mode and refresh the receiver state."""
        async with self.command_lock:
            await self.receiver.async_eco_mode(mode)
            await self.receiver.async_update()
        self.async_set_updated_data(None)

    async def async_recover_audio(self) -> None:
        """
        Power cycle the receiver and restore its selected input.

        This performs a soft power cycle (standby off/on), it does not cut
        electrical power. The previously selected input is restored once the
        receiver is back online.
        """
        async with self.command_lock:
            await self.receiver.async_update()
            previous_input = self.receiver.input_func
            await self.receiver.async_power_off()
            await asyncio.sleep(DEFAULT_POWER_OFF_DELAY)
            await self.receiver.async_power_on()
            await asyncio.sleep(DEFAULT_POWER_ON_DELAY)
            await self.receiver.async_update()
            if previous_input in self.receiver.input_func_list:
                await self.receiver.async_set_input_func(previous_input)
            with contextlib.suppress(DenonAvrError):
                await self.receiver.async_update_audyssey()
        self.async_set_updated_data(None)

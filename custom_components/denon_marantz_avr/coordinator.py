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
import time
from typing import TYPE_CHECKING

from denonavr.const import ALL_TELNET_EVENTS, POWER_ON
from denonavr.exceptions import DenonAvrError
from homeassistant.core import callback
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONTROLS_SCAN_INTERVAL,
    DEFAULT_POWER_OFF_DELAY,
    DEFAULT_POWER_ON_DELAY,
    DOMAIN,
)
from .webapi import (
    async_get_audio_info,
    async_get_information,
    async_get_sound_mode_settings,
    async_get_video_info,
    async_select_genre,
    async_select_sound_mode,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from denonavr import DenonAVR
    from homeassistant.core import HomeAssistant

    from .webapi import AudioInfo, Information, SoundModeSettings, VideoInfo

_LOGGER = logging.getLogger(__name__)

# The receiver pushes Telnet events in bursts (a batch of property updates
# every few seconds). Coalesce a burst into a single entity refresh instead
# of refreshing once per event.
_TELNET_DEBOUNCE_SECONDS = 0.5

# After changing a web-API setting (sound category/mode), the receiver takes a
# moment to apply it. Wait briefly before reading it back, otherwise the poll
# can return the old value and the entity appears to revert the change.
_WEB_SETTLE_SECONDS = 0.8

# The receiver's port-11080 web server is fragile. When it stops answering,
# leave it alone for this long instead of retrying on every poll.
_WEB_BACKOFF_SECONDS = 300.0


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
        # Coalesce bursts of Telnet events into a single entity refresh.
        self._telnet_debouncer = Debouncer(
            hass,
            _LOGGER,
            cooldown=_TELNET_DEBOUNCE_SECONDS,
            immediate=True,
            function=self._async_push_telnet_update,
        )
        # Real sound-mode list / current category from the port-11080 web API.
        self.sound_modes: SoundModeSettings | None = None
        # Active input-signal / speaker channels from the same web API.
        self.audio_info: AudioInfo | None = None
        # Current source / audio format / decoding (info type 1).
        self.information: Information | None = None
        # Current HDMI video status (info type 3).
        self.video_info: VideoInfo | None = None
        self.web_available = False
        self._web_probed = False
        # Monotonic time before which the web API is left alone (back-off).
        self._web_retry_at = 0.0

    @property
    def _telnet_ok(self) -> bool:
        """Return True while the library's Telnet link keeps state current."""
        return bool(self.receiver.telnet_connected and self.receiver.telnet_healthy)

    def _clear_web_status(self) -> None:
        """Forget the live status blocks (their sensors become unavailable)."""
        self.audio_info = None
        self.information = None
        self.video_info = None

    async def _async_update_web(self) -> None:
        """
        Refresh the web-API sound modes and audio/video status, gently.

        The receiver's port-11080 web server is easy to overwhelm, so:

        * it is only read while the receiver is on (after the first probe);
        * requests go one at a time, never in parallel;
        * the cheap sound-mode read goes first -- if it fails the server is in
          trouble, so the other reads are skipped and the API is left alone
          for a few minutes instead of being retried on every poll.
        """
        if self._web_probed and not self.web_available:
            return
        if self._web_probed and self.receiver.power != POWER_ON:
            self._clear_web_status()
            return
        now = time.monotonic()
        if now < self._web_retry_at:
            return

        client = get_async_client(self.hass)
        host = self.receiver.host
        settings = await async_get_sound_mode_settings(client, host)
        if settings is None:
            if not self._web_probed:
                # First probe: this receiver does not serve the web API.
                self._web_probed = True
                self.web_available = False
                return
            self._web_retry_at = now + _WEB_BACKOFF_SECONDS
            self._clear_web_status()
            _LOGGER.debug(
                "Web API on %s is not answering; pausing web reads for %.0f s",
                host,
                _WEB_BACKOFF_SECONDS,
            )
            return

        self._web_probed = True
        self.web_available = True
        self.sound_modes = settings
        if self.receiver.power != POWER_ON:
            self._clear_web_status()
            return
        self.audio_info = await async_get_audio_info(client, host)
        self.information = await async_get_information(client, host)
        self.video_info = await async_get_video_info(client, host)

    async def async_set_sound_category(self, index: int) -> None:
        """Select a sound-mode category (genre) and refresh."""
        await async_select_genre(get_async_client(self.hass), self.receiver.host, index)
        await asyncio.sleep(_WEB_SETTLE_SECONDS)
        await self.async_request_refresh()

    async def async_set_sound_mode(self, index: int) -> None:
        """Select a sound mode by its web-API index and refresh."""
        await async_select_sound_mode(
            get_async_client(self.hass), self.receiver.host, index
        )
        await asyncio.sleep(_WEB_SETTLE_SECONDS)
        await self.async_request_refresh()

    async def _async_push_telnet_update(self) -> None:
        """
        Refresh the control entities with the latest Telnet-pushed state.

        Only notify the listeners: ``async_set_updated_data`` would also
        reschedule the next poll, and as the receiver pushes events every few
        seconds the periodic refresh (and the web-API status) never ran.
        """
        self.async_update_listeners()

    @callback
    def async_register_telnet_listener(self) -> Callable[[], None]:
        """
        Refresh the control entities in real time on Telnet events.

        Many of the receiver's extra settings (Dialog Enhancer, M-DAX, audio
        delay, Bluetooth transmitter, ...) are only pushed over Telnet. The
        30 s poll already reads their current value, but registering for
        Telnet events lets the controls update immediately. The receiver
        pushes events in bursts, so refreshes are debounced to one per burst.
        Returns a callback that unregisters the listener.
        """

        def _telnet_callback(zone: str, event: str, parameter: str) -> None:  # noqa: ARG001
            self.hass.async_create_task(self._telnet_debouncer.async_call())

        self.receiver.register_callback(ALL_TELNET_EVENTS, _telnet_callback)

        def _unregister() -> None:
            self.receiver.unregister_callback(ALL_TELNET_EVENTS, _telnet_callback)
            self._telnet_debouncer.async_cancel()

        return _unregister

    async def async_send(self, command: Callable[[], Awaitable[None]]) -> None:
        """Run a single receiver command, serialized, then refresh entities."""
        async with self.command_lock:
            await command()
        self.async_set_updated_data(None)

    async def _async_update_data(self) -> None:
        """
        Read current receiver and Audyssey settings.

        While the Telnet link is healthy it already keeps every setting
        current (power, inputs, sound mode, Audyssey, Eco, ...), so the HTTP
        reads are skipped -- the same rule the media player follows. Without
        Telnet, the plain receiver update must succeed for the controls to be
        available, but the Audyssey read is best-effort: some models or sound
        modes do not expose it, and a failure there should not take the
        whole integration down.
        """
        if not self._telnet_ok:
            try:
                async with self.command_lock:
                    await self.receiver.async_update()
                    with contextlib.suppress(DenonAvrError):
                        await self.receiver.async_update_audyssey()
            except DenonAvrError as err:
                raise UpdateFailed from err
        await self._async_update_web()

    async def async_refresh_audyssey(self) -> None:
        """Re-read the Audyssey settings on demand (the Refresh button)."""
        async with self.command_lock:
            with contextlib.suppress(DenonAvrError):
                await self.receiver.async_update_audyssey()
        self.async_update_listeners()

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

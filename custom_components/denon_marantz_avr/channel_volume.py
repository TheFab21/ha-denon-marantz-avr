"""
Channel volume management for Denon/Marantz AVR integration.

This module provides the ChannelVolumeManager class for managing individual
speaker channel volume controls through Home Assistant number entities.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING
from urllib.parse import quote

from denonavr.const import POWER_ON
from denonavr.exceptions import DenonAvrError
from homeassistant.components.number import NumberEntity

from .const import (
    CHANNEL_MAP,
    CHANNEL_VOLUME_STEP_DB,
    CV_TELNET_PORT,
    CV_TELNET_TIMEOUT,
    MAX_CHANNEL_VOLUME_DB,
    MIN_CHANNEL_VOLUME_DB,
    ZONE_PREFIXES,
)

if TYPE_CHECKING:
    from denonavr import DenonAVR
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Debounce window for coordinated receiver updates.
# HA polls entities every 10 s; any entity calls within this window
# after the first successful HTTP update are no-ops.
_RECEIVER_UPDATE_DEBOUNCE_S: float = 5.0

# HTTP endpoint that accepts the same raw command strings as Telnet. Used as a
# fallback when the library's Telnet connection is not available.
_APP_DIRECT_PATH = "/goform/formiPhoneAppDirect.xml?"


class ChannelVolumeManager:
    """
    Manages channel volume entities and communication with the receiver.

    This class coordinates channel volume functionality by:
    - Creating and managing ChannelVolumeNumber entities
    - Sending CV commands through the library's own Telnet connection (or the
      HTTP AppDirect endpoint when Telnet is down) -- never a second Telnet
      connection: the receiver only reliably supports a single Telnet client,
      and an extra, unread connection fills its send buffers and can hang it
    - Receiving CV events via the library's persistent telnet connection
    - Preventing feedback loops using pending counters
    """

    def __init__(
        self,
        receiver: DenonAVR,
        zone: str,
        hass: HomeAssistant,
        unique_id_base: str,
    ) -> None:
        """
        Initialize the channel volume manager.

        Args:
            receiver: DenonAVR instance for communication with the receiver
            zone: Zone name (Main, Zone2, or Zone3)
            hass: Home Assistant instance
            unique_id_base: Base unique ID (not used, kept for compatibility)

        """
        self.receiver = receiver
        self.zone = zone
        self.hass = hass

        # Initialize pending counters for all channels to 0
        # Tracks expected CV events to prevent feedback loops
        self.pending_counters: dict[str, int] = dict.fromkeys(CHANNEL_MAP, 0)

        # Initialize channel volumes for state tracking
        # None indicates value not yet received from receiver
        self.channel_volumes: dict[str, float | None] = dict.fromkeys(CHANNEL_MAP)

        # Store entity references for updates
        # Populated during async_setup
        self.entities: dict[str, object] = {}

        # Track last known power state to detect changes
        self._last_power_state: str | None = None

        # Track receiver availability (network connectivity)
        # This is updated by async_update_receiver
        self.receiver_available: bool = True

        # Coordination for receiver HTTP updates.
        # Lock ensures only one HTTP call runs at a time; timestamp lets
        # subsequent callers within the same poll cycle skip redundantly.
        self._update_lock: asyncio.Lock = asyncio.Lock()
        self._last_receiver_update: float = 0.0

    @property
    def is_receiver_powered_on(self) -> bool:
        """Return True if the receiver is powered on."""
        # Check if receiver power is ON
        return self.receiver.power == POWER_ON

    @property
    def _telnet_ready(self) -> bool:
        """Return True when the library's Telnet connection can be used."""
        return bool(self.receiver.telnet_connected and self.receiver.telnet_healthy)

    async def async_send_cv_command(
        self,
        channel: str,
        value: float,
    ) -> None:
        """
        Send a channel volume command to the receiver.

        Goes through the library's existing Telnet connection when it is
        healthy, otherwise through the HTTP AppDirect endpoint. No extra
        Telnet connection is ever opened for this.

        Args:
            channel: Channel code (FL, FR, C, SL, SR, SW)
            value: Volume in dB (-12.0 to +12.0)

        """
        # Format CV command with zone prefix
        zone_prefix = ZONE_PREFIXES.get(self.zone, "")
        protocol_value = db_to_protocol(value)
        command = f"{zone_prefix}CV{channel} {protocol_value}"

        via_telnet = self._telnet_ready
        if via_telnet:
            # The receiver echoes the change back over Telnet; count it so the
            # echo does not bounce the entity. Increment before sending, as
            # the echo can arrive before the send call returns.
            self.pending_counters[channel] += 1

        try:
            if via_telnet:
                await self.receiver.async_send_telnet_commands(command)
            else:
                await self.receiver.async_get_command(
                    f"{_APP_DIRECT_PATH}{quote(command)}"
                )
            _LOGGER.debug(
                "Sent CV command to %s via %s: %s",
                self.receiver.host,
                "telnet" if via_telnet else "http",
                command,
            )
        except (DenonAvrError, TimeoutError, OSError):
            _LOGGER.exception(
                "Failed to send CV command to %s for channel %s",
                self.receiver.host,
                channel,
            )
            if via_telnet:
                self.pending_counters[channel] -= 1

    def _cv_callback(
        self,
        zone: str,
        event: str,
        parameter: str,
    ) -> None:
        """
        Handle CV events from the persistent telnet connection.

        Args:
            zone: Zone identifier (Main, Zone2, Zone3, or ALL_ZONES)
            event: Event type (should be "CV")
            parameter: Event parameter (e.g., "FL 50")

        """
        # Expected parts count for CV event parameter
        expected_parts = 2

        try:
            # Validate this is for our zone
            if zone not in (self.zone, "ALL_ZONES"):
                return

            # Ignore telnet protocol messages
            if parameter.strip() in ("END", ""):
                return

            # Parse CV event parameter: "FL 50" or "FR 535"
            parts = parameter.strip().split()
            if len(parts) != expected_parts:
                _LOGGER.debug(
                    "Ignoring CV event with unexpected format: %s",
                    parameter,
                )
                return

            channel_code = parts[0]
            protocol_value = parts[1]

            # Validate channel code
            if channel_code not in CHANNEL_MAP:
                _LOGGER.warning(
                    "Unknown channel code in CV event: %s",
                    channel_code,
                )
                return

            # Check pending counter
            if self.pending_counters[channel_code] > 0:
                # Decrement counter and skip entity update (feedback prevention)
                self.pending_counters[channel_code] -= 1
                _LOGGER.debug(
                    "Skipping CV event for %s (pending counter: %d)",
                    channel_code,
                    self.pending_counters[channel_code],
                )
                return

            # Convert protocol value to dB
            db_value = protocol_to_db(protocol_value)

            # Update channel volume state
            self.channel_volumes[channel_code] = db_value

            # Update entity if it exists
            if channel_code in self.entities:
                entity = self.entities[channel_code]
                if hasattr(entity, "async_write_ha_state"):
                    entity.async_write_ha_state()
                    _LOGGER.debug(
                        "Updated %s channel %s to %.1f dB",
                        self.zone,
                        channel_code,
                        db_value,
                    )

        except (ValueError, IndexError) as err:
            _LOGGER.warning(
                "Failed to parse CV event parameter '%s': %s",
                parameter,
                err,
            )
        except Exception:
            _LOGGER.exception(
                "Unexpected error in CV callback for zone %s, event %s, parameter '%s'",
                zone,
                event,
                parameter,
            )

    def _power_callback(
        self,
        zone: str,
        event: str,
        parameter: str,
    ) -> None:
        """
        Handle power state change events.

        Args:
            zone: Zone identifier (Main, Zone2, Zone3, or ALL_ZONES)
            event: Event type (ZM for Main, Z2 for Zone2, Z3 for Zone3)
            parameter: Power state parameter

        """
        try:
            # Validate this is for our zone
            if zone not in (self.zone, "ALL_ZONES"):
                return

            # Check if power state changed
            current_power = self.receiver.power
            if current_power != self._last_power_state:
                _LOGGER.debug(
                    "Power state changed for %s zone %s: %s -> %s",
                    self.receiver.host,
                    self.zone,
                    self._last_power_state,
                    current_power,
                )
                self._last_power_state = current_power

                # Update all channel entities to reflect new availability
                for entity in self.entities.values():
                    if hasattr(entity, "async_schedule_update_ha_state"):
                        entity.async_schedule_update_ha_state(force_refresh=True)

        except Exception:
            _LOGGER.exception(
                "Error in power callback: zone=%s event=%s param=%s",
                zone,
                event,
                parameter,
            )

    async def _get_supported_channels(self) -> list[str]:
        """
        Get all standard channels.

        Returns all standard channels. Entity availability will be managed
        dynamically based on whether the receiver actually reports values
        for each channel.

        Returns:
            List of all standard channel codes (FL, FR, C, SL, SR, SW)

        """
        _LOGGER.debug(
            "Creating entities for all standard channels for %s zone %s",
            self.receiver.host,
            self.zone,
        )
        return list(CHANNEL_MAP.keys())

    async def _query_initial_values(self) -> None:
        """
        Ask the receiver for the current channel levels.

        With the library's Telnet connection up, ``CV?`` is sent through it:
        the receiver answers with ``CV..`` events that reach ``_cv_callback``,
        exactly like any other level change. Only when Telnet is disabled is a
        short-lived connection opened, read once and closed straight away --
        nothing is ever left open and unread on the receiver.
        """
        zone_prefix = ZONE_PREFIXES.get(self.zone, "")
        query_command = f"{zone_prefix}CV?"

        if self._telnet_ready:
            try:
                await self.receiver.async_send_telnet_commands(query_command)
            except (DenonAvrError, TimeoutError, OSError) as err:
                _LOGGER.debug(
                    "Initial CV query over telnet failed for %s zone %s: %s",
                    self.receiver.host,
                    self.zone,
                    err,
                )
            return

        response = await self._async_query_short_lived(query_command)
        if response is not None:
            self._apply_cv_response(response)

    async def _async_query_short_lived(self, command: str) -> str | None:
        """Send one query on a temporary Telnet connection and close it."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.receiver.host, CV_TELNET_PORT),
                timeout=CV_TELNET_TIMEOUT,
            )
        except (TimeoutError, OSError) as err:
            _LOGGER.warning(
                "Failed to query initial channel values for %s zone %s: %s",
                self.receiver.host,
                self.zone,
                err,
            )
            return None
        try:
            writer.write(f"{command}\r".encode("ascii"))
            await writer.drain()
            data = await asyncio.wait_for(reader.read(4096), timeout=CV_TELNET_TIMEOUT)
        except (TimeoutError, OSError) as err:
            _LOGGER.warning(
                "Failed to query initial channel values for %s zone %s: %s",
                self.receiver.host,
                self.zone,
                err,
            )
            return None
        finally:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()
        return data.decode("ascii", errors="replace")

    def _apply_cv_response(self, response: str) -> None:
        """Parse a raw ``CV?`` reply (CR-separated ``CVFL 50`` lines) into levels."""
        expected_parts = 2
        zone_prefix = ZONE_PREFIXES.get(self.zone, "")
        for raw_line in response.split("\r"):
            parsed_line = raw_line.strip()
            if parsed_line.startswith(zone_prefix + "CV"):
                parsed_line = parsed_line[len(zone_prefix) + 2 :]
            elif parsed_line.startswith("CV"):
                parsed_line = parsed_line[2:]
            else:
                continue
            parts = parsed_line.split()
            if len(parts) < expected_parts or parts[0] not in self.channel_volumes:
                continue
            try:
                self.channel_volumes[parts[0]] = protocol_to_db(parts[1])
            except (ValueError, IndexError) as err:
                _LOGGER.warning(
                    "Failed to parse initial CV value '%s' for channel %s: %s",
                    parts[1],
                    parts[0],
                    err,
                )

    async def async_setup(
        self,
        device_info: dict,
        unique_id_base: str,
        device_name: str,
    ) -> list:
        """
        Set up channel volume entities.

        Args:
            device_info: Device information for entity registration
            unique_id_base: Base unique ID for entity generation
            device_name: Device name for entity naming

        Returns:
            List of ChannelVolumeNumber entities to add to Home Assistant

        """
        # Get supported channels
        supported_channels = await self._get_supported_channels()

        # Create entities for each supported channel
        entities = []
        for channel in supported_channels:
            entity = ChannelVolumeNumber(
                manager=self,
                channel=channel,
                zone=self.zone,
                device_info=device_info,
                unique_id_base=unique_id_base,
                device_name=device_name,
            )
            entities.append(entity)
            self.entities[channel] = entity

        return entities

    async def async_initialize(self) -> None:
        """
        Initialize channel volume manager after entities are added to HA.

        This must be called after entities are added to Home Assistant to ensure
        the hass attribute is set before any callbacks are triggered.
        """
        # Register CV callback with receiver's telnet callback system
        try:
            if hasattr(self.receiver, "register_callback"):
                self.receiver.register_callback("CV", self._cv_callback)
                _LOGGER.debug(
                    "Registered CV callback for %s zone %s",
                    self.receiver.host,
                    self.zone,
                )
        except Exception:
            _LOGGER.exception(
                "Failed to register CV callback for %s zone %s",
                self.receiver.host,
                self.zone,
            )

        # Register power state callback
        try:
            if hasattr(self.receiver, "register_callback"):
                # Register for zone-specific power events
                if self.zone == "Main":
                    power_event = "ZM"
                elif self.zone == "Zone2":
                    power_event = "Z2"
                elif self.zone == "Zone3":
                    power_event = "Z3"
                else:
                    power_event = "ZM"  # Default to main zone

                self.receiver.register_callback(power_event, self._power_callback)
                _LOGGER.debug(
                    "Registered power callback (%s) for %s zone %s",
                    power_event,
                    self.receiver.host,
                    self.zone,
                )

                # Initialize last power state
                self._last_power_state = self.receiver.power
        except Exception:
            _LOGGER.exception(
                "Failed to register power callback for %s zone %s",
                self.receiver.host,
                self.zone,
            )

        # Query initial channel values to determine availability
        await self._query_initial_values()

    async def async_update_receiver(self) -> None:
        """
        Update receiver state, coordinating across all channel entities.

        Called by every ChannelVolumeNumber.async_update. A lock plus a
        debounce timestamp guarantee that at most one HTTP call to
        receiver.async_update() is made per HA poll cycle, regardless of
        how many channel entities trigger the update simultaneously.
        """
        # Fast path: live telnet proves the receiver is reachable.
        if self.receiver.telnet_connected and self.receiver.telnet_healthy:
            if not self.receiver_available:
                _LOGGER.info(
                    "Receiver %s zone %s is available again (telnet healthy)",
                    self.receiver.host,
                    self.zone,
                )
                self.receiver_available = True
            return

        # Skip if another entity already performed the HTTP update recently.
        loop = asyncio.get_running_loop()
        if loop.time() - self._last_receiver_update < _RECEIVER_UPDATE_DEBOUNCE_S:
            return

        async with self._update_lock:
            # Re-check after acquiring the lock: a concurrent entity may have
            # just completed the update while we were waiting.
            if loop.time() - self._last_receiver_update < _RECEIVER_UPDATE_DEBOUNCE_S:
                return

            try:
                await self.receiver.async_update()
                if not self.receiver_available:
                    _LOGGER.info(
                        "Receiver %s zone %s is available again (HTTP)",
                        self.receiver.host,
                        self.zone,
                    )
                    self.receiver_available = True
                self._last_receiver_update = loop.time()
            except Exception:  # noqa: BLE001
                if self.receiver_available:
                    _LOGGER.warning(
                        "Receiver %s zone %s is unavailable (network error)",
                        self.receiver.host,
                        self.zone,
                    )
                self.receiver_available = False


def protocol_to_db(protocol_value: str, offset: int = 50) -> float:
    """
    Convert protocol value to dB.

    Args:
        protocol_value: String from receiver (2-digit or 3-digit)
        offset: Protocol offset (default 50, so 50 = 0.0 dB)

    Returns:
        Volume in dB

    Examples:
        "53" → +3.0 dB (53 - 50)
        "535" → +3.5 dB (535 / 10 - 50)
        "50" → 0.0 dB
        "38" → -12.0 dB

    """
    # Length for 3-digit half-dB step values
    half_db_length = 3

    protocol_value = protocol_value.strip()
    raw = int(protocol_value)
    if len(protocol_value) == half_db_length:
        # 3-digit: half dB step
        return raw / 10 - offset
    # 2-digit: whole dB step
    return float(raw - offset)


def db_to_protocol(db_value: float, offset: int = 50) -> str:
    """
    Convert dB to protocol value.

    Args:
        db_value: Volume in dB (-12.0 to +12.0)
        offset: Protocol offset (default 50, so 0.0 dB = 50)

    Returns:
        Protocol string (2-digit for whole dB, 3-digit for half dB)

    Examples:
        +3.0 → "53" (whole dB)
        +3.5 → "535" (half dB)
        0.0 → "50"
        -12.0 → "38"

    """
    if db_value % 1 == 0:
        # Whole dB: 2-digit string
        return str(int(db_value) + offset)
    # Half dB: 3-digit string
    return str(int((db_value + offset) * 10))


class ChannelVolumeNumber(NumberEntity):
    """
    Home Assistant number entity for individual channel volume control.

    Represents a single channel's volume as a number entity with proper
    bounds, step size, and unit of measurement.
    """

    # Enable periodic updates
    _attr_should_poll = True

    def __init__(  # noqa: PLR0913
        self,
        manager: ChannelVolumeManager,
        channel: str,
        zone: str,
        device_info: dict,
        *,
        unique_id_base: str,
        device_name: str,
    ) -> None:
        """
        Initialize the channel volume number entity.

        Args:
            manager: ChannelVolumeManager instance for command sending
            channel: Channel code (FL, FR, C, SL, SR, SW)
            zone: Zone name (Main, Zone2, or Zone3)
            device_info: Device information for entity registration
            unique_id_base: Base unique ID for entity generation
            device_name: Device name for entity naming

        """
        super().__init__()

        self._manager = manager
        self._channel = channel
        self._zone = zone

        # Generate entity name and ID
        channel_name = CHANNEL_MAP[channel].lower().replace(" ", "_")

        # Build entity name with device and zone context
        if zone == "Main":
            # Main zone: "Device Front Left Volume"
            self._attr_name = f"{device_name} {CHANNEL_MAP[channel]} Volume"
        else:
            # Other zones: "Device Zone2 Front Left Volume"
            self._attr_name = f"{device_name} {zone} {CHANNEL_MAP[channel]} Volume"

        # Build unique_id
        zone_suffix = "" if zone == "Main" else f"_{zone.lower()}"
        self._attr_unique_id = f"{unique_id_base}{zone_suffix}_{channel_name}_volume"
        self._attr_device_info = device_info

        # Set icon based on channel type
        if channel == "SW":
            self._attr_icon = "mdi:smoke-detector"
        else:
            self._attr_icon = "mdi:speaker"

    async def async_set_native_value(self, value: float) -> None:
        """
        Set the channel volume.

        Args:
            value: Volume in dB (-12.0 to +12.0)

        """
        try:
            # Optimistically update the state before sending the command
            # This ensures the UI reflects the change immediately
            self._manager.channel_volumes[self._channel] = value
            await self._manager.async_send_cv_command(self._channel, value)
        except Exception:
            _LOGGER.exception(
                "Failed to set channel %s volume to %.1f dB",
                self._channel,
                value,
            )

    async def async_update(self) -> None:
        """
        Update entity state.

        Delegates to the manager so that all channel entities share a single
        receiver.async_update() call per HA poll cycle instead of each
        issuing an independent HTTP request.
        """
        await self._manager.async_update_receiver()

    @property
    def native_value(self) -> float | None:
        """Return the current channel volume in dB."""
        return self._manager.channel_volumes.get(self._channel)

    @property
    def available(self) -> bool:
        """
        Return True if entity is available.

        A channel is considered available if:
        1. The receiver is available (responding to network requests)
        2. The receiver is powered on
        3. We've received at least one CV event for it from the receiver

        Note: Receiver availability is tracked by the async_update method
        which catches network errors.
        """
        receiver_powered_on = self._manager.is_receiver_powered_on
        has_value = self._manager.channel_volumes.get(self._channel) is not None

        return self._manager.receiver_available and receiver_powered_on and has_value

    @property
    def native_min_value(self) -> float:
        """Return minimum volume (-12.0 dB)."""
        return MIN_CHANNEL_VOLUME_DB

    @property
    def native_max_value(self) -> float:
        """Return maximum volume (+12.0 dB)."""
        return MAX_CHANNEL_VOLUME_DB

    @property
    def native_step(self) -> float:
        """Return volume step size (0.5 dB)."""
        return CHANNEL_VOLUME_STEP_DB

    @property
    def native_unit_of_measurement(self) -> str:
        """Return unit of measurement (dB)."""
        return "dB"

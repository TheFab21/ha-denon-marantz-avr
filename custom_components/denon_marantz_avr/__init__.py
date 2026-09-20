"""
The Denon & Marantz AVR component.

This integration merges three community projects into a single, complete
custom component for Denon and Marantz network receivers:

* a full media player (HTTP + real-time Telnet push, multi-zone),
* per-channel volume ``number`` entities, and
* the extra Audyssey / Eco ``switch`` / ``select`` / ``button`` controls that
  the core integration does not expose.

Everything is driven from one config entry and one connection to the receiver.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from denonavr.exceptions import AvrNetworkError, AvrTimoutError
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, EVENT_HOMEASSISTANT_STOP
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.httpx_client import get_async_client

from .const import (
    CONF_SHOW_ALL_SOURCES,
    CONF_UPDATE_AUDYSSEY,
    CONF_USE_TELNET,
    CONF_ZONE2,
    CONF_ZONE3,
    DEFAULT_SHOW_SOURCES,
    DEFAULT_TIMEOUT,
    DEFAULT_UPDATE_AUDYSSEY,
    DEFAULT_USE_TELNET,
    DEFAULT_ZONE2,
    DEFAULT_ZONE3,
    PLATFORMS,
)
from .coordinator import DenonControlsCoordinator
from .receiver import ConnectDenonAVR

if TYPE_CHECKING:
    from denonavr import DenonAVR
    from homeassistant.core import Event, HomeAssistant

_LOGGER = logging.getLogger(__name__)


@dataclass
class DenonMarantzData:
    """Runtime data shared by every platform of this integration."""

    receiver: DenonAVR
    controls: DenonControlsCoordinator


type DenonavrConfigEntry = ConfigEntry[DenonMarantzData]


async def async_setup_entry(hass: HomeAssistant, entry: DenonavrConfigEntry) -> bool:
    """Set up the Denon & Marantz AVR components from a config entry."""
    # Connect to receiver
    connect_denonavr = ConnectDenonAVR(
        entry.data[CONF_HOST],
        DEFAULT_TIMEOUT,
        entry.options.get(CONF_SHOW_ALL_SOURCES, DEFAULT_SHOW_SOURCES),
        entry.options.get(CONF_ZONE2, DEFAULT_ZONE2),
        entry.options.get(CONF_ZONE3, DEFAULT_ZONE3),
        entry.options.get(CONF_USE_TELNET, DEFAULT_USE_TELNET),
        entry.options.get(CONF_UPDATE_AUDYSSEY, DEFAULT_UPDATE_AUDYSSEY),
        lambda: get_async_client(hass),
    )
    try:
        await connect_denonavr.async_connect_receiver()
    except (AvrNetworkError, AvrTimoutError) as ex:
        raise ConfigEntryNotReady from ex
    receiver = connect_denonavr.receiver
    if receiver is None:
        raise ConfigEntryNotReady

    # Coordinator for the extra Audyssey / Eco controls. It reuses the same
    # receiver instance, so no second connection is opened.
    device_id = entry.unique_id or entry.entry_id
    controls = DenonControlsCoordinator(hass, receiver, device_id)
    await controls.async_config_entry_first_refresh()

    entry.runtime_data = DenonMarantzData(receiver=receiver, controls=controls)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    use_telnet = entry.options.get(CONF_USE_TELNET, DEFAULT_USE_TELNET)

    async def _async_disconnect(_event: Event) -> None:
        """Disconnect from Telnet."""
        if use_telnet and receiver is not None:
            await receiver.async_telnet_disconnect()

    if use_telnet:
        entry.async_on_unload(
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_disconnect)
        )

    return True


async def async_unload_entry(
    hass: HomeAssistant, config_entry: DenonavrConfigEntry
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    )

    if config_entry.options.get(CONF_USE_TELNET, DEFAULT_USE_TELNET):
        receiver = config_entry.runtime_data.receiver
        await receiver.async_telnet_disconnect()

    # Remove zone2 and zone3 entities if needed
    entity_registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(entity_registry, config_entry.entry_id)
    unique_id = config_entry.unique_id or config_entry.entry_id
    zone2_id = f"{unique_id}-Zone2"
    zone3_id = f"{unique_id}-Zone3"
    for entry in entries:
        if entry.unique_id == zone2_id and not config_entry.options.get(CONF_ZONE2):
            entity_registry.async_remove(entry.entity_id)
            _LOGGER.debug("Removing zone2 from Denon/Marantz AVR")
        if entry.unique_id == zone3_id and not config_entry.options.get(CONF_ZONE3):
            entity_registry.async_remove(entry.entity_id)
            _LOGGER.debug("Removing zone3 from Denon/Marantz AVR")

    return unload_ok

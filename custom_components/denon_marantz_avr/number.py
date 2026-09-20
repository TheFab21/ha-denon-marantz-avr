"""Support for Denon AVR channel volume controls."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceInfo

from .channel_volume import ChannelVolumeManager
from .const import CONF_MANUFACTURER, CONF_SERIAL_NUMBER, DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import DenonavrConfigEntry

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: DenonavrConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up channel volume number entities from a config entry."""
    receiver = config_entry.runtime_data.receiver
    entities = []
    managers = []

    try:
        # Create ChannelVolumeManager for each zone
        for zone_name in receiver.zones:
            # Generate unique_id_base for this zone
            if config_entry.data[CONF_SERIAL_NUMBER] is not None:
                unique_id_base = f"{config_entry.unique_id}"
            else:
                unique_id_base = f"{config_entry.entry_id}"

            # Create device info for entity registration
            device_info = DeviceInfo(
                identifiers={(DOMAIN, unique_id_base)},
                manufacturer=config_entry.data.get(CONF_MANUFACTURER, "Denon"),
                name=receiver.name,
                model=receiver.model_name,
            )

            # Create manager for this zone
            manager = ChannelVolumeManager(
                receiver=receiver,
                zone=zone_name,
                hass=hass,
                unique_id_base=unique_id_base,
            )
            managers.append(manager)

            # Set up entities for this zone
            zone_entities = await manager.async_setup(
                device_info=device_info,
                unique_id_base=unique_id_base,
                device_name=receiver.name,
            )
            entities.extend(zone_entities)

        _LOGGER.debug(
            "Created %d channel volume entities for %s at %s",
            len(entities),
            receiver.manufacturer,
            receiver.host,
        )

        # Add all entities to Home Assistant
        async_add_entities(entities, update_before_add=False)

        # Initialize managers after entities are added to HA
        for manager in managers:
            await manager.async_initialize()

    except Exception:
        _LOGGER.exception(
            "Failed to set up channel volume entities for %s",
            receiver.host,
        )

"""Support for Denon AVR channel volume controls."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.number import NumberEntity
from homeassistant.const import UnitOfTime
from homeassistant.helpers.device_registry import DeviceInfo

from .channel_volume import ChannelVolumeManager
from .const import (
    CONF_MANUFACTURER,
    CONF_SERIAL_NUMBER,
    DOMAIN,
    MAX_DELAY_TIME_MS,
    MAX_SLEEP_MINUTES,
    MIN_DELAY_TIME_MS,
    MIN_SLEEP_MINUTES,
)
from .entity import DenonControlsEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import DenonavrConfigEntry
    from .coordinator import DenonControlsCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: DenonavrConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up number entities (audio delay, sleep timer, channel volume)."""
    coordinator = config_entry.runtime_data.controls
    receiver = coordinator.receiver

    # Telnet-only receiver settings, only added when the receiver reports them.
    control_numbers: list[NumberEntity] = []
    if receiver.delay_time is not None:
        control_numbers.append(AudioDelayNumber(coordinator))
    if receiver.sleep is not None:
        control_numbers.append(SleepTimerNumber(coordinator))
    if control_numbers:
        async_add_entities(control_numbers)

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


class AudioDelayNumber(DenonControlsEntity, NumberEntity):
    """Control the receiver's audio delay (in milliseconds)."""

    _attr_translation_key = "audio_delay"
    _attr_native_min_value = MIN_DELAY_TIME_MS
    _attr_native_max_value = MAX_DELAY_TIME_MS
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MILLISECONDS

    def __init__(self, coordinator: DenonControlsCoordinator) -> None:
        """Initialize the audio delay number."""
        super().__init__(coordinator, "audio_delay")

    @property
    def native_value(self) -> float | None:
        """Return the current audio delay in ms."""
        return self.coordinator.receiver.delay_time

    async def async_set_native_value(self, value: float) -> None:
        """Set the audio delay."""
        await self.coordinator.async_send(
            lambda: self.coordinator.receiver.async_delay_time(int(value))
        )


class SleepTimerNumber(DenonControlsEntity, NumberEntity):
    """Control the receiver's sleep timer (0 = off, in minutes)."""

    _attr_translation_key = "sleep_timer"
    _attr_native_min_value = MIN_SLEEP_MINUTES
    _attr_native_max_value = MAX_SLEEP_MINUTES
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def __init__(self, coordinator: DenonControlsCoordinator) -> None:
        """Initialize the sleep timer number."""
        super().__init__(coordinator, "sleep_timer")

    @property
    def native_value(self) -> float | None:
        """Return the current sleep timer in minutes (0 when off)."""
        sleep = self.coordinator.receiver.sleep
        if sleep is None:
            return None
        if sleep == "OFF":
            return 0
        return int(sleep)

    async def async_set_native_value(self, value: float) -> None:
        """Set the sleep timer; 0 turns it off."""
        minutes = int(value)
        target = "OFF" if minutes <= 0 else minutes
        await self.coordinator.async_send(
            lambda: self.coordinator.receiver.async_sleep(target)
        )

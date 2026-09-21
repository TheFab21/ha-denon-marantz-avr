"""Switch entities for the Denon/Marantz AVR controls."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity

from .const import CONF_USE_TELNET, DEFAULT_USE_TELNET
from .entity import DenonControlsEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import DenonavrConfigEntry
    from .coordinator import DenonControlsCoordinator


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: DenonavrConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up switch controls."""
    coordinator = entry.runtime_data.controls

    entities: list[SwitchEntity] = [DynamicEqSwitch(coordinator)]

    # Telnet-only settings. They arrive asynchronously after connect, so they
    # are created whenever Telnet is enabled (not gated on the racy initial
    # value) and show their state once the receiver reports it.
    if entry.options.get(CONF_USE_TELNET, DEFAULT_USE_TELNET):
        entities.append(BluetoothTransmitterSwitch(coordinator))
        entities.append(GraphicEqSwitch(coordinator))

    async_add_entities(entities)


class DynamicEqSwitch(DenonControlsEntity, SwitchEntity):
    """Control Audyssey Dynamic EQ."""

    _attr_translation_key = "dynamic_eq"

    def __init__(self, coordinator: DenonControlsCoordinator) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, "dynamic_eq")

    @property
    def is_on(self) -> bool | None:
        """Return whether Dynamic EQ is enabled."""
        return self.coordinator.receiver.audyssey.dynamic_eq

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable Dynamic EQ."""
        await self.coordinator.async_run_command(
            self.coordinator.receiver.audyssey.async_dynamiceq_on
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable Dynamic EQ."""
        await self.coordinator.async_run_command(
            self.coordinator.receiver.audyssey.async_dynamiceq_off
        )


class BluetoothTransmitterSwitch(DenonControlsEntity, SwitchEntity):
    """Control the receiver's Bluetooth transmitter."""

    _attr_translation_key = "bt_transmitter"

    def __init__(self, coordinator: DenonControlsCoordinator) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, "bt_transmitter")

    @property
    def is_on(self) -> bool | None:
        """Return whether the Bluetooth transmitter is on."""
        return self.coordinator.receiver.bt_transmitter

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the Bluetooth transmitter on."""
        await self.coordinator.async_send(
            self.coordinator.receiver.async_bt_transmitter_on
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the Bluetooth transmitter off."""
        await self.coordinator.async_send(
            self.coordinator.receiver.async_bt_transmitter_off
        )


class GraphicEqSwitch(DenonControlsEntity, SwitchEntity):
    """Control the receiver's Graphic EQ."""

    _attr_translation_key = "graphic_eq"

    def __init__(self, coordinator: DenonControlsCoordinator) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, "graphic_eq")

    @property
    def is_on(self) -> bool | None:
        """Return whether the Graphic EQ is enabled."""
        return self.coordinator.receiver.graphic_eq

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the Graphic EQ."""
        await self.coordinator.async_send(self.coordinator.receiver.async_graphic_eq_on)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the Graphic EQ."""
        await self.coordinator.async_send(
            self.coordinator.receiver.async_graphic_eq_off
        )

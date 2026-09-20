"""Switch entities for the Denon/Marantz AVR controls."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity

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
    async_add_entities([DynamicEqSwitch(entry.runtime_data.controls)])


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

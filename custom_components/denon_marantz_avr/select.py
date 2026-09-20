"""Select entities for the Denon/Marantz AVR controls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity, SelectEntityDescription

from .const import ECO_MODE_OPTIONS
from .entity import DenonControlsEntity

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import DenonavrConfigEntry
    from .coordinator import DenonControlsCoordinator


@dataclass(frozen=True, kw_only=True)
class AudysseySelectDescription(SelectEntityDescription):
    """Describe an Audyssey select."""

    value_fn: Callable[[], str | None]
    options_fn: Callable[[], list[str]]
    set_fn: Callable[[str], Awaitable[None]]


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: DenonavrConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up receiver select controls."""
    coordinator = entry.runtime_data.controls
    audyssey = coordinator.receiver.audyssey
    descriptions = (
        AudysseySelectDescription(
            key="dynamic_volume",
            translation_key="dynamic_volume",
            value_fn=lambda: audyssey.dynamic_volume,
            options_fn=lambda: audyssey.dynamic_volume_setting_list,
            set_fn=audyssey.async_set_dynamicvol,
        ),
        AudysseySelectDescription(
            key="reference_level_offset",
            translation_key="reference_level_offset",
            value_fn=lambda: audyssey.reference_level_offset,
            options_fn=lambda: audyssey.reference_level_offset_setting_list,
            set_fn=audyssey.async_set_reflevoffset,
        ),
        AudysseySelectDescription(
            key="multi_eq",
            translation_key="multi_eq",
            value_fn=lambda: audyssey.multi_eq,
            options_fn=lambda: audyssey.multi_eq_setting_list,
            set_fn=audyssey.async_set_multieq,
        ),
    )
    async_add_entities(
        [
            *(AudysseySelect(coordinator, description) for description in descriptions),
            EcoModeSelect(coordinator),
        ]
    )


class AudysseySelect(DenonControlsEntity, SelectEntity):
    """Represent an Audyssey setting."""

    def __init__(
        self,
        coordinator: DenonControlsCoordinator,
        description: AudysseySelectDescription,
    ) -> None:
        """Initialize an Audyssey select."""
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._attr_translation_key = description.translation_key

    @property
    def available(self) -> bool:
        """Return whether this setting can currently be changed."""
        if self.entity_description.key == "reference_level_offset":
            return (
                super().available
                and self.coordinator.receiver.audyssey.dynamic_eq is True
            )
        return super().available

    @property
    def current_option(self) -> str | None:
        """Return the current setting."""
        return self.entity_description.value_fn()

    @property
    def options(self) -> list[str]:
        """Return available settings."""
        return self.entity_description.options_fn() or []

    async def async_select_option(self, option: str) -> None:
        """Change the setting."""
        if self.entity_description.key == "reference_level_offset":
            await self.coordinator.async_request_refresh()
        await self.coordinator.async_run_command(
            lambda: self.entity_description.set_fn(option)
        )


class EcoModeSelect(DenonControlsEntity, SelectEntity):
    """Display and control the receiver's Eco mode."""

    _attr_translation_key = "eco_mode"
    _attr_options = ECO_MODE_OPTIONS

    def __init__(self, coordinator: DenonControlsCoordinator) -> None:
        """Initialize the Eco mode select."""
        super().__init__(coordinator, "eco_mode")

    @property
    def current_option(self) -> str | None:
        """Return the current Eco mode."""
        return self.coordinator.receiver.eco_mode

    async def async_select_option(self, option: str) -> None:
        """Change the Eco mode."""
        await self.coordinator.async_set_eco_mode(option)

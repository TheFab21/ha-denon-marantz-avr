"""Button entities for the Denon/Marantz AVR controls."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription

from .entity import DenonControlsEntity

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import DenonavrConfigEntry
    from .coordinator import DenonControlsCoordinator


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: DenonavrConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up receiver buttons."""
    coordinator = entry.runtime_data.controls
    async_add_entities(
        [
            DenonButton(
                coordinator,
                ButtonEntityDescription(
                    key="refresh_audyssey", translation_key="refresh_audyssey"
                ),
                coordinator.async_request_refresh,
            ),
            DenonButton(
                coordinator,
                ButtonEntityDescription(
                    key="recover_audio", translation_key="recover_audio"
                ),
                coordinator.async_recover_audio,
            ),
        ]
    )


class DenonButton(DenonControlsEntity, ButtonEntity):
    """Represent a receiver command button."""

    def __init__(
        self,
        coordinator: DenonControlsCoordinator,
        description: ButtonEntityDescription,
        press_action: Callable[[], Awaitable[None]],
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._press_action = press_action

    async def async_press(self) -> None:
        """Run the receiver command."""
        await self._press_action()

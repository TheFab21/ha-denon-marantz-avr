"""Sensor entities for the Denon/Marantz AVR web-API audio status."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.sensor import SensorEntity

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
    """Set up the audio-status sensors (only when the web API is available)."""
    coordinator = entry.runtime_data.controls
    if not coordinator.web_available or coordinator.audio_info is None:
        return
    async_add_entities(
        [
            InputSignalSensor(coordinator),
            ActiveSpeakersSensor(coordinator),
        ]
    )


class InputSignalSensor(DenonControlsEntity, SensorEntity):
    """The channels present in the incoming audio signal."""

    _attr_translation_key = "input_signal"

    def __init__(self, coordinator: DenonControlsCoordinator) -> None:
        """Initialize the input-signal sensor."""
        super().__init__(coordinator, "input_signal")

    @property
    def native_value(self) -> str | None:
        """Return the active input channels as a space-separated string."""
        audio = self.coordinator.audio_info
        return audio.input_signal_text if audio is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, list[str]]:
        """Return the active input channels as a list."""
        audio = self.coordinator.audio_info
        return {"channels": list(audio.input_signal) if audio is not None else []}


class ActiveSpeakersSensor(DenonControlsEntity, SensorEntity):
    """The speakers the receiver is currently driving."""

    _attr_translation_key = "active_speakers"

    def __init__(self, coordinator: DenonControlsCoordinator) -> None:
        """Initialize the active-speakers sensor."""
        super().__init__(coordinator, "active_speakers")

    @property
    def native_value(self) -> str | None:
        """Return the active speakers as a space-separated string."""
        audio = self.coordinator.audio_info
        return audio.active_speakers_text if audio is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, list[str]]:
        """Return the active speakers as a list."""
        audio = self.coordinator.audio_info
        return {"speakers": list(audio.active_speakers) if audio is not None else []}

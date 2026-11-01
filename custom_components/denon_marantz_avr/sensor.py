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
    """Set up the audio/video-status sensors (only when the web API is up)."""
    coordinator = entry.runtime_data.controls
    if not coordinator.web_available:
        return
    entities: list[SensorEntity] = []
    if coordinator.audio_info is not None:
        entities.append(InputSignalSensor(coordinator))
        entities.append(ActiveSpeakersSensor(coordinator))
        entities.append(DiracSensor(coordinator))
    if coordinator.information is not None:
        entities.append(AudioFormatSensor(coordinator))
        entities.append(DecodedModeSensor(coordinator))
    if coordinator.video_info is not None:
        entities.append(VideoSignalSensor(coordinator))
        entities.append(HdrSensor(coordinator))
        entities.append(AllmSensor(coordinator))
        entities.append(QftSensor(coordinator))
    async_add_entities(entities)


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


class AudioFormatSensor(DenonControlsEntity, SensorEntity):
    """The incoming audio format (e.g. PCM, Dolby TrueHD, DTS-HD MA)."""

    _attr_translation_key = "audio_format"

    def __init__(self, coordinator: DenonControlsCoordinator) -> None:
        """Initialize the audio-format sensor."""
        super().__init__(coordinator, "audio_format")

    @property
    def native_value(self) -> str | None:
        """Return the incoming audio format."""
        info = self.coordinator.information
        return info.signal if info is not None else None


class DecodedModeSensor(DenonControlsEntity, SensorEntity):
    """The active surround decoder / processing (e.g. DTS Neural:X)."""

    _attr_translation_key = "decoded_mode"

    def __init__(self, coordinator: DenonControlsCoordinator) -> None:
        """Initialize the decoded-mode sensor."""
        super().__init__(coordinator, "decoded_mode")

    @property
    def native_value(self) -> str | None:
        """Return the active decoding mode."""
        info = self.coordinator.information
        return info.sound if info is not None else None


class VideoSignalSensor(DenonControlsEntity, SensorEntity):
    """The HDMI video signal (output resolution, with details in attributes)."""

    _attr_translation_key = "video_signal"

    def __init__(self, coordinator: DenonControlsCoordinator) -> None:
        """Initialize the video-signal sensor."""
        super().__init__(coordinator, "video_signal")

    @property
    def native_value(self) -> str | None:
        """Return the output video resolution."""
        video = self.coordinator.video_info
        return video.resolution_out if video is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return the detailed video fields (HDR, color space, depth...)."""
        video = self.coordinator.video_info
        return video.attributes if video is not None else {}


class HdrSensor(DenonControlsEntity, SensorEntity):
    """The HDMI output HDR format (e.g. HDR10, Dolby Vision, or none)."""

    _attr_translation_key = "hdr"

    def __init__(self, coordinator: DenonControlsCoordinator) -> None:
        """Initialize the HDR sensor."""
        super().__init__(coordinator, "hdr")

    @property
    def native_value(self) -> str | None:
        """Return the output HDR format."""
        video = self.coordinator.video_info
        return video.hdr_out if video is not None else None


def _on_off(*, value: bool | None) -> str | None:
    """Map an optional boolean to an "On"/"Off" string."""
    if value is None:
        return None
    return "On" if value else "Off"


class AllmSensor(DenonControlsEntity, SensorEntity):
    """Auto Low Latency Mode (HDMI 2.1 gaming) on the HDMI output."""

    _attr_translation_key = "allm"

    def __init__(self, coordinator: DenonControlsCoordinator) -> None:
        """Initialize the ALLM sensor."""
        super().__init__(coordinator, "allm")

    @property
    def native_value(self) -> str | None:
        """Return whether ALLM is on."""
        video = self.coordinator.video_info
        return _on_off(value=video.allm) if video is not None else None


class QftSensor(DenonControlsEntity, SensorEntity):
    """Quick Frame Transport (HDMI 2.1 gaming) on the HDMI output."""

    _attr_translation_key = "qft"

    def __init__(self, coordinator: DenonControlsCoordinator) -> None:
        """Initialize the QFT sensor."""
        super().__init__(coordinator, "qft")

    @property
    def native_value(self) -> str | None:
        """Return whether QFT is on."""
        video = self.coordinator.video_info
        return _on_off(value=video.qft) if video is not None else None


class DiracSensor(DenonControlsEntity, SensorEntity):
    """Dirac Live room correction state (filter name when active, else Off)."""

    _attr_translation_key = "dirac_live"

    def __init__(self, coordinator: DenonControlsCoordinator) -> None:
        """Initialize the Dirac Live sensor."""
        super().__init__(coordinator, "dirac_live")

    @property
    def native_value(self) -> str | None:
        """Return the Dirac Live state."""
        audio = self.coordinator.audio_info
        return audio.dirac_state if audio is not None else None

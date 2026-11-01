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
    # Create all web-API sensors whenever the receiver's port-11080 API is
    # reachable. The individual audio/video blocks are only populated while a
    # signal is playing, so gating creation on their presence at setup time
    # would permanently drop sensors whenever Home Assistant happens to start
    # with the receiver idle. Each sensor reports None (unknown) until its
    # block appears and updates live from then on.
    entities: list[SensorEntity] = [
        InputSignalSensor(coordinator),
        ActiveSpeakersSensor(coordinator),
        DiracSensor(coordinator),
        AudioFormatSensor(coordinator),
        DecodedModeSensor(coordinator),
        VideoInputSensor(coordinator),
        VideoSignalSensor(coordinator),
        HdrSensor(coordinator),
        AllmSensor(coordinator),
        QftSensor(coordinator),
    ]
    async_add_entities(entities)


class _WebStatusSensor(DenonControlsEntity, SensorEntity):
    """
    Base for a sensor backed by one of the port-11080 status blocks.

    The receiver's web server returns an error for every block while it is
    in standby or transitioning power, which blanks the backing block to
    ``None``. Report the sensor as *unavailable* then, rather than showing a
    misleading "unknown" state, and let it recover automatically once the
    block is read again.
    """

    #: Name of the coordinator attribute holding this sensor's status block.
    _web_block: str

    @property
    def available(self) -> bool:
        """Return True only while this sensor's status block is present."""
        block = getattr(self.coordinator, self._web_block)
        return super().available and block is not None


class InputSignalSensor(_WebStatusSensor):
    """The channels present in the incoming audio signal."""

    _attr_translation_key = "input_signal"
    _web_block = "audio_info"

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


class ActiveSpeakersSensor(_WebStatusSensor):
    """The speakers the receiver is currently driving."""

    _attr_translation_key = "active_speakers"
    _web_block = "audio_info"

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


class AudioFormatSensor(_WebStatusSensor):
    """The incoming audio format (e.g. PCM, Dolby TrueHD, DTS-HD MA)."""

    _attr_translation_key = "audio_format"
    _web_block = "information"

    def __init__(self, coordinator: DenonControlsCoordinator) -> None:
        """Initialize the audio-format sensor."""
        super().__init__(coordinator, "audio_format")

    @property
    def native_value(self) -> str | None:
        """Return the incoming audio format."""
        info = self.coordinator.information
        return info.signal if info is not None else None


class DecodedModeSensor(_WebStatusSensor):
    """The active surround decoder / processing (e.g. DTS Neural:X)."""

    _attr_translation_key = "decoded_mode"
    _web_block = "information"

    def __init__(self, coordinator: DenonControlsCoordinator) -> None:
        """Initialize the decoded-mode sensor."""
        super().__init__(coordinator, "decoded_mode")

    @property
    def native_value(self) -> str | None:
        """Return the active decoding mode."""
        info = self.coordinator.information
        return info.sound if info is not None else None


class VideoInputSensor(_WebStatusSensor):
    """The incoming HDMI video signal (input resolution, details in attributes)."""

    _attr_translation_key = "video_input"
    _web_block = "video_info"

    def __init__(self, coordinator: DenonControlsCoordinator) -> None:
        """Initialize the video-input sensor."""
        super().__init__(coordinator, "video_input")

    @property
    def native_value(self) -> str | None:
        """Return the incoming video resolution."""
        video = self.coordinator.video_info
        return video.resolution_in if video is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return the incoming video fields (HDR, color space, depth, FRL)."""
        video = self.coordinator.video_info
        return video.input_attributes if video is not None else {}


class VideoSignalSensor(_WebStatusSensor):
    """The outgoing HDMI video signal (output resolution, details in attributes)."""

    _attr_translation_key = "video_signal"
    _web_block = "video_info"

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
        """Return the outgoing video fields (HDR, color space, depth, FRL)."""
        video = self.coordinator.video_info
        return video.output_attributes if video is not None else {}


class HdrSensor(_WebStatusSensor):
    """The HDMI output HDR format (e.g. HDR10, Dolby Vision, or none)."""

    _attr_translation_key = "hdr"
    _web_block = "video_info"

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


class AllmSensor(_WebStatusSensor):
    """Auto Low Latency Mode (HDMI 2.1 gaming) on the HDMI output."""

    _attr_translation_key = "allm"
    _web_block = "video_info"

    def __init__(self, coordinator: DenonControlsCoordinator) -> None:
        """Initialize the ALLM sensor."""
        super().__init__(coordinator, "allm")

    @property
    def native_value(self) -> str | None:
        """Return whether ALLM is on."""
        video = self.coordinator.video_info
        return _on_off(value=video.allm) if video is not None else None


class QftSensor(_WebStatusSensor):
    """Quick Frame Transport (HDMI 2.1 gaming) on the HDMI output."""

    _attr_translation_key = "qft"
    _web_block = "video_info"

    def __init__(self, coordinator: DenonControlsCoordinator) -> None:
        """Initialize the QFT sensor."""
        super().__init__(coordinator, "qft")

    @property
    def native_value(self) -> str | None:
        """Return whether QFT is on."""
        video = self.coordinator.video_info
        return _on_off(value=video.qft) if video is not None else None


class DiracSensor(_WebStatusSensor):
    """Dirac Live room correction state (filter name when active, else Off)."""

    _attr_translation_key = "dirac_live"
    _web_block = "audio_info"

    def __init__(self, coordinator: DenonControlsCoordinator) -> None:
        """Initialize the Dirac Live sensor."""
        super().__init__(coordinator, "dirac_live")

    @property
    def native_value(self) -> str | None:
        """Return the Dirac Live state."""
        audio = self.coordinator.audio_info
        return audio.dirac_state if audio is not None else None

"""Support for Denon AVR receivers using their HTTP interface."""

from __future__ import annotations

import logging
from datetime import timedelta
from functools import wraps
from typing import TYPE_CHECKING, Any, Concatenate

import voluptuous as vol
from denonavr.const import (
    ALL_TELNET_EVENTS,
    ALL_ZONES,
    MAIN_ZONE,
    POWER_ON,
    STATE_OFF,
    STATE_ON,
    STATE_PAUSED,
    STATE_PLAYING,
)
from denonavr.exceptions import (
    AvrCommandError,
    AvrForbiddenError,
    AvrNetworkError,
    AvrProcessingError,
    AvrTimoutError,
    DenonAvrError,
)
from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.const import ATTR_COMMAND, CONF_HOST, CONF_MODEL, CONF_TYPE
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    CONF_MANUFACTURER,
    CONF_SERIAL_NUMBER,
    CONF_UPDATE_AUDYSSEY,
    DEFAULT_UPDATE_AUDYSSEY,
    DOMAIN,
)
from .heos_media_player import HeosStreamingPlayer
from .util import sanitize_image_url

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine
    from datetime import datetime

    from denonavr import DenonAVR
    from homeassistant.components.media_player import BrowseMedia, RepeatMode
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import DenonavrConfigEntry
    from .webapi import SoundModeSettings

_LOGGER = logging.getLogger(__name__)

ATTR_SOUND_MODE_RAW = "sound_mode_raw"
ATTR_DYNAMIC_EQ = "dynamic_eq"

SUPPORT_DENON = (
    MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.VOLUME_SET
)

SUPPORT_MEDIA_MODES = (
    MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.PLAY
)

# Offered whenever the receiver's HEOS player is reachable: playing media on it
# switches the receiver to its network (HEOS) input by itself.
SUPPORT_HEOS = (
    MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.BROWSE_MEDIA
    | MediaPlayerEntityFeature.MEDIA_ENQUEUE
)

SCAN_INTERVAL = timedelta(seconds=10)
PARALLEL_UPDATES = 1

# Services
SERVICE_GET_COMMAND = "get_command"
SERVICE_SET_DYNAMIC_EQ = "set_dynamic_eq"
SERVICE_UPDATE_AUDYSSEY = "update_audyssey"

# HA Telnet events
TELNET_EVENTS = {
    "HD",
    "MS",
    "MU",
    "MV",
    "NS",
    "NSE",
    "PS",
    "SI",
    "SS",
    "TF",
    "ZM",
    "Z2",
    "Z3",
}

DENON_STATE_MAPPING = {
    STATE_ON: MediaPlayerState.ON,
    STATE_OFF: MediaPlayerState.OFF,
    STATE_PLAYING: MediaPlayerState.PLAYING,
    STATE_PAUSED: MediaPlayerState.PAUSED,
}


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    config_entry: DenonavrConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Denon/Marantz AVR receiver from a config entry."""
    entities = []
    receiver = config_entry.runtime_data.receiver
    update_audyssey = config_entry.options.get(
        CONF_UPDATE_AUDYSSEY, DEFAULT_UPDATE_AUDYSSEY
    )
    for receiver_zone in receiver.zones.values():
        if config_entry.data[CONF_SERIAL_NUMBER] is not None:
            unique_id = f"{config_entry.unique_id}-{receiver_zone.zone}"
        else:
            unique_id = f"{config_entry.entry_id}-{receiver_zone.zone}"
        entities.append(
            DenonDevice(
                receiver_zone,
                unique_id,
                config_entry,
                update_audyssey,
            )
        )
    # Optional HEOS network-streaming player on the same device.
    heos = config_entry.runtime_data.heos
    if heos is not None and heos.player is not None:
        device_id = config_entry.unique_id or config_entry.entry_id
        entities.append(HeosStreamingPlayer(heos, device_id))

    _LOGGER.debug(
        "%s receiver at host %s initialized", receiver.manufacturer, receiver.host
    )

    # Register additional services
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_GET_COMMAND,
        {vol.Required(ATTR_COMMAND): cv.string},
        f"async_{SERVICE_GET_COMMAND}",
    )
    platform.async_register_entity_service(
        SERVICE_SET_DYNAMIC_EQ,
        {vol.Required(ATTR_DYNAMIC_EQ): cv.boolean},
        f"async_{SERVICE_SET_DYNAMIC_EQ}",
    )
    platform.async_register_entity_service(
        SERVICE_UPDATE_AUDYSSEY,
        None,
        f"async_{SERVICE_UPDATE_AUDYSSEY}",
    )

    async_add_entities(entities, update_before_add=True)


def async_log_errors[DenonDeviceT: DenonDevice, **P, R](
    func: Callable[Concatenate[DenonDeviceT, P], Awaitable[R]],
) -> Callable[Concatenate[DenonDeviceT, P], Coroutine[Any, Any, R | None]]:
    """
    Log errors occurred when calling a Denon AVR receiver.

    Decorates methods of DenonDevice class.
    Declaration of staticmethod for this method is at the end of this class.
    """

    @wraps(func)
    async def wrapper(
        self: DenonDeviceT, *args: P.args, **kwargs: P.kwargs
    ) -> R | None:
        available = True
        try:
            return await func(self, *args, **kwargs)
        except AvrTimoutError:
            available = False
            if self.available:
                _LOGGER.warning(
                    (
                        "Timeout connecting to Denon AVR receiver at host %s. "
                        "Device is unavailable"
                    ),
                    self._receiver.host,
                )
                self._attr_available = False
        except AvrNetworkError:
            available = False
            if self.available:
                _LOGGER.warning(
                    (
                        "Network error connecting to Denon AVR receiver at host %s. "
                        "Device is unavailable"
                    ),
                    self._receiver.host,
                )
                self._attr_available = False
        except AvrProcessingError:
            available = True
            if self.available:
                _LOGGER.warning(
                    (
                        "Update of Denon AVR receiver at host %s not complete. "
                        "Device is still available"
                    ),
                    self._receiver.host,
                )
        except AvrForbiddenError:
            available = False
            if self.available:
                _LOGGER.warning(
                    (
                        "Denon AVR receiver at host %s responded with HTTP 403 error. "
                        "Device is unavailable. Please consider power cycling your "
                        "receiver"
                    ),
                    self._receiver.host,
                )
                self._attr_available = False
        except AvrCommandError:
            available = False
            _LOGGER.exception(
                "Command %s failed with error",
                func.__name__,
            )
        except DenonAvrError:
            available = False
            _LOGGER.exception(
                "Error occurred in method %s for Denon AVR receiver", func.__name__
            )
        finally:
            if available and not self.available:
                _LOGGER.warning(
                    "Denon AVR receiver at host %s is available again",
                    self._receiver.host,
                )
                self._attr_available = True
        return None

    return wrapper


class DenonDevice(MediaPlayerEntity):
    """Representation of a Denon Media Player Device."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_device_class = MediaPlayerDeviceClass.RECEIVER

    def __init__(
        self,
        receiver: DenonAVR,
        unique_id: str,
        config_entry: DenonavrConfigEntry,
        update_audyssey: bool,  # noqa: FBT001
    ) -> None:
        """Initialize the device."""
        self._attr_unique_id = unique_id
        if not config_entry.unique_id:
            msg = "Config entry must have a unique_id"
            raise ValueError(msg)
        self._attr_device_info = DeviceInfo(
            configuration_url=f"http://{config_entry.data[CONF_HOST]}/",
            hw_version=config_entry.data[CONF_TYPE],
            identifiers={(DOMAIN, config_entry.unique_id)},
            manufacturer=config_entry.data[CONF_MANUFACTURER],
            model=config_entry.data[CONF_MODEL],
            name=receiver.name,
        )
        self._fallback_sound_mode_list = receiver.sound_mode_list
        self._receiver = receiver
        self._update_audyssey = update_audyssey

        # Real, device-reported sound modes from the port-11080 web API (main
        # zone only). They are read by the shared controls coordinator; the
        # media player never queries the web API itself, so the receiver's
        # fragile web server is polled from a single place.
        self._is_main_zone = receiver.zone == MAIN_ZONE
        self._controls = config_entry.runtime_data.controls

        # The receiver's own HEOS player (main zone only), used headless: while
        # a network source is selected this entity shows the HEOS now-playing
        # and offers its transport, repeat/shuffle, favorites, media browsing
        # and play_media -- one complete media player instead of two.
        heos = config_entry.runtime_data.heos
        self._heos: HeosStreamingPlayer | None = None
        if self._is_main_zone and heos is not None and heos.player is not None:
            self._heos = HeosStreamingPlayer(heos, config_entry.unique_id)

        self._supported_features_base = SUPPORT_DENON
        self._supported_features_base |= (
            self._receiver.support_sound_mode
            and MediaPlayerEntityFeature.SELECT_SOUND_MODE
        )

    def _telnet_callback(self, zone: str, event: str, parameter: str) -> None:
        """Process a telnet command callback."""
        # There are multiple checks implemented which reduce unnecessary
        # updates of the ha state machine
        if zone not in (self._receiver.zone, ALL_ZONES):
            return
        if event not in TELNET_EVENTS:
            return
        # Some updates trigger multiple events like one for artist and one for
        # title for one change. We skip every event except the last one
        if event == "NSE" and not parameter.startswith("4"):
            return
        if event == "TA" and not parameter.startswith("ANNAME"):
            return
        if event == "HD" and not parameter.startswith("ALBUM"):
            return
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Register for telnet (and HEOS) events."""
        self._receiver.register_callback(ALL_TELNET_EVENTS, self._telnet_callback)
        if (heos := self._heos) is not None:
            heos.attach(self.hass, self.entity_id)
            player = heos.streaming.player
            if player is not None:
                self.async_on_remove(
                    player.add_on_player_event(self._async_on_heos_event)
                )
            self.async_on_remove(
                heos.streaming.heos.add_on_connected(self._async_on_heos_connection)
            )
            self.async_on_remove(
                heos.streaming.heos.add_on_disconnected(self._async_on_heos_connection)
            )

    async def _async_on_heos_event(self, event: str) -> None:
        if self._heos is not None:
            self._heos.process_player_event(event)
        self.async_write_ha_state()

    async def _async_on_heos_connection(self) -> None:
        if self._heos is not None:
            self._heos.process_connection_change()
        self.async_write_ha_state()

    @property
    def _heos_ready(self) -> HeosStreamingPlayer | None:
        """Return the HEOS player while it is connected."""
        if self._heos is not None and self._heos.available:
            return self._heos
        return None

    @property
    def _heos_active(self) -> HeosStreamingPlayer | None:
        """Return the HEOS player while it drives what the receiver plays."""
        heos = self._heos_ready
        receiver = self._receiver
        if (
            heos is not None
            and receiver.power == POWER_ON
            and receiver.input_func in receiver.netaudio_func_list
        ):
            return heos
        return None

    async def async_will_remove_from_hass(self) -> None:
        """Clean up the entity."""
        if self._receiver.telnet_connected:
            await self._receiver.async_telnet_disconnect()
        self._receiver.unregister_callback(ALL_TELNET_EVENTS, self._telnet_callback)

    @property
    def _web_sound_modes(self) -> SoundModeSettings | None:
        """Return the device-reported sound modes, when the web API serves them."""
        if not self._is_main_zone or not self._controls.web_available:
            return None
        return self._controls.sound_modes

    @async_log_errors
    async def async_update(self) -> None:
        """Get the latest status information from device."""
        receiver = self._receiver

        # We skip the update if telnet is healthy.
        # When telnet recovers it automatically updates all properties.
        if receiver.telnet_connected and receiver.telnet_healthy:
            return

        await receiver.async_update()

        if self._update_audyssey:
            await receiver.async_update_audyssey()

    @property
    def state(self) -> MediaPlayerState | None:
        """Return the state of the device."""
        if (heos := self._heos_active) is not None:
            return heos.state
        return DENON_STATE_MAPPING.get(self._receiver.state)

    @property
    def source_list(self) -> list[str]:
        """Return the receiver inputs, followed by the HEOS favorites."""
        sources = list(self._receiver.input_func_list or [])
        if (heos := self._heos_ready) is not None:
            sources.extend(
                favorite.name
                for favorite in heos.streaming.favorites.values()
                if favorite.name not in sources
            )
        return sources

    @property
    def is_volume_muted(self) -> bool:
        """Return boolean if volume is currently muted."""
        return self._receiver.muted

    @property
    def volume_level(self) -> float | None:
        """Volume level of the media player (0..1)."""
        # Volume is sent in a format like -50.0. Minimum is -80.0,
        # maximum is 18.0
        if self._receiver.volume is None:
            return None
        return (float(self._receiver.volume) + 80) / 100

    @property
    def source(self) -> str | None:
        """Return the current input source (or the HEOS favorite playing)."""
        if (heos := self._heos_active) is not None:
            name = heos.source
            if name is not None and heos.streaming.favorite_index(name) is not None:
                return name
        return self._receiver.input_func

    @property
    def sound_mode_list(self) -> list[str] | None:
        """
        Return the selectable sound modes.

        Prefer the real, device-reported list from the web API; fall back to
        the denonavr static list when the API is unavailable.
        """
        if (settings := self._web_sound_modes) is not None:
            return settings.names
        return self._fallback_sound_mode_list

    @property
    def sound_mode(self) -> str | None:
        """Return the current sound mode."""
        if (settings := self._web_sound_modes) is not None and (
            current := settings.current
        ) is not None:
            return current
        return self._receiver.sound_mode

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Flag media player features that are supported."""
        features = self._supported_features_base
        if self._heos_ready is not None:
            features |= SUPPORT_HEOS
        if (heos := self._heos_active) is not None:
            # Transport, stop, repeat/shuffle as the current HEOS media allows.
            return features | heos.supported_features
        if self._receiver.input_func in self._receiver.netaudio_func_list:
            return features | SUPPORT_MEDIA_MODES
        return features

    @property
    def media_content_type(self) -> MediaType:
        """Content type of current playing media."""
        if self._heos_active is not None:
            return MediaType.MUSIC
        if self._receiver.state in {MediaPlayerState.PLAYING, MediaPlayerState.PAUSED}:
            return MediaType.MUSIC
        return MediaType.CHANNEL

    @property
    def media_content_id(self) -> str | None:
        """Return the HEOS media id of what is playing."""
        if (heos := self._heos_active) is not None:
            return heos.media_content_id
        return None

    @property
    def media_image_remotely_accessible(self) -> bool:
        """HEOS cover art is served from the internet, the receiver's is local."""
        return self._heos_active is not None

    @property
    def media_image_url(self) -> str | None:
        """Image url of current playing media."""
        if (heos := self._heos_active) is not None and (
            url := heos.media_image_url
        ) is not None:
            return url
        if self._receiver.input_func in self._receiver.playing_func_list:
            return sanitize_image_url(self._receiver.image_url)
        return None

    @property
    def media_title(self) -> str | None:
        """Title of current playing media."""
        if (heos := self._heos_active) is not None and (
            title := heos.media_title
        ) is not None:
            return title
        if self._receiver.input_func not in self._receiver.playing_func_list:
            return self._receiver.input_func
        if self._receiver.title is not None:
            return self._receiver.title
        return self._receiver.frequency

    @property
    def media_artist(self) -> str | None:
        """Artist of current playing media, music track only."""
        if (heos := self._heos_active) is not None and (
            artist := heos.media_artist
        ) is not None:
            return artist
        if self._receiver.artist is not None:
            return self._receiver.artist
        return self._receiver.band

    @property
    def media_album_name(self) -> str | None:
        """Album name of current playing media, music track only."""
        if (heos := self._heos_active) is not None and (
            album := heos.media_album_name
        ) is not None:
            return album
        if self._receiver.album is not None:
            return self._receiver.album
        return self._receiver.station

    @property
    def media_duration(self) -> int | None:
        """Duration of the HEOS track, in seconds."""
        heos = self._heos_active
        return heos.media_duration if heos is not None else None

    @property
    def media_position(self) -> int | None:
        """Position in the HEOS track, in seconds."""
        heos = self._heos_active
        return heos.media_position if heos is not None else None

    @property
    def media_position_updated_at(self) -> datetime | None:
        """When the HEOS track position was last valid."""
        heos = self._heos_active
        return heos.media_position_updated_at if heos is not None else None

    @property
    def repeat(self) -> RepeatMode | None:
        """Repeat mode of the HEOS queue."""
        heos = self._heos_active
        return heos.repeat if heos is not None else None

    @property
    def shuffle(self) -> bool | None:
        """Shuffle state of the HEOS queue."""
        heos = self._heos_active
        return heos.shuffle if heos is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return device specific state attributes."""
        receiver = self._receiver
        if receiver.power != POWER_ON:
            return {}
        state_attributes: dict[str, Any] = {}
        if (
            sound_mode_raw := receiver.sound_mode_raw
        ) is not None and receiver.support_sound_mode:
            state_attributes[ATTR_SOUND_MODE_RAW] = sound_mode_raw
        if (dynamic_eq := receiver.dynamic_eq) is not None:
            state_attributes[ATTR_DYNAMIC_EQ] = dynamic_eq
        return state_attributes

    @property
    def dynamic_eq(self) -> bool | None:
        """Status of DynamicEQ."""
        return self._receiver.dynamic_eq

    @async_log_errors
    async def async_media_play_pause(self) -> None:
        """Play or pause the media player."""
        if (heos := self._heos_active) is not None:
            if heos.state == MediaPlayerState.PLAYING:
                await heos.async_media_pause()
            else:
                await heos.async_media_play()
            return
        await self._receiver.async_toggle_play_pause()

    @async_log_errors
    async def async_media_play(self) -> None:
        """Send play command."""
        if (heos := self._heos_active) is not None:
            await heos.async_media_play()
            return
        await self._receiver.async_play()

    @async_log_errors
    async def async_media_pause(self) -> None:
        """Send pause command."""
        if (heos := self._heos_active) is not None:
            await heos.async_media_pause()
            return
        await self._receiver.async_pause()

    async def async_media_stop(self) -> None:
        """Send stop command (HEOS only)."""
        if (heos := self._heos_active) is not None:
            await heos.async_media_stop()

    @async_log_errors
    async def async_media_previous_track(self) -> None:
        """Send previous track command."""
        if (heos := self._heos_active) is not None:
            await heos.async_media_previous_track()
            return
        await self._receiver.async_previous_track()

    @async_log_errors
    async def async_media_next_track(self) -> None:
        """Send next track command."""
        if (heos := self._heos_active) is not None:
            await heos.async_media_next_track()
            return
        await self._receiver.async_next_track()

    async def async_set_repeat(self, repeat: RepeatMode) -> None:
        """Set the HEOS repeat mode."""
        if (heos := self._heos_active) is not None:
            await heos.async_set_repeat(repeat)

    async def async_set_shuffle(self, shuffle: bool) -> None:  # noqa: FBT001
        """Enable or disable HEOS shuffle."""
        if (heos := self._heos_active) is not None:
            await heos.async_set_shuffle(shuffle)

    @async_log_errors
    async def async_select_source(self, source: str) -> None:
        """Select a receiver input, or play a HEOS favorite."""
        heos = self._heos_ready
        if (
            heos is not None
            and source not in (self._receiver.input_func_list or [])
            and heos.streaming.favorite_index(source) is not None
        ):
            await heos.async_select_source(source)
            return
        await self._receiver.async_set_input_func(source)

    async def async_play_media(
        self, media_type: MediaType | str, media_id: str, **kwargs: Any
    ) -> None:
        """Play media through the receiver's HEOS player."""
        if (heos := self._heos_ready) is None:
            msg = "Playing media needs the receiver's HEOS player"
            raise HomeAssistantError(msg)
        await heos.async_play_media(media_type, media_id, **kwargs)

    async def async_browse_media(
        self,
        media_content_type: MediaType | str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Browse HEOS music sources, favorites and media-source items."""
        if (heos := self._heos_ready) is None:
            msg = "Browsing media needs the receiver's HEOS player"
            raise HomeAssistantError(msg)
        return await heos.async_browse_media(media_content_type, media_content_id)

    @async_log_errors
    async def async_select_sound_mode(self, sound_mode: str) -> None:
        """
        Select sound mode.

        Use the web API (by receiver index) when it drives the list, so the
        names always match; otherwise use the denonavr Telnet/HTTP command.
        """
        settings = self._web_sound_modes
        index = settings.index_for(sound_mode) if settings is not None else None
        if index is not None:
            # The coordinator applies it, waits for the receiver to settle and
            # re-reads the list, so the new mode is shown (no apparent revert).
            await self._controls.async_set_sound_mode(index)
            self.async_write_ha_state()
            return
        await self._receiver.async_set_sound_mode(sound_mode)

    @async_log_errors
    async def async_turn_on(self) -> None:
        """Turn on media player."""
        await self._receiver.async_power_on()

    @async_log_errors
    async def async_turn_off(self) -> None:
        """Turn off media player."""
        await self._receiver.async_power_off()

    @async_log_errors
    async def async_volume_up(self) -> None:
        """Volume up the media player."""
        await self._receiver.async_volume_up()

    @async_log_errors
    async def async_volume_down(self) -> None:
        """Volume down media player."""
        await self._receiver.async_volume_down()

    @async_log_errors
    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, range 0..1."""
        # Maximum volume constant
        max_volume = 18

        # Volume has to be sent in a format like -50.0. Minimum is -80.0,
        # maximum is 18.0
        volume_denon = float((volume * 100) - 80)
        if volume_denon > max_volume:
            volume_denon = float(max_volume)
        await self._receiver.async_set_volume(volume_denon)

    @async_log_errors
    async def async_mute_volume(self, mute: bool) -> None:  # noqa: FBT001
        """Send mute command."""
        await self._receiver.async_mute(mute)

    @async_log_errors
    async def async_get_command(
        self,
        command: str,
        **kwargs: Any,
    ) -> str:
        """Send generic command."""
        return await self._receiver.async_get_command(command)

    @async_log_errors
    async def async_update_audyssey(self) -> None:
        """Get the latest audyssey information from device."""
        await self._receiver.async_update_audyssey()

    @async_log_errors
    async def async_set_dynamic_eq(
        self,
        dynamic_eq: bool,  # noqa: FBT001
    ) -> None:
        """Turn DynamicEQ on or off."""
        if dynamic_eq:
            await self._receiver.async_dynamic_eq_on()
        else:
            await self._receiver.async_dynamic_eq_off()

        if self._update_audyssey:
            await self._receiver.async_update_audyssey()

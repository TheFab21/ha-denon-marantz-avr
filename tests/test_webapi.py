"""Tests for the webapi audio parser."""

from custom_components.denon_marantz_avr.webapi import (
    _parse_audio,
    _parse_information,
    _parse_video,
    async_get_audio_info,
)

# Real sample from a Denon AVR-X4400H (Apple TV, 2.0 PCM upmixed to Neural:X).
SAMPLE_AUDIO = """<?xml version="1.0" encoding="utf-8"?>
<Audio><Volume>340</Volume><VolumeScale>1</VolumeScale>
<InputSignal mode="channel_icon"><List>
<Speaker index="0">2</Speaker><Speaker index="1">2</Speaker>
<Speaker index="2">1</Speaker><Speaker index="3">1</Speaker>
<Speaker index="5">1</Speaker><Speaker index="6">1</Speaker>
<Speaker index="30">0</Speaker></List></InputSignal>
<ActiveSpeaker><List>
<Speaker index="0">2</Speaker><Speaker index="1">2</Speaker>
<Speaker index="2">2</Speaker><Speaker index="3">0</Speaker>
<Speaker index="5">2</Speaker><Speaker index="6">2</Speaker>
<Speaker index="7">0</Speaker></List></ActiveSpeaker>
<BluetoothTransmitter>2</BluetoothTransmitter></Audio>"""


class TestParseAudio:
    def test_parses_active_channels(self) -> None:
        audio = _parse_audio(SAMPLE_AUDIO)
        assert audio is not None
        # Only index 0/1 carry value "2" in the input signal -> FL, FR.
        assert audio.input_signal == ["FL", "FR"]
        assert audio.input_signal_text == "FL FR"
        # Active speakers are the value-"2" entries 0,1,2,5,6.
        assert audio.active_speakers == ["FL", "FR", "C", "SL", "SR"]
        assert audio.active_speakers_text == "FL FR C SL SR"

    def test_empty_sections_give_no_channels(self) -> None:
        audio = _parse_audio(
            "<Audio><InputSignal><List></List></InputSignal>"
            "<ActiveSpeaker><List></List></ActiveSpeaker></Audio>"
        )
        assert audio is not None
        assert audio.input_signal == []
        assert audio.input_signal_text is None
        assert audio.active_speakers_text is None

    def test_wrong_root_returns_none(self) -> None:
        assert _parse_audio("<SomethingElse/>") is None

    def test_invalid_xml_returns_none(self) -> None:
        assert _parse_audio("not xml <<<") is None


SAMPLE_INFORMATION = (
    "<Information><Source>Apple TV</Source><Signal>PCM</Signal>"
    '<Video display="1"/><Sound>DTS Neural:X</Sound></Information>'
)

SAMPLE_VIDEO = (
    "<Video><Resolution><Input>4K50</Input><Output>4K50</Output></Resolution>"
    "<HDR><Input>HDR10</Input><Output>HDR10</Output></HDR>"
    "<ColorSpace><Input>YCbCr 4:2:0</Input><Output>YCbCr 4:2:0</Output></ColorSpace>"
    "<Colorimetry><Input>BT.2020</Input><Output>BT.2020</Output></Colorimetry>"
    "<PixelDepth><Input>10bits</Input><Output>8bits</Output></PixelDepth>"
    "<ALLM>2</ALLM><QFT>2</QFT>"
    "<FRLRate><Input>---</Input><Output>---</Output></FRLRate></Video>"
)


class TestParseInformation:
    def test_parses_source_signal_sound(self) -> None:
        info = _parse_information(SAMPLE_INFORMATION)
        assert info is not None
        assert info.source == "Apple TV"
        assert info.signal == "PCM"
        assert info.sound == "DTS Neural:X"

    def test_wrong_root_returns_none(self) -> None:
        assert _parse_information("<Video/>") is None


class TestParseVideo:
    def test_parses_in_out_fields(self) -> None:
        video = _parse_video(SAMPLE_VIDEO)
        assert video is not None
        assert video.resolution_in == "4K50"
        assert video.resolution_out == "4K50"
        assert video.hdr_out == "HDR10"
        assert video.color_space_out == "YCbCr 4:2:0"
        assert video.colorimetry_out == "BT.2020"
        assert video.pixel_depth_in == "10bits"
        assert video.pixel_depth_out == "8bits"

    def test_input_and_output_attributes(self) -> None:
        video = _parse_video(SAMPLE_VIDEO)
        assert video is not None
        assert video.input_attributes["resolution"] == "4K50"
        assert video.input_attributes["pixel_depth"] == "10bits"
        assert video.output_attributes["pixel_depth"] == "8bits"
        # The "---" FRL placeholder is treated as no value in both views.
        assert "frl" not in video.input_attributes
        assert "frl" not in video.output_attributes

    def test_parses_frl_rate(self) -> None:
        video = _parse_video(
            "<Video><FRLRate><Input>24G</Input><Output>18G</Output></FRLRate></Video>"
        )
        assert video is not None
        assert video.frl_in == "24G"
        assert video.frl_out == "18G"
        assert video.input_attributes["frl"] == "24G"
        assert video.output_attributes["frl"] == "18G"

    def test_placeholder_becomes_none(self) -> None:
        video = _parse_video(SAMPLE_VIDEO)
        assert video is not None
        # FRLRate "---" must be treated as no value, and omitted from attributes.
        assert "frl_out" not in video.attributes
        assert video.attributes["resolution_out"] == "4K50"

    def test_wrong_root_returns_none(self) -> None:
        assert _parse_video("<Audio/>") is None


SAMPLE_AUDIO_DIRAC = (
    "<Audio><InputSignal><List></List></InputSignal>"
    "<ActiveSpeaker><List></List></ActiveSpeaker>"
    '<DiracLive display="3"><Name>Movie</Name></DiracLive></Audio>'
)


class TestDiracAndGaming:
    def test_dirac_inactive_when_display_not_3(self) -> None:
        # SAMPLE_AUDIO has <DiracLive display="1"/> -> inactive.
        audio = _parse_audio(
            SAMPLE_AUDIO.replace("</Audio>", '<DiracLive display="1"/></Audio>')
        )
        assert audio is not None
        assert audio.dirac_active is False
        assert audio.dirac_state == "Off"

    def test_dirac_active_shows_filter_name(self) -> None:
        audio = _parse_audio(SAMPLE_AUDIO_DIRAC)
        assert audio is not None
        assert audio.dirac_active is True
        assert audio.dirac_state == "Movie"

    def test_allm_qft_off_when_not_one(self) -> None:
        # SAMPLE_VIDEO has ALLM=2 / QFT=2 -> off.
        video = _parse_video(SAMPLE_VIDEO)
        assert video is not None
        assert video.allm is False
        assert video.qft is False

    def test_allm_on_when_one(self) -> None:
        video = _parse_video("<Video><ALLM>1</ALLM><QFT>0</QFT></Video>")
        assert video is not None
        assert video.allm is True
        assert video.qft is False


# Real captures from a Marantz CINEMA (Apple TV, 2.0 PCM upmixed to DTS
# Neural:X), taken from the receiver's own web UI on port 11080. The live
# status blocks all come from the "info" section:
#   /ajax/info/get_config?type=1   -> <Information>
#   /ajax/info/get_config?type=2   -> <Audio>
#   /ajax/info/get_config?type=3   -> <Video>
# The audio block carries the extra Audyssey sub-block and an EXT (index 35)
# input channel that the AVR-X4400H sample above does not, so it guards the
# parser against those real-world extras.
MARANTZ_AUDIO = (
    "<Audio><Volume>335</Volume><VolumeScale>1</VolumeScale>"
    '<InputSignal mode="channel_icon"><List>'
    '<Speaker index="0">2</Speaker><Speaker index="1">2</Speaker>'
    '<Speaker index="2">1</Speaker><Speaker index="3">1</Speaker>'
    '<Speaker index="5">1</Speaker><Speaker index="6">1</Speaker>'
    '<Speaker index="7">1</Speaker><Speaker index="8">1</Speaker>'
    '<Speaker index="9">1</Speaker><Speaker index="12">1</Speaker>'
    '<Speaker index="13">1</Speaker><Speaker index="10">1</Speaker>'
    '<Speaker index="11">1</Speaker><Speaker index="35">1</Speaker>'
    '<Speaker index="30">0</Speaker><Speaker index="24">0</Speaker>'
    '<Speaker index="25">0</Speaker><Speaker index="31">0</Speaker>'
    "</List></InputSignal>"
    "<ActiveSpeaker><List>"
    '<Speaker index="0">2</Speaker><Speaker index="1">2</Speaker>'
    '<Speaker index="2">2</Speaker><Speaker index="3">0</Speaker>'
    '<Speaker index="5">2</Speaker><Speaker index="6">2</Speaker>'
    '<Speaker index="7">0</Speaker><Speaker index="8">0</Speaker>'
    "</List></ActiveSpeaker>"
    "<BluetoothTransmitter>2</BluetoothTransmitter>"
    '<Audyssey display="3"><MultEQ group="2">1</MultEQ>'
    '<DynamicEQ display="3">1</DynamicEQ>'
    '<DynamicVolume display="3">2</DynamicVolume></Audyssey>'
    '<DiracLive display="1"/></Audio>'
)

MARANTZ_INFORMATION = (
    "<Information><Source>Apple TV</Source><Signal>PCM</Signal>"
    '<Video display="1"/><Sound>DTS Neural:X</Sound></Information>'
)

MARANTZ_VIDEO = (
    "<Video><Resolution><Input>4K50</Input><Output>4K50</Output></Resolution>"
    "<HDR><Input>HDR10</Input><Output>HDR10</Output></HDR>"
    "<ColorSpace><Input>YCbCr 4:2:0</Input><Output>YCbCr 4:2:0</Output></ColorSpace>"
    "<Colorimetry><Input>BT.2020</Input><Output>BT.2020</Output></Colorimetry>"
    "<PixelDepth><Input>10bits</Input><Output>8bits</Output></PixelDepth>"
    "<ALLM>2</ALLM><QFT>2</QFT>"
    "<FRLRate><Input>---</Input><Output>---</Output></FRLRate></Video>"
)


class TestMarantzCinemaCapture:
    """Regression tests against real Marantz CINEMA web-API responses."""

    def test_audio_channels_and_dirac(self) -> None:
        audio = _parse_audio(MARANTZ_AUDIO)
        assert audio is not None
        # The EXT (index 35) channel is only "available" (1), not active (2).
        assert audio.input_signal == ["FL", "FR"]
        assert audio.active_speakers == ["FL", "FR", "C", "SL", "SR"]
        # Dirac is present but inactive (display="1").
        assert audio.dirac_active is False
        assert audio.dirac_state == "Off"

    def test_information_fields(self) -> None:
        info = _parse_information(MARANTZ_INFORMATION)
        assert info is not None
        assert info.source == "Apple TV"
        assert info.signal == "PCM"
        assert info.sound == "DTS Neural:X"

    def test_video_input_output(self) -> None:
        video = _parse_video(MARANTZ_VIDEO)
        assert video is not None
        # The receiver down-converts 10-bit input to 8-bit output.
        assert video.input_attributes["pixel_depth"] == "10bits"
        assert video.output_attributes["pixel_depth"] == "8bits"
        assert video.resolution_in == "4K50"
        assert video.resolution_out == "4K50"
        assert video.allm is False
        assert video.qft is False
        # FRLRate "---" is treated as no value.
        assert "frl" not in video.output_attributes


class _FakeResponse:
    """A minimal stand-in for an httpx response."""

    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        """No-op: the fake response is always a success."""


class _RecordingClient:
    """An httpx-like async client that records the request it is given."""

    def __init__(self, body: str) -> None:
        self._body = body
        self.calls: list[tuple[str, dict]] = []

    async def get(self, url: str, **kwargs: object) -> _FakeResponse:
        """Record the request (url + params) and return the canned body."""
        self.calls.append((url, kwargs.get("params") or {}))
        return _FakeResponse(self._body)


class TestAudioEndpoint:
    """The live <Audio> status is served by /ajax/info/get_config?type=2.

    Regression guard: it is NOT /ajax/audio/get_config?type=1, which returns
    the audio *setup menu* (<listSetupMenu>) and left the input-signal /
    active-speakers / Dirac sensors unknown.
    """

    async def test_audio_info_requests_info_type_2(self) -> None:
        client = _RecordingClient(MARANTZ_AUDIO)
        audio = await async_get_audio_info(client, "192.0.2.1")
        url, params = client.calls[0]
        assert url.endswith("/ajax/info/get_config")
        assert params == {"type": 2}
        assert audio is not None
        assert audio.active_speakers == ["FL", "FR", "C", "SL", "SR"]

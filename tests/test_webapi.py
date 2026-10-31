"""Tests for the webapi audio parser."""

from custom_components.denon_marantz_avr.webapi import (
    _parse_audio,
    _parse_information,
    _parse_video,
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
        assert video.resolution_out == "4K50"
        assert video.hdr_out == "HDR10"
        assert video.color_space_out == "YCbCr 4:2:0"
        assert video.colorimetry_out == "BT.2020"
        assert video.pixel_depth_in == "10bits"
        assert video.pixel_depth_out == "8bits"

    def test_placeholder_becomes_none(self) -> None:
        video = _parse_video(SAMPLE_VIDEO)
        assert video is not None
        # FRLRate "---" must be treated as no value, and omitted from attributes.
        assert "frl_rate_out" not in video.attributes
        assert video.attributes["resolution_out"] == "4K50"

    def test_wrong_root_returns_none(self) -> None:
        assert _parse_video("<Audio/>") is None

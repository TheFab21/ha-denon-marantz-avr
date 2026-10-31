"""Tests for the webapi audio parser."""

from custom_components.denon_marantz_avr.webapi import _parse_audio

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

# Denon & Marantz AVR for Home Assistant

[![GitHub Release](https://img.shields.io/github/v/release/TheFab21/ha-denon-marantz-avr?style=flat)](https://github.com/TheFab21/ha-denon-marantz-avr/releases/latest)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

A **complete** custom Home Assistant integration for Denon and Marantz A/V
network receivers. It merges three community projects into a single component
with **one config entry, one connection to the receiver, and one device** in
Home Assistant:

- A full **media player** (HTTP control + real-time Telnet push, multi-zone).
- Per-channel **volume** controls (`number` entities, in dB).
- The extra **Audyssey / Eco controls** that the core integration does not
  expose — Dynamic EQ, Dynamic Volume, Reference Level Offset, MultiEQ, Eco
  mode, plus *Refresh Audyssey* and *Recover audio* buttons.

> **Domain:** `denon_marantz_avr` — deliberately distinct from the built-in
> `denonavr` integration. Using a brand-new domain means this component never
> shadows or conflicts with a core Home Assistant integration and keeps working
> across Home Assistant upgrades. You can even run it side by side with the
> official integration while you migrate.

## Features

| Area | What you get |
|------|--------------|
| **Media player** | Power, volume (set/step/mute), source selection, sound-mode selection, transport controls and now-playing metadata for network sources |
| **Real sound-mode list** | On recent receivers (HEOS-era, port 11080) the sound-mode list is read live from the device, so only the modes actually available for the current input are shown — with automatic fallback to the library list on older models |
| **Multi-zone** | Main Zone plus optional Zone 2 and Zone 3 as separate entities |
| **Real-time updates** | Telnet push connection (`local_push`) for instant state changes, with HTTP fallback |
| **Discovery** | SSDP auto-discovery of Denon, Denon Professional and Marantz receivers |
| **Channel volume** | Per-channel trim (Front L/R, Center, Surround L/R, Subwoofer) as `number` entities in dB |
| **Audyssey** | Dynamic EQ (`switch`), Dynamic Volume / Reference Level Offset / MultiEQ (`select`) |
| **Eco mode** | Off / Auto / On (`select`) |
| **Advanced audio** | Dialog Enhancer, M‑DAX / Audio Restorer, DRC, Bluetooth output, Speaker preset (`select`); Bluetooth transmitter, Graphic EQ (`switch`); audio delay, sleep timer (`number`) — capability-detected, Telnet only |
| **Buttons** | Refresh Audyssey, Recover audio (soft power-cycle that restores the previous input) |
| **Services** | `get_command`, `set_dynamic_eq`, `update_audyssey` |

## Supported devices

- Denon AVR network receivers
- Denon Professional AVR receivers
- Marantz AVR network receivers

## Installation

### HACS (recommended)

1. In HACS, open the three-dot menu → **Custom repositories**.
2. Add `https://github.com/thefab21/ha-denon-marantz-avr` with category **Integration**.
3. Install **Denon & Marantz AVR** and restart Home Assistant.

### Manual

1. Copy `custom_components/denon_marantz_avr` into your Home Assistant
   `config/custom_components` directory.
2. Restart Home Assistant.

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **Denon & Marantz AVR**.
3. Leave the address blank to auto-discover, or enter the receiver's IP address.

Discovered receivers are also offered automatically as a notification.

### Options

After setup, open the integration options to configure:

- **Show all sources** — list every input source, including hidden ones.
- **Set up Zone 2 / Zone 3** — add extra zone media players.
- **Use Telnet connection** — real-time push updates (enabled by default for new
  installs). Only one Telnet client can be connected to the receiver at a time.
- **Update Audyssey settings** — also poll Audyssey values with the media player.

## Entities

All entities are grouped under a single Home Assistant device per receiver:

- `media_player.*` — one per active zone
- `number.*` — per-channel volume trim, plus audio delay and sleep timer
- `switch.*` — Dynamic EQ, Bluetooth transmitter, Graphic EQ
- `select.*` — Dynamic Volume, Reference Level Offset, MultiEQ, Eco mode, Dialog
  Enhancer, M‑DAX / Audio Restorer, DRC, Bluetooth output, Speaker preset
- `button.*` — Refresh Audyssey, Recover audio

> The advanced audio entities (Dialog Enhancer, M‑DAX, DRC, delay, sleep,
> Bluetooth, Graphic EQ, Speaker preset) are **created only when your receiver
> reports that setting** over its Telnet connection — option lists come from the
> `denonavr` library, nothing is hard-coded — so you only see the controls your
> model actually supports. Keep the **Telnet** option enabled for them to appear.

## Services

### `denon_marantz_avr.get_command`

Send a raw HTTP GET command to the receiver.

```yaml
action: denon_marantz_avr.get_command
target:
  entity_id: media_player.denon_avr
data:
  command: "/goform/formiPhoneAppDirect.xml?SYSTANDBY"
```

### `denon_marantz_avr.set_dynamic_eq`

```yaml
action: denon_marantz_avr.set_dynamic_eq
target:
  entity_id: media_player.denon_avr
data:
  dynamic_eq: true
```

### `denon_marantz_avr.update_audyssey`

```yaml
action: denon_marantz_avr.update_audyssey
target:
  entity_id: media_player.denon_avr
```

## How it works

The integration wraps the [`denonavr`](https://github.com/ol-iver/denonavr)
Python library. A single `DenonAVR` instance is created per config entry and
shared by every platform:

- The **media player** and **channel-volume** entities use the receiver
  directly and receive push updates over Telnet.
- A lightweight **coordinator** polls the Audyssey/Eco state (which is not sent
  over Telnet) and serializes control commands, backing the `switch`, `select`
  and `button` entities.

The *Recover audio* button performs a **soft** power cycle (standby off/on) and
restores the previously selected input. It never cuts electrical power; do not
use it while the receiver is updating its firmware.

## Development

```bash
scripts/setup      # install dependencies
scripts/develop    # run a local Home Assistant with the integration loaded
scripts/lint       # ruff format + check
python -m pytest   # run the unit tests
```

## Credits

This project unifies and builds on the work of several community projects:

- [`foxey/ha-marantz-plus`](https://github.com/foxey/ha-marantz-plus) — media
  player, config flow, channel volume and services base.
- [`cvanvliet/ha-denonavr-controls`](https://github.com/cvanvliet/ha-denonavr-controls) —
  the native Audyssey / Eco `switch` / `select` / `button` controls.
- [`frawau/ha-aiomadeavr`](https://github.com/frawau/ha-aiomadeavr) — the
  real-time Telnet-push approach.
- The [`denonavr`](https://github.com/ol-iver/denonavr) library by
  [@ol-iver](https://github.com/ol-iver).
- Based on the core Home Assistant
  [denonavr](https://www.home-assistant.io/integrations/denonavr) integration.

## License

MIT License — see [LICENSE](LICENSE).

---

**Note:** This is a custom integration and is not officially supported by Home
Assistant, Denon or Marantz.

# Network ports used by Denon / Marantz (HEOS) receivers

Reference of the network services a HEOS-era Denon/Marantz receiver exposes,
and which ones this integration uses. Handy when setting up firewall rules or
VLANs: Home Assistant needs outbound access to the receiver on the **Used**
ports below.

## Used by this integration

| Port | Service | How it's used |
|------|---------|---------------|
| **TCP 23** | HEOS Serial Control (Telnet) | Real-time push of receiver state (via `denonavr`) |
| **TCP 80** | HEOS HTTP Server | HTTP control — `/goform/…` commands (via `denonavr`) |
| **TCP 1255** | HEOS Command Line Interface | HEOS Built-in streaming player — now-playing, browse, transport (via `pyheos`) |
| **TCP 11080** | HEOS Web UI | Real sound modes, sound category, input signal / active speakers, audio format, decoded mode, video/HDR/ALLM/QFT, Dirac state |
| **TCP 60006** | HEOS UPnP Server | Album-art image URLs |
| **UDP 1900 / 5353** | SSDP / mDNS | Auto-discovery of the receiver |

> The classic "AVR Remote app" API on **TCP 8080** (`/goform/AppCommand.xml`,
> `formiPhoneAppDirect.xml`) is the same `/goform/` protocol the integration
> already drives on port 80 — it exposes nothing extra. Smart Select / Quick
> Select presets are recalled through it (`MSSMART{n}` / `MSQUICK{n}`).

## Other services on the receiver (not used here)

| Port | Service | Notes |
|------|---------|-------|
| TCP 443 / 1256 | HTTPS / secure CLI | Secure variants of 80 / 1255 |
| TCP 3100 / 3101 | Tidal Connect / Qobuz Connect | Driven by those apps, not by HA |
| TCP 7000 | Apple AirPlay | Handled by Home Assistant's own AirPlay support |
| TCP 8015 / 60080 | HEOS UPnP server / controller | Internal UPnP |
| TCP 8080 | HEOS Web API (AVR Remote app) | Classic `/goform/` API — see note above |
| TCP 8090 | Dirac Control | Dirac Live tuning (only relevant with a Dirac licence) |
| TCP 10800 / 10101 / 10234 / 10555 | iHiji / HEOS Comms / Playlist / Discovery | Internal HEOS services |
| UDP 1678–1687 | HEOS system / upgrade / IPC | Internal HEOS services |

Ports and services are taken from the receiver's own documentation; exact
availability varies by model and firmware.

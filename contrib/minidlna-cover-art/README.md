# Optional MiniDLNA folder-art fallback for HEOS browsing

> Contributed by [@Sven-Tarras](https://github.com/Sven-Tarras) — see
> [issue #12](https://github.com/TheFab21/ha-denon-marantz-avr/issues/12).
> Provided as-is; it is **not** covered by the integration's support.

To use it, set **Folder artwork service URL** in the integration's options
(Settings → Devices & Services → Denon & Marantz AVR → Configure) to this
service's address, e.g. `http://YOUR_MINIDLNA_HOST:8765/`. When set, folders
browsed over HEOS that lack artwork are resolved through this service.

This is a small **external proof-of-concept service**, not a built-in feature of `ha-denon-marantz-avr`. It resolves a MiniDLNA storage-folder object ID to its `AlbumArt` URL by reading the local MiniDLNA SQLite database in read-only mode.

## Requirements

- Python 3 (standard library only)
- Access to MiniDLNA's SQLite database (`files.db`), typically on the same host
- MiniDLNA's HTTP `AlbumArt` endpoint reachable by Home Assistant and the browser displaying artwork
- The integration must receive MiniDLNA-compatible `container_id` values from HEOS

## Run

```bash
export MINIDLNA_DB_PATH=/var/cache/minidlna/files.db
export MINIDLNA_BASE_URL=http://YOUR_MINIDLNA_HOST:8200
# Only on a trusted LAN; restrict access with firewall rules.
export COVER_LISTEN_HOST=0.0.0.0
export COVER_LISTEN_PORT=8765
python3 server.py
```

Example request: `GET http://YOUR_MINIDLNA_HOST:8765/?container_id=64%240%240`

Example response: `{"thumbnail":"http://YOUR_MINIDLNA_HOST:8200/AlbumArt/123-456.jpg"}` or `{"thumbnail":null}`.

## Integration-side support (now native)

You no longer need to patch the integration: as of **v1.4.8** it calls this
service automatically when **Folder artwork service URL** is set in the options.
During HEOS browsing, for the browsed folder and each child folder that has no
artwork and is a container with a container ID, the integration queries the
service (`?container_id=...`) and uses the returned `thumbnail`. Lookups run
concurrently, time out after 5 s and fail silently, so a slow or absent service
never blocks browsing.

You only need to run this service and point the option at it.

## Limitations and security

- MiniDLNA database layout and `AlbumArt/<cover_id>-<detail_id>.jpg` naming are implementation-dependent; validate against the installed MiniDLNA version.
- Only `container.storageFolder` rows with `ALBUM_ART > 0` are handled. Other containers or missing art return `null`.
- This service has **no authentication**. Default binding is localhost. If exposing it to Home Assistant on a trusted LAN, use a firewall to limit clients; do not expose it to the internet.
- The service does not alter the database. It does not implement any album-specific hard-coded exceptions.
- The server is a proof of concept, not a production-hardened public API.

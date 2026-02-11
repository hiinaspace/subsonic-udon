# Subsonic Udon

VRChat music player world backed by a Subsonic-compatible music server.

## Agent Workflow

- When editing UdonSharp scripts in this repo, use the local `unity-editor-bridge` skill (`.codex/skills/unity-editor-bridge/`) to run `did-it-work`/`logs-since` checks and capture actual Unity compile errors after asset refresh.
- When you need scene/asset inspection or targeted editor-side changes, prefer the skill's C# eval flow (`unity-bridge-csharp-run.sh`) instead of editing Unity YAML assets directly.

## Architecture

Two components:
1. **Proxy server** (`server/`): Python/FastAPI proxy that bridges a Subsonic server to VRChat. Exposes enumerable static HLS URLs (`/0001.m3u8` ... `/NNNN.m3u8`) and a `metadata.json` mapping track info to slots. Transcodes audio to HLS VOD via ffmpeg with disk caching.
2. **Unity package** (`Packages/com.subsonic-udon.vvmw/`): UdonSharp VPM package that pre-generates VRCUrl slots at editor time, fetches metadata at runtime, and plays tracks through VizVid.

VRChat constraint: VRCUrl objects must be statically embedded in the world asset bundle — they cannot be constructed at runtime. The proxy provides a fixed set of slot URLs that the Unity side pre-generates.

## Server Development

```bash
cd server

# Install dependencies
uv sync

# Run tests
uv run pytest

# Run dev server
uv run uvicorn subsonic_proxy.app:app --reload

# Lint
uv run ruff check src/ tests/
uv run ruff format src/ tests/
```

### Environment Variables

All prefixed with `SUBSONIC_PROXY_`:

| Variable | Required | Default | Description |
|---|---|---|---|
| `SUBSONIC_PROXY_SUBSONIC_URL` | yes | - | Subsonic server URL |
| `SUBSONIC_PROXY_SUBSONIC_USER` | yes | - | Subsonic username |
| `SUBSONIC_PROXY_SUBSONIC_PASSWORD` | yes | - | Subsonic password |
| `SUBSONIC_PROXY_BASE_URL` | no | `http://localhost:8000` | Public URL of this proxy |
| `SUBSONIC_PROXY_SLOT_COUNT` | no | `1000` | Number of HLS URL slots |
| `SUBSONIC_PROXY_CACHE_DIR` | no | `./cache` | HLS segment cache directory |
| `SUBSONIC_PROXY_CACHE_TTL_SECONDS` | no | `3600` | Cache expiration in seconds |

### Subsonic API Notes

- Auth: token-based (`t=md5(password+salt)`, `s=salt`)
- `getAlbumList2` response: `subsonic-response.albumList2.album[]`
- `getAlbum` response: `subsonic-response.album.song[]` (key is `song`, NOT `songs`)
- IDs are hex hashes (e.g. `001ad6b8826407b505b1996697e2a8e3`)

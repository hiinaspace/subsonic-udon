# Subsonic Udon

VRChat music player world backed by a Subsonic-compatible music server. Browse and play your music library in VRChat through VizVid.

## Architecture

Two components:

1. **Proxy server** (`server/`): Python/FastAPI service that bridges a Subsonic server to VRChat. Exposes enumerable static HLS URLs (`/0001.m3u8` ... `/NNNN.m3u8`) and a `/metadata.json` endpoint mapping track info to slots. Transcodes audio to HLS via ffmpeg with disk caching.

2. **VPM package** (`Packages/space.hiina.subsonic-udon/`): UdonSharp package that pre-generates VRCUrl slots at editor time, fetches metadata at runtime, and plays tracks through VizVid.

VRChat constraint: VRCUrl objects must be statically embedded in the world asset bundle and cannot be constructed at runtime. The proxy provides a fixed set of slot URLs that the Unity side pre-generates.

## Server

```bash
cd server
uv sync
uv run uvicorn subsonic_proxy.app:app --reload
```

See `CLAUDE.md` for full environment variable reference.

## Unity Package

Requires VRChat Worlds SDK 3.9+ and VizVid 1.5.3+.

1. Add `Packages/space.hiina.subsonic-udon/` to your Unity project.
2. Add a `SubsonicBrowser` component to a GameObject.
3. In the inspector, set the proxy Base URL and click "Generate Slots".
4. Assign a VizVid `FrontendHandler` reference and set the player index for AVPro (HLS).

## License

TBD

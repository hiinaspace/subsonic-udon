import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

from subsonic_proxy.cache import CacheManager
from subsonic_proxy.config import Settings
from subsonic_proxy.metadata import MetadataBuilder, MetadataResponse
from subsonic_proxy.subsonic import SubsonicClient
from subsonic_proxy.transcoder import HLSTranscoder, TranscodeError


class AppState:
    settings: Settings
    subsonic: SubsonicClient
    transcoder: HLSTranscoder
    cache: CacheManager
    metadata_builder: MetadataBuilder
    metadata: MetadataResponse


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the FastAPI application. Pass settings for testing; omit for production
    (will read from env vars at startup)."""

    @asynccontextmanager
    async def lifespan(the_app: FastAPI):
        nonlocal settings
        if settings is None:
            settings = Settings()

        # Configure logging
        logging.basicConfig(
            level=getattr(logging, settings.log_level.upper()),
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # Suppress noisy HTTP client logs
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)

        logger = logging.getLogger(__name__)
        logger.info("Starting Subsonic VRChat Proxy")

        state = AppState()
        state.settings = settings
        state.subsonic = SubsonicClient(settings)
        state.cache = CacheManager(
            cache_dir=Path(settings.cache_dir),
            ttl_seconds=settings.cache_ttl_seconds,
        )
        state.transcoder = HLSTranscoder(
            settings=settings,
            cache_manager=state.cache,
            subsonic_client=state.subsonic,
        )
        state.metadata_builder = MetadataBuilder(settings=settings, subsonic=state.subsonic)
        state.metadata = await state.metadata_builder.build()
        the_app.state.svc = state
        yield
        await state.subsonic.close()

    application = FastAPI(title="Subsonic VRChat Proxy", lifespan=lifespan)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.get("/metadata.json")
    async def get_metadata():
        state: AppState = application.state.svc
        return state.metadata

    @application.get("/{slot_id}.m3u8")
    async def get_hls_playlist(slot_id: str):
        state: AppState = application.state.svc
        logger = logging.getLogger(__name__)

        if slot_id not in state.metadata.tracks:
            logger.warning(f"Slot {slot_id} not found")
            raise HTTPException(404, f"Slot {slot_id} not found")

        track = state.metadata.tracks[slot_id]
        stream_url = state.subsonic.get_stream_url(track.id)

        # Prepare track info dict
        track_info = {
            "title": track.title,
            "artist": track.artist,
            "album": track.album,
            "coverArt": track.cover_art,
        }

        try:
            logger.info(f"Serving HLS for slot {slot_id}: {track.title} - {track.artist}")
            m3u8_path = await state.transcoder.ensure_transcoded(slot_id, stream_url, track_info)
        except TranscodeError as e:
            logger.error(f"Transcoding failed for slot {slot_id}: {e}")
            raise HTTPException(502, f"Transcoding failed: {e}")

        content = m3u8_path.read_text()
        base_url = state.settings.base_url.rstrip("/")
        content = re.sub(
            r"(seg\d+\.ts)",
            lambda m: f"{base_url}/segments/{slot_id}/{m.group(1)}",
            content,
        )
        return Response(content, media_type="application/vnd.apple.mpegurl")

    @application.get("/segments/{slot_id}/{segment_name}")
    async def get_segment(slot_id: str, segment_name: str):
        state: AppState = application.state.svc
        segment_path = Path(state.settings.cache_dir) / "segments" / slot_id / segment_name
        if not segment_path.exists():
            raise HTTPException(404, "Segment not found")
        return FileResponse(segment_path, media_type="video/mp2t")

    @application.get("/{slot_id}.mp3")
    async def get_audio(slot_id: str):
        """Proxy audio file directly from Subsonic (no transcoding)."""
        state: AppState = application.state.svc
        logger = logging.getLogger(__name__)

        # Validate slot exists
        if slot_id not in state.metadata.tracks:
            logger.warning(f"Slot {slot_id} not found")
            raise HTTPException(404, f"Slot {slot_id} not found")

        track = state.metadata.tracks[slot_id]

        # Check cache first
        cache_path = Path(state.settings.cache_dir) / "audio" / f"{slot_id}.mp3"
        if cache_path.exists() and not state.cache.is_expired(cache_path):
            logger.info(f"Serving cached audio for slot {slot_id}: {track.title}")
            return FileResponse(
                cache_path,
                media_type="audio/mpeg",
                headers={
                    "Accept-Ranges": "bytes",
                    "Content-Disposition": f'inline; filename="{slot_id}.mp3"',
                },
            )

        # Download from Subsonic and cache
        logger.info(f"Downloading audio for slot {slot_id}: {track.title} - {track.artist}")
        audio_format = getattr(state.settings, "audio_format", "mp3")
        max_bitrate = getattr(state.settings, "audio_max_bitrate", 320)
        audio_data = await state.subsonic.get_audio_stream(
            track.id, format=audio_format, max_bitrate=max_bitrate
        )

        # Save to cache
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(audio_data)

        logger.info(f"Cached audio for slot {slot_id} ({len(audio_data) / 1024 / 1024:.2f} MB)")

        return FileResponse(
            cache_path,
            media_type="audio/mpeg",
            headers={
                "Accept-Ranges": "bytes",
                "Content-Disposition": f'inline; filename="{slot_id}.mp3"',
            },
        )

    @application.post("/refresh")
    async def refresh():
        state: AppState = application.state.svc
        state.metadata = await state.metadata_builder.build(force_refresh=True)
        return {"status": "ok", "track_count": len(state.metadata.tracks)}

    return application


# Default app for uvicorn: `uvicorn subsonic_proxy.app:app`
# Settings loaded from env vars at startup (lifespan), not at import time.
app = create_app()

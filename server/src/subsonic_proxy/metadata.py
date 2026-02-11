import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

from subsonic_proxy.config import Settings
from subsonic_proxy.subsonic import SubsonicClient

logger = logging.getLogger(__name__)


class TrackInfo(BaseModel):
    id: str
    title: str
    artist: str
    album: str
    album_id: str
    duration: int
    cover_art: str | None = None


class AlbumInfo(BaseModel):
    name: str
    artist: str
    track_slots: list[str]


class MetadataResponse(BaseModel):
    version: int
    base_url: str
    slot_count: int
    tracks: dict[str, TrackInfo]
    albums: dict[str, AlbumInfo]


class MetadataBuilder:
    def __init__(self, settings: Settings, subsonic: SubsonicClient):
        self._settings = settings
        self._subsonic = subsonic
        self._cache_path = Path(settings.cache_dir) / "metadata.json"
        self._cache_ttl = timedelta(seconds=settings.cache_ttl_seconds)

    def _load_from_cache(self) -> MetadataResponse | None:
        """Load metadata from cache if it exists and is fresh."""
        if not self._cache_path.exists():
            logger.info("No cached metadata found")
            return None

        # Check if cache is expired
        mtime = datetime.fromtimestamp(self._cache_path.stat().st_mtime)
        if datetime.now() - mtime > self._cache_ttl:
            logger.info("Cached metadata expired (age: %s)", datetime.now() - mtime)
            return None

        try:
            logger.info("Loading metadata from cache (%s old)", datetime.now() - mtime)
            data = json.loads(self._cache_path.read_text())
            return MetadataResponse(**data)
        except Exception as e:
            logger.warning(f"Failed to load cached metadata: {e}")
            return None

    def _save_to_cache(self, metadata: MetadataResponse):
        """Save metadata to cache."""
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(metadata.model_dump_json(indent=2))
            logger.info(f"Saved metadata to cache: {len(metadata.tracks)} tracks")
        except Exception as e:
            logger.warning(f"Failed to save metadata to cache: {e}")

    async def build(self, force_refresh: bool = False) -> MetadataResponse:
        """Build metadata from Subsonic server or load from cache.

        Args:
            force_refresh: If True, ignore cache and rebuild from server
        """
        # Try to load from cache first (unless force refresh)
        if not force_refresh:
            cached = self._load_from_cache()
            if cached is not None:
                # Update base_url in case it changed
                cached.base_url = self._settings.base_url
                return cached

        logger.info("Building metadata from Subsonic server (this may take a moment)...")
        all_tracks = await self._subsonic.get_all_tracks(
            strategy=self._settings.selection_strategy,
            max_count=self._settings.slot_count,
        )

        tracks: dict[str, TrackInfo] = {}
        albums: dict[str, AlbumInfo] = {}

        for i, song in enumerate(all_tracks):
            slot_id = f"{i + 1:04d}"
            album_id = song.get("albumId", "")

            tracks[slot_id] = TrackInfo(
                id=song["id"],
                title=song.get("title", ""),
                artist=song.get("artist", ""),
                album=song.get("album", ""),
                album_id=album_id,
                duration=song.get("duration", 0),
                cover_art=song.get("coverArt"),
            )

            if album_id and album_id not in albums:
                albums[album_id] = AlbumInfo(
                    name=song.get("album", ""),
                    artist=song.get("artist", ""),
                    track_slots=[],
                )
            if album_id:
                albums[album_id].track_slots.append(slot_id)

        metadata = MetadataResponse(
            version=1,
            base_url=self._settings.base_url,
            slot_count=self._settings.slot_count,
            tracks=tracks,
            albums=albums,
        )

        # Save to cache for next time
        self._save_to_cache(metadata)

        return metadata

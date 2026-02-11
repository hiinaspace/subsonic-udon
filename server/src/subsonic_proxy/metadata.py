from pydantic import BaseModel

from subsonic_proxy.config import Settings
from subsonic_proxy.subsonic import SubsonicClient


class TrackInfo(BaseModel):
    id: str
    title: str
    artist: str
    album: str
    album_id: str
    duration: int


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

    async def build(self) -> MetadataResponse:
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
            )

            if album_id and album_id not in albums:
                albums[album_id] = AlbumInfo(
                    name=song.get("album", ""),
                    artist=song.get("artist", ""),
                    track_slots=[],
                )
            if album_id:
                albums[album_id].track_slots.append(slot_id)

        return MetadataResponse(
            version=1,
            base_url=self._settings.base_url,
            slot_count=self._settings.slot_count,
            tracks=tracks,
            albums=albums,
        )

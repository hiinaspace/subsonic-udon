"""Integration tests against a real Subsonic server.

Run with: uv run pytest tests/test_integration.py -v

Requires a .env file in server/ or env vars set:
    SUBSONIC_PROXY_SUBSONIC_URL=https://your-server.example.com
    SUBSONIC_PROXY_SUBSONIC_USER=youruser
    SUBSONIC_PROXY_SUBSONIC_PASSWORD=yourpass
"""

import os

import pytest

from subsonic_proxy.config import Settings
from subsonic_proxy.metadata import MetadataBuilder
from subsonic_proxy.subsonic import SubsonicClient

pytestmark = pytest.mark.skipif(
    not os.environ.get("SUBSONIC_PROXY_SUBSONIC_URL"),
    reason="Set SUBSONIC_PROXY_SUBSONIC_URL (and _USER, _PASSWORD) to run integration tests",
)


@pytest.fixture(scope="module")
def real_settings():
    return Settings(
        _env_file=".env",
        cache_dir="./test_cache",
        base_url="http://localhost:8000",
        slot_count=20,
    )


class TestRealSubsonicClient:
    @pytest.mark.anyio
    async def test_ping(self, real_settings):
        async with SubsonicClient(real_settings) as client:
            sr = await client._get("ping")
            assert sr["status"] == "ok"

    @pytest.mark.anyio
    async def test_get_album_list(self, real_settings):
        async with SubsonicClient(real_settings) as client:
            albums = await client.get_album_list(size=5)
        assert len(albums) > 0
        album = albums[0]
        assert "id" in album
        assert "name" in album
        assert "artist" in album

    @pytest.mark.anyio
    async def test_get_album_has_song_key(self, real_settings):
        """Verify the real API uses 'song' not 'songs'."""
        async with SubsonicClient(real_settings) as client:
            albums = await client.get_album_list(size=1)
            album = await client.get_album(albums[0]["id"])
        assert "song" in album
        assert isinstance(album["song"], list)
        assert len(album["song"]) > 0
        song = album["song"][0]
        assert "id" in song
        assert "title" in song
        assert "duration" in song

    @pytest.mark.anyio
    async def test_get_stream_url_is_valid(self, real_settings):
        """Verify stream URL construction is valid (doesn't actually stream)."""
        async with SubsonicClient(real_settings) as client:
            albums = await client.get_album_list(size=1)
            album = await client.get_album(albums[0]["id"])
            song_id = album["song"][0]["id"]
            url = client.get_stream_url(song_id)
        assert "stream.view" in url
        assert f"id={song_id}" in url

    @pytest.mark.anyio
    async def test_get_all_tracks(self, real_settings):
        async with SubsonicClient(real_settings) as client:
            tracks = await client.get_all_tracks(max_count=10)
        assert len(tracks) > 0
        assert len(tracks) <= 10
        for track in tracks:
            assert "id" in track
            assert "title" in track


class TestRealMetadataBuilder:
    @pytest.mark.anyio
    async def test_builds_metadata(self, real_settings):
        async with SubsonicClient(real_settings) as subsonic:
            builder = MetadataBuilder(settings=real_settings, subsonic=subsonic)
            metadata = await builder.build()

        assert metadata.version == 1
        assert len(metadata.tracks) > 0
        assert len(metadata.tracks) <= 20
        assert len(metadata.albums) > 0

        # Check a track has all fields
        first_slot = sorted(metadata.tracks.keys())[0]
        track = metadata.tracks[first_slot]
        assert track.title
        assert track.id
        assert track.duration > 0

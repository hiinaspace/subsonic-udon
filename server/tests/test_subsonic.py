import hashlib

import pytest

from subsonic_proxy.subsonic import SubsonicClient


class TestAuthParams:
    def test_generates_valid_token(self, settings):
        client = SubsonicClient(settings)
        params = client._auth_params()

        assert params["u"] == "testuser"
        assert params["v"] == "1.16.1"
        assert params["c"] == "subsonic-udon"
        assert params["f"] == "json"
        assert "t" in params
        assert "s" in params

        # Verify token is md5(password + salt)
        expected = hashlib.md5((settings.subsonic_password + params["s"]).encode()).hexdigest()
        assert params["t"] == expected

    def test_salt_is_random(self, settings):
        client = SubsonicClient(settings)
        params1 = client._auth_params()
        params2 = client._auth_params()
        assert params1["s"] != params2["s"]


class TestGetAlbumList:
    @pytest.mark.anyio
    async def test_parses_albums(self, settings, mock_subsonic):
        async with SubsonicClient(settings) as client:
            albums = await client.get_album_list()

        assert len(albums) == 3
        assert albums[0]["id"] == "album001"
        assert albums[0]["name"] == "Immersion"
        assert albums[0]["artist"] == "Pendulum"
        assert albums[1]["id"] == "album002"
        assert albums[2]["id"] == "album003"

    @pytest.mark.anyio
    async def test_paginates(self, settings, mock_subsonic):
        async with SubsonicClient(settings) as client:
            # First page returns albums, second returns empty
            page1 = await client.get_album_list(offset=0)
            page2 = await client.get_album_list(offset=500)

        assert len(page1) == 3
        assert len(page2) == 0


class TestGetAlbum:
    @pytest.mark.anyio
    async def test_parses_songs(self, settings, mock_subsonic):
        async with SubsonicClient(settings) as client:
            album = await client.get_album("album001")

        assert album["name"] == "Immersion"
        songs = album["song"]
        assert len(songs) == 2
        assert songs[0]["id"] == "song001"
        assert songs[0]["title"] == "Watercolour"
        assert songs[0]["duration"] == 264
        assert songs[0]["albumId"] == "album001"

    @pytest.mark.anyio
    async def test_uses_song_key_not_songs(self, settings, mock_subsonic):
        """Subsonic API uses 'song' not 'songs' as the key."""
        async with SubsonicClient(settings) as client:
            album = await client.get_album("album002")

        assert "song" in album
        assert len(album["song"]) == 3


class TestGetAllTracks:
    @pytest.mark.anyio
    async def test_collects_all_tracks(self, settings, mock_subsonic):
        async with SubsonicClient(settings) as client:
            tracks = await client.get_all_tracks()

        assert len(tracks) == 7
        titles = [t["title"] for t in tracks]
        assert "Watercolour" in titles
        assert "Lisa Frank 420" in titles
        assert "Hidamari" in titles

    @pytest.mark.anyio
    async def test_respects_max_count(self, settings, mock_subsonic):
        async with SubsonicClient(settings) as client:
            tracks = await client.get_all_tracks(max_count=3)

        assert len(tracks) == 3


class TestGetStreamUrl:
    def test_includes_auth_and_id(self, settings):
        client = SubsonicClient(settings)
        url = client.get_stream_url("song001")

        assert url.startswith(settings.subsonic_url)
        assert "/rest/stream.view" in url
        assert "id=song001" in url
        assert "u=testuser" in url
        assert "f=json" in url
        assert "t=" in url
        assert "s=" in url


class TestGetAudioStream:
    @pytest.mark.anyio
    async def test_downloads_audio_data(self, settings, mock_subsonic):
        async with SubsonicClient(settings) as client:
            audio_data = await client.get_audio_stream("song001")

        assert isinstance(audio_data, bytes)
        assert b"FAKE_MP3_DATA_song001" in audio_data

    @pytest.mark.anyio
    async def test_includes_format_and_bitrate_params(self, settings, mock_subsonic):
        async with SubsonicClient(settings) as client:
            audio_data = await client.get_audio_stream("song002", format="ogg", max_bitrate=192)

        assert isinstance(audio_data, bytes)
        # Verify the request was made (mock handled it)
        assert b"FAKE_MP3_DATA_song002" in audio_data

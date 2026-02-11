import pytest
from httpx import ASGITransport, AsyncClient

from subsonic_proxy.app import AppState, create_app
from subsonic_proxy.cache import CacheManager
from subsonic_proxy.config import Settings
from subsonic_proxy.metadata import MetadataBuilder
from subsonic_proxy.subsonic import SubsonicClient
from subsonic_proxy.transcoder import HLSTranscoder
from tests.conftest import MOCK_SUBSONIC_URL

from pathlib import Path


@pytest.fixture
def test_settings(tmp_path):
    return Settings(
        subsonic_url=MOCK_SUBSONIC_URL,
        subsonic_user="testuser",
        subsonic_password="testpass",
        cache_dir=str(tmp_path / "cache"),
        base_url="http://localhost:8000",
        slot_count=1000,
    )


@pytest.fixture
async def client(test_settings, mock_subsonic):
    """Create a test app with pre-initialized state (bypassing lifespan)."""
    test_app = create_app(settings=test_settings)

    # Manually initialize state instead of relying on lifespan
    state = AppState()
    state.settings = test_settings
    state.subsonic = SubsonicClient(test_settings)
    state.cache = CacheManager(
        cache_dir=Path(test_settings.cache_dir),
        ttl_seconds=test_settings.cache_ttl_seconds,
    )
    state.transcoder = HLSTranscoder(
        settings=test_settings, cache_manager=state.cache, subsonic_client=state.subsonic
    )
    state.metadata_builder = MetadataBuilder(settings=test_settings, subsonic=state.subsonic)
    state.metadata = await state.metadata_builder.build()
    test_app.state.svc = state

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await state.subsonic.close()


class TestMetadataEndpoint:
    @pytest.mark.anyio
    async def test_schema(self, client):
        resp = await client.get("/metadata.json")
        assert resp.status_code == 200
        data = resp.json()
        assert "version" in data
        assert "base_url" in data
        assert "slot_count" in data
        assert "tracks" in data
        assert "albums" in data
        assert data["version"] == 1

    @pytest.mark.anyio
    async def test_tracks_have_required_fields(self, client):
        resp = await client.get("/metadata.json")
        data = resp.json()
        for slot_id, track in data["tracks"].items():
            assert "id" in track
            assert "title" in track
            assert "artist" in track
            assert "album" in track
            assert "album_id" in track
            assert "duration" in track
            assert slot_id.isdigit()

    @pytest.mark.anyio
    async def test_slot_count_matches(self, client):
        resp = await client.get("/metadata.json")
        data = resp.json()
        assert data["slot_count"] == 1000
        # We have 7 mock tracks, all should be mapped
        assert len(data["tracks"]) == 7

    @pytest.mark.anyio
    async def test_albums_have_required_fields(self, client):
        resp = await client.get("/metadata.json")
        data = resp.json()
        for album_id, album in data["albums"].items():
            assert "name" in album
            assert "artist" in album
            assert "track_slots" in album
            assert isinstance(album["track_slots"], list)

    @pytest.mark.anyio
    async def test_tracks_have_sequential_slot_ids(self, client):
        resp = await client.get("/metadata.json")
        data = resp.json()
        slot_ids = sorted(data["tracks"].keys())
        expected = [f"{i + 1:04d}" for i in range(len(slot_ids))]
        assert slot_ids == expected


class TestHLSEndpoint:
    @pytest.mark.anyio
    async def test_invalid_slot_404(self, client):
        resp = await client.get("/9999.m3u8")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_nonexistent_slot_format_404(self, client):
        resp = await client.get("/notaslot.m3u8")
        assert resp.status_code == 404


class TestSegmentEndpoint:
    @pytest.mark.anyio
    async def test_missing_segment_404(self, client):
        resp = await client.get("/segments/0001/seg000.ts")
        assert resp.status_code == 404


class TestAudioEndpoint:
    @pytest.mark.anyio
    async def test_invalid_slot_404(self, client):
        resp = await client.get("/9999.mp3")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_nonexistent_slot_format_404(self, client):
        resp = await client.get("/notaslot.mp3")
        assert resp.status_code == 404


class TestRefreshEndpoint:
    @pytest.mark.anyio
    async def test_refresh_returns_ok(self, client):
        resp = await client.post("/refresh")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "track_count" in data


class TestCORS:
    @pytest.mark.anyio
    async def test_cors_headers(self, client):
        resp = await client.options(
            "/metadata.json",
            headers={"Origin": "https://example.com", "Access-Control-Request-Method": "GET"},
        )
        assert resp.headers.get("access-control-allow-origin") == "*"

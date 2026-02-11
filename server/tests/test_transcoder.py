import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from subsonic_proxy.cache import CacheManager
from subsonic_proxy.transcoder import HLSTranscoder


@pytest.fixture
def cache_dir(tmp_path):
    return tmp_path / "cache"


@pytest.fixture
def cache_manager(cache_dir):
    return CacheManager(cache_dir=cache_dir, ttl_seconds=3600)


@pytest.fixture
def transcoder(settings, cache_manager):
    return HLSTranscoder(settings=settings, cache_manager=cache_manager)


def _create_fake_hls(slot_dir: Path):
    """Create fake HLS files to simulate ffmpeg output."""
    slot_dir.mkdir(parents=True, exist_ok=True)
    m3u8_content = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:3\n"
        "#EXT-X-TARGETDURATION:10\n"
        "#EXT-X-MEDIA-SEQUENCE:0\n"
        "#EXT-X-PLAYLIST-TYPE:VOD\n"
        "#EXTINF:10.0,\n"
        "seg000.ts\n"
        "#EXTINF:10.0,\n"
        "seg001.ts\n"
        "#EXTINF:4.5,\n"
        "seg002.ts\n"
        "#EXT-X-ENDLIST\n"
    )
    (slot_dir / "index.m3u8").write_text(m3u8_content)
    (slot_dir / "seg000.ts").write_bytes(b"\x00" * 1024)
    (slot_dir / "seg001.ts").write_bytes(b"\x00" * 1024)
    (slot_dir / "seg002.ts").write_bytes(b"\x00" * 1024)


class TestHLSTranscoder:
    @pytest.mark.anyio
    async def test_transcode_creates_files(self, transcoder, cache_dir):
        slot_dir = cache_dir / "segments" / "0001"

        async def fake_ffmpeg(*args, **kwargs):
            _create_fake_hls(slot_dir)

        with patch.object(transcoder, "_run_ffmpeg", new=AsyncMock(side_effect=fake_ffmpeg)):
            m3u8_path = await transcoder.ensure_transcoded("0001", "song001")

        assert m3u8_path.exists()
        assert (slot_dir / "seg000.ts").exists()
        assert (slot_dir / "seg001.ts").exists()

    @pytest.mark.anyio
    async def test_m3u8_is_valid_hls(self, transcoder, cache_dir):
        slot_dir = cache_dir / "segments" / "0001"

        async def fake_ffmpeg(*args, **kwargs):
            _create_fake_hls(slot_dir)

        with patch.object(transcoder, "_run_ffmpeg", new=AsyncMock(side_effect=fake_ffmpeg)):
            m3u8_path = await transcoder.ensure_transcoded("0001", "song001")

        content = m3u8_path.read_text()
        assert "#EXTM3U" in content
        assert "#EXT-X-PLAYLIST-TYPE:VOD" in content
        assert "#EXT-X-ENDLIST" in content

    @pytest.mark.anyio
    async def test_cached_transcode_skips_ffmpeg(self, transcoder, cache_dir):
        slot_dir = cache_dir / "segments" / "0001"
        _create_fake_hls(slot_dir)

        mock_ffmpeg = AsyncMock()
        with patch.object(transcoder, "_run_ffmpeg", new=mock_ffmpeg):
            await transcoder.ensure_transcoded("0001", "song001")

        mock_ffmpeg.assert_not_called()

    @pytest.mark.anyio
    async def test_expired_cache_retranscodes(self, cache_dir):
        cache_manager = CacheManager(cache_dir=cache_dir, ttl_seconds=0)
        settings_with_zero_ttl = type(
            "S",
            (),
            {
                "cache_dir": str(cache_dir),
                "ffmpeg_path": "ffmpeg",
                "hls_segment_duration": 10,
                "audio_bitrate": "192k",
            },
        )()
        transcoder = HLSTranscoder(settings=settings_with_zero_ttl, cache_manager=cache_manager)

        slot_dir = cache_dir / "segments" / "0001"
        _create_fake_hls(slot_dir)
        # Set mtime to the past to ensure expiration
        old_time = time.time() - 10
        os.utime(slot_dir / "index.m3u8", (old_time, old_time))

        call_count = 0

        async def fake_ffmpeg(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            _create_fake_hls(slot_dir)

        with patch.object(transcoder, "_run_ffmpeg", new=AsyncMock(side_effect=fake_ffmpeg)):
            await transcoder.ensure_transcoded("0001", "song001")

        assert call_count == 1


class TestCacheManager:
    def test_not_expired_within_ttl(self, cache_dir, cache_manager):
        slot_dir = cache_dir / "segments" / "0001"
        _create_fake_hls(slot_dir)
        assert not cache_manager.is_expired(slot_dir / "index.m3u8")

    def test_expired_when_old(self, cache_dir):
        manager = CacheManager(cache_dir=cache_dir, ttl_seconds=0)
        slot_dir = cache_dir / "segments" / "0001"
        _create_fake_hls(slot_dir)
        old_time = time.time() - 10
        os.utime(slot_dir / "index.m3u8", (old_time, old_time))
        assert manager.is_expired(slot_dir / "index.m3u8")

    def test_expired_when_missing(self, cache_manager, cache_dir):
        assert cache_manager.is_expired(cache_dir / "nonexistent")

    def test_cleanup_removes_expired(self, cache_dir):
        manager = CacheManager(cache_dir=cache_dir, ttl_seconds=0)
        slot_dir = cache_dir / "segments" / "0001"
        _create_fake_hls(slot_dir)
        old_time = time.time() - 10
        os.utime(slot_dir / "index.m3u8", (old_time, old_time))

        manager.cleanup()
        assert not slot_dir.exists()

    def test_cleanup_keeps_fresh(self, cache_dir, cache_manager):
        slot_dir = cache_dir / "segments" / "0001"
        _create_fake_hls(slot_dir)

        cache_manager.cleanup()
        assert slot_dir.exists()

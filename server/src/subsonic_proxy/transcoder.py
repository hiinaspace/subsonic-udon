import asyncio
from pathlib import Path

from subsonic_proxy.cache import CacheManager


class TranscodeError(Exception):
    pass


class HLSTranscoder:
    def __init__(self, settings, cache_manager: CacheManager):
        self._cache_dir = Path(settings.cache_dir)
        self._segment_duration = settings.hls_segment_duration
        self._audio_bitrate = settings.audio_bitrate
        self._ffmpeg_path = settings.ffmpeg_path
        self._cache_manager = cache_manager

    def _slot_dir(self, slot_id: str) -> Path:
        return self._cache_dir / "segments" / slot_id

    async def ensure_transcoded(self, slot_id: str, stream_url: str) -> Path:
        slot_dir = self._slot_dir(slot_id)
        m3u8_path = slot_dir / "index.m3u8"

        if m3u8_path.exists() and not self._cache_manager.is_expired(m3u8_path):
            return m3u8_path

        slot_dir.mkdir(parents=True, exist_ok=True)
        await self._run_ffmpeg(stream_url, slot_dir)
        return m3u8_path

    async def _run_ffmpeg(self, input_url: str, output_dir: Path):
        cmd = [
            self._ffmpeg_path,
            "-y",
            "-i",
            input_url,
            "-vn",
            "-acodec",
            "aac",
            "-b:a",
            self._audio_bitrate,
            "-f",
            "hls",
            "-hls_time",
            str(self._segment_duration),
            "-hls_playlist_type",
            "vod",
            "-hls_segment_filename",
            str(output_dir / "seg%03d.ts"),
            str(output_dir / "index.m3u8"),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise TranscodeError(f"ffmpeg failed (exit {proc.returncode}): {stderr.decode()}")

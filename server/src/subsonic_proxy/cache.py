import shutil
from datetime import datetime, timedelta
from pathlib import Path


class CacheManager:
    def __init__(self, cache_dir: Path | str, ttl_seconds: int):
        self.cache_dir = Path(cache_dir)
        self.ttl = timedelta(seconds=ttl_seconds)

    def is_expired(self, path: Path) -> bool:
        if not path.exists():
            return True
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        return datetime.now() - mtime > self.ttl

    def get_cover_art_path(self, cover_art_id: str) -> Path:
        """Get path for cached cover art."""
        cover_dir = self.cache_dir / "covers"
        cover_dir.mkdir(parents=True, exist_ok=True)
        return cover_dir / f"{cover_art_id}.jpg"

    def is_cover_art_cached(self, cover_art_id: str) -> bool:
        """Check if cover art is cached and not expired."""
        path = self.get_cover_art_path(cover_art_id)
        return path.exists() and not self.is_expired(path)

    def cleanup(self):
        # Clean up expired segment directories
        segments_dir = self.cache_dir / "segments"
        if segments_dir.exists():
            for slot_dir in segments_dir.iterdir():
                if not slot_dir.is_dir():
                    continue
                m3u8 = slot_dir / "index.m3u8"
                if self.is_expired(m3u8):
                    shutil.rmtree(slot_dir)

        # Clean up expired cover art
        covers_dir = self.cache_dir / "covers"
        if covers_dir.exists():
            for cover_file in covers_dir.iterdir():
                if cover_file.is_file() and self.is_expired(cover_file):
                    cover_file.unlink()

        # Clean up expired audio files
        audio_dir = self.cache_dir / "audio"
        if audio_dir.exists():
            for audio_file in audio_dir.iterdir():
                if audio_file.is_file() and self.is_expired(audio_file):
                    audio_file.unlink()

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

    def cleanup(self):
        segments_dir = self.cache_dir / "segments"
        if not segments_dir.exists():
            return
        for slot_dir in segments_dir.iterdir():
            if not slot_dir.is_dir():
                continue
            m3u8 = slot_dir / "index.m3u8"
            if self.is_expired(m3u8):
                shutil.rmtree(slot_dir)

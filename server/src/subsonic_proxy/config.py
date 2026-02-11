from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SUBSONIC_PROXY_")

    subsonic_url: str
    subsonic_user: str
    subsonic_password: str
    subsonic_api_version: str = "1.16.1"
    subsonic_client_id: str = "subsonic-udon"

    cache_dir: str = "./cache"
    cache_ttl_seconds: int = 3600

    slot_count: int = 1000
    base_url: str = "http://localhost:8000"

    ffmpeg_path: str = "ffmpeg"
    hls_segment_duration: int = 10
    audio_bitrate: str = "192k"

    selection_strategy: str = "recent"

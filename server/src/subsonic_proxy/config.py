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

    # Video generation settings
    video_width: int = 640
    video_height: int = 640
    video_framerate: int = 1  # Low framerate with pre-rendered overlay
    video_bitrate: str = "50k"
    video_maxrate: str = "75k"
    video_bufsize: str = "150k"

    # Text overlay settings (Noto Sans CJK supports Japanese/Chinese/Korean)
    text_font: str = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"

    # Fallback cover art
    fallback_bg_color: str = "#1a1a2e"

    # Logging
    log_level: str = "INFO"

    # Concurrency limits
    max_concurrent_transcodes: int = 3

    # Audio streaming settings
    audio_format: str = "mp3"  # Format for direct streaming
    audio_max_bitrate: int = 320  # Maximum bitrate in kbps

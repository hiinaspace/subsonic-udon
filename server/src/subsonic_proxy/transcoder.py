import asyncio
import logging
import time
from pathlib import Path

from filelock import FileLock, Timeout
from PIL import Image, ImageDraw, ImageFont

from subsonic_proxy.cache import CacheManager

logger = logging.getLogger(__name__)


class TranscodeError(Exception):
    pass


class HLSTranscoder:
    def __init__(self, settings, cache_manager: CacheManager, subsonic_client):
        self._cache_dir = Path(settings.cache_dir)
        self._segment_duration = settings.hls_segment_duration
        self._audio_bitrate = settings.audio_bitrate
        self._ffmpeg_path = settings.ffmpeg_path
        self._cache_manager = cache_manager
        self._subsonic = subsonic_client

        # Video settings
        self._video_width = settings.video_width
        self._video_height = settings.video_height
        self._video_framerate = settings.video_framerate
        self._video_bitrate = settings.video_bitrate
        self._video_maxrate = settings.video_maxrate
        self._video_bufsize = settings.video_bufsize

        # Text overlay settings
        self._text_font = settings.text_font
        self._validate_font()

        # Fallback cover art
        self._fallback_color = settings.fallback_bg_color

        # Concurrency control
        self._max_concurrent = settings.max_concurrent_transcodes
        self._transcode_semaphore = asyncio.Semaphore(self._max_concurrent)

    def _validate_font(self):
        """Check if font file exists, log warning with suggestions if not."""
        font_path = Path(self._text_font)
        if not font_path.exists():
            logger.warning(
                f"Font file not found: {self._text_font}. "
                "Text overlays may not render correctly, especially for non-ASCII characters."
            )
            # Suggest common alternatives
            fallbacks = [
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",  # macOS
            ]
            available = [f for f in fallbacks if Path(f).exists()]
            if available:
                logger.warning(f"Available fonts on this system: {', '.join(available)}")
                logger.warning(
                    f"Set SUBSONIC_PROXY_TEXT_FONT environment variable to use a different font"
                )

    def _slot_dir(self, slot_id: str) -> Path:
        return self._cache_dir / "segments" / slot_id

    def _get_lock_path(self, slot_id: str) -> Path:
        """Get the lock file path for a slot."""
        locks_dir = self._cache_dir / "locks"
        locks_dir.mkdir(parents=True, exist_ok=True)
        return locks_dir / f"{slot_id}.lock"

    async def ensure_transcoded(self, slot_id: str, stream_url: str, track_info: dict) -> Path:
        """Ensure track is transcoded with video.

        track_info should contain: title, artist, album, coverArt (optional)

        Uses file-based locking to prevent multiple concurrent transcodes of the same slot,
        and a semaphore to limit total concurrent transcodes.
        """
        slot_dir = self._slot_dir(slot_id)
        m3u8_path = slot_dir / "index.m3u8"

        # Quick check without lock - cache hit path is fast
        if m3u8_path.exists() and not self._cache_manager.is_expired(m3u8_path):
            logger.info(f"Using cached HLS for slot {slot_id}")
            return m3u8_path

        # Acquire per-slot file lock to prevent concurrent transcoding of same track
        lock_path = self._get_lock_path(slot_id)
        lock = FileLock(lock_path, timeout=300)  # 5 minute timeout

        try:
            # Run lock acquisition in thread pool to avoid blocking event loop
            await asyncio.to_thread(lock.acquire)
            try:
                # Double-check after acquiring lock (another request might have finished)
                if m3u8_path.exists() and not self._cache_manager.is_expired(m3u8_path):
                    logger.info(f"Using cached HLS for slot {slot_id} (completed while waiting)")
                    return m3u8_path

                # Acquire global semaphore to limit concurrent transcodes
                async with self._transcode_semaphore:
                    logger.info(
                        f"Starting transcode for slot {slot_id}: "
                        f"{track_info.get('title', 'Unknown')} "
                        f"(active transcodes: {self._max_concurrent - self._transcode_semaphore._value})"
                    )
                    slot_dir.mkdir(parents=True, exist_ok=True)

                    # Prepare cover art
                    cover_art_path = slot_dir / "cover.jpg"
                    cover_art_id = track_info.get("coverArt")
                    cover_art_path = await self._prepare_cover_art(cover_art_id, cover_art_path)

                    # Pre-render text overlay onto cover art (much faster than FFmpeg drawtext)
                    rendered_path = slot_dir / "rendered.jpg"
                    await asyncio.to_thread(
                        self._render_overlay, cover_art_path, track_info, rendered_path
                    )

                    await self._run_ffmpeg(stream_url, slot_dir, rendered_path)

                    logger.info(f"Transcode complete for slot {slot_id}")
                    return m3u8_path
            finally:
                await asyncio.to_thread(lock.release)
        except Timeout:
            logger.error(f"Timeout waiting for transcode lock for slot {slot_id}")
            raise TranscodeError(
                f"Transcode lock timeout for slot {slot_id} - another transcode may be stuck"
            )

    async def _prepare_cover_art(self, cover_art_id: str | None, output_path: Path) -> Path:
        """Fetch or retrieve cached album art, or generate fallback."""
        # Check cache first
        if cover_art_id and self._cache_manager.is_cover_art_cached(cover_art_id):
            logger.info(f"Using cached cover art: {cover_art_id}")
            return self._cache_manager.get_cover_art_path(cover_art_id)

        # Try to fetch from Subsonic
        if cover_art_id:
            try:
                logger.info(f"Fetching cover art from Subsonic: {cover_art_id}")
                art_data = await self._subsonic.get_cover_art(cover_art_id)
                cached_path = self._cache_manager.get_cover_art_path(cover_art_id)
                cached_path.write_bytes(art_data)
                logger.info(f"Saved cover art to cache: {cached_path}")
                return cached_path
            except Exception as e:
                logger.warning(f"Failed to fetch cover art {cover_art_id}: {e}. Using fallback.")

        # Generate fallback using FFmpeg color filter
        logger.info("Generating fallback cover art")
        await self._generate_fallback_cover(output_path)
        return output_path

    async def _generate_fallback_cover(self, output_path: Path):
        """Generate a solid color fallback image using PIL."""
        # Parse hex color
        color = self._fallback_color.lstrip("#")
        rgb = tuple(int(color[i : i + 2], 16) for i in (0, 2, 4))

        # Create solid color image
        img = Image.new("RGB", (self._video_width, self._video_height), rgb)
        img.save(output_path, "JPEG", quality=85)

    def _render_overlay(self, cover_art_path: Path, track_info: dict, output_path: Path):
        """Pre-render text overlay onto cover art using PIL.

        This is much faster than using FFmpeg's drawtext filter.
        """
        try:
            # Load cover art
            img = Image.open(cover_art_path)

            # Resize to target dimensions if needed
            if img.size != (self._video_width, self._video_height):
                img = img.resize(
                    (self._video_width, self._video_height), Image.Resampling.LANCZOS
                )

            # Convert to RGB if needed (handle RGBA, grayscale, etc.)
            if img.mode != "RGB":
                img = img.convert("RGB")

            # Create drawing context
            draw = ImageDraw.Draw(img)

            # Load font (try to load from path, fallback to default)
            try:
                font_large = ImageFont.truetype(self._text_font, 32)
                font_medium = ImageFont.truetype(self._text_font, 24)
                font_small = ImageFont.truetype(self._text_font, 20)
            except Exception as e:
                logger.warning(f"Failed to load font {self._text_font}: {e}. Using default font.")
                font_large = ImageFont.load_default()
                font_medium = ImageFont.load_default()
                font_small = ImageFont.load_default()

            # Extract metadata
            title = track_info.get("title", "Unknown Title")
            artist = track_info.get("artist", "Unknown Artist")
            album = track_info.get("album", "Unknown Album")

            # Calculate text positions (centered horizontally)
            img_width, img_height = img.size
            center_y = img_height // 2

            # Helper to draw text with background box
            def draw_text_with_bg(text, font, y_offset):
                # Get text bounding box
                bbox = draw.textbbox((0, 0), text, font=font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]

                # Calculate position (centered)
                x = (img_width - text_width) // 2
                y = center_y + y_offset - text_height // 2

                # Draw semi-transparent background box
                padding = 5
                box_coords = [
                    x - padding,
                    y - padding,
                    x + text_width + padding,
                    y + text_height + padding,
                ]
                draw.rectangle(box_coords, fill=(0, 0, 0, 128))

                # Draw text
                draw.text((x, y), text, fill="white", font=font)

            # Draw title, artist, album
            draw_text_with_bg(title, font_large, -80)
            draw_text_with_bg(artist, font_medium, -20)
            draw_text_with_bg(album, font_small, 30)

            # Save pre-rendered image
            img.save(output_path, "JPEG", quality=85)
            logger.debug(f"Pre-rendered overlay to {output_path}")

        except Exception as e:
            logger.error(f"Failed to render overlay: {e}")
            # Fallback: just copy the original cover art
            import shutil

            shutil.copy(cover_art_path, output_path)

    async def _run_ffmpeg(self, input_url: str, output_dir: Path, rendered_cover_path: Path):
        """Run FFmpeg to transcode with pre-rendered video overlay."""
        start_time = time.time()

        cmd = [
            self._ffmpeg_path,
            "-y",
            # Input 0: pre-rendered cover art (already has text overlay and correct size)
            "-loop",
            "1",
            "-framerate",
            str(self._video_framerate),
            "-i",
            str(rendered_cover_path),
            # Input 1: audio stream
            "-i",
            input_url,
            # Map streams directly (no filter needed - image already prepared)
            "-map",
            "0:v",  # Video from input 0
            "-map",
            "1:a",  # Audio from input 1
            # Video encoding - simple settings work fine for VRChat
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "ultrafast",
            "-tune",
            "stillimage",  # Optimize for static image
            # Bitrate constraints
            "-b:v",
            self._video_bitrate,
            "-maxrate",
            self._video_maxrate,
            "-bufsize",
            self._video_bufsize,
            # Audio encoding
            "-c:a",
            "aac",
            "-b:a",
            self._audio_bitrate,
            # Use shortest stream (audio) as duration
            "-shortest",
            # HLS output
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

        logger.debug(f"FFmpeg command: {' '.join(cmd)}")

        # Execute and capture output
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        elapsed = time.time() - start_time

        if proc.returncode != 0:
            logger.error(f"FFmpeg failed (exit {proc.returncode}) after {elapsed:.2f}s")
            logger.error(f"FFmpeg stderr: {stderr.decode()}")
            raise TranscodeError(f"ffmpeg failed (exit {proc.returncode}): {stderr.decode()}")

        # Log success with size info
        total_size = sum(f.stat().st_size for f in output_dir.glob("*.ts"))
        total_mb = total_size / (1024 * 1024)
        logger.info(f"FFmpeg completed in {elapsed:.2f}s, output size: {total_mb:.2f} MB")

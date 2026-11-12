import sys
import time
import asyncio
from pathlib import Path
from typing import Optional, List, Callable, Dict, Any
from datetime import datetime

from telethon import TelegramClient
from telethon.tl.types import (
    MessageMediaDocument,
    DocumentAttributeAudio,
    DocumentAttributeFilename,
    Channel,
    Chat,
    User
)

from config import Config
from utils import (
    sanitize_filename,
    extract_episode_number,
    format_duration,
    format_size
)
from metadata_manager import EpisodeMetadata, embed_id3_tags, build_channel_catalog
import fast_telethon


def render_progress_bar(current: int, total: int, start_time: float, prefix: str = "Downloading"):
    """Displays a single-line terminal progress bar with speed and ETA."""
    if not total or total <= 0:
        return

    elapsed = time.time() - start_time
    percent = (current / total) * 100
    speed = current / elapsed if elapsed > 0 else 0
    speed_str = f"{format_size(int(speed))}/s"
    eta_sec = int((total - current) / speed) if speed > 0 else 0
    eta_str = f"{eta_sec}s" if eta_sec < 60 else f"{eta_sec // 60}m {eta_sec % 60}s"

    bar_len = 25
    filled_len = int(bar_len * current // total)
    bar = "█" * filled_len + "░" * (bar_len - filled_len)

    line = f"\r  {prefix}: [{bar}] {percent:5.1f}% | {format_size(current)}/{format_size(total)} | {speed_str} | ETA: {eta_str} "
    sys.stdout.write(line)
    sys.stdout.flush()
    if current >= total:
        sys.stdout.write("\n")
        sys.stdout.flush()


class PodcastDownloader:
    def __init__(self, config: Config, loop: Optional[asyncio.AbstractEventLoop] = None):
        self.config = config
        self.loop = loop
        proxy = self.config.proxy_tuple
        self.channel_entity = None
        self.channel_title = ""
        self.channel_username = ""

        try:
            api_id_int = int(self.config.api_id)
        except ValueError:
            api_id_int = 6

        self.client = TelegramClient(
            str(self.config.session_path),
            api_id_int,
            self.config.api_hash,
            proxy=proxy,
            device_model="Samsung SM-G998B",
            system_version="SDK 33",
            app_version="10.8.1",
            lang_code="en",
            system_lang_code="en",
            loop=loop
        )

    async def connect(self):
        """Connects and authorizes with Telegram via QR Code or Phone."""
        try:
            if not self.client.is_connected():
                await self.client.connect()
        except Exception as conn_err:
            print(f"\n⚠️ Connection to Telegram failed: {conn_err}")
            if not self.config.proxy_enabled:
                print("💡 Note: If you are in a country with restricted Telegram access,")
                print("   enable the proxy in settings (e.g. SOCKS5 127.0.0.1:10808 or 7890).")
                enable_now = input("Enable local proxy now (127.0.0.1:10808)? [Y/n]: ").strip().lower()
                if enable_now in ("", "y", "yes"):
                    self.config.update(PROXY_ENABLED="true", PROXY_TYPE="socks5", PROXY_HOST="127.0.0.1", PROXY_PORT="10808")
                    # Recreate client with proxy
                    self.client = TelegramClient(
                        str(self.config.session_path),
                        int(self.config.api_id),
                        self.config.api_hash,
                        proxy=self.config.proxy_tuple,
                        device_model="Desktop",
                        system_version="Windows 11",
                        app_version="5.0.0"
                    )
                    await self.client.connect()
            else:
                raise conn_err

        if not await self.client.is_user_authorized():
            print("\n" + "="*60)
            print("🔑 Telegram Login Required")
            print("Choose your login method:")
            print("  [1] 📲 Scan QR Code with Telegram Mobile App (Fastest & Easiest)")
            print("  [2] 📱 Phone Number + Verification Code")
            print("="*60)
            login_choice = input("Select [1/2] (Default: 1): ").strip()

            if login_choice == "2":
                phone = self.config.phone or input("Enter phone number (+98...): ").strip()
                await self.client.start(phone=phone)
                self.config.update(TG_PHONE=phone)
            else:
                # QR Code Login
                try:
                    import qrcode
                    qr_login = await self.client.qr_login()
                    print("\n📲 Open Telegram on your phone:")
                    print("   Settings -> Devices -> Link Desktop Device")
                    print("   Then scan this QR code:\n")

                    qr = qrcode.QRCode()
                    qr.add_data(qr_login.url)
                    qr.print_ascii(invert=True)

                    print("\nWaiting for QR scan...")
                    try:
                        user = await qr_login.wait(timeout=90)
                    except asyncio.TimeoutError:
                        print("QR code expired. Falling back to phone number login:")
                        phone = self.config.phone or input("Enter phone number (+98...): ").strip()
                        await self.client.start(phone=phone)
                        self.config.update(TG_PHONE=phone)
                except Exception as qr_err:
                    print(f"QR Login notice: {qr_err}. Falling back to phone login:")
                    phone = self.config.phone or input("Enter phone number (+98...): ").strip()
                    await self.client.start(phone=phone)
                    self.config.update(TG_PHONE=phone)

        me = await self.client.get_me()
        user_name = (me.first_name or "") + (f" {me.last_name}" if me.last_name else "")
        print(f"\n✅ Logged in as: {user_name} (@{me.username or 'NoUsername'})")

    async def resolve_channel(self, target: Optional[str] = None):
        """Resolves target channel username/link/id."""
        target = target or self.config.target_channel
        if not target:
            raise ValueError("Target channel is not specified in settings or input.")

        self.config.target_channel = target
        # Clean target if it's a URL (e.g. https://t.me/agrafoss)
        cleaned_target = target.strip()
        if "t.me/" in cleaned_target:
            cleaned_target = cleaned_target.split("t.me/")[-1].split("/")[0]

        try:
            self.channel_entity = await self.client.get_entity(cleaned_target)
        except Exception as e:
            raise RuntimeError(f"Could not find or access channel '{target}': {e}")

        if isinstance(self.channel_entity, (Channel, Chat)):
            self.channel_title = getattr(self.channel_entity, "title", "Podcast Channel")
            self.channel_username = getattr(self.channel_entity, "username", None)
            if self.channel_username:
                self.channel_username = f"@{self.channel_username}"
        elif isinstance(self.channel_entity, User):
            self.channel_title = self.channel_entity.first_name
            self.channel_username = f"@{self.channel_entity.username}" if self.channel_entity.username else None
        else:
            self.channel_title = str(cleaned_target)

        print(f"Target Resolved: {self.channel_title} ({self.channel_username or 'ID: ' + str(self.channel_entity.id)})")
        return self.channel_entity

    @staticmethod
    def is_audio_message(message) -> bool:
        """Determines if a Telegram message contains an audio or podcast track."""
        if not message or not message.media:
            return False

        if isinstance(message.media, MessageMediaDocument):
            doc = message.media.document
            if not doc:
                return False
            # Check mime type
            if doc.mime_type and doc.mime_type.lower().startswith("audio/"):
                return True
            # Check attributes
            for attr in doc.attributes:
                if isinstance(attr, DocumentAttributeAudio):
                    return True
        return False

    @staticmethod
    def extract_audio_details(message, default_channel_name: str = ""):
        """Extracts title, artist, duration, size, filename from an audio message."""
        doc = message.media.document
        duration = 0
        title = ""
        performer = ""
        file_name = f"audio_{message.id}.mp3"

        for attr in doc.attributes:
            if isinstance(attr, DocumentAttributeAudio):
                duration = attr.duration or 0
                title = attr.title or ""
                performer = attr.performer or ""
            elif isinstance(attr, DocumentAttributeFilename):
                file_name = attr.file_name or file_name

        file_size = doc.size or 0
        caption = message.message or ""

        # If title is blank, try to extract from caption or filename
        if not title:
            # Fallback to filename without extension
            title = Path(file_name).stem

        return {
            "title": title,
            "performer": performer or default_channel_name,
            "duration": duration,
            "file_size": file_size,
            "file_name": file_name,
            "caption": caption
        }

    async def scan_podcasts(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Scans the channel for audio podcast messages."""
        if not self.channel_entity:
            await self.resolve_channel()

        print(f"Scanning messages in '{self.channel_title}'...")
        podcasts = []

        async for message in self.client.iter_messages(self.channel_entity, limit=limit):
            if self.is_audio_message(message):
                details = self.extract_audio_details(message, self.channel_title)
                ep_num = extract_episode_number(details["caption"], details["title"])

                meta = EpisodeMetadata(
                    message_id=message.id,
                    channel_name=self.channel_title,
                    channel_username=self.channel_username,
                    date=message.date,
                    title=details["title"],
                    artist=details["performer"],
                    duration=details["duration"],
                    file_size=details["file_size"],
                    caption=details["caption"],
                    audio_filename=details["file_name"],
                    episode_number=ep_num
                )
                podcasts.append({
                    "message": message,
                    "metadata": meta
                })

        # Reverse so older episodes come first chronologically (or sorted by ep number)
        podcasts.reverse()
        print(f"Found {len(podcasts)} podcast episodes.")
        return podcasts

    async def download_episode(
        self,
        podcast_item: Dict[str, Any],
        channel_base_dir: Path,
        on_progress: Optional[Callable[[int, int], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None
    ) -> Path:
        """
        Downloads the audio, extracts cover/thumbnail, saves info.md & info.json,
        and embeds ID3 tags.
        """
        message = podcast_item["message"]
        metadata: EpisodeMetadata = podcast_item["metadata"]

        ep_folder = channel_base_dir / "episodes" / metadata.folder_name
        ep_folder.mkdir(parents=True, exist_ok=True)

        cover_path = ep_folder / "cover.jpg"
        audio_ext = Path(metadata.audio_filename).suffix or ".mp3"
        safe_audio_name = f"audio{audio_ext}"
        audio_path = ep_folder / safe_audio_name

        print(f"\n🎧 Processing: {metadata.title}")
        if metadata.episode_number is not None:
            print(f"   Episode #{metadata.episode_number} | Duration: {format_duration(metadata.duration)} | Size: {format_size(metadata.file_size)}")
        print(f"   Folder: {ep_folder.name}")

        # 1. Download Thumbnail / Cover
        if self.config.download_thumbnail and not cover_path.exists():
            try:
                # Check if document has embedded thumbs
                doc = message.media.document
                if getattr(doc, "thumbs", None):
                    await self.client.download_media(message, file=str(cover_path), thumb=-1)
                
                # If no doc thumb, try message photo or channel photo
                if not cover_path.exists() or cover_path.stat().st_size == 0:
                    if self.channel_entity:
                        await self.client.download_profile_photo(self.channel_entity, file=str(cover_path))
                
                if cover_path.exists() and cover_path.stat().st_size > 0:
                    print(f"   Saved thumbnail cover: {cover_path.name}")
            except Exception as e:
                print(f"   Thumbnail note: {e}")

        # 2. Save info.md and info.json (Immediate metadata & notes record)
        cover_filename = cover_path.name if cover_path.exists() else None
        metadata.save_info(ep_folder, cover_filename=cover_filename)
        print(f"   Saved notes & metadata: info.md & info.json")

        # 3. Download Audio
        if self.config.download_audio:
            if audio_path.exists() and audio_path.stat().st_size == metadata.file_size:
                print(f"   Audio already downloaded ({format_size(audio_path.stat().st_size)}), skipping download.")
            else:
                start_time = time.time()
                
                def prog(cur, tot):
                    if is_cancelled and is_cancelled():
                        raise asyncio.CancelledError("Download cancelled by user")
                    if on_progress:
                        on_progress(cur, tot)
                    else:
                        render_progress_bar(cur, tot, start_time, prefix="Audio")

                print(f"   Downloading audio file ({format_size(metadata.file_size)})...")
                await self.client.download_media(
                    message,
                    file=str(audio_path),
                    progress_callback=prog
                )
                print(f"   Download complete in {int(time.time() - start_time)}s.")

        # 4. Embed ID3 Tags into MP3
        if self.config.embed_metadata and audio_path.exists() and audio_path.suffix.lower() == ".mp3":
            success = embed_id3_tags(audio_path, metadata, cover_path if cover_path.exists() else None)
            if success:
                print(f"   Embedded ID3 metadata & album cover into {audio_path.name}.")

        return ep_folder

    async def download_all(
        self,
        episodes_filter: Optional[Callable[[EpisodeMetadata], bool]] = None,
        limit: Optional[int] = None
    ) -> List[Path]:
        """Runs the complete download & organization process for matching episodes."""
        await self.connect()
        await self.resolve_channel()

        # Sanitize channel folder name
        safe_channel_name = sanitize_filename(self.channel_title, max_length=60)
        channel_dir = self.config.output_dir / safe_channel_name
        channel_dir.mkdir(parents=True, exist_ok=True)

        podcasts = await self.scan_podcasts(limit=limit)
        if not podcasts:
            print("No audio podcasts found to download.")
            return []

        # Filter if specified
        if episodes_filter:
            podcasts = [p for p in podcasts if episodes_filter(p["metadata"])]
            print(f"Episodes matching filter: {len(podcasts)}")

        downloaded_dirs = []
        for i, item in enumerate(podcasts, 1):
            print(f"\n--- Episode [{i}/{len(podcasts)}] ---")
            ep_dir = await self.download_episode(item, channel_dir)
            downloaded_dirs.append(ep_dir)

        # Generate / Update master catalog README.md
        print("\nUpdating Channel Catalog...")
        readme_path = build_channel_catalog(channel_dir, channel_title=self.channel_title)
        print(f"Catalog updated: {readme_path}")

        return downloaded_dirs


import os
import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime

from utils import (
    sanitize_filename,
    extract_episode_number,
    extract_series_title,
    format_duration,
    format_size
)

# Mutagen imports for audio tagging
try:
    from mutagen.mp3 import MP3
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, TRCK, COMM, APIC, ID3NoHeaderError
    from mutagen.mp4 import MP4, MP4Cover
    from mutagen.oggvorbis import OggVorbis
    from mutagen.flac import FLAC, Picture
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False


class EpisodeMetadata:
    def __init__(
        self,
        message_id: int,
        channel_name: str,
        channel_username: Optional[str],
        date: datetime,
        title: str,
        artist: Optional[str],
        duration: int,
        file_size: int,
        caption: str,
        audio_filename: str,
        episode_number: Optional[int] = None
    ):
        self.message_id = message_id
        self.channel_name = channel_name
        self.channel_username = channel_username
        self.date = date
        self.caption = caption or ""
        self.duration = duration
        self.file_size = file_size
        self.audio_filename = audio_filename

        # Clean title
        self.title = title or audio_filename or f"Audio_{message_id}"
        self.artist = artist or channel_name

        # Detect episode number if not provided
        self.episode_number = episode_number if episode_number is not None else extract_episode_number(self.caption, self.title)
        self.series_title = extract_series_title(self.caption, self.title)

    @property
    def folder_name(self) -> str:
        """Returns safe folder name for this episode."""
        if self.episode_number is not None:
            prefix = f"{self.episode_number:03d}"
        else:
            prefix = f"Msg_{self.message_id}"
        
        safe_title = sanitize_filename(self.title, max_length=80)
        return f"{prefix} - {safe_title}"

    @property
    def message_url(self) -> Optional[str]:
        if self.channel_username:
            username = self.channel_username.lstrip("@")
            return f"https://t.me/{username}/{self.message_id}"
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "channel_name": self.channel_name,
            "channel_username": self.channel_username,
            "message_url": self.message_url,
            "episode_number": self.episode_number,
            "title": self.title,
            "artist": self.artist,
            "series_title": self.series_title,
            "date": self.date.isoformat() if self.date else None,
            "duration_seconds": self.duration,
            "duration_formatted": format_duration(self.duration),
            "file_size_bytes": self.file_size,
            "file_size_formatted": format_size(self.file_size),
            "audio_filename": self.audio_filename,
            "caption": self.caption
        }

    def save_info(self, ep_dir: Path, cover_filename: Optional[str] = "cover.jpg"):
        """Saves info.json and info.md inside the episode folder."""
        ep_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. Save JSON
        json_path = ep_dir / "info.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

        # 2. Save Markdown
        md_path = ep_dir / "info.md"
        lines = []
        ep_str = f"Episode {self.episode_number}: " if self.episode_number else ""
        lines.append(f"# {ep_str}{self.title}\n")
        
        if cover_filename and (ep_dir / cover_filename).exists():
            lines.append(f"![Cover]({cover_filename})\n")

        lines.append("## ℹ️ Episode Details\n")
        lines.append(f"- **Channel:** {self.channel_name} ({self.channel_username or 'Private'})")
        if self.message_url:
            lines.append(f"- **Telegram Post:** [{self.message_url}]({self.message_url})")
        if self.date:
            lines.append(f"- **Release Date:** {self.date.strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"- **Duration:** {format_duration(self.duration)}")
        lines.append(f"- **File Size:** {format_size(self.file_size)}")
        if self.artist:
            lines.append(f"- **Speaker / Host:** {self.artist}")
        lines.append("\n---\n")

        lines.append("## 📝 Description & Notes\n")
        if self.caption:
            lines.append(self.caption)
        else:
            lines.append("*No text caption provided in Telegram message.*")

        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))


def embed_audio_tags(
    audio_path: Path,
    metadata: EpisodeMetadata,
    cover_path: Optional[Path] = None
) -> bool:
    """Embeds metadata (title, artist, album, track number, caption, and cover art) into audio file."""
    if not MUTAGEN_AVAILABLE or not audio_path.exists():
        return False

    ext = audio_path.suffix.lower()
    try:
        if ext == ".mp3":
            try:
                audio = ID3(audio_path)
            except ID3NoHeaderError:
                audio = ID3()

            audio.add(TIT2(encoding=3, text=metadata.title))
            if metadata.artist:
                audio.add(TPE1(encoding=3, text=metadata.artist))
            if metadata.series_title:
                audio.add(TALB(encoding=3, text=metadata.series_title))
            if metadata.episode_number:
                audio.add(TRCK(encoding=3, text=str(metadata.episode_number)))
            if metadata.caption:
                audio.add(COMM(encoding=3, lang="eng", desc="Telegram Caption", text=metadata.caption))

            if cover_path and cover_path.exists():
                mime = "image/jpeg" if cover_path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
                with open(cover_path, "rb") as img_f:
                    audio.add(APIC(
                        encoding=3,
                        mime=mime,
                        type=3,  # Front cover
                        desc="Cover",
                        data=img_f.read()
                    ))
            audio.save(audio_path, v2_version=3)
            return True

        elif ext in (".m4a", ".mp4", ".aac"):
            mp4 = MP4(audio_path)
            mp4["\xa9nam"] = metadata.title
            if metadata.artist:
                mp4["\xa9ART"] = metadata.artist
            if metadata.series_title:
                mp4["\xa9alb"] = metadata.series_title
            if metadata.episode_number:
                mp4["trkn"] = [(metadata.episode_number, 0)]
            if metadata.caption:
                mp4["\xa9cmt"] = metadata.caption
            if cover_path and cover_path.exists():
                img_format = MP4Cover.FORMAT_JPEG if cover_path.suffix.lower() in (".jpg", ".jpeg") else MP4Cover.FORMAT_PNG
                with open(cover_path, "rb") as img_f:
                    mp4["covr"] = [MP4Cover(img_f.read(), imageformat=img_format)]
            mp4.save()
            return True

        elif ext in (".ogg", ".oga"):
            ogg = OggVorbis(audio_path)
            ogg["title"] = metadata.title
            if metadata.artist:
                ogg["artist"] = metadata.artist
            if metadata.series_title:
                ogg["album"] = metadata.series_title
            if metadata.episode_number:
                ogg["tracknumber"] = str(metadata.episode_number)
            if metadata.caption:
                ogg["comment"] = metadata.caption
            ogg.save()
            return True

        elif ext == ".flac":
            flac = FLAC(audio_path)
            flac["title"] = metadata.title
            if metadata.artist:
                flac["artist"] = metadata.artist
            if metadata.series_title:
                flac["album"] = metadata.series_title
            if metadata.episode_number:
                flac["tracknumber"] = str(metadata.episode_number)
            if metadata.caption:
                flac["comment"] = metadata.caption
            if cover_path and cover_path.exists():
                pic = Picture()
                pic.type = 3
                pic.mime = "image/jpeg" if cover_path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
                with open(cover_path, "rb") as img_f:
                    pic.data = img_f.read()
                flac.clear_pictures()
                flac.add_picture(pic)
            flac.save()
            return True

    except Exception as e:
        print(f"Warning: Failed to embed audio tags into {audio_path.name}: {e}")
        return False

    return False


# Keep alias for backwards compatibility
embed_id3_tags = embed_audio_tags


def build_channel_catalog(channel_dir: Path, channel_title: str = "Telegram Podcasts") -> Path:
    """
    Scans all episode subdirectories, reads their info.json,
    and builds a comprehensive README.md / Catalog in channel_dir.
    """
    episodes_dir = channel_dir / "episodes"
    if not episodes_dir.exists():
        episodes_dir.mkdir(parents=True, exist_ok=True)

    episodes_data = []
    for item in episodes_dir.iterdir():
        if item.is_dir():
            json_file = item / "info.json"
            if json_file.exists():
                try:
                    with open(json_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        data["_folder_name"] = item.name
                        episodes_data.append(data)
                except Exception:
                    continue

    # Sort episodes by episode_number (if available) or date
    def sort_key(ep):
        ep_num = ep.get("episode_number")
        if ep_num is not None:
            return (0, ep_num)
        return (1, ep.get("date") or "")

    episodes_data.sort(key=sort_key)

    total_episodes = len(episodes_data)
    total_duration_sec = sum(ep.get("duration_seconds", 0) for ep in episodes_data)
    total_size_bytes = sum(ep.get("file_size_bytes", 0) for ep in episodes_data)

    catalog_lines = [
        f"# 🎙️ {channel_title} - Podcast Archive",
        "",
        f"> Automatically archived and organized from Telegram.",
        "",
        "### 📊 Archive Summary",
        f"- **Total Episodes:** {total_episodes}",
        f"- **Total Duration:** {format_duration(total_duration_sec)}",
        f"- **Total Size:** {format_size(total_size_bytes)}",
        f"- **Last Updated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "---",
        "",
        "### 📚 Episodes Catalog",
        "",
        "| # | Title | Duration | Size | Date | Details |",
        "|---|---|---|---|---|---|"
    ]

    for ep in episodes_data:
        ep_num = ep.get("episode_number")
        ep_str = f"**{ep_num:03d}**" if ep_num is not None else "-"
        title = ep.get("title", "Untitled").replace("|", "-")
        duration = ep.get("duration_formatted", "-")
        size = ep.get("file_size_formatted", "-")
        date_str = (ep.get("date") or "")[:10]
        folder_name = ep.get("_folder_name")
        folder_link = f"[Notes & Audio](episodes/{folder_name}/info.md)"

        catalog_lines.append(f"| {ep_str} | {title} | {duration} | {size} | {date_str} | {folder_link} |")

    catalog_lines.append("")
    catalog_lines.append("---")
    catalog_lines.append("*Generated by [Telegram Podcast Downloader & Organizer](https://github.com)*")

    readme_path = channel_dir / "README.md"
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write("\n".join(catalog_lines))

    return readme_path


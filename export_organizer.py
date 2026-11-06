import os
import json
import re
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
from datetime import datetime

from bs4 import BeautifulSoup

from utils import (
    sanitize_filename,
    extract_episode_number,
    extract_series_title,
    format_duration,
    format_size,
    to_ascii_digits
)
from metadata_manager import EpisodeMetadata, embed_audio_tags, build_channel_catalog


def find_recent_telegram_exports() -> List[Path]:
    """Finds recently exported ChatExport_* directories in common Windows locations."""
    user_home = Path.home()
    search_dirs = [
        user_home / "Downloads" / "Telegram Desktop",
        user_home / "Downloads",
        user_home / "Documents" / "Telegram Desktop",
        user_home / "Documents",
        user_home / "Desktop",
        Path(".")
    ]

    found = []
    for d in search_dirs:
        if d.exists():
            for p in d.glob("ChatExport_*"):
                if p.is_dir() and ((p / "result.json").exists() or (p / "messages.html").exists()):
                    found.append(p)

    # Sort newest first
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return found


def parse_telegram_text_entities(text_field: Union[str, list]) -> str:
    """
    Parses Telegram JSON export 'text' field.
    Handles both plain string and mixed list of strings / entity dicts (links, hashtags, bold, etc.).
    Preserves clickable Markdown links: [text](href).
    """
    if isinstance(text_field, str):
        return text_field.strip()

    if not isinstance(text_field, list):
        return str(text_field or "")

    result_parts = []
    for item in text_field:
        if isinstance(item, str):
            result_parts.append(item)
        elif isinstance(item, dict):
            entity_type = item.get("type", "")
            raw_text = item.get("text", "")
            
            if entity_type == "text_link" and "href" in item:
                result_parts.append(f"[{raw_text}]({item['href']})")
            elif entity_type == "link":
                result_parts.append(raw_text)
            elif entity_type == "bold":
                result_parts.append(f"**{raw_text}**")
            elif entity_type == "italic":
                result_parts.append(f"*{raw_text}*")
            else:
                result_parts.append(raw_text)

    return "".join(result_parts).strip()


class TelegramExportOrganizer:
    def __init__(self, export_dir: Path, output_dir: Path, copy_files: bool = True):
        self.export_dir = Path(export_dir).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.copy_files = copy_files  # If False, moves files instead of copying

    def detect_export_type(self) -> str:
        """Determines whether export is JSON, HTML, or raw audio folder."""
        if (self.export_dir / "result.json").exists():
            return "json"
        
        html_files = list(self.export_dir.glob("messages*.html"))
        if html_files:
            return "html"
        
        # Check if folder just contains audio files
        audio_files = list(self.export_dir.glob("*.mp3")) + list(self.export_dir.glob("*.m4a"))
        if audio_files:
            return "raw_audio"

        return "unknown"

    def process(self) -> List[Path]:
        exp_type = self.detect_export_type()
        if exp_type == "json":
            return self.process_json_export()
        elif exp_type == "html":
            return self.process_html_export()
        elif exp_type == "raw_audio":
            return self.process_raw_audio_folder()
        else:
            raise FileNotFoundError(
                f"Could not detect valid Telegram export in '{self.export_dir}'.\n"
                "Expected 'result.json', 'messages.html', or audio files (.mp3)."
            )

    def process_json_export(self) -> List[Path]:
        """Processes Telegram Desktop JSON export ('result.json')."""
        json_path = self.export_dir / "result.json"
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        channel_name = data.get("name", "Telegram Podcast")
        channel_id = str(data.get("id", ""))
        safe_channel_name = sanitize_filename(channel_name, max_length=60)
        target_channel_dir = self.output_dir / safe_channel_name
        target_channel_dir.mkdir(parents=True, exist_ok=True)

        messages = data.get("messages", [])
        episodes_processed = []

        print(f"\n📂 Processing Telegram JSON Export: '{channel_name}'")
        print(f"   Total messages in export: {len(messages)}")

        # Collect audio messages
        audio_messages = []
        for msg in messages:
            if msg.get("type") != "message":
                continue
            
            media_type = msg.get("media_type")
            mime_type = msg.get("mime_type", "")
            file_field = msg.get("file", "")

            # Check if this message has an audio file
            is_audio = (
                media_type in ("audio_file", "voice_message") or
                mime_type.startswith("audio/") or
                file_field.lower().endswith((".mp3", ".m4a", ".ogg", ".opus", ".flac", ".wav"))
            )

            if is_audio and file_field:
                audio_messages.append(msg)

        print(f"   Found {len(audio_messages)} audio/podcast messages.\n")

        for idx, msg in enumerate(audio_messages, 1):
            msg_id = msg.get("id", idx)
            raw_caption = parse_telegram_text_entities(msg.get("text", ""))
            
            title = msg.get("title") or ""
            performer = msg.get("performer") or ""
            duration = msg.get("duration_seconds") or 0
            
            relative_file = msg.get("file", "")
            source_audio_path = self.export_dir / relative_file

            if not source_audio_path.exists():
                print(f"⚠️ Audio file not found on disk: {relative_file}")
                continue

            file_size = source_audio_path.stat().st_size

            # If title is empty, deduce from filename or caption
            if not title:
                title = source_audio_path.stem

            date_str = msg.get("date", "")
            date_obj = None
            try:
                date_obj = datetime.fromisoformat(date_str) if date_str else None
            except Exception:
                pass

            # Detect episode number
            ep_num = extract_episode_number(raw_caption, title)

            metadata = EpisodeMetadata(
                message_id=msg_id,
                channel_name=channel_name,
                channel_username=None,
                date=date_obj,
                title=title,
                artist=performer or channel_name,
                duration=duration,
                file_size=file_size,
                caption=raw_caption,
                audio_filename=source_audio_path.name,
                episode_number=ep_num
            )

            ep_dir = target_channel_dir / "episodes" / metadata.folder_name
            ep_dir.mkdir(parents=True, exist_ok=True)

            # Copy / move audio file
            target_audio_ext = source_audio_path.suffix.lower() or ".mp3"
            target_audio_path = ep_dir / f"audio{target_audio_ext}"
            
            if not target_audio_path.exists() or target_audio_path.stat().st_size != file_size:
                if self.copy_files:
                    shutil.copy2(source_audio_path, target_audio_path)
                else:
                    shutil.move(str(source_audio_path), str(target_audio_path))

            # Copy / extract thumbnail if available in export
            cover_path = ep_dir / "cover.jpg"
            thumb_field = msg.get("thumbnail")
            if thumb_field:
                source_thumb = self.export_dir / thumb_field
                if source_thumb.exists() and not cover_path.exists():
                    shutil.copy2(source_thumb, cover_path)

            # Check if channel profile photo or general photo exists in export
            if not cover_path.exists():
                profile_photos = list(self.export_dir.glob("photos/*.jpg")) + list(self.export_dir.glob("*.jpg"))
                if profile_photos:
                    shutil.copy2(profile_photos[0], cover_path)

            # Save notes & metadata
            cover_name = cover_path.name if cover_path.exists() else None
            metadata.save_info(ep_dir, cover_filename=cover_name)

            # Embed tags into audio
            embed_audio_tags(target_audio_path, metadata, cover_path if cover_path.exists() else None)

            ep_label = f"Ep #{ep_num:03d}" if ep_num is not None else f"Msg #{msg_id}"
            print(f"  ✅ [{idx}/{len(audio_messages)}] {ep_label}: {title} ({format_duration(duration)})")
            episodes_processed.append(ep_dir)

        # Build Master Catalog README.md
        readme_path = build_channel_catalog(target_channel_dir, channel_title=channel_name)
        print(f"\n✨ Catalog generated: {readme_path}")
        return episodes_processed

    def process_html_export(self) -> List[Path]:
        """Processes Telegram Desktop HTML export ('messages.html')."""
        html_files = sorted(self.export_dir.glob("messages*.html"))
        if not html_files:
            return []

        # Parse first HTML file to get channel title
        channel_name = "Telegram Podcast"
        with open(html_files[0], "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f.read(), "html.parser")
            title_node = soup.find("div", class_="text bold") or soup.find("title")
            if title_node:
                channel_name = title_node.get_text(strip=True)

        safe_channel_name = sanitize_filename(channel_name, max_length=60)
        target_channel_dir = self.output_dir / safe_channel_name
        target_channel_dir.mkdir(parents=True, exist_ok=True)

        episodes_processed = []
        total_audio = 0

        for html_file in html_files:
            with open(html_file, "r", encoding="utf-8") as f:
                soup = BeautifulSoup(f.read(), "html.parser")

            msg_divs = soup.find_all("div", class_="message")
            for msg_div in msg_divs:
                # Look for media audio
                media_div = msg_div.find("div", class_="media_audio_file") or msg_div.find("div", class_="media_voice_message")
                if not media_div:
                    continue

                total_audio += 1
                link_node = media_div.find("a", href=True)
                if not link_node:
                    continue

                audio_rel_path = link_node["href"]
                source_audio = self.export_dir / audio_rel_path
                if not source_audio.exists():
                    continue

                # Details
                title_node = media_div.find("div", class_="title")
                title = title_node.get_text(strip=True) if title_node else source_audio.stem
                
                perf_node = media_div.find("div", class_="performer")
                performer = perf_node.get_text(strip=True) if perf_node else channel_name

                caption_div = msg_div.find("div", class_="text")
                caption = caption_div.get_text("\n", strip=True) if caption_div else ""

                date_node = msg_div.find("div", class_="date")
                date_title = date_node.get("title", "") if date_node else ""

                ep_num = extract_episode_number(caption, title)

                metadata = EpisodeMetadata(
                    message_id=total_audio,
                    channel_name=channel_name,
                    channel_username=None,
                    date=None,
                    title=title,
                    artist=performer,
                    duration=0,
                    file_size=source_audio.stat().st_size,
                    caption=caption,
                    audio_filename=source_audio.name,
                    episode_number=ep_num
                )

                ep_dir = target_channel_dir / "episodes" / metadata.folder_name
                ep_dir.mkdir(parents=True, exist_ok=True)

                target_audio_path = ep_dir / f"audio{source_audio.suffix.lower() or '.mp3'}"
                if not target_audio_path.exists():
                    shutil.copy2(source_audio, target_audio_path)

                cover_path = ep_dir / "cover.jpg"
                metadata.save_info(ep_dir, cover_filename=cover_path.name if cover_path.exists() else None)
                embed_audio_tags(target_audio_path, metadata, cover_path if cover_path.exists() else None)
                episodes_processed.append(ep_dir)

        build_channel_catalog(target_channel_dir, channel_title=channel_name)
        return episodes_processed

    def process_raw_audio_folder(self) -> List[Path]:
        """Processes a simple folder containing audio files (e.g. manually downloaded)."""
        audio_files = sorted(
            list(self.export_dir.glob("*.mp3")) +
            list(self.export_dir.glob("*.m4a")) +
            list(self.export_dir.glob("*.ogg"))
        )

        folder_name = self.export_dir.name
        channel_dir = self.output_dir / sanitize_filename(folder_name, max_length=60)
        channel_dir.mkdir(parents=True, exist_ok=True)

        episodes_processed = []
        for idx, audio_file in enumerate(audio_files, 1):
            stem = audio_file.stem
            ep_num = extract_episode_number(stem, stem)

            metadata = EpisodeMetadata(
                message_id=idx,
                channel_name=folder_name,
                channel_username=None,
                date=None,
                title=stem,
                artist=folder_name,
                duration=0,
                file_size=audio_file.stat().st_size,
                caption="",
                audio_filename=audio_file.name,
                episode_number=ep_num
            )

            ep_dir = channel_dir / "episodes" / metadata.folder_name
            ep_dir.mkdir(parents=True, exist_ok=True)

            target_audio = ep_dir / f"audio{audio_file.suffix.lower()}"
            if not target_audio.exists():
                shutil.copy2(audio_file, target_audio)

            metadata.save_info(ep_dir)
            embed_audio_tags(target_audio, metadata)
            episodes_processed.append(ep_dir)

        build_channel_catalog(channel_dir, channel_title=folder_name)
        return episodes_processed

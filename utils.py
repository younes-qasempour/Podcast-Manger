import re
import unicodedata
from typing import Optional, Tuple, List, Dict


PERSIAN_ARABIC_DIGIT_MAP = str.maketrans({
    '۰': '0', '۱': '1', '۲': '2', '۳': '3', '۴': '4',
    '۵': '5', '۶': '6', '۷': '7', '۸': '8', '۹': '9',
    '٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4',
    '٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9'
})


def to_ascii_digits(text: str) -> str:
    """Converts Persian and Arabic digits to standard ASCII digits."""
    if not text:
        return ""
    return text.translate(PERSIAN_ARABIC_DIGIT_MAP)


def sanitize_filename(filename: str, max_length: int = 120, replacement: str = "-") -> str:
    """
    Sanitizes a string to be a safe filename across Windows, macOS, and Linux.
    Replaces illegal characters: < > : " / \\ | ? * and control chars.
    Preserves Persian, Arabic, and UTF-8 characters.
    """
    if not filename:
        return "untitled"

    # Normalize unicode
    filename = unicodedata.normalize("NFC", filename)

    # Replace forbidden Windows characters
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', replacement, filename)
    
    # Replace multiple dashes or spaces
    filename = re.sub(r'\s+', ' ', filename)
    filename = re.sub(r'-+', '-', filename)
    
    # Strip spaces and dots from start and end (Windows doesn't allow trailing dots/spaces)
    filename = filename.strip(' .-_')

    if not filename:
        return "untitled"

    # Truncate if too long (keeping extension intact if present)
    if len(filename) > max_length:
        filename = filename[:max_length].rstrip(' .-_')

    return filename


def extract_episode_number(caption: str, title: str = "") -> Optional[int]:
    """
    Tries to find the podcast episode number from caption or audio title.
    Handles Persian digits (e.g. اپیزود ۹۱ or (91) or #چنین_گفت_زرتشت ۹۱).
    """
    combined = f"{title}\n{caption}"
    normalized = to_ascii_digits(combined)

    # Patterns ordered by specificity
    patterns = [
        # Explicit episode keywords in Persian / English
        r'(?:اپیزود|قسمت|بخش|episode|ep\.?)\s*[:#-]?\s*(\d+)',
        # Number in parentheses at end of title: e.g. "تحلیل چنین گفت زرتشت (91)"
        r'\(\s*(\d+)\s*\)',
        # Hashtags followed by episode number: e.g. #چنین_گفت_زرتشت ۹۱
        r'#\S+\s+(\d+)\b',
        # Standalone "اپیزود ۹۱" without colon
        r'اپیزود\s+(\d+)',
        # Common pattern: " - 91 - " or " - 91 "
        r'\s-\s*(\d+)\s*-?\s*',
    ]

    for pattern in patterns:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if match:
            try:
                ep_num = int(match.group(1))
                # Validate reasonable episode number range (1 to 9999)
                if 1 <= ep_num <= 9999:
                    return ep_num
            except (ValueError, IndexError):
                continue

    return None


def extract_series_title(caption: str, title: str = "") -> str:
    """
    Attempts to extract a sensible series title or book/topic name.
    """
    if title:
        # e.g. "علی شاهی - تحلیل «چنین گفت زرتشت» (91)" -> "علی شاهی - تحلیل چنین گفت زرتشت"
        cleaned = re.sub(r'\(\s*\d+\s*\)', '', title).strip(' -_')
        if cleaned:
            return cleaned

    # Fallback to first line of caption
    lines = [line.strip() for line in caption.splitlines() if line.strip()]
    if lines:
        first_line = lines[0]
        # Remove hashtags or links if first line is short
        first_line = re.sub(r'#\S+', '', first_line).strip()
        if len(first_line) > 3:
            return first_line[:80]

    return "Podcast"


def extract_hashtags(text: str) -> List[str]:
    """Extracts all hashtags from text (e.g. #چنین_گفت_زرتشت)."""
    if not text:
        return []
    # Match Persian and English hashtags
    tags = re.findall(r'#([\w\u0600-\u06FF]+)', text)
    return [f"#{t}" for t in tags]


def clean_for_terminal(text: str, max_length: int = 60) -> str:
    """Cleans text for terminal display without reversing characters."""
    if not text:
        return ""
    clean = text.replace('\n', ' ').strip()
    if len(clean) > max_length:
        clean = clean[:max_length] + "..."
    return clean


def format_size(size_bytes: int) -> str:
    """Formats bytes into human readable string (KB, MB, GB)."""
    if not size_bytes or size_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_idx = 0
    size = float(size_bytes)
    while size >= 1024.0 and unit_idx < len(units) - 1:
        size /= 1024.0
        unit_idx += 1
    return f"{size:.1f} {units[unit_idx]}"


def format_duration(seconds: int) -> str:
    """Formats seconds into HH:MM:SS or MM:SS."""
    if not seconds or seconds <= 0:
        return "00:00"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


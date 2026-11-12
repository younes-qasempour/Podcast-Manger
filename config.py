import os
from pathlib import Path
from typing import Optional, Tuple, Dict, Any


def load_env_file(dotenv_path: Optional[Path] = None) -> Dict[str, str]:
    """Loads key-value pairs from .env file into os.environ if not already set."""
    if dotenv_path is None:
        dotenv_path = Path(__file__).resolve().parent / ".env"
    
    env_vars = {}
    if not dotenv_path.exists():
        return env_vars

    with open(dotenv_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip("'\"")
            env_vars[key] = val
            if key not in os.environ:
                os.environ[key] = val
    return env_vars


def save_env_file(data: Dict[str, Any], dotenv_path: Optional[Path] = None):
    """Saves or updates key-value pairs into the .env file while preserving comments."""
    if dotenv_path is None:
        dotenv_path = Path(__file__).resolve().parent / ".env"

    existing_lines = []
    if dotenv_path.exists():
        with open(dotenv_path, "r", encoding="utf-8") as f:
            existing_lines = f.readlines()

    keys_written = set()
    new_lines = []
    for line in existing_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k in data:
                new_lines.append(f"{k}={data[k]}\n")
                keys_written.add(k)
                continue
        new_lines.append(line)

    # Append any remaining keys that weren't in the file
    for k, v in data.items():
        if k not in keys_written:
            new_lines.append(f"{k}={v}\n")

    with open(dotenv_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


DEFAULT_API_ID = "2040"
DEFAULT_API_HASH = "b18441a1ff607e10a989891a5462e627"


class Config:
    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or Path(__file__).resolve().parent
        self.env_file = self.root_dir / ".env"
        self.reload()

    def reload(self):
        load_env_file(self.env_file)
        
        self.api_id = os.getenv("TG_API_ID", "").strip() or DEFAULT_API_ID
        self.api_hash = os.getenv("TG_API_HASH", "").strip() or DEFAULT_API_HASH
        self.phone = os.getenv("TG_PHONE", "").strip()
        self.session_name = os.getenv("TG_SESSION_NAME", "tg_podcast_session").strip()
        self.session_path = self.root_dir / self.session_name
        
        self.target_channel = os.getenv("TARGET_CHANNEL", "@agrafoss").strip()
        
        output_dir_str = os.getenv("OUTPUT_DIR", "./podcasts").strip()
        self.output_dir = (self.root_dir / output_dir_str).resolve()
        
        self.download_audio = os.getenv("DOWNLOAD_AUDIO", "true").lower() in ("true", "1", "yes")
        self.download_thumbnail = os.getenv("DOWNLOAD_THUMBNAIL", "true").lower() in ("true", "1", "yes")
        self.embed_metadata = os.getenv("EMBED_METADATA_IN_MP3", "true").lower() in ("true", "1", "yes")
        
        self.proxy_enabled = os.getenv("PROXY_ENABLED", "false").lower() in ("true", "1", "yes")
        self.proxy_type = os.getenv("PROXY_TYPE", "socks5").lower().strip()
        self.proxy_host = os.getenv("PROXY_HOST", "127.0.0.1").strip()
        try:
            self.proxy_port = int(os.getenv("PROXY_PORT", "10808").strip())
        except ValueError:
            self.proxy_port = 10808
            
        self.git_remote_url = os.getenv("GIT_REMOTE_URL", "").strip()
        self.git_push_audio = os.getenv("GIT_PUSH_AUDIO", "false").lower() in ("true", "1", "yes")

    @property
    def proxy_tuple(self) -> Optional[Tuple[str, str, int]]:
        """Returns proxy tuple for Telethon if proxy is enabled."""
        if not self.proxy_enabled or not self.proxy_host or not self.proxy_port:
            return None
        return (self.proxy_type, self.proxy_host, self.proxy_port)

    def is_configured(self) -> bool:
        """Returns True since built-in client credentials are used out of the box."""
        return True

    def update(self, **kwargs):
        """Updates settings in memory and writes them to .env."""
        str_kwargs = {k: str(v) for k, v in kwargs.items()}
        save_env_file(str_kwargs, self.env_file)
        self.reload()


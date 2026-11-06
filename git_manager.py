import subprocess
import shutil
from pathlib import Path
from typing import Optional, Tuple, Dict, Any


class GitManager:
    def __init__(self, repo_dir: Path, push_audio: bool = False, remote_url: Optional[str] = None):
        self.repo_dir = repo_dir
        self.push_audio = push_audio
        self.remote_url = remote_url or ""

    def _run_git(self, args: list) -> Tuple[int, str, str]:
        """Runs a git command in the repo directory."""
        try:
            res = subprocess.run(
                ["git"] + args,
                cwd=str(self.repo_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace"
            )
            return res.returncode, res.stdout.strip(), res.stderr.strip()
        except FileNotFoundError:
            return -1, "", "git executable not found on system PATH."
        except Exception as e:
            return -1, "", str(e)

    def is_git_installed(self) -> bool:
        """Checks if git CLI is available."""
        code, out, _ = self._run_git(["--version"])
        return code == 0

    def is_repo(self) -> bool:
        """Checks if current directory is a git repository."""
        return (self.repo_dir / ".git").is_dir()

    def init_repo(self) -> bool:
        """Initializes a git repository with main branch if not already initialized."""
        if not self.is_repo():
            code, out, err = self._run_git(["init", "-b", "main"])
            if code != 0:
                # Fallback for older git versions
                self._run_git(["init"])
                self._run_git(["branch", "-M", "main"])
            print("Initialized local Git repository.")
            
        self.setup_gitignore()
        return True

    def setup_gitignore(self):
        """Creates or updates .gitignore with required exclusions."""
        gitignore_path = self.repo_dir / ".gitignore"
        existing = ""
        if gitignore_path.exists():
            existing = gitignore_path.read_text(encoding="utf-8")

        needed_lines = [
            "# Sensitive Telegram Credentials & Sessions",
            ".env",
            "*.session",
            "*.session-journal",
            "",
            "# Python artifacts",
            "__pycache__/",
            "*.py[cod]",
            "*$py.class",
            ".pytest_cache/",
            "",
            "# IDE & OS files",
            ".vscode/",
            ".idea/",
            "Thumbs.db",
            "Desktop.ini"
        ]

        if not self.push_audio:
            needed_lines.extend([
                "",
                "# Audio files (kept locally to avoid GitHub 100MB per-file upload limit)",
                "*.mp3",
                "*.m4a",
                "*.ogg",
                "*.wav",
                "*.flac"
            ])

        # Write or update if missing key entries
        if ".env" not in existing or "*.session" not in existing:
            gitignore_path.write_text("\n".join(needed_lines) + "\n", encoding="utf-8")
            print("Updated .gitignore.")

    def configure_lfs_if_needed(self) -> bool:
        """If user explicitly chose to push audio to GitHub, configure Git LFS."""
        if not self.push_audio:
            return True

        # Check git-lfs
        code, _, _ = self._run_git(["lfs", "version"])
        if code != 0:
            print("Warning: git-lfs is not installed or enabled. Files > 100MB will fail on GitHub.")
            return False

        self._run_git(["lfs", "install"])
        self._run_git(["lfs", "track", "*.mp3", "*.m4a", "*.ogg"])
        self._run_git(["add", ".gitattributes"])
        return True

    def set_user_if_missing(self, name: str = "Telegram Downloader", email: str = "podcast@archive.local"):
        """Ensures local git user.name and user.email are set."""
        code, out, _ = self._run_git(["config", "user.name"])
        if code != 0 or not out:
            self._run_git(["config", "user.name", name])
        
        code, out, _ = self._run_git(["config", "user.email"])
        if code != 0 or not out:
            self._run_git(["config", "user.email", email])

    def get_remote_url(self) -> Optional[str]:
        """Gets origin remote URL if configured."""
        code, out, _ = self._run_git(["remote", "get-url", "origin"])
        if code == 0 and out:
            return out
        return None

    def set_remote_url(self, url: str) -> bool:
        """Sets or updates origin remote URL."""
        if not url:
            return False
        current = self.get_remote_url()
        if current:
            code, _, err = self._run_git(["remote", "set-url", "origin", url])
        else:
            code, _, err = self._run_git(["remote", "add", "origin", url])
        return code == 0

    def commit_all(self, message: str) -> Tuple[bool, str]:
        """Stages all changes and commits them with the given message."""
        self.init_repo()
        self.set_user_if_missing()

        if self.push_audio:
            self.configure_lfs_if_needed()

        # Stage files
        code, _, err = self._run_git(["add", "-A"])
        if code != 0:
            return False, f"Git add failed: {err}"

        # Check status
        code, out, _ = self._run_git(["status", "--porcelain"])
        if not out.strip():
            return True, "No changes to commit (working tree clean)."

        # Commit
        code, out, err = self._run_git(["commit", "-m", message])
        if code != 0:
            return False, f"Git commit failed: {err or out}"

        return True, "Changes committed successfully."

    def push(self, branch: str = "main") -> Tuple[bool, str]:
        """Pushes commits to the remote origin."""
        remote = self.get_remote_url() or self.remote_url
        if not remote:
            return False, "No remote origin configured. Set your GitHub repo URL first."

        # Ensure current branch name is main or branch
        self._run_git(["branch", "-M", branch])

        code, out, err = self._run_git(["push", "-u", "origin", branch])
        if code != 0:
            msg = err or out
            if "GH001: Large files detected" in msg:
                return False, (
                    "GitHub rejected push: files > 100MB detected!\n"
                    "Tip: Keep audio files local and only push notes/catalog/code, "
                    "or enable Git LFS in settings."
                )
            if "Authentication failed" in msg or "Permission denied" in msg:
                return False, (
                    "GitHub Authentication Failed.\n"
                    "Make sure you have push permissions or use a GitHub Personal Access Token (PAT)."
                )
            return False, f"Git push failed: {msg}"

        return True, f"Successfully pushed to {remote} on branch {branch}!"


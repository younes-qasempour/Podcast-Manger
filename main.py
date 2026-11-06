import sys
import os
import asyncio
import argparse
from pathlib import Path
from typing import Optional, List, Set

from config import Config
from downloader import PodcastDownloader
from export_organizer import TelegramExportOrganizer
from git_manager import GitManager
from metadata_manager import build_channel_catalog
from utils import sanitize_filename, extract_episode_number, to_ascii_digits


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def print_banner():
    banner = r"""
╔═════════════════════════════════════════════════════════════════════════╗
║               📻 Telegram Podcast Downloader & Organizer                ║
║           Organize Captions, Thumbnails, MP3s & Push to GitHub          ║
╚═════════════════════════════════════════════════════════════════════════╝
    """
    print(banner)


def run_export_import(cfg: Config):
    """Processes an exported Telegram folder (result.json, messages.html, or audio folder)."""
    print("\n📂 Telegram Desktop Export Mode (Zero API Required):")
    print("-----------------------------------------------------")
    print("How to export in Telegram Desktop:")
    print("  1. Open Telegram Desktop and go to your podcast channel/chat (e.g. آگرافوس).")
    print("  2. Click the 3 dots '⋮' (top-right) -> 'Export chat history'.")
    print("  3. Check 'Audio files' (فایل‌های صوتی) and set size slider to max (2000 MB).")
    print("  4. Choose format: 'Machine-readable JSON' (or HTML).")
    print("  5. Click 'Export' and note the destination folder.\n")

    folder_input = input("Enter path to Telegram export folder (or press Enter for './export'): ").strip().strip('"\'')
    if not folder_input:
        folder_input = "./export"

    export_path = Path(folder_input).resolve()
    if not export_path.exists():
        print(f"\n❌ Error: Folder '{export_path}' does not exist.")
        input("\nPress Enter to return...")
        return

    print(f"\nScanning export in: {export_path}")
    try:
        organizer = TelegramExportOrganizer(export_path, cfg.output_dir, copy_files=True)
        exp_type = organizer.detect_export_type()
        print(f"Detected format: {exp_type.upper()}")

        episodes = organizer.process()
        print(f"\n🎉 Successfully organized {len(episodes)} episodes into: {cfg.output_dir}")

        # Offer Git Commit & Push
        prompt_git_push = input("\nDo you want to commit & push these to GitHub now? [Y/n]: ").strip().lower()
        if prompt_git_push in ("", "y", "yes"):
            run_git_push(cfg, commit_msg=f"Archive update: Organized {len(episodes)} podcast episodes")

    except Exception as e:
        print(f"\n❌ Error processing export: {e}")
        import traceback
        traceback.print_exc()

    input("\nPress Enter to return to menu...")


def run_git_push(cfg: Config, commit_msg: Optional[str] = None):
    """Handles git repository initialization, staging, commit, and push."""
    git_mgr = GitManager(cfg.root_dir, push_audio=cfg.git_push_audio, remote_url=cfg.git_remote_url)

    if not git_mgr.is_git_installed():
        print("\n❌ Git is not installed or not in PATH.")
        input("\nPress Enter to return...")
        return

    print("\n🔧 Checking Git repository status...")
    git_mgr.init_repo()

    current_remote = git_mgr.get_remote_url()
    if not current_remote:
        if cfg.git_remote_url:
            git_mgr.set_remote_url(cfg.git_remote_url)
            print(f"Set Git remote origin: {cfg.git_remote_url}")
        else:
            print("\n⚠️ No GitHub remote URL configured.")
            url = input("Enter your GitHub repository URL (e.g. https://github.com/username/repo.git): ").strip()
            if url:
                git_mgr.set_remote_url(url)
                cfg.update(GIT_REMOTE_URL=url)
            else:
                print("Skipping push without remote URL.")

    # Commit message
    if not commit_msg:
        commit_msg = input("\nEnter commit message (leave empty for default): ").strip()
    if not commit_msg:
        commit_msg = "Update podcast archive, metadata, and catalogs"

    print("\n📦 Staging and committing changes...")
    ok, msg = git_mgr.commit_all(commit_msg)
    print(msg)

    # Push
    if git_mgr.get_remote_url():
        print("\n🚀 Pushing to GitHub...")
        push_ok, push_msg = git_mgr.push()
        print(push_msg)
    else:
        print("Note: Commits saved locally. Add a remote URL to push to GitHub.")

    input("\nPress Enter to continue...")


async def run_api_download_menu(cfg: Config):
    """Sub-menu for downloading via Telegram API (Telethon)."""
    if not cfg.is_configured():
        print("\n⚠️ Telegram API credentials are missing!")
        print("Telegram's website (my.telegram.org) often gives an error when generating new API keys.")
        print("💡 TIP: Use Menu Option [1] ('Organize from Telegram Desktop Export') instead! It needs NO API keys.")
        try_anyway = input("\nDo you still want to enter API ID & Hash? [y/N]: ").strip().lower()
        if try_anyway not in ("y", "yes"):
            return
        api_id = input("Enter API_ID: ").strip()
        api_hash = input("Enter API_HASH: ").strip()
        if api_id and api_hash:
            cfg.update(TG_API_ID=api_id, TG_API_HASH=api_hash)

    downloader = PodcastDownloader(cfg)
    try:
        await downloader.connect()
        await downloader.resolve_channel()
    except Exception as e:
        print(f"\n❌ Connection error: {e}")
        input("\nPress Enter to return...")
        return

    print("\nSelect Download Mode:")
    print("  [1] Download ALL episodes in channel")
    print("  [2] Download Latest N episodes (e.g. last 5)")
    print("  [3] Download Specific Episode Number(s) (e.g. 91, 92 or 90-95)")
    print("  [4] Scan and List episodes only (dry run)")
    print("  [0] Cancel")

    mode = input("\nChoice [1-4]: ").strip()
    if mode == "1":
        await downloader.download_all()
    elif mode == "2":
        n_str = input("How many latest episodes to download? [e.g. 5]: ").strip()
        try:
            n = int(n_str)
            podcasts = await downloader.scan_podcasts()
            selected = podcasts[-n:] if len(podcasts) >= n else podcasts
            channel_name = sanitize_filename(downloader.channel_title, max_length=60)
            channel_dir = cfg.output_dir / channel_name
            channel_dir.mkdir(parents=True, exist_ok=True)
            for i, p in enumerate(selected, 1):
                print(f"\n--- Episode [{i}/{len(selected)}] ---")
                await downloader.download_episode(p, channel_dir)
            build_channel_catalog(channel_dir, channel_title=downloader.channel_title)
        except ValueError:
            print("Invalid number.")
    elif mode == "3":
        ep_input = input("Enter episode numbers (e.g. 91, 92 or range 90-95): ").strip()
        ep_numbers: Set[int] = set()
        clean_input = to_ascii_digits(ep_input)
        for part in clean_input.split(","):
            part = part.strip()
            if "-" in part:
                try:
                    start, end = part.split("-", 1)
                    ep_numbers.update(range(int(start), int(end) + 1))
                except ValueError:
                    pass
            elif part.isdigit():
                ep_numbers.add(int(part))

        if not ep_numbers:
            print("No valid episode numbers found.")
            return

        print(f"Targeting episodes: {sorted(ep_numbers)}")
        await downloader.download_all(episodes_filter=lambda meta: meta.episode_number in ep_numbers)
    elif mode == "4":
        podcasts = await downloader.scan_podcasts()
        print(f"\nFound {len(podcasts)} audio tracks:")
        for item in podcasts:
            m = item["metadata"]
            ep = f"Ep #{m.episode_number:03d}" if m.episode_number is not None else "No Ep#"
            print(f"  • {ep} | {m.title} | {m.file_size_formatted} | {m.duration_formatted}")

    input("\nPress Enter to return...")


def prompt_settings(cfg: Config):
    """Interactive settings editor."""
    while True:
        clear_screen()
        print_banner()
        print("⚙️  Current Settings:\n")
        print(f"  [1] Output Directory:    {cfg.output_dir}")
        print(f"  [2] GitHub Remote URL:   {cfg.git_remote_url or '(Not set)'}")
        print(f"  [3] Git Push Audio:      {cfg.git_push_audio} (Recommended: False to avoid 100MB limit)")
        print(f"  [4] Target Channel:      {cfg.target_channel}")
        print(f"  [5] Telegram API ID:     {cfg.api_id or '(Not set)'}")
        print(f"  [6] Telegram API Hash:   {cfg.api_hash[:6] + '...' if cfg.api_hash else '(Not set)'}")
        print(f"  [7] Proxy Enabled:       {cfg.proxy_enabled} ({cfg.proxy_type}://{cfg.proxy_host}:{cfg.proxy_port})")
        print("\n  [0] Back to Main Menu")

        choice = input("\nSelect setting to change [0-7]: ").strip()
        if choice == "0":
            break
        elif choice == "1":
            val = input("Enter Output directory: ").strip()
            if val: cfg.update(OUTPUT_DIR=val)
        elif choice == "2":
            val = input("Enter GitHub repository URL (e.g. https://github.com/user/repo.git): ").strip()
            if val: cfg.update(GIT_REMOTE_URL=val)
        elif choice == "3":
            val = input("Push audio files to GitHub? [y/N]: ").strip().lower() in ("y", "yes")
            cfg.update(GIT_PUSH_AUDIO=str(val).lower())
        elif choice == "4":
            val = input("Enter Target Channel username or link (e.g. @agrafoss): ").strip()
            if val: cfg.update(TARGET_CHANNEL=val)
        elif choice == "5":
            val = input("Enter API ID: ").strip()
            if val: cfg.update(TG_API_ID=val)
        elif choice == "6":
            val = input("Enter API Hash: ").strip()
            if val: cfg.update(TG_API_HASH=val)
        elif choice == "7":
            p_en = input("Enable proxy? [y/N]: ").strip().lower() in ("y", "yes", "true", "1")
            p_type = input(f"Proxy type [{cfg.proxy_type}]: ").strip() or cfg.proxy_type
            p_host = input(f"Proxy host [{cfg.proxy_host}]: ").strip() or cfg.proxy_host
            p_port = input(f"Proxy port [{cfg.proxy_port}]: ").strip() or str(cfg.proxy_port)
            cfg.update(PROXY_ENABLED=str(p_en).lower(), PROXY_TYPE=p_type, PROXY_HOST=p_host, PROXY_PORT=p_port)


def main_menu():
    cfg = Config()
    
    while True:
        clear_screen()
        print_banner()
        print("Select an option:\n")
        print("  🌟 [1] 📂 Organize from Telegram Desktop Export  (Recommended - Zero API needed!)")
        print("     [2] 📥 Download via Telegram API (Telethon)     (Requires API credentials)")
        print("     [3] 📚 Regenerate Channel Catalog (README.md)")
        print("     [4] 🚀 Commit and Push Archive to GitHub")
        print("     [5] ⚙️  Settings & Configuration")
        print("\n     [0] 🚪 Exit")

        choice = input("\nEnter choice [0-5]: ").strip()
        if choice == "1":
            run_export_import(cfg)
        elif choice == "2":
            asyncio.run(run_api_download_menu(cfg))
        elif choice == "3":
            if cfg.output_dir.exists():
                for ch_dir in cfg.output_dir.iterdir():
                    if ch_dir.is_dir() and (ch_dir / "episodes").exists():
                        readme = build_channel_catalog(ch_dir, channel_title=ch_dir.name)
                        print(f"Catalog regenerated: {readme}")
            else:
                print("Output directory does not exist yet.")
            input("\nPress Enter to continue...")
        elif choice == "4":
            run_git_push(cfg)
        elif choice == "5":
            prompt_settings(cfg)
        elif choice == "0":
            print("\nGoodbye! 👋")
            break


def parse_cli_args():
    parser = argparse.ArgumentParser(description="Telegram Podcast Downloader, Organizer and GitHub Archiver")
    parser.add_argument("--import-export", type=str, help="Path to Telegram Desktop export folder to organize")
    parser.add_argument("--download-all", action="store_true", help="Download all podcast episodes from target channel via API")
    parser.add_argument("--latest", type=int, help="Download latest N podcast episodes via API")
    parser.add_argument("--episodes", type=str, help="Comma-separated episode numbers (e.g. '91,92' or '90-95')")
    parser.add_argument("--channel", type=str, help="Override target channel username or link")
    parser.add_argument("--push", action="store_true", help="Commit and push to GitHub")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_cli_args()
    cfg = Config()

    if args.channel:
        cfg.target_channel = args.channel

    if args.import_export:
        organizer = TelegramExportOrganizer(Path(args.import_export), cfg.output_dir)
        organizer.process()
        if args.push:
            run_git_push(cfg, commit_msg="Update podcast archive from export")
    elif args.push:
        run_git_push(cfg)
    elif args.download_all or args.latest or args.episodes:
        downloader = PodcastDownloader(cfg)
        async def run_cli():
            await downloader.connect()
            await downloader.resolve_channel()
            if args.download_all:
                await downloader.download_all()
            elif args.latest:
                podcasts = await downloader.scan_podcasts()
                selected = podcasts[-args.latest:]
                channel_name = sanitize_filename(downloader.channel_title, max_length=60)
                ch_dir = cfg.output_dir / channel_name
                for item in selected:
                    await downloader.download_episode(item, ch_dir)
                build_channel_catalog(ch_dir, channel_title=downloader.channel_title)
            elif args.episodes:
                clean = to_ascii_digits(args.episodes)
                ep_nums = set()
                for p in clean.split(","):
                    if "-" in p:
                        s, e = p.split("-", 1)
                        ep_nums.update(range(int(s), int(e) + 1))
                    elif p.strip().isdigit():
                        ep_nums.add(int(p.strip()))
                await downloader.download_all(episodes_filter=lambda meta: meta.episode_number in ep_nums)

        asyncio.run(run_cli())
    else:
        try:
            main_menu()
        except KeyboardInterrupt:
            print("\nExiting...")

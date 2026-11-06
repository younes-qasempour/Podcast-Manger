import sys
import os
import asyncio
import argparse
from pathlib import Path
from typing import Optional, List, Set

from config import Config
from downloader import PodcastDownloader
from export_organizer import TelegramExportOrganizer, find_recent_telegram_exports
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

    recent_exports = find_recent_telegram_exports()
    default_prompt = "./export"
    if recent_exports:
        default_prompt = str(recent_exports[0])
        print(f"✨ Found recent Telegram Export:")
        print(f"   --> {default_prompt}\n")

    folder_input = input(f"Enter path to Telegram export folder (Press Enter for default):\n[{default_prompt}]: ").strip().strip('"\'')
    if not folder_input:
        folder_input = default_prompt

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


async def run_direct_telegram_download(cfg: Config):
    """Direct login into Telegram, scans channel, lets user select episodes to download, and pushes to Git."""
    clear_screen()
    print_banner()
    print("🚀 Direct Telegram Downloader")
    print("------------------------------------------------------------------")
    print(f"Target Channel: {cfg.target_channel}")
    ch_choice = input(f"Press Enter to use '{cfg.target_channel}', or type a new channel username/link: ").strip()
    if ch_choice:
        cfg.update(TARGET_CHANNEL=ch_choice)

    downloader = PodcastDownloader(cfg)
    try:
        print("\nConnecting to Telegram...")
        await downloader.connect()
        await downloader.resolve_channel()
    except Exception as e:
        print(f"\n❌ Connection failed: {e}")
        input("\nPress Enter to return...")
        return

    print("\nScanning podcasts in channel...")
    try:
        podcasts = await downloader.scan_podcasts()
    except Exception as e:
        print(f"\n❌ Failed to scan channel: {e}")
        input("\nPress Enter to return...")
        return

    if not podcasts:
        print("No audio podcasts found in this channel.")
        input("\nPress Enter to return...")
        return

    print(f"\n🎧 Found {len(podcasts)} podcast episodes in '{downloader.channel_title}':\n")
    # Show last 15 episodes preview
    show_list = podcasts[-20:] if len(podcasts) > 20 else podcasts
    start_idx = len(podcasts) - len(show_list) + 1
    for i, item in enumerate(show_list, start=start_idx):
        m = item["metadata"]
        ep_str = f"Ep #{m.episode_number:03d}" if m.episode_number is not None else "No Ep#"
        print(f"  [{i:02d}] {ep_str} | {m.title[:55]} | {m.duration_formatted} | {m.file_size_formatted}")

    if len(podcasts) > 20:
        print(f"  ... (and {len(podcasts) - 20} older episodes)")

    print("\n" + "="*65)
    print("Choose which episodes to download:")
    print("  • Type 'all' to download all episodes")
    print("  • Type 'latest 5' (or any number) for the most recent episodes")
    print("  • Type episode numbers, e.g.: 91, 92 or 90-95")
    print("  • Type list index numbers, e.g.: 1, 2 or 1-5")
    print("  • Type '0' to cancel")
    print("="*65)

    selection = input("\nYour selection: ").strip().lower()
    if not selection or selection == "0":
        return

    selected_podcasts = []
    clean_selection = to_ascii_digits(selection)

    if clean_selection == "all":
        selected_podcasts = podcasts
    elif clean_selection.startswith("latest"):
        parts = clean_selection.split()
        count = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 5
        selected_podcasts = podcasts[-count:]
    else:
        # Check if numbers are episode numbers or indices
        target_nums = set()
        for part in clean_selection.split(","):
            part = part.strip()
            if "-" in part:
                try:
                    s, e = part.split("-", 1)
                    target_nums.update(range(int(s), int(e) + 1))
                except ValueError:
                    pass
            elif part.isdigit():
                target_nums.add(int(part))

        # First match by episode_number
        matched_by_ep = [p for p in podcasts if p["metadata"].episode_number in target_nums]
        if matched_by_ep:
            selected_podcasts = matched_by_ep
        else:
            # Fallback to 1-based index
            selected_podcasts = [p for idx, p in enumerate(podcasts, 1) if idx in target_nums]

    if not selected_podcasts:
        print("No matching episodes found.")
        input("\nPress Enter to return...")
        return

    print(f"\nSelected {len(selected_podcasts)} episode(s) to download.")
    safe_ch_name = sanitize_filename(downloader.channel_title, max_length=60)
    ch_dir = cfg.output_dir / safe_ch_name
    ch_dir.mkdir(parents=True, exist_ok=True)

    for idx, item in enumerate(selected_podcasts, 1):
        print(f"\n=================== [{idx}/{len(selected_podcasts)}] ===================")
        await downloader.download_episode(item, ch_dir)

    # Update Catalog & RSS
    print("\nUpdating Catalog & Podcast RSS Feed...")
    readme_path = build_channel_catalog(ch_dir, channel_title=downloader.channel_title)
    print(f"Catalog updated: {readme_path}")

    # Prompt Git Commit & Push
    git_prompt = input("\n🚀 Do you want to commit & push these to GitHub now? [Y/n]: ").strip().lower()
    if git_prompt in ("", "y", "yes"):
        run_git_push(cfg, commit_msg=f"Add {len(selected_podcasts)} episodes from {downloader.channel_title}")

    input("\nPress Enter to return to menu...")


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
        print("  🚀 [1] 📥 Direct Telegram Login & Download  (QR Code or Phone - No my.telegram.org needed!)")
        print("     [2] 📂 Organize from Telegram Desktop Export  (Offline mode from exported folder)")
        print("     [3] 📚 Regenerate Channel Catalog & RSS (README.md & feed.xml)")
        print("     [4] 🚀 Commit and Push Archive to GitHub")
        print("     [5] ⚙️  Settings & Configuration")
        print("\n     [0] 🚪 Exit")

        choice = input("\nEnter choice [0-5]: ").strip()
        if choice == "1":
            asyncio.run(run_direct_telegram_download(cfg))
        elif choice == "2":
            run_export_import(cfg)
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

import sys
import os
import asyncio
import argparse
from pathlib import Path
from typing import Optional, List, Set

from config import Config
from downloader import PodcastDownloader
from git_manager import GitManager
from metadata_manager import build_channel_catalog, embed_id3_tags, EpisodeMetadata
from utils import sanitize_filename, extract_episode_number, to_ascii_digits


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def print_banner():
    banner = r"""
╔═════════════════════════════════════════════════════════════════════════╗
║               📻 Telegram Podcast Downloader & Organizer                ║
║                 Downloads, Tags, Organizes & Pushes to Git              ║
╚═════════════════════════════════════════════════════════════════════════╝
    """
    print(banner)


def check_setup(cfg: Config) -> bool:
    """Checks if Telegram API ID and Hash are set up."""
    if not cfg.is_configured():
        print("\n⚠️ Telegram API credentials are missing!")
        print("To download podcasts from Telegram, you need free API credentials:")
        print("  1. Open https://my.telegram.org in your browser.")
        print("  2. Log in with your phone number.")
        print("  3. Go to 'API development tools' and create an app (any title/short name).")
        print("  4. Copy your 'App api_id' and 'App api_hash'.\n")

        setup_now = input("Do you want to enter them now? [Y/n]: ").strip().lower()
        if setup_now in ("", "y", "yes"):
            api_id = input("Enter API_ID (numbers only): ").strip()
            api_hash = input("Enter API_HASH: ").strip()
            if api_id and api_hash:
                cfg.update(TG_API_ID=api_id, TG_API_HASH=api_hash)
                print("Credentials saved to .env file!\n")
                return True
        return False
    return True


def prompt_settings(cfg: Config):
    """Interactive settings editor."""
    while True:
        clear_screen()
        print_banner()
        print("⚙️  Current Settings:\n")
        print(f"  [1] Telegram API ID:     {cfg.api_id or '(Not set)'}")
        print(f"  [2] Telegram API Hash:   {cfg.api_hash[:6] + '...' if cfg.api_hash else '(Not set)'}")
        print(f"  [3] Target Channel:      {cfg.target_channel}")
        print(f"  [4] Download Folder:     {cfg.output_dir}")
        print(f"  [5] Proxy Enabled:       {cfg.proxy_enabled} ({cfg.proxy_type}://{cfg.proxy_host}:{cfg.proxy_port})")
        print(f"  [6] GitHub Remote URL:   {cfg.git_remote_url or '(Not set)'}")
        print(f"  [7] Git Push Audio:      {cfg.git_push_audio} (Recommended: False to avoid 100MB limit)")
        print("\n  [0] Back to Main Menu")

        choice = input("\nSelect setting to change [0-7]: ").strip()
        if choice == "0":
            break
        elif choice == "1":
            val = input("Enter API ID: ").strip()
            if val: cfg.update(TG_API_ID=val)
        elif choice == "2":
            val = input("Enter API Hash: ").strip()
            if val: cfg.update(TG_API_HASH=val)
        elif choice == "3":
            val = input("Enter Target Channel username or link (e.g. @agrafoss): ").strip()
            if val: cfg.update(TARGET_CHANNEL=val)
        elif choice == "4":
            val = input("Enter Output directory: ").strip()
            if val: cfg.update(OUTPUT_DIR=val)
        elif choice == "5":
            p_en = input("Enable proxy? [y/N]: ").strip().lower() in ("y", "yes", "true", "1")
            p_type = input(f"Proxy type [{cfg.proxy_type}]: ").strip() or cfg.proxy_type
            p_host = input(f"Proxy host [{cfg.proxy_host}]: ").strip() or cfg.proxy_host
            p_port = input(f"Proxy port [{cfg.proxy_port}]: ").strip() or str(cfg.proxy_port)
            cfg.update(PROXY_ENABLED=str(p_en).lower(), PROXY_TYPE=p_type, PROXY_HOST=p_host, PROXY_PORT=p_port)
        elif choice == "6":
            val = input("Enter GitHub repository URL (e.g. https://github.com/user/repo.git): ").strip()
            if val: cfg.update(GIT_REMOTE_URL=val)
        elif choice == "7":
            val = input("Push audio files to GitHub? [y/N] (Warning: files > 100MB require Git LFS): ").strip().lower() in ("y", "yes")
            cfg.update(GIT_PUSH_AUDIO=str(val).lower())


async def run_download_menu(cfg: Config):
    """Sub-menu for downloading options."""
    if not check_setup(cfg):
        return

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


async def run_pipeline(cfg: Config):
    """Executes the complete pipeline: Download latest -> Organize -> Update Catalog -> Git Push."""
    if not check_setup(cfg):
        return

    print("\n⚡ Starting Full Pipeline...")
    downloader = PodcastDownloader(cfg)
    try:
        await downloader.connect()
        await downloader.resolve_channel()
        await downloader.download_all()
        print("\n✅ Download and organization completed!")
        
        # Git Commit & Push
        run_git_push(cfg, commit_msg=f"Update {downloader.channel_title} podcast archive")
    except Exception as e:
        print(f"\n❌ Pipeline failed: {e}")
        input("\nPress Enter to return...")


def main_menu():
    cfg = Config()
    
    while True:
        clear_screen()
        print_banner()
        print("Select an action:\n")
        print("  [1] 📥 Download Podcasts from Telegram")
        print("  [2] 📚 Regenerate Channel Catalog (README.md)")
        print("  [3] 🚀 Commit and Push Changes to GitHub")
        print("  [4] ⚡ Run Full Automated Pipeline (Download -> Organize -> Push)")
        print("  [5] ⚙️  Settings & Telegram Credentials")
        print("\n  [0] 🚪 Exit")

        choice = input("\nEnter choice [0-5]: ").strip()
        if choice == "1":
            asyncio.run(run_download_menu(cfg))
        elif choice == "2":
            # Rebuild catalogs for all directories in output_dir
            if cfg.output_dir.exists():
                for ch_dir in cfg.output_dir.iterdir():
                    if ch_dir.is_dir() and (ch_dir / "episodes").exists():
                        readme = build_channel_catalog(ch_dir, channel_title=ch_dir.name)
                        print(f"Catalog regenerated: {readme}")
            else:
                print("Output directory does not exist yet.")
            input("\nPress Enter to continue...")
        elif choice == "3":
            run_git_push(cfg)
        elif choice == "4":
            asyncio.run(run_pipeline(cfg))
        elif choice == "5":
            prompt_settings(cfg)
        elif choice == "0":
            print("\nGoodbye! 👋")
            break


def parse_cli_args():
    parser = argparse.ArgumentParser(description="Telegram Podcast Downloader, Organizer and GitHub Archiver")
    parser.add_argument("--download-all", action="store_true", help="Download all podcast episodes from target channel")
    parser.add_argument("--latest", type=int, help="Download latest N podcast episodes")
    parser.add_argument("--episodes", type=str, help="Comma-separated episode numbers (e.g. '91,92' or '90-95')")
    parser.add_argument("--channel", type=str, help="Override target channel username or link")
    parser.add_argument("--push", action="store_true", help="Commit and push to GitHub")
    parser.add_argument("--pipeline", action="store_true", help="Run full pipeline (Download + Catalog + Git Push)")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_cli_args()
    cfg = Config()

    if args.channel:
        cfg.target_channel = args.channel

    # CLI mode if any flag passed
    if args.download_all or args.latest or args.episodes or args.push or args.pipeline:
        if args.pipeline:
            asyncio.run(run_pipeline(cfg))
        elif args.push:
            run_git_push(cfg)
        elif args.download_all or args.latest or args.episodes:
            if not check_setup(cfg):
                sys.exit(1)
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
        # Interactive mode
        try:
            main_menu()
        except KeyboardInterrupt:
            print("\nExiting...")

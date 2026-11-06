# 🎙️ Telegram Podcast Downloader & Organizer

An automated tool to download, organize, tag, and archive podcasts and audio series directly from Telegram channels or chats. It saves complete episode notes/captions as Markdown, extracts thumbnails/covers, embeds ID3 metadata into MP3s, generates a master catalog, and commits & pushes everything to GitHub.

---

## ✨ Features

- **🚀 MTProto High-Speed Downloader:** Uses [Telethon](https://github.com/LonamiWebs/Telethon) and `cryptg` to download files up to 2 GB (unlike Telegram Bots which are capped at 20 MB).
- **📂 Automatic Folder & File Organization:** Automatically extracts episode numbers (supports Persian and English digits: `۹۱` -> `91`) and organizes each episode into its own clean directory.
- **📝 Formatted Markdown Captions:** Extracts Telegram captions, descriptions, and hashtags into formatted `info.md` and machine-readable `info.json` files.
- **🖼️ Thumbnail & Cover Art Extraction:** Extracts embedded audio thumbnails, message photos, or channel profile photos to `cover.jpg`.
- **🏷️ MP3 ID3 Tagging:** Automatically embeds episode title, artist, album name, track number, episode caption/lyrics, and cover art directly into the MP3 using `mutagen`.
- **📊 Master Catalog Generator:** Automatically builds a comprehensive `README.md` catalog with a table of contents, episode metrics (total duration, total size, episode count), and direct links.
- **🐙 Git & GitHub Integration:** Automatically initializes the repository, sets up `.gitignore` to protect credentials and handle GitHub's 100 MB per-file limit, commits changes, and pushes to your GitHub repo.
- **🛡️ Proxy Support:** Built-in SOCKS5 and HTTP proxy support (e.g. for V2Ray, Clash, Nekoray in restricted regions).

---

## 📁 Directory Structure Created by the App

```text
podcasts/
└── آگرافوس/
    ├── README.md                                  # Auto-generated Master Catalog & Table of Contents
    └── episodes/
        ├── 091 - علی شاهی - تحلیل «چنین گفت زرتشت» (91)/
        │   ├── audio.mp3                          # Downloaded audio file (with ID3 tags embedded)
        │   ├── cover.jpg                          # Episode cover thumbnail
        │   ├── info.md                            # Complete episode note, description & Telegram link
        │   └── info.json                          # Full metadata in JSON format
        │
        └── 092 - علی شاهی - تحلیل «چنین گفت زرتشت» (92)/
            ├── audio.mp3
            ├── cover.jpg
            ├── info.md
            └── info.json
```

---

## 🚀 Quick Start Guide

### 1. Requirements

- Python 3.9+
- Git installed on your system

Install required packages:
```bash
pip install -r requirements.txt
```

### 2. Get Telegram API Credentials (Free)

Telegram user applications require an `api_id` and `api_hash`:
1. Go to [https://my.telegram.org](https://my.telegram.org) and log in with your Telegram phone number.
2. Click on **API development tools**.
3. Fill in the short form (any app name and short name).
4. Copy your **App api_id** and **App api_hash**.

### 3. Configure `.env`

Copy `.env.example` to `.env`:
```bash
copy .env.example .env
```

Open `.env` and fill in your details:
```env
TG_API_ID=12345678
TG_API_HASH=your_telegram_api_hash_here
TARGET_CHANNEL=@agrafoss

# If you use a VPN/Proxy (e.g. V2Ray on port 10808 or Clash on 7890):
PROXY_ENABLED=false
PROXY_TYPE=socks5
PROXY_HOST=127.0.0.1
PROXY_PORT=10808

# GitHub repository remote URL:
GIT_REMOTE_URL=https://github.com/YOUR_USERNAME/YOUR_REPO.git
GIT_PUSH_AUDIO=false
```

> **Note on GitHub & Large Audio Files:**
> GitHub enforces a strict **100 MB per-file upload limit**. Since podcast episodes often exceed 150 MB (e.g. 155 MB and 163 MB as shown in your screenshot), `GIT_PUSH_AUDIO` is set to `false` by default. This ensures audio files stay safely on your local drive, while the episode notes (`info.md`), JSON metadata, thumbnails (`cover.jpg`), catalog, and code are committed and pushed to GitHub.

---

## 💻 How to Use

### Method A: Interactive Menu (Recommended)

Run:
```bash
python main.py
```

You will see an intuitive menu:
```text
╔═════════════════════════════════════════════════════════════════════════╗
║               📻 Telegram Podcast Downloader & Organizer                ║
║                 Downloads, Tags, Organizes & Pushes to Git              ║
╚═════════════════════════════════════════════════════════════════════════╝

Select an action:
  [1] 📥 Download Podcasts from Telegram
  [2] 📚 Regenerate Channel Catalog (README.md)
  [3] 🚀 Commit and Push Changes to GitHub
  [4] ⚡ Run Full Automated Pipeline (Download -> Organize -> Push)
  [5] ⚙️  Settings & Telegram Credentials

  [0] 🚪 Exit
```

### Method B: Command Line (Fast / Scripted)

- **Download latest 5 episodes:**
  ```bash
  python main.py --latest 5
  ```

- **Download specific episodes (e.g. 91 and 92):**
  ```bash
  python main.py --episodes "91,92"
  ```

- **Download an episode range (e.g. 90 to 95):**
  ```bash
  python main.py --episodes "90-95"
  ```

- **Download all episodes in the channel:**
  ```bash
  python main.py --download-all
  ```

- **Run full pipeline (Download + Tag + Catalog + Push to GitHub):**
  ```bash
  python main.py --pipeline
  ```

- **Commit and Push changes to GitHub:**
  ```bash
  python main.py --push
  ```

---

## 🔒 Security & Privacy

- Your `.env` and `*.session` files are **strictly ignored** by `.gitignore`. They will never be pushed to your public or private GitHub repository.
- Telegram sessions are stored locally in your project folder, so you only log in once.


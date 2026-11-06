# 🎙️ Telegram Podcast Organizer & GitHub Archiver

A smart tool to organize, tag, catalog, and archive podcasts and audio series from Telegram channels or chats directly into GitHub. Supports **Telegram Desktop Export** (zero API keys required) as well as the **Telegram MTProto API**.

---

## 🌟 The Zero-API Approach (Recommended)

Telegram's developer website (`my.telegram.org`) frequently returns errors when creating new API credentials.  
To bypass this completely, this app supports **Telegram Desktop Chat Export**:

### How it works:
1. Open **Telegram Desktop** and navigate to your podcast channel or chat (e.g. `آگرافوس`).
2. Click the three dots `⋮` at the top right $\rightarrow$ **Export chat history** *(خروجی گرفتن از گفتگو)*.
3. In the export window:
   - Check **Audio files** *(فایل‌های صوتی)*.
   - Set the size limit slider to **2000 MB**.
   - Choose format: **Machine-readable JSON** (or HTML).
   - Click **Export**.
4. Run our app:
   ```powershell
   python main.py
   ```
   Select **Option [1]** and give it the path to the exported folder.

The app will automatically:
- 🔍 Detect every podcast episode and its episode number (e.g. `اپیزود ۹۱` $\rightarrow$ `91`).
- 📁 Create structured folders for each episode.
- 📝 Extract full descriptions, Persian captions, and clickable links into `info.md` and `info.json`.
- 🖼️ Extract and attach cover thumbnails (`cover.jpg`).
- 🏷️ Embed ID3 tags (Title, Artist, Album, Track #, Caption, Cover Art) directly into the audio files.
- 📊 Generate a **Master Catalog (`README.md`)** with total episode count, total duration, and table of contents.
- 🚀 Commit and push the organized archive directly to your **GitHub** repository!

---

## 📁 Output Folder Structure

```text
podcasts/
└── آگرافوس/
    ├── README.md                                  # Master Catalog & Table of Contents
    └── episodes/
        ├── 091 - علی شاهی - تحلیل «چنین گفت زرتشت» (91)/
        │   ├── audio.mp3                          # Audio track with embedded tags & album art
        │   ├── cover.jpg                          # Episode cover thumbnail
        │   ├── info.md                            # Full description text, Persian caption & post link
        │   └── info.json                          # Full metadata in JSON
        └── 092 - علی شاهی - تحلیل «چنین گفت زرتشت» (92)/
            ├── ...
```

---

> [!IMPORTANT]
> **GitHub 100 MB Limit**  
> GitHub enforces a strict 100 MB per-file limit. Since podcast episodes are often ~150 MB+, the `.gitignore` automatically keeps the heavy audio files safely on your local disk, while committing and pushing all **captions/notes (`info.md`)**, **thumbnails (`cover.jpg`)**, **metadata (`info.json`)**, **catalog table (`README.md`)**, and **scripts** to GitHub.

---

## 🚀 How to Run

### 1. Interactive Menu
```powershell
python main.py
```

### 2. Direct Command Line
- **Organize from Telegram Desktop Export:**
  ```powershell
  python main.py --import-export "C:\path\to\Telegram Desktop\ChatExport_..."
  ```
- **Organize and immediately push to GitHub:**
  ```powershell
  python main.py --import-export "C:\path\to\Telegram Desktop\ChatExport_..." --push
  ```
- **Push existing catalog and notes to GitHub:**
  ```powershell
  python main.py --push
  ```

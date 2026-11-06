import sys
import os
import json
import shutil
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QTextEdit,
    QProgressBar, QGroupBox, QCheckBox, QMessageBox, QSplitter,
    QListWidget, QListWidgetItem, QTabWidget, QComboBox, QFormLayout,
    QSpinBox, QFrame, QScrollArea
)
from PyQt6.QtCore import pyqtSignal, QObject, Qt, QSize
from PyQt6.QtGui import QFont, QIcon, QPixmap, QImage
from PIL import Image

from config import Config
from export_organizer import TelegramExportOrganizer, find_recent_telegram_exports
from git_manager import GitManager
from metadata_manager import (
    EpisodeMetadata, embed_audio_tags, build_channel_catalog
)
from utils import sanitize_filename, format_duration, format_size


class WorkerSignals(QObject):
    log = pyqtSignal(str)
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(bool, str)


class PodcastStudioGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = Config()
        self.current_episodes: List[Dict[str, Any]] = []
        self.selected_ep_index = -1
        self.pending_new_cover_path: Optional[Path] = None

        self.init_ui()
        self.load_series_list()

    def init_ui(self):
        self.setWindowTitle("🎙️ Telegram Podcast Studio & Explorer")
        self.resize(1150, 780)
        self.setMinimumSize(900, 650)

        # Apply dark modern theme with smooth contrast
        self.setStyleSheet("""
            QMainWindow {
                background-color: #181825;
                color: #cdd6f4;
            }
            QWidget {
                color: #cdd6f4;
                font-family: 'Segoe UI', 'Tahoma', 'Vazirmatn', sans-serif;
                font-size: 13px;
            }
            QTabWidget::pane {
                border: 1px solid #313244;
                background-color: #1e1e2e;
                border-radius: 8px;
            }
            QTabBar::tab {
                background-color: #181825;
                color: #a6adc8;
                padding: 10px 24px;
                margin-right: 4px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background-color: #1e1e2e;
                color: #89b4fa;
                border-bottom: 2px solid #89b4fa;
            }
            QGroupBox {
                border: 1px solid #45475a;
                border-radius: 8px;
                margin-top: 10px;
                font-weight: bold;
                padding: 14px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 5px;
                color: #89b4fa;
            }
            QLineEdit, QSpinBox, QComboBox {
                background-color: #313244;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 7px 10px;
                color: #f5e0dc;
            }
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
                border: 1px solid #89b4fa;
            }
            QTextEdit {
                background-color: #181825;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 8px;
                color: #cdd6f4;
                font-size: 13px;
                line-height: 1.4;
            }
            QListWidget {
                background-color: #181825;
                border: 1px solid #313244;
                border-radius: 8px;
                outline: none;
                padding: 4px;
            }
            QListWidget::item {
                border-radius: 6px;
                padding: 8px;
                margin-bottom: 4px;
                background-color: #1e1e2e;
            }
            QListWidget::item:hover {
                background-color: #313244;
            }
            QListWidget::item:selected {
                background-color: #45475a;
                border-left: 3px solid #89b4fa;
            }
            QPushButton {
                background-color: #89b4fa;
                color: #11111b;
                font-weight: bold;
                border-radius: 6px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #b4befe;
            }
            QPushButton#saveBtn {
                background-color: #a6e3a1;
                color: #11111b;
                font-size: 14px;
                padding: 10px 20px;
            }
            QPushButton#saveBtn:hover {
                background-color: #94e2d5;
            }
            QPushButton#playBtn {
                background-color: #f9e2af;
                color: #11111b;
            }
            QPushButton#playBtn:hover {
                background-color: #fab387;
            }
            QPushButton#gitBtn {
                background-color: #cba6f7;
                color: #11111b;
            }
            QPushButton#gitBtn:hover {
                background-color: #f5c2e7;
            }
            QPushButton#browseBtn {
                background-color: #45475a;
                color: #cdd6f4;
            }
            QPushButton#browseBtn:hover {
                background-color: #585b70;
            }
            QProgressBar {
                border: 1px solid #45475a;
                border-radius: 5px;
                text-align: center;
                background-color: #313244;
            }
            QProgressBar::chunk {
                background-color: #a6e3a1;
                border-radius: 4px;
            }
        """)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        # Tab Widget
        self.tabs = QTabWidget()
        root_layout.addWidget(self.tabs)

        # Tab 1: Library & Metadata Editor
        self.library_tab = QWidget()
        self.init_library_tab()
        self.tabs.addTab(self.library_tab, "📚 Podcast Library & Studio")

        # Tab 2: Downloader & Importer
        self.downloader_tab = QWidget()
        self.init_downloader_tab()
        self.tabs.addTab(self.downloader_tab, "📥 Downloader & Git Sync")

        # Status Bar
        self.statusBar().showMessage("Ready.")

    # =========================================================================
    # TAB 1: Library & Editor
    # =========================================================================
    def init_library_tab(self):
        layout = QVBoxLayout(self.library_tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Top Bar: Series selection & search
        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel("Podcast Series:"))
        self.series_combo = QComboBox()
        self.series_combo.setMinimumWidth(220)
        self.series_combo.currentIndexChanged.connect(self.on_series_selected)
        top_bar.addWidget(self.series_combo)

        top_bar.addSpacing(15)
        top_bar.addWidget(QLabel("🔍 Search:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search by episode #, title, or keywords...")
        self.search_input.textChanged.connect(self.filter_episodes)
        top_bar.addWidget(self.search_input)

        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.setObjectName("browseBtn")
        refresh_btn.clicked.connect(self.load_series_list)
        top_bar.addWidget(refresh_btn)

        open_series_folder_btn = QPushButton("📂 Open Series Folder")
        open_series_folder_btn.setObjectName("browseBtn")
        open_series_folder_btn.clicked.connect(self.open_current_series_folder)
        top_bar.addWidget(open_series_folder_btn)

        layout.addLayout(top_bar)

        # Splitter: Left = Episode List, Right = Metadata & Cover Editor
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(8)

        # Left: Episode List
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.ep_count_label = QLabel("Episodes: 0")
        self.ep_count_label.setStyleSheet("color: #a6adc8; font-weight: bold;")
        left_layout.addWidget(self.ep_count_label)

        self.episode_list = QListWidget()
        self.episode_list.setIconSize(QSize(48, 48))
        self.episode_list.currentRowChanged.connect(self.on_episode_clicked)
        left_layout.addWidget(self.episode_list)
        splitter.addWidget(left_widget)

        # Right: Detail & Editor
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(10, 0, 10, 10)
        right_layout.setSpacing(12)

        # Artwork + Quick Action Bar
        art_box = QHBoxLayout()
        art_box.setSpacing(15)

        # Cover Preview Label
        self.cover_label = QLabel()
        self.cover_label.setFixedSize(180, 180)
        self.cover_label.setStyleSheet("""
            QLabel {
                border: 2px dashed #45475a;
                border-radius: 10px;
                background-color: #181825;
            }
        """)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setText("No Cover")
        art_box.addWidget(self.cover_label)

        # Cover buttons & Audio controls
        art_btn_layout = QVBoxLayout()
        art_btn_layout.setSpacing(8)

        change_cover_btn = QPushButton("🖼️ Change Thumbnail...")
        change_cover_btn.clicked.connect(self.browse_new_cover)
        art_btn_layout.addWidget(change_cover_btn)

        remove_cover_btn = QPushButton("🗑️ Reset Thumbnail")
        remove_cover_btn.setObjectName("browseBtn")
        remove_cover_btn.clicked.connect(self.reset_cover)
        art_btn_layout.addWidget(remove_cover_btn)

        art_btn_layout.addSpacing(10)

        self.play_audio_btn = QPushButton("▶️ Play Audio Track")
        self.play_audio_btn.setObjectName("playBtn")
        self.play_audio_btn.clicked.connect(self.play_audio_file)
        art_btn_layout.addWidget(self.play_audio_btn)

        self.open_ep_folder_btn = QPushButton("📁 Open Episode Folder")
        self.open_ep_folder_btn.setObjectName("browseBtn")
        self.open_ep_folder_btn.clicked.connect(self.open_episode_folder)
        art_btn_layout.addWidget(self.open_ep_folder_btn)

        art_btn_layout.addStretch()
        art_box.addLayout(art_btn_layout)
        art_box.addStretch()

        right_layout.addLayout(art_box)

        # Metadata Form
        form_group = QGroupBox("📝 Episode Information")
        form_layout = QFormLayout(form_group)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form_layout.setSpacing(10)

        self.ep_num_spin = QSpinBox()
        self.ep_num_spin.setRange(0, 9999)
        form_layout.addRow("Episode #:", self.ep_num_spin)

        self.title_input = QLineEdit()
        form_layout.addRow("Title:", self.title_input)

        self.artist_input = QLineEdit()
        form_layout.addRow("Speaker / Host:", self.artist_input)

        self.series_input = QLineEdit()
        form_layout.addRow("Series Title:", self.series_input)

        self.file_info_label = QLabel("Duration: - | Size: -")
        self.file_info_label.setStyleSheet("color: #89b4fa; font-weight: bold;")
        form_layout.addRow("Audio Info:", self.file_info_label)

        right_layout.addWidget(form_group)

        # Caption / Description Editor
        notes_group = QGroupBox("📖 Description, Persian Captions & Notes")
        notes_layout = QVBoxLayout(notes_group)
        self.caption_edit = QTextEdit()
        self.caption_edit.setMinimumHeight(180)
        self.caption_edit.setPlaceholderText("Enter episode description, notes, timestamps, or hashtags...")
        notes_layout.addWidget(self.caption_edit)
        right_layout.addWidget(notes_group)

        # Bottom Save & Git Actions
        action_bar = QHBoxLayout()
        action_bar.setSpacing(12)

        self.save_btn = QPushButton("💾 Save Changes (Update Tags, Notes & Catalog)")
        self.save_btn.setObjectName("saveBtn")
        self.save_btn.clicked.connect(self.save_episode_changes)
        action_bar.addWidget(self.save_btn)

        self.push_git_btn = QPushButton("🚀 Commit & Push to GitHub")
        self.push_git_btn.setObjectName("gitBtn")
        self.push_git_btn.clicked.connect(self.quick_git_push)
        action_bar.addWidget(self.push_git_btn)

        right_layout.addLayout(action_bar)
        right_layout.addStretch()

        right_scroll.setWidget(right_widget)
        splitter.addWidget(right_scroll)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 5)
        layout.addWidget(splitter)

    # =========================================================================
    # TAB 2: Downloader & Git Sync
    # =========================================================================
    def init_downloader_tab(self):
        layout = QVBoxLayout(self.downloader_tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        title = QLabel("⚙️ Download Settings & Git Synchronization")
        title.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        title.setStyleSheet("color: #89b4fa;")
        layout.addWidget(title)

        # Settings Box
        sett_box = QGroupBox("Repository & Destination")
        sett_layout = QFormLayout(sett_box)
        sett_layout.setSpacing(10)

        self.git_url_input = QLineEdit(self.cfg.git_remote_url)
        self.git_url_input.setPlaceholderText("https://github.com/username/my-podcast-archive.git")
        sett_layout.addRow("GitHub Remote URL:", self.git_url_input)

        self.channel_input = QLineEdit(self.cfg.target_channel)
        sett_layout.addRow("Target Telegram Channel:", self.channel_input)

        self.output_dir_input = QLineEdit(str(self.cfg.output_dir))
        sett_layout.addRow("Podcasts Output Directory:", self.output_dir_input)

        layout.addWidget(sett_box)

        # Action Buttons
        btn_box = QHBoxLayout()
        sync_git_btn = QPushButton("🚀 Push Whole Archive to GitHub")
        sync_git_btn.setObjectName("gitBtn")
        sync_git_btn.clicked.connect(self.sync_all_to_github)
        btn_box.addWidget(sync_git_btn)

        rebuild_cat_btn = QPushButton("📚 Rebuild All Catalogs (README & RSS)")
        rebuild_cat_btn.clicked.connect(self.rebuild_all_catalogs)
        btn_box.addWidget(rebuild_cat_btn)

        layout.addLayout(btn_box)

        # Console
        console_box = QGroupBox("Console & Sync Log")
        console_layout = QVBoxLayout(console_box)
        self.console_text = QTextEdit()
        self.console_text.setReadOnly(True)
        console_layout.addWidget(self.console_text)
        layout.addWidget(console_box)

        layout.addStretch()

    # =========================================================================
    # Library Logic: Loading & Displaying Series & Episodes
    # =========================================================================
    def load_series_list(self):
        """Scans the output directory for all series folders."""
        self.series_combo.blockSignals(True)
        self.series_combo.clear()

        out_dir = self.cfg.output_dir
        if out_dir.exists():
            for item in sorted(out_dir.iterdir()):
                if item.is_dir() and (item / "episodes").exists():
                    self.series_combo.addItem(f"📁 {item.name}", userData=str(item))

        self.series_combo.blockSignals(False)

        if self.series_combo.count() > 0:
            self.series_combo.setCurrentIndex(0)
            self.load_episodes_for_series(Path(self.series_combo.currentData()))
        else:
            self.episode_list.clear()
            self.ep_count_label.setText("No downloaded series found yet in podcasts/.")

    def on_series_selected(self, index: int):
        data = self.series_combo.currentData()
        if data:
            self.load_episodes_for_series(Path(data))

    def load_episodes_for_series(self, series_dir: Path):
        """Loads all episodes from the given series directory."""
        self.current_episodes.clear()
        self.episode_list.clear()

        episodes_dir = series_dir / "episodes"
        if not episodes_dir.exists():
            return

        ep_folders = [f for f in episodes_dir.iterdir() if f.is_dir()]
        loaded_data = []

        for folder in ep_folders:
            info_json = folder / "info.json"
            if info_json.exists():
                try:
                    with open(info_json, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        data["_folder_path"] = folder
                        loaded_data.append(data)
                except Exception:
                    pass
            else:
                # Basic fallback
                loaded_data.append({
                    "title": folder.name,
                    "episode_number": None,
                    "duration_formatted": "-",
                    "file_size_formatted": "-",
                    "_folder_path": folder
                })

        # Sort by episode_number ascending
        def sort_key(d):
            ep_num = d.get("episode_number")
            return (0, ep_num) if ep_num is not None else (1, d.get("title", ""))

        loaded_data.sort(key=sort_key)
        self.current_episodes = loaded_data

        # Populate List
        self.populate_episode_list(self.current_episodes)
        self.ep_count_label.setText(f"Episodes: {len(self.current_episodes)}")

        if self.current_episodes:
            self.episode_list.setCurrentRow(0)

    def populate_episode_list(self, ep_list: List[Dict[str, Any]]):
        self.episode_list.clear()
        for ep in ep_list:
            ep_num = ep.get("episode_number")
            ep_badge = f"Ep #{ep_num:03d}" if ep_num is not None else "No Ep#"
            title = ep.get("title", "Untitled")
            dur = ep.get("duration_formatted", "-")
            size = ep.get("file_size_formatted", "-")

            item_text = f"{ep_badge} | {title}\n  ⏱ {dur}  •  💾 {size}"
            list_item = QListWidgetItem(item_text)

            # Thumbnail Icon
            folder = ep.get("_folder_path")
            cover_file = folder / "cover.jpg" if folder else None
            if cover_file and cover_file.exists():
                list_item.setIcon(QIcon(str(cover_file)))

            self.episode_list.addItem(list_item)

    def filter_episodes(self, query: str):
        query = query.strip().lower()
        if not query:
            self.populate_episode_list(self.current_episodes)
            return

        filtered = []
        for ep in self.current_episodes:
            title = ep.get("title", "").lower()
            caption = ep.get("caption", "").lower()
            ep_num = str(ep.get("episode_number") or "")
            if query in title or query in caption or query == ep_num:
                filtered.append(ep)

        self.populate_episode_list(filtered)

    def on_episode_clicked(self, row: int):
        if row < 0 or row >= len(self.current_episodes):
            return

        self.selected_ep_index = row
        self.pending_new_cover_path = None
        data = self.current_episodes[row]

        # Populate Fields
        self.ep_num_spin.setValue(data.get("episode_number") or 0)
        self.title_input.setText(data.get("title", ""))
        self.artist_input.setText(data.get("artist", ""))
        self.series_input.setText(data.get("series_title", ""))
        self.caption_edit.setPlainText(data.get("caption", ""))

        dur = data.get("duration_formatted", "-")
        size = data.get("file_size_formatted", "-")
        audio_name = data.get("audio_filename", "audio.mp3")
        self.file_info_label.setText(f"Duration: {dur}  |  Size: {size}  |  File: {audio_name}")

        # Load Cover Preview
        folder = Path(data["_folder_path"])
        cover_path = folder / "cover.jpg"
        self.display_cover(cover_path if cover_path.exists() else None)

    def display_cover(self, image_path: Optional[Path]):
        if image_path and image_path.exists():
            pixmap = QPixmap(str(image_path))
            if not pixmap.isNull():
                scaled = pixmap.scaled(180, 180, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.cover_label.setPixmap(scaled)
                self.cover_label.setText("")
                return
        self.cover_label.setPixmap(QPixmap())
        self.cover_label.setText("No Cover Image")

    def browse_new_cover(self):
        if self.selected_ep_index < 0:
            QMessageBox.warning(self, "Notice", "Please select an episode from the list first.")
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select New Cover Image",
            "",
            "Image Files (*.jpg *.jpeg *.png *.webp)"
        )
        if file_path:
            p = Path(file_path)
            self.pending_new_cover_path = p
            self.display_cover(p)
            self.statusBar().showMessage(f"Selected new thumbnail: {p.name} (Click 'Save Changes' to apply).")

    def reset_cover(self):
        if self.selected_ep_index < 0:
            return
        data = self.current_episodes[self.selected_ep_index]
        orig_cover = Path(data["_folder_path"]) / "cover.jpg"
        self.pending_new_cover_path = None
        self.display_cover(orig_cover if orig_cover.exists() else None)

    def play_audio_file(self):
        if self.selected_ep_index < 0:
            return
        data = self.current_episodes[self.selected_ep_index]
        folder = Path(data["_folder_path"])
        # Find audio file
        audio_files = list(folder.glob("audio.*")) + list(folder.glob("*.mp3")) + list(folder.glob("*.m4a"))
        if audio_files:
            try:
                os.startfile(str(audio_files[0]))
                self.statusBar().showMessage(f"Playing: {audio_files[0].name}")
            except Exception as e:
                QMessageBox.critical(self, "Playback Error", str(e))
        else:
            QMessageBox.warning(self, "File Not Found", "No audio file found in this episode folder.")

    def open_episode_folder(self):
        if self.selected_ep_index < 0:
            return
        folder = self.current_episodes[self.selected_ep_index]["_folder_path"]
        os.startfile(str(folder))

    def open_current_series_folder(self):
        data = self.series_combo.currentData()
        if data:
            os.startfile(data)

    # =========================================================================
    # Saving Changes & Mutagen Re-tagging
    # =========================================================================
    def save_episode_changes(self):
        if self.selected_ep_index < 0:
            return

        ep_data = self.current_episodes[self.selected_ep_index]
        folder = Path(ep_data["_folder_path"])

        new_ep_num = self.ep_num_spin.value() or None
        new_title = self.title_input.text().strip() or ep_data.get("title", "")
        new_artist = self.artist_input.text().strip() or ep_data.get("artist", "")
        new_series = self.series_input.text().strip() or ep_data.get("series_title", "")
        new_caption = self.caption_edit.toPlainText().strip()

        # Update dictionary
        ep_data["episode_number"] = new_ep_num
        ep_data["title"] = new_title
        ep_data["artist"] = new_artist
        ep_data["series_title"] = new_series
        ep_data["caption"] = new_caption

        # 1. Update Thumbnail if a new one was selected
        cover_path = folder / "cover.jpg"
        if self.pending_new_cover_path and self.pending_new_cover_path.exists():
            try:
                # Convert to clean RGB JPEG
                with Image.open(self.pending_new_cover_path) as im:
                    rgb_im = im.convert("RGB")
                    rgb_im.save(cover_path, "JPEG", quality=92)
                self.pending_new_cover_path = None
            except Exception as e:
                QMessageBox.warning(self, "Thumbnail Warning", f"Could not process image: {e}")

        # 2. Save info.json
        with open(folder / "info.json", "w", encoding="utf-8") as f:
            # exclude _folder_path from json
            to_save = {k: v for k, v in ep_data.items() if not k.startswith("_")}
            json.dump(to_save, f, ensure_ascii=False, indent=2)

        # 3. Create EpisodeMetadata object to regenerate info.md and tags
        meta = EpisodeMetadata(
            message_id=ep_data.get("message_id", 0),
            channel_name=ep_data.get("channel_name", "Podcast"),
            channel_username=ep_data.get("channel_username"),
            date=None,
            title=new_title,
            artist=new_artist,
            duration=ep_data.get("duration_seconds", 0),
            file_size=ep_data.get("file_size_bytes", 0),
            caption=new_caption,
            audio_filename=ep_data.get("audio_filename", "audio.mp3"),
            episode_number=new_ep_num
        )
        meta.series_title = new_series
        meta.save_info(folder, cover_filename="cover.jpg" if cover_path.exists() else None)

        # 4. Embed updated tags & album cover into audio file
        audio_files = list(folder.glob("audio.*")) + list(folder.glob("*.mp3")) + list(folder.glob("*.m4a"))
        if audio_files:
            embed_audio_tags(audio_files[0], meta, cover_path if cover_path.exists() else None)

        # 5. Rebuild series catalog README.md and feed.xml
        series_dir = folder.parent.parent
        build_channel_catalog(series_dir, channel_title=series_dir.name)

        self.statusBar().showMessage("✅ Episode metadata, ID3 tags, and catalog updated successfully!")
        QMessageBox.information(
            self,
            "Saved",
            f"Successfully updated '{new_title}'!\n\n• info.json & info.md rewritten\n• Audio ID3 tags updated\n• Catalog & RSS feed refreshed"
        )

        # Refresh List Display
        self.populate_episode_list(self.current_episodes)
        self.episode_list.setCurrentRow(self.selected_ep_index)

    # =========================================================================
    # Git Sync Actions
    # =========================================================================
    def quick_git_push(self):
        commit_msg = f"Update podcast metadata: {self.title_input.text() or 'episodes'}"
        self.run_git_task(commit_msg)

    def sync_all_to_github(self):
        remote_url = self.git_url_input.text().strip()
        if remote_url:
            self.cfg.update(GIT_REMOTE_URL=remote_url)
        self.run_git_task("Sync podcast archive and catalogs to GitHub")

    def run_git_task(self, commit_msg: str):
        self.statusBar().showMessage("Git: Committing and pushing to GitHub...")
        
        def worker():
            git_mgr = GitManager(self.cfg.root_dir, push_audio=self.cfg.git_push_audio, remote_url=self.cfg.git_remote_url)
            git_mgr.init_repo()
            if self.cfg.git_remote_url:
                git_mgr.set_remote_url(self.cfg.git_remote_url)

            ok, c_msg = git_mgr.commit_all(commit_msg)
            if not git_mgr.get_remote_url():
                return ok, f"{c_msg}\n(Set your GitHub remote URL in Downloader Tab to push to remote)."

            p_ok, p_msg = git_mgr.push()
            return p_ok, f"{c_msg}\n{p_msg}"

        threading.Thread(target=lambda: self.on_git_finished(*worker()), daemon=True).start()

    def on_git_finished(self, success: bool, msg: str):
        self.statusBar().showMessage("Git task finished.")
        if success:
            QMessageBox.information(self, "Git Result", msg)
        else:
            QMessageBox.warning(self, "Git Result", msg)

    def rebuild_all_catalogs(self):
        out_dir = self.cfg.output_dir
        count = 0
        if out_dir.exists():
            for item in out_dir.iterdir():
                if item.is_dir() and (item / "episodes").exists():
                    build_channel_catalog(item, channel_title=item.name)
                    count += 1
        QMessageBox.information(self, "Catalogs Rebuilt", f"Rebuilt README.md & feed.xml for {count} series!")


def main():
    app = QApplication(sys.argv)
    window = PodcastStudioGUI()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

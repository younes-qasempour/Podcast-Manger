import sys
import os
import json
import time
import asyncio
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any, Set
from collections import Counter

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QTextEdit,
    QProgressBar, QGroupBox, QCheckBox, QMessageBox, QSplitter,
    QListWidget, QListWidgetItem, QTabWidget, QComboBox, QFormLayout,
    QSpinBox, QFrame, QScrollArea, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView
)
from PyQt6.QtCore import pyqtSignal, QObject, Qt, QSize
from PyQt6.QtGui import QFont, QIcon, QPixmap, QColor
from PIL import Image

from config import Config
from downloader import PodcastDownloader
from git_manager import GitManager
from metadata_manager import (
    EpisodeMetadata, embed_audio_tags, build_channel_catalog
)
from utils import (
    sanitize_filename, format_duration, format_size,
    extract_hashtags, clean_for_terminal
)


# =============================================================================
# Background Worker Signals for Thread Safety
# =============================================================================
class DownloaderSignals(QObject):
    log = pyqtSignal(str)
    scan_finished = pyqtSignal(list, dict, str)  # all_podcasts, series_dict, channel_title
    overall_progress = pyqtSignal(int, int)       # current_ep_idx, total_eps
    file_progress = pyqtSignal(int, int, str)     # current_bytes, total_bytes, status_text
    episode_finished = pyqtSignal(int, str)       # episode index, folder name
    download_all_finished = pyqtSignal(bool, str) # success, message


class GitSignals(QObject):
    log = pyqtSignal(str)
    finished = pyqtSignal(bool, str)


# =============================================================================
# Main GUI Window
# =============================================================================
class PodcastStudioGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = Config()

        # Library State
        self.current_library_episodes: List[Dict[str, Any]] = []
        self.selected_lib_index = -1
        self.pending_new_cover_path: Optional[Path] = None

        # Downloader State
        self.downloader: Optional[PodcastDownloader] = None
        self.scanned_podcasts: List[Dict[str, Any]] = []
        self.series_groups: Dict[str, List[Dict[str, Any]]] = {}
        self.is_download_running = False
        self.cancel_download = False

        self.init_ui()
        self.load_library_series_list()

    def init_ui(self):
        self.setWindowTitle("🎙️ Telegram Podcast Studio & Downloader")
        self.resize(1180, 820)
        self.setMinimumSize(950, 680)

        # Dark modern theme with smooth contrast and clean Persian typography
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
                padding: 11px 26px;
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
            QTableWidget {
                background-color: #181825;
                border: 1px solid #313244;
                border-radius: 8px;
                gridline-color: #313244;
                selection-background-color: #45475a;
            }
            QHeaderView::section {
                background-color: #1e1e2e;
                color: #89b4fa;
                font-weight: bold;
                padding: 6px;
                border: 1px solid #313244;
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
            QPushButton#actionBtn {
                background-color: #a6e3a1;
                color: #11111b;
                font-size: 14px;
                padding: 10px 20px;
            }
            QPushButton#actionBtn:hover {
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
            QPushButton#cancelBtn {
                background-color: #f38ba8;
                color: #11111b;
            }
            QPushButton#cancelBtn:hover {
                background-color: #eba0ac;
            }
            QPushButton#secondaryBtn {
                background-color: #45475a;
                color: #cdd6f4;
            }
            QPushButton#secondaryBtn:hover {
                background-color: #585b70;
            }
            QProgressBar {
                border: 1px solid #45475a;
                border-radius: 5px;
                text-align: center;
                background-color: #313244;
                font-weight: bold;
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

        # TAB 1: Library & Studio
        self.library_tab = QWidget()
        self.init_library_tab()
        self.tabs.addTab(self.library_tab, "📚 Podcast Library & Studio")

        # TAB 2: Downloader
        self.downloader_tab = QWidget()
        self.init_downloader_tab()
        self.tabs.addTab(self.downloader_tab, "📥 Telegram Downloader")

        # TAB 3: Git & Settings
        self.settings_tab = QWidget()
        self.init_settings_tab()
        self.tabs.addTab(self.settings_tab, "🐙 GitHub Sync & Settings")

        # Status Bar
        self.statusBar().showMessage("Ready.")

    # =========================================================================
    # TAB 1: Library & Studio (Explorer, Info Editor, Thumbnail Customizer)
    # =========================================================================
    def init_library_tab(self):
        layout = QVBoxLayout(self.library_tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Top Bar: Series selection & search
        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel("Series:"))
        self.lib_series_combo = QComboBox()
        self.lib_series_combo.setMinimumWidth(220)
        self.lib_series_combo.currentIndexChanged.connect(self.on_library_series_selected)
        top_bar.addWidget(self.lib_series_combo)

        top_bar.addSpacing(15)
        top_bar.addWidget(QLabel("🔍 Search:"))
        self.lib_search_input = QLineEdit()
        self.lib_search_input.setPlaceholderText("Search by episode #, title, or notes...")
        self.lib_search_input.textChanged.connect(self.filter_library_episodes)
        top_bar.addWidget(self.lib_search_input)

        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.setObjectName("secondaryBtn")
        refresh_btn.clicked.connect(self.load_library_series_list)
        top_bar.addWidget(refresh_btn)

        open_folder_btn = QPushButton("📂 Open Folder")
        open_folder_btn.setObjectName("secondaryBtn")
        open_folder_btn.clicked.connect(self.open_current_series_folder)
        top_bar.addWidget(open_folder_btn)

        layout.addLayout(top_bar)

        # Splitter: Left = Episode List, Right = Metadata & Cover Editor
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(8)

        # Left: Episode List
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.lib_count_label = QLabel("Episodes: 0")
        self.lib_count_label.setStyleSheet("color: #a6adc8; font-weight: bold;")
        left_layout.addWidget(self.lib_count_label)

        self.lib_episode_list = QListWidget()
        self.lib_episode_list.setIconSize(QSize(48, 48))
        self.lib_episode_list.currentRowChanged.connect(self.on_library_episode_clicked)
        left_layout.addWidget(self.lib_episode_list)
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

        reset_cover_btn = QPushButton("🗑️ Reset Thumbnail")
        reset_cover_btn.setObjectName("secondaryBtn")
        reset_cover_btn.clicked.connect(self.reset_cover)
        art_btn_layout.addWidget(reset_cover_btn)

        art_btn_layout.addSpacing(10)

        self.play_audio_btn = QPushButton("▶️ Play Audio Track")
        self.play_audio_btn.setObjectName("playBtn")
        self.play_audio_btn.clicked.connect(self.play_audio_file)
        art_btn_layout.addWidget(self.play_audio_btn)

        self.open_ep_folder_btn = QPushButton("📁 Open Episode Folder")
        self.open_ep_folder_btn.setObjectName("secondaryBtn")
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

        # Save Button
        action_bar = QHBoxLayout()
        action_bar.setSpacing(12)

        self.save_btn = QPushButton("💾 Save Changes (Update Tags, Notes & Catalog)")
        self.save_btn.setObjectName("actionBtn")
        self.save_btn.clicked.connect(self.save_episode_changes)
        action_bar.addWidget(self.save_btn)

        right_layout.addLayout(action_bar)
        right_layout.addStretch()

        right_scroll.setWidget(right_widget)
        splitter.addWidget(right_scroll)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 5)
        layout.addWidget(splitter)

    # =========================================================================
    # TAB 2: Downloader (Scan, Series Picker, Checklist, Live Download)
    # =========================================================================
    def init_downloader_tab(self):
        layout = QVBoxLayout(self.downloader_tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Connection Row
        conn_box = QGroupBox("1. Telegram Channel Connection")
        conn_layout = QHBoxLayout(conn_box)

        conn_layout.addWidget(QLabel("Target Channel:"))
        self.dl_channel_input = QLineEdit(self.cfg.target_channel)
        self.dl_channel_input.setPlaceholderText("@agrafoss or https://t.me/agrafoss")
        conn_layout.addWidget(self.dl_channel_input)

        self.scan_btn = QPushButton("🔗 Scan Channel Podcasts")
        self.scan_btn.clicked.connect(self.start_channel_scan)
        conn_layout.addWidget(self.scan_btn)

        self.account_badge = QLabel("⚪ Not scanned yet")
        self.account_badge.setStyleSheet("color: #a6adc8; font-weight: bold; margin-left: 10px;")
        conn_layout.addWidget(self.account_badge)

        layout.addWidget(conn_box)

        # Series Filter Row
        series_filter_box = QHBoxLayout()
        series_filter_box.addWidget(QLabel("📚 Filter by Series / Hashtag:"))
        self.dl_series_combo = QComboBox()
        self.dl_series_combo.setMinimumWidth(260)
        self.dl_series_combo.currentIndexChanged.connect(self.on_dl_series_changed)
        series_filter_box.addWidget(self.dl_series_combo)

        series_filter_box.addSpacing(20)

        # Selection Helpers
        select_all_btn = QPushButton("☑️ Select All")
        select_all_btn.setObjectName("secondaryBtn")
        select_all_btn.clicked.connect(lambda: self.set_table_selection(True))
        series_filter_box.addWidget(select_all_btn)

        deselect_btn = QPushButton("☐ Deselect All")
        deselect_btn.setObjectName("secondaryBtn")
        deselect_btn.clicked.connect(lambda: self.set_table_selection(False))
        series_filter_box.addWidget(deselect_btn)

        select_latest5_btn = QPushButton("✨ Latest 5")
        select_latest5_btn.setObjectName("secondaryBtn")
        select_latest5_btn.clicked.connect(lambda: self.select_latest_n(5))
        series_filter_box.addWidget(select_latest5_btn)

        select_undownloaded_btn = QPushButton("🔄 Un-downloaded Only")
        select_undownloaded_btn.setObjectName("secondaryBtn")
        select_undownloaded_btn.clicked.connect(self.select_undownloaded_only)
        series_filter_box.addWidget(select_undownloaded_btn)

        series_filter_box.addStretch()
        layout.addLayout(series_filter_box)

        # Episodes Table
        self.ep_table = QTableWidget()
        self.ep_table.setColumnCount(5)
        self.ep_table.setHorizontalHeaderLabels(["Download", "Ep #", "Title", "Duration", "Size"])
        self.ep_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.ep_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.ep_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.ep_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.ep_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.ep_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.ep_table.setAlternatingRowColors(True)
        self.ep_table.cellClicked.connect(self.on_table_cell_clicked)
        layout.addWidget(self.ep_table)

        # Progress & Action Controls
        control_box = QVBoxLayout()

        prog_row = QHBoxLayout()
        self.overall_label = QLabel("Overall Progress:")
        self.overall_label.setStyleSheet("font-weight: bold; color: #89b4fa;")
        self.overall_bar = QProgressBar()
        self.overall_bar.setValue(0)
        prog_row.addWidget(self.overall_label)
        prog_row.addWidget(self.overall_bar)
        control_box.addLayout(prog_row)

        file_prog_row = QHBoxLayout()
        self.file_label = QLabel("Current File:")
        self.file_label.setStyleSheet("color: #a6adc8;")
        self.file_bar = QProgressBar()
        self.file_bar.setValue(0)
        file_prog_row.addWidget(self.file_label)
        file_prog_row.addWidget(self.file_bar)
        control_box.addLayout(file_prog_row)

        # Big Download Button
        action_row = QHBoxLayout()
        self.download_btn = QPushButton("📥 Download Selected Episodes")
        self.download_btn.setObjectName("actionBtn")
        self.download_btn.clicked.connect(self.start_downloading_selected)
        action_row.addWidget(self.download_btn)

        self.cancel_btn = QPushButton("⛔ Cancel")
        self.cancel_btn.setObjectName("cancelBtn")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.on_cancel_download)
        action_row.addWidget(self.cancel_btn)

        control_box.addLayout(action_row)
        layout.addLayout(control_box)

        # Downloader Log Box
        self.dl_log_text = QTextEdit()
        self.dl_log_text.setMaximumHeight(110)
        self.dl_log_text.setReadOnly(True)
        layout.addWidget(self.dl_log_text)

    # =========================================================================
    # TAB 3: Git & Sync Settings
    # =========================================================================
    def init_settings_tab(self):
        layout = QVBoxLayout(self.settings_tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        title = QLabel("🐙 GitHub Sync & Storage Settings")
        title.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        title.setStyleSheet("color: #89b4fa;")
        layout.addWidget(title)

        sett_box = QGroupBox("GitHub Configuration")
        sett_layout = QFormLayout(sett_box)
        sett_layout.setSpacing(10)

        self.git_url_input = QLineEdit(self.cfg.git_remote_url)
        self.git_url_input.setPlaceholderText("https://github.com/username/my-podcast-archive.git")
        sett_layout.addRow("GitHub Remote URL:", self.git_url_input)

        self.git_commit_input = QLineEdit("Update podcast archive: Notes, covers, and catalogs")
        sett_layout.addRow("Default Commit Message:", self.git_commit_input)

        self.out_dir_display = QLineEdit(str(self.cfg.output_dir))
        self.out_dir_display.setReadOnly(True)
        sett_layout.addRow("Podcasts Output Folder:", self.out_dir_display)

        layout.addWidget(sett_box)

        btn_box = QHBoxLayout()
        sync_git_btn = QPushButton("🚀 Commit & Push Entire Archive to GitHub")
        sync_git_btn.setObjectName("gitBtn")
        sync_git_btn.clicked.connect(self.sync_all_to_github)
        btn_box.addWidget(sync_git_btn)

        rebuild_cat_btn = QPushButton("📚 Rebuild All Catalogs (README & RSS)")
        rebuild_cat_btn.clicked.connect(self.rebuild_all_catalogs)
        btn_box.addWidget(rebuild_cat_btn)

        layout.addLayout(btn_box)

        log_box = QGroupBox("Git Sync Console")
        log_layout = QVBoxLayout(log_box)
        self.git_log_text = QTextEdit()
        self.git_log_text.setReadOnly(True)
        log_layout.addWidget(self.git_log_text)
        layout.addWidget(log_box)

        layout.addStretch()

    # =========================================================================
    # Downloader Logic (Scanning Channel & Populating Table)
    # =========================================================================
    def log_dl(self, text: str):
        self.dl_log_text.append(text)
        self.dl_log_text.verticalScrollBar().setValue(self.dl_log_text.verticalScrollBar().maximum())

    def start_channel_scan(self):
        target = self.dl_channel_input.text().strip() or self.cfg.target_channel
        self.cfg.update(TARGET_CHANNEL=target)

        self.scan_btn.setEnabled(False)
        self.account_badge.setText("⏳ Connecting & scanning...")
        self.log_dl(f"Connecting to Telegram for target: {target}...")

        self.dl_signals = DownloaderSignals()
        self.dl_signals.log.connect(self.log_dl)
        self.dl_signals.scan_finished.connect(self.on_channel_scanned)

        def worker():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                dl = PodcastDownloader(self.cfg)
                self.downloader = dl
                loop.run_until_complete(dl.connect())
                loop.run_until_complete(dl.resolve_channel())
                podcasts = loop.run_until_complete(dl.scan_podcasts())

                # Analyze series hashtags
                series_map: Dict[str, List[Dict[str, Any]]] = {}
                for item in podcasts:
                    m = item["metadata"]
                    tags = extract_hashtags(m.caption) + extract_hashtags(m.title)
                    main_tag = tags[0] if tags else "Other"
                    if main_tag not in series_map:
                        series_map[main_tag] = []
                    series_map[main_tag].append(item)

                self.dl_signals.scan_finished.emit(podcasts, series_map, dl.channel_title)
            except Exception as e:
                self.dl_signals.log.emit(f"❌ Scan failed: {e}")
                self.dl_signals.scan_finished.emit([], {}, "")
            finally:
                loop.close()

        threading.Thread(target=worker, daemon=True).start()

    def on_channel_scanned(self, podcasts: list, series_map: dict, channel_title: str):
        self.scan_btn.setEnabled(True)
        if not podcasts:
            self.account_badge.setText("❌ Scan failed or no podcasts found")
            return

        self.scanned_podcasts = podcasts
        self.series_groups = series_map
        self.account_badge.setText(f"✅ {channel_title} ({len(podcasts)} episodes)")
        self.log_dl(f"Scan complete: Found {len(podcasts)} episodes across {len(series_map)} series.")

        # Populate Series Dropdown
        self.dl_series_combo.blockSignals(True)
        self.dl_series_combo.clear()
        self.dl_series_combo.addItem(f"All Episodes ({len(podcasts)} tracks)", userData="ALL")

        # Sort series by count descending
        sorted_series = sorted(series_map.items(), key=lambda x: len(x[1]), reverse=True)
        for tag, items in sorted_series:
            self.dl_series_combo.addItem(f"{tag} ({len(items)} episodes)", userData=tag)

        self.dl_series_combo.blockSignals(False)
        self.on_dl_series_changed(0)

    def on_dl_series_changed(self, index: int):
        data = self.dl_series_combo.currentData()
        if not data:
            return

        if data == "ALL":
            active_list = self.scanned_podcasts
        else:
            active_list = self.series_groups.get(data, [])

        # Sort episodes ascending by episode number (1, 2, ... 92)
        def ep_key(item):
            num = item["metadata"].episode_number
            return (0, num) if num is not None else (1, item["metadata"].message_id)

        sorted_list = sorted(active_list, key=ep_key)
        self.populate_downloader_table(sorted_list)

    def populate_downloader_table(self, items: List[Dict[str, Any]]):
        self.ep_table.setRowCount(len(items))

        # Check existing series folder
        active_series = self.dl_series_combo.currentData()
        series_clean = sanitize_filename(active_series.lstrip("#") if active_series and active_series != "ALL" else (self.downloader.channel_title if self.downloader else "podcasts"), max_length=50)
        series_dir = self.cfg.output_dir / series_clean

        for row, item in enumerate(items):
            m: EpisodeMetadata = item["metadata"]
            
            # Check if downloaded locally
            ep_folder = series_dir / "episodes" / m.folder_name
            is_downloaded = (ep_folder / "audio.mp3").exists()

            # Checkbox item
            chk_item = QTableWidgetItem()
            chk_item.setCheckState(Qt.CheckState.Unchecked if is_downloaded else Qt.CheckState.Checked)
            chk_item.setData(Qt.ItemDataRole.UserRole, item)
            self.ep_table.setItem(row, 0, chk_item)

            # Ep number
            ep_str = f"Ep #{m.episode_number:03d}" if m.episode_number is not None else "No Ep#"
            ep_item = QTableWidgetItem(ep_str)
            ep_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.ep_table.setItem(row, 1, ep_item)

            # Title + Status
            status_tag = " [✅ Saved]" if is_downloaded else ""
            title_item = QTableWidgetItem(f"{m.title}{status_tag}")
            if is_downloaded:
                title_item.setForeground(QColor("#a6e3a1"))
            self.ep_table.setItem(row, 2, title_item)

            # Duration
            dur_item = QTableWidgetItem(m.duration_formatted)
            dur_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.ep_table.setItem(row, 3, dur_item)

            # File Size
            size_item = QTableWidgetItem(m.file_size_formatted)
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.ep_table.setItem(row, 4, size_item)

    def on_table_cell_clicked(self, row: int, col: int):
        # Toggle checkbox on row click
        item = self.ep_table.item(row, 0)
        if item and col != 0:
            new_state = Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked
            item.setCheckState(new_state)

    def set_table_selection(self, select: bool):
        for r in range(self.ep_table.rowCount()):
            item = self.ep_table.item(r, 0)
            if item:
                item.setCheckState(Qt.CheckState.Checked if select else Qt.CheckState.Unchecked)

    def select_latest_n(self, n: int):
        self.set_table_selection(False)
        total = self.ep_table.rowCount()
        start = max(0, total - n)
        for r in range(start, total):
            item = self.ep_table.item(r, 0)
            if item:
                item.setCheckState(Qt.CheckState.Checked)

    def select_undownloaded_only(self):
        for r in range(self.ep_table.rowCount()):
            chk_item = self.ep_table.item(r, 0)
            title_item = self.ep_table.item(r, 2)
            if chk_item and title_item:
                is_saved = "[✅ Saved]" in title_item.text()
                chk_item.setCheckState(Qt.CheckState.Unchecked if is_saved else Qt.CheckState.Checked)

    # =========================================================================
    # Download Execution
    # =========================================================================
    def start_downloading_selected(self):
        if self.is_download_running:
            return

        # Collect selected episodes
        selected_items = []
        for r in range(self.ep_table.rowCount()):
            item = self.ep_table.item(r, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                data = item.data(Qt.ItemDataRole.UserRole)
                if data:
                    selected_items.append(data)

        if not selected_items:
            QMessageBox.warning(self, "No Episodes Selected", "Please select at least one episode using the checkboxes.")
            return

        # Target Series Folder
        active_series = self.dl_series_combo.currentData()
        series_clean = sanitize_filename(
            active_series.lstrip("#") if active_series and active_series != "ALL" else (self.downloader.channel_title if self.downloader else "podcasts"),
            max_length=50
        )
        series_dir = self.cfg.output_dir / series_clean
        series_dir.mkdir(parents=True, exist_ok=True)

        self.is_download_running = True
        self.cancel_download = False
        self.download_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.overall_bar.setRange(0, len(selected_items))
        self.overall_bar.setValue(0)

        self.log_dl(f"\n🚀 Starting download of {len(selected_items)} episodes to: {series_dir.name}/")

        self.dl_signals = DownloaderSignals()
        self.dl_signals.log.connect(self.log_dl)
        self.dl_signals.overall_progress.connect(self.on_overall_progress)
        self.dl_signals.file_progress.connect(self.on_file_progress)
        self.dl_signals.download_all_finished.connect(self.on_download_finished)

        def worker():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                dl = self.downloader or PodcastDownloader(self.cfg)
                if not dl.client.is_connected():
                    loop.run_until_complete(dl.connect())

                for idx, ep_item in enumerate(selected_items, 1):
                    if self.cancel_download:
                        self.dl_signals.log.emit("🛑 Download cancelled by user.")
                        break

                    m = ep_item["metadata"]
                    self.dl_signals.overall_progress.emit(idx - 1, len(selected_items))
                    self.dl_signals.log.emit(f"[{idx}/{len(selected_items)}] Downloading: {m.title} ({m.file_size_formatted})...")

                    start_time = time.time()

                    def prog(cur, tot):
                        elapsed = time.time() - start_time
                        spd = cur / elapsed if elapsed > 0 else 0
                        pct = int((cur / tot) * 100) if tot > 0 else 0
                        txt = f"{pct}% | {format_size(cur)}/{format_size(tot)} | {format_size(int(spd))}/s"
                        self.dl_signals.file_progress.emit(cur, tot, txt)

                    loop.run_until_complete(dl.download_episode(ep_item, series_dir, on_progress=prog))

                # Rebuild catalog for series
                series_display_title = active_series if active_series and active_series != "ALL" else dl.channel_title
                build_channel_catalog(series_dir, channel_title=series_display_title)
                self.dl_signals.download_all_finished.emit(True, f"Finished downloading episodes to '{series_dir.name}'!")
            except Exception as e:
                self.dl_signals.download_all_finished.emit(False, str(e))
            finally:
                loop.close()

        threading.Thread(target=worker, daemon=True).start()

    def on_overall_progress(self, current: int, total: int):
        self.overall_bar.setValue(current)
        self.overall_label.setText(f"Overall Progress: [{current}/{total}]")

    def on_file_progress(self, current: int, total: int, status_text: str):
        self.file_bar.setRange(0, total if total > 0 else 100)
        self.file_bar.setValue(current)
        self.file_label.setText(f"Current File: {status_text}")

    def on_cancel_download(self):
        self.cancel_download = True
        self.cancel_btn.setEnabled(False)
        self.log_dl("Cancelling download after current chunk...")

    def on_download_finished(self, success: bool, msg: str):
        self.is_download_running = False
        self.download_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.overall_bar.setValue(self.overall_bar.maximum())
        self.file_bar.setValue(self.file_bar.maximum())

        if success:
            self.log_dl(f"🎉 {msg}")
            QMessageBox.information(
                self,
                "Download Complete",
                f"{msg}\n\n• Audio files saved & ID3 tagged\n• Catalog & RSS feed updated\n• Now visible in 'Podcast Library & Studio' tab!"
            )
            # Refresh Downloader Table status
            self.on_dl_series_changed(self.dl_series_combo.currentIndex())
            # Refresh Library Tab
            self.load_library_series_list()
        else:
            self.log_dl(f"❌ Error during download: {msg}")
            QMessageBox.critical(self, "Download Error", msg)

    # =========================================================================
    # Library Logic (Loading & Editing)
    # =========================================================================
    def load_library_series_list(self):
        self.lib_series_combo.blockSignals(True)
        self.lib_series_combo.clear()

        out_dir = self.cfg.output_dir
        if out_dir.exists():
            for item in sorted(out_dir.iterdir()):
                if item.is_dir() and (item / "episodes").exists():
                    self.lib_series_combo.addItem(f"📁 {item.name}", userData=str(item))

        self.lib_series_combo.blockSignals(False)

        if self.lib_series_combo.count() > 0:
            self.lib_series_combo.setCurrentIndex(0)
            self.load_episodes_for_series(Path(self.lib_series_combo.currentData()))
        else:
            self.lib_episode_list.clear()
            self.lib_count_label.setText("No downloaded series found yet in podcasts/.")

    def on_library_series_selected(self, index: int):
        data = self.lib_series_combo.currentData()
        if data:
            self.load_episodes_for_series(Path(data))

    def load_episodes_for_series(self, series_dir: Path):
        self.current_library_episodes.clear()
        self.lib_episode_list.clear()

        episodes_dir = series_dir / "episodes"
        if not episodes_dir.exists():
            return

        loaded_data = []
        for folder in episodes_dir.iterdir():
            if folder.is_dir():
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
                    loaded_data.append({
                        "title": folder.name,
                        "episode_number": None,
                        "duration_formatted": "-",
                        "file_size_formatted": "-",
                        "_folder_path": folder
                    })

        def sort_key(d):
            ep_num = d.get("episode_number")
            return (0, ep_num) if ep_num is not None else (1, d.get("title", ""))

        loaded_data.sort(key=sort_key)
        self.current_library_episodes = loaded_data

        self.populate_library_list(self.current_library_episodes)
        self.lib_count_label.setText(f"Episodes: {len(self.current_library_episodes)}")

        if self.current_library_episodes:
            self.lib_episode_list.setCurrentRow(0)

    def populate_library_list(self, ep_list: List[Dict[str, Any]]):
        self.lib_episode_list.clear()
        for ep in ep_list:
            ep_num = ep.get("episode_number")
            ep_badge = f"Ep #{ep_num:03d}" if ep_num is not None else "No Ep#"
            title = ep.get("title", "Untitled")
            dur = ep.get("duration_formatted", "-")
            size = ep.get("file_size_formatted", "-")

            item_text = f"{ep_badge} | {title}\n  ⏱ {dur}  •  💾 {size}"
            list_item = QListWidgetItem(item_text)

            folder = ep.get("_folder_path")
            cover_file = folder / "cover.jpg" if folder else None
            if cover_file and cover_file.exists():
                list_item.setIcon(QIcon(str(cover_file)))

            self.lib_episode_list.addItem(list_item)

    def filter_library_episodes(self, query: str):
        query = query.strip().lower()
        if not query:
            self.populate_library_list(self.current_library_episodes)
            return

        filtered = []
        for ep in self.current_library_episodes:
            title = ep.get("title", "").lower()
            caption = ep.get("caption", "").lower()
            ep_num = str(ep.get("episode_number") or "")
            if query in title or query in caption or query == ep_num:
                filtered.append(ep)

        self.populate_library_list(filtered)

    def on_library_episode_clicked(self, row: int):
        if row < 0 or row >= len(self.current_library_episodes):
            return

        self.selected_lib_index = row
        self.pending_new_cover_path = None
        data = self.current_library_episodes[row]

        self.ep_num_spin.setValue(data.get("episode_number") or 0)
        self.title_input.setText(data.get("title", ""))
        self.artist_input.setText(data.get("artist", ""))
        self.series_input.setText(data.get("series_title", ""))
        self.caption_edit.setPlainText(data.get("caption", ""))

        dur = data.get("duration_formatted", "-")
        size = data.get("file_size_formatted", "-")
        audio_name = data.get("audio_filename", "audio.mp3")
        self.file_info_label.setText(f"Duration: {dur}  |  Size: {size}  |  File: {audio_name}")

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
        if self.selected_lib_index < 0:
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
        if self.selected_lib_index < 0:
            return
        data = self.current_library_episodes[self.selected_lib_index]
        orig_cover = Path(data["_folder_path"]) / "cover.jpg"
        self.pending_new_cover_path = None
        self.display_cover(orig_cover if orig_cover.exists() else None)

    def play_audio_file(self):
        if self.selected_lib_index < 0:
            return
        data = self.current_library_episodes[self.selected_lib_index]
        folder = Path(data["_folder_path"])
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
        if self.selected_lib_index < 0:
            return
        folder = self.current_library_episodes[self.selected_lib_index]["_folder_path"]
        os.startfile(str(folder))

    def open_current_series_folder(self):
        data = self.lib_series_combo.currentData()
        if data:
            os.startfile(data)

    def save_episode_changes(self):
        if self.selected_lib_index < 0:
            return

        ep_data = self.current_library_episodes[self.selected_lib_index]
        folder = Path(ep_data["_folder_path"])

        new_ep_num = self.ep_num_spin.value() or None
        new_title = self.title_input.text().strip() or ep_data.get("title", "")
        new_artist = self.artist_input.text().strip() or ep_data.get("artist", "")
        new_series = self.series_input.text().strip() or ep_data.get("series_title", "")
        new_caption = self.caption_edit.toPlainText().strip()

        ep_data["episode_number"] = new_ep_num
        ep_data["title"] = new_title
        ep_data["artist"] = new_artist
        ep_data["series_title"] = new_series
        ep_data["caption"] = new_caption

        # 1. Update Thumbnail if picked
        cover_path = folder / "cover.jpg"
        if self.pending_new_cover_path and self.pending_new_cover_path.exists():
            try:
                with Image.open(self.pending_new_cover_path) as im:
                    rgb_im = im.convert("RGB")
                    rgb_im.save(cover_path, "JPEG", quality=92)
                self.pending_new_cover_path = None
            except Exception as e:
                QMessageBox.warning(self, "Thumbnail Warning", f"Could not process image: {e}")

        # 2. Save info.json
        with open(folder / "info.json", "w", encoding="utf-8") as f:
            to_save = {k: v for k, v in ep_data.items() if not k.startswith("_")}
            json.dump(to_save, f, ensure_ascii=False, indent=2)

        # 3. Save info.md
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

        # 4. Embed ID3 tags into audio
        audio_files = list(folder.glob("audio.*")) + list(folder.glob("*.mp3")) + list(folder.glob("*.m4a"))
        if audio_files:
            embed_audio_tags(audio_files[0], meta, cover_path if cover_path.exists() else None)

        # 5. Refresh Catalog README and RSS
        series_dir = folder.parent.parent
        build_channel_catalog(series_dir, channel_title=series_dir.name)

        self.statusBar().showMessage("✅ Episode metadata, ID3 tags, and catalog updated successfully!")
        QMessageBox.information(
            self,
            "Saved",
            f"Successfully updated '{new_title}'!\n\n• info.json & info.md rewritten\n• Audio ID3 tags updated\n• Catalog & RSS feed refreshed"
        )

        self.populate_library_list(self.current_library_episodes)
        self.lib_episode_list.setCurrentRow(self.selected_lib_index)

    # =========================================================================
    # Git Synchronization
    # =========================================================================
    def sync_all_to_github(self):
        remote_url = self.git_url_input.text().strip()
        commit_msg = self.git_commit_input.text().strip() or "Sync podcast archive and catalogs to GitHub"
        if remote_url:
            self.cfg.update(GIT_REMOTE_URL=remote_url)

        self.statusBar().showMessage("Git: Committing and pushing to GitHub...")
        self.git_log_text.append(f"Starting Git synchronization to {remote_url or 'local repo'}...")

        def worker():
            git_mgr = GitManager(self.cfg.root_dir, push_audio=self.cfg.git_push_audio, remote_url=self.cfg.git_remote_url)
            git_mgr.init_repo()
            if self.cfg.git_remote_url:
                git_mgr.set_remote_url(self.cfg.git_remote_url)

            ok, c_msg = git_mgr.commit_all(commit_msg)
            if not git_mgr.get_remote_url():
                return ok, f"{c_msg}\n(Set your GitHub remote URL to push to remote)."

            p_ok, p_msg = git_mgr.push()
            return p_ok, f"{c_msg}\n{p_msg}"

        threading.Thread(target=lambda: self.on_git_sync_done(*worker()), daemon=True).start()

    def on_git_sync_done(self, success: bool, msg: str):
        self.statusBar().showMessage("Git sync finished.")
        self.git_log_text.append(msg)
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

import sys
import os
import threading
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QTextEdit,
    QProgressBar, QGroupBox, QCheckBox, QMessageBox
)
from PyQt6.QtCore import pyqtSignal, QObject, Qt
from PyQt6.QtGui import QFont, QIcon

from config import Config
from export_organizer import TelegramExportOrganizer, find_recent_telegram_exports
from git_manager import GitManager
from metadata_manager import build_channel_catalog


class WorkerSignals(QObject):
    log = pyqtSignal(str)
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(bool, str)


class PodcastOrganizerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = Config()
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Telegram Podcast Organizer & GitHub Archiver")
        self.resize(850, 700)
        self.setStyleSheet("""
            QMainWindow { background-color: #1e1e2e; color: #cdd6f4; }
            QWidget { color: #cdd6f4; font-family: 'Segoe UI', Tahoma, sans-serif; font-size: 13px; }
            QGroupBox { border: 1px solid #45475a; border-radius: 8px; margin-top: 10px; font-weight: bold; padding: 12px; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: #89b4fa; }
            QLineEdit { background-color: #313244; border: 1px solid #45475a; border-radius: 5px; padding: 6px; color: #f5e0dc; }
            QLineEdit:focus { border: 1px solid #89b4fa; }
            QPushButton { background-color: #89b4fa; color: #11111b; font-weight: bold; border-radius: 6px; padding: 8px 15px; }
            QPushButton:hover { background-color: #b4befe; }
            QPushButton#actionBtn { background-color: #a6e3a1; color: #11111b; font-size: 14px; padding: 10px; }
            QPushButton#actionBtn:hover { background-color: #94e2d5; }
            QPushButton#pushBtn { background-color: #f9e2af; color: #11111b; font-size: 14px; padding: 10px; }
            QPushButton#pushBtn:hover { background-color: #fab387; }
            QTextEdit { background-color: #11111b; border: 1px solid #313244; border-radius: 6px; font-family: 'Consolas', monospace; font-size: 12px; color: #a6adc8; }
            QProgressBar { border: 1px solid #45475a; border-radius: 5px; text-align: center; background-color: #313244; }
            QProgressBar::chunk { background-color: #a6e3a1; border-radius: 4px; }
        """)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # Title Banner
        title_label = QLabel("🎙️ Telegram Podcast Organizer & GitHub Archiver")
        title_font = QFont("Segoe UI", 16, QFont.Weight.Bold)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #89b4fa; margin-bottom: 2px;")
        main_layout.addWidget(title_label)

        sub_label = QLabel("Zero-API Mode: Reads Telegram Desktop Chat Export (result.json / HTML), tags MP3s & pushes to Git.")
        sub_label.setStyleSheet("color: #a6adc8; margin-bottom: 8px;")
        main_layout.addWidget(sub_label)

        # Section 1: Telegram Export Folder
        export_group = QGroupBox("1. Telegram Desktop Export Folder")
        export_layout = QHBoxLayout(export_group)
        self.export_input = QLineEdit()
        self.export_input.setPlaceholderText("Path to ChatExport_... folder containing result.json")
        
        # Check for auto-detected export
        recents = find_recent_telegram_exports()
        if recents:
            self.export_input.setText(str(recents[0]))

        browse_export_btn = QPushButton("Browse...")
        browse_export_btn.clicked.connect(self.browse_export_folder)
        export_layout.addWidget(self.export_input)
        export_layout.addWidget(browse_export_btn)
        main_layout.addWidget(export_group)

        # Section 2: Output & GitHub Settings
        settings_group = QGroupBox("2. Archive & GitHub Settings")
        settings_layout = QVBoxLayout(settings_group)

        # Output folder row
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Output Folder:"))
        self.output_input = QLineEdit(str(self.cfg.output_dir))
        browse_out_btn = QPushButton("Browse...")
        browse_out_btn.clicked.connect(self.browse_output_folder)
        out_row.addWidget(self.output_input)
        out_row.addWidget(browse_out_btn)
        settings_layout.addLayout(out_row)

        # GitHub URL row
        git_row = QHBoxLayout()
        git_row.addWidget(QLabel("GitHub Repo URL:"))
        self.git_input = QLineEdit(self.cfg.git_remote_url)
        self.git_input.setPlaceholderText("https://github.com/username/my-podcast-archive.git")
        git_row.addWidget(self.git_input)
        settings_layout.addLayout(git_row)

        # Commit message row
        commit_row = QHBoxLayout()
        commit_row.addWidget(QLabel("Commit Message:"))
        self.commit_input = QLineEdit("Archive update: Organize podcasts and update catalog")
        commit_row.addWidget(self.commit_input)
        settings_layout.addLayout(commit_row)

        main_layout.addWidget(settings_group)

        # Action Buttons Row
        action_layout = QHBoxLayout()
        self.organize_btn = QPushButton("📂 1. Organize & Tag Episodes")
        self.organize_btn.setObjectName("actionBtn")
        self.organize_btn.clicked.connect(self.start_organizing)

        self.push_btn = QPushButton("🚀 2. Commit & Push to GitHub")
        self.push_btn.setObjectName("pushBtn")
        self.push_btn.clicked.connect(self.start_git_push)

        action_layout.addWidget(self.organize_btn)
        action_layout.addWidget(self.push_btn)
        main_layout.addLayout(action_layout)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        # Section 3: Log Console
        log_group = QGroupBox("Console & Status Log")
        log_layout = QVBoxLayout(log_group)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        main_layout.addWidget(log_group)

        self.log("App ready. To begin: Export chat from Telegram Desktop (as JSON), select the folder above, and click 'Organize'.")

    def log(self, text: str):
        self.log_text.append(text)
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())

    def browse_export_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Telegram Export Directory")
        if folder:
            self.export_input.setText(folder)

    def browse_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if folder:
            self.output_input.setText(folder)

    def set_buttons_enabled(self, enabled: bool):
        self.organize_btn.setEnabled(enabled)
        self.push_btn.setEnabled(enabled)

    def start_organizing(self):
        export_path = Path(self.export_input.text().strip())
        if not export_path.exists():
            QMessageBox.critical(self, "Error", f"Export folder does not exist:\n{export_path}")
            return

        out_path = Path(self.output_input.text().strip())
        self.set_buttons_enabled(False)
        self.progress_bar.setRange(0, 0)  # indeterminate

        self.signals = WorkerSignals()
        self.signals.log.connect(self.log)
        self.signals.finished.connect(self.on_organize_finished)

        def worker():
            try:
                self.signals.log.emit(f"Scanning export: {export_path}")
                organizer = TelegramExportOrganizer(export_path, out_path, copy_files=True)
                episodes = organizer.process()
                self.signals.finished.emit(True, f"Successfully organized {len(episodes)} episodes!")
            except Exception as e:
                self.signals.finished.emit(False, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def on_organize_finished(self, success: bool, message: str):
        self.set_buttons_enabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100 if success else 0)
        if success:
            self.log(f"🎉 {message}")
            QMessageBox.information(self, "Complete", f"{message}\n\nYou can now click '2. Commit & Push to GitHub'!")
        else:
            self.log(f"❌ Error: {message}")
            QMessageBox.critical(self, "Error", f"Failed to organize:\n{message}")

    def start_git_push(self):
        repo_url = self.git_input.text().strip()
        commit_msg = self.commit_input.text().strip() or "Archive update"
        
        self.set_buttons_enabled(False)
        self.progress_bar.setRange(0, 0)

        self.signals = WorkerSignals()
        self.signals.log.connect(self.log)
        self.signals.finished.connect(self.on_push_finished)

        def worker():
            try:
                self.signals.log.emit("Initializing Git & checking repository...")
                git_mgr = GitManager(self.cfg.root_dir, push_audio=self.cfg.git_push_audio, remote_url=repo_url)
                git_mgr.init_repo()

                if repo_url:
                    git_mgr.set_remote_url(repo_url)
                    self.signals.log.emit(f"Set origin: {repo_url}")

                self.signals.log.emit("Staging files and committing...")
                ok, c_msg = git_mgr.commit_all(commit_msg)
                self.signals.log.emit(c_msg)

                if git_mgr.get_remote_url():
                    self.signals.log.emit("Pushing to GitHub...")
                    p_ok, p_msg = git_mgr.push()
                    self.signals.finished.emit(p_ok, p_msg)
                else:
                    self.signals.finished.emit(True, "Committed locally. (Enter GitHub URL to push).")

            except Exception as e:
                self.signals.finished.emit(False, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def on_push_finished(self, success: bool, message: str):
        self.set_buttons_enabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100 if success else 0)
        self.log(message)
        if success:
            QMessageBox.information(self, "Git Result", message)
        else:
            QMessageBox.warning(self, "Git Result", message)


def main():
    app = QApplication(sys.argv)
    window = PodcastOrganizerApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

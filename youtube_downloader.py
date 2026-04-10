"""
YouTube Batch Downloader - Apple Music Optimized
Requirements: pip install pyqt5 yt-dlp mutagen
Additional Requirements: FFmpeg and AtomicParsley must be in your PATH.
"""

import sys
import os
import socket
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QProgressBar,
    QFileDialog, QTextEdit, QGroupBox, QFrame, QPlainTextEdit
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject
import yt_dlp

socket.setdefaulttimeout(30)

# ─────────────────────────────────────────────
#  Worker – handles multiple downloads
# ─────────────────────────────────────────────
class DownloadWorker(QObject):
    progress = pyqtSignal(float, str)  # (percent, info)
    log      = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def __init__(self, urls: list, fmt: str, out_dir: str, quality: str):
        super().__init__()
        self.urls = urls
        self.fmt = fmt
        self.out_dir = out_dir
        self.quality = quality
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        total_urls = len(self.urls)
        
        for index, url in enumerate(self.urls):
            if self._cancelled:
                break
            
            self.log.emit(f"--- Starting {index+1}/{total_urls}: {url} ---")
            success = self._download_single(url, index, total_urls)
            if not success and total_urls == 1:
                return 

        if self._cancelled:
            self.finished.emit(False, "Batch cancelled.")
        else:
            self.finished.emit(True, f"✅ Batch complete! {total_urls} items processed.")

    def _download_single(self, url, index, total_count):
        def progress_hook(d):
            if self._cancelled:
                raise Exception("Cancelled")
            if d["status"] == "downloading":
                p = d.get("downloaded_bytes", 0) / d.get("total_bytes", 1) * 100
                global_pct = ((index + (p / 100)) / total_count) * 100
                speed = d.get("_speed_str", "").strip()
                self.progress.emit(global_pct, f"Item {index+1}/{total_count} | Speed: {speed}")

        template = os.path.join(self.out_dir, "%(title)s.%(ext)s")
        
        # Base Options for Apple Music Metadata & Quality
        ydl_opts = {
            "outtmpl": template,
            "progress_hooks": [progress_hook],
            "socket_timeout": 30,
            "retries": 3,
            "noplaylist": True,
            "quiet": True,
            "http_headers": {"User-Agent": "Mozilla/5.0"},
            "writethumbnail": True,  # Required for the "icon"
        }

        if self.fmt == "m4a (Apple Music)":
            # Downloads the best possible audio stream directly without re-encoding
            ydl_opts.update({
                "format": "bestaudio[ext=m4a]/bestaudio/best", 
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "m4a",
                    },
                    {
                        "key": "FFmpegMetadata", # Injects Artist, Album, Title
                        "add_metadata": True,
                    },
                    {
                        "key": "EmbedThumbnail", # Embeds the icon/album art
                    }
                ],
            })
        elif self.fmt == "mp3":
            kbps = self.quality.replace("k", "")
            ydl_opts.update({
                "format": "bestaudio/best",
                "postprocessors": [
                    {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": kbps},
                    {"key": "FFmpegMetadata", "add_metadata": True},
                    {"key": "EmbedThumbnail"}
                ],
            })
        else:
            # Video settings
            res_map = {"best": "bestvideo+bestaudio/best", "1080": "bestvideo[height<=1080]+bestaudio/best", 
                       "720": "bestvideo[height<=720]+bestaudio/best", "480": "bestvideo[height<=480]+bestaudio/best"}
            ydl_opts.update({
                "format": res_map.get(self.quality, res_map["best"]),
                "merge_output_format": "mp4",
                "postprocessors": [
                    {"key": "FFmpegMetadata", "add_metadata": True},
                    {"key": "EmbedThumbnail"}
                ]
            })

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                self.log.emit(f"✅ Finished: {info.get('title', 'Unknown')}")
            return True
        except Exception as e:
            self.log.emit(f"❌ Error on item {index+1}: {str(e)}")
            return False

# ─────────────────────────────────────────────
#  Main Window
# ─────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Apple Music Batch Downloader")
        self.setMinimumSize(750, 600)
        self._thread = None
        self._worker = None
        self._build_ui()
        self._apply_style()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 20, 20, 20)

        title = QLabel("📥 Apple Music Local Library Downloader")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)

        url_box = QGroupBox("Video URLs (One per line)")
        url_lay = QVBoxLayout(url_box)
        self.url_input = QPlainTextEdit()
        self.url_input.setPlaceholderText("Paste YouTube links here...")
        url_lay.addWidget(self.url_input)
        root.addWidget(url_box, 1)

        opts_lay = QHBoxLayout()
        
        self.fmt_combo = QComboBox()
        self.fmt_combo.addItems(["m4a (Apple Music)", "mp3", "mp4"])
        self.fmt_combo.currentTextChanged.connect(self._update_qual_list)
        
        self.qual_combo = QComboBox()
        self._update_qual_list("m4a (Apple Music)")

        self.dir_label = QLabel(os.path.expanduser("~/Downloads"))
        self.dir_label.setObjectName("dirLabel")
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self._browse)

        opts_lay.addWidget(QLabel("Format:"))
        opts_lay.addWidget(self.fmt_combo)
        opts_lay.addWidget(QLabel("Quality:"))
        opts_lay.addWidget(self.qual_combo)
        opts_lay.addWidget(self.dir_label, 1)
        opts_lay.addWidget(browse_btn)
        root.addLayout(opts_lay)

        self.progress_bar = QProgressBar()
        root.addWidget(self.progress_bar)
        self.status_label = QLabel("Idle")
        self.status_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self.status_label)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setFixedHeight(150)
        root.addWidget(self.log_area)

        btn_row = QHBoxLayout()
        self.download_btn = QPushButton("🚀 Start Batch")
        self.download_btn.setObjectName("downloadBtn")
        self.download_btn.clicked.connect(self._start_download)
        
        self.cancel_btn = QPushButton("Stop")
        self.cancel_btn.setObjectName("cancelBtn")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)

        btn_row.addWidget(self.download_btn)
        btn_row.addWidget(self.cancel_btn)
        root.addLayout(btn_row)

    def _update_qual_list(self, fmt):
        self.qual_combo.clear()
        if fmt == "m4a (Apple Music)":
            self.qual_combo.addItems(["Best (Lossless-approx)"])
        elif fmt == "mp4":
            self.qual_combo.addItems(["best", "1080", "720", "480"])
        else:
            self.qual_combo.addItems(["320k", "192k", "128k"])

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Save Folder", self.dir_label.text())
        if d: self.dir_label.setText(d)

    def _start_download(self):
        urls = [u.strip() for u in self.url_input.toPlainText().split('\n') if u.strip()]
        if not urls:
            self.log_area.append("⚠ Please enter at least one URL.")
            return

        self.download_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.log_area.clear()
        
        self._worker = DownloadWorker(urls, self.fmt_combo.currentText(), self.dir_label.text(), self.qual_combo.currentText())
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.log.connect(lambda m: self.log_area.append(m))
        self._worker.finished.connect(self._on_finished)
        self._thread.start()

    def _on_progress(self, pct, info):
        self.progress_bar.setValue(int(pct))
        self.status_label.setText(info)

    def _on_finished(self, success, msg):
        self.download_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.status_label.setText(msg)
        self._thread.quit()

    def _cancel(self):
        if self._worker: self._worker.cancel()

    def _apply_style(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #1e1e2e; color: #cdd6f4; font-family: 'Segoe UI'; }
            QLabel { color: #cdd6f4; }
            QLabel#title { font-size: 20px; font-weight: bold; color: #cba6f7; }
            QGroupBox { border: 1px solid #45475a; border-radius: 8px; color: #a6e3a1; margin-top: 10px; padding: 10px; }
            QPlainTextEdit, QTextEdit, QLineEdit { background-color: #313244; border: 1px solid #45475a; color: #cdd6f4; border-radius: 5px; }
            QPushButton { background-color: #45475a; color: white; padding: 8px; border-radius: 5px; font-weight: bold; }
            QPushButton#downloadBtn { background-color: #cba6f7; color: #1e1e2e; }
            QPushButton#cancelBtn { background-color: #f38ba8; color: #1e1e2e; }
            QProgressBar { border: 1px solid #45475a; border-radius: 5px; text-align: center; background: #313244; color: #1e1e2e; font-weight: bold; }
            QProgressBar::chunk { background-color: #a6e3a1; }
        """)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())
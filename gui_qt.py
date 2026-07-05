"""
gui_qt.py
YouTube 다운로더 GUI (PyQt6 + qdarkstyle 다크테마).

core/downloader.py 로직을 그대로 재사용. Tkinter 버전(gui_tkinter.py)과
동일한 흐름/기능을 PyQt6 위젯으로 구현한 것.

설치 필요: pip install PyQt6 qdarkstyle (requirements.txt에 포함됨)
"""

from __future__ import annotations

import sys

import qdarkstyle
from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.downloader import (
    download_playlist,
    download_single,
    is_playlist_url,
    list_formats,
)

# 한글이 깨지지 않는 폰트로 통일 (Windows 기본 한글 폰트)
FONT_FAMILY = "Malgun Gothic"


# ---------------------------------------------------------------------------
# 백그라운드 작업용 워커 (스레드 안전하게 signal로 UI에 결과 전달)
# ---------------------------------------------------------------------------

class FetchWorker(QObject):
    done = pyqtSignal(str, list)
    error = pyqtSignal(str)

    def __init__(self, url: str):
        super().__init__()
        self.url = url

    def run(self):
        try:
            title, formats = list_formats(self.url)
            self.done.emit(title, formats)
        except Exception as e:
            self.error.emit(str(e))


class DownloadWorker(QObject):
    progress = pyqtSignal(float)
    log = pyqtSignal(str)
    done = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, url: str, audio_only: bool, format_id: str | None, playlist: bool):
        super().__init__()
        self.url = url
        self.audio_only = audio_only
        self.format_id = format_id
        self.playlist = playlist

    def _hook(self, d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes", 0)
            if total:
                self.progress.emit(downloaded / total * 100)
        elif d.get("status") == "finished":
            self.progress.emit(100)
            self.log.emit("다운로드된 파일 병합/후처리 중...")

    def run(self):
        try:
            if self.playlist:
                self.log.emit("재생목록 다운로드 시작...")
                download_playlist(
                    self.url,
                    audio_only=self.audio_only,
                    max_height=1080,
                    progress_hook=self._hook,
                )
            else:
                self.log.emit("다운로드 시작...")
                download_single(
                    self.url,
                    format_id=self.format_id,
                    audio_only=self.audio_only,
                    progress_hook=self._hook,
                )
            self.done.emit()
        except Exception as e:
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# 메인 윈도우
# ---------------------------------------------------------------------------

class YtdlQtGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YouTube 다운로더 (Qt)")
        self.setFixedSize(560, 520)

        self.formats = []
        self._fetch_thread = None
        self._download_thread = None

        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # URL 입력
        row_url = QHBoxLayout()
        row_url.addWidget(QLabel("URL"))
        self.url_edit = QLineEdit()
        row_url.addWidget(self.url_edit)
        self.fetch_btn = QPushButton("조회")
        self.fetch_btn.clicked.connect(self.on_fetch)
        row_url.addWidget(self.fetch_btn)
        layout.addLayout(row_url)

        # 영상/음원 선택
        row_type = QHBoxLayout()
        self.radio_video = QRadioButton("영상 (mp4)")
        self.radio_audio = QRadioButton("음원 (mp3)")
        self.radio_video.setChecked(True)
        row_type.addWidget(self.radio_video)
        row_type.addWidget(self.radio_audio)
        row_type.addStretch()
        layout.addLayout(row_type)

        # 상태 라벨
        self.status_label = QLabel("URL을 입력하고 조회를 눌러줘.")
        self.status_label.setStyleSheet("color: #555;")
        layout.addWidget(self.status_label)

        # 화질 목록
        self.format_list = QListWidget()
        self.format_list.setFont(self._mono_font())
        layout.addWidget(self.format_list, stretch=1)

        # 다운로드 버튼 + 진행률
        row_dl = QHBoxLayout()
        self.download_btn = QPushButton("다운로드")
        self.download_btn.setEnabled(False)
        self.download_btn.clicked.connect(self.on_download)
        row_dl.addWidget(self.download_btn)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        row_dl.addWidget(self.progress_bar, stretch=1)
        layout.addLayout(row_dl)

        # 로그창
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setFont(self._mono_font())
        self.log_edit.setFixedHeight(140)
        layout.addWidget(self.log_edit)

    @staticmethod
    def _mono_font():
        return QFont(FONT_FAMILY, 10)

    def _log(self, msg: str):
        self.log_edit.append(msg)

    # ------------------------------------------------------------------
    # 포맷 조회
    # ------------------------------------------------------------------
    def on_fetch(self):
        url = self.url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "입력 필요", "URL을 입력해줘.")
            return

        self.format_list.clear()
        self.download_btn.setEnabled(False)
        self.formats = []

        if is_playlist_url(url):
            self.status_label.setText("재생목록으로 인식됨. 1080p 이하 최고화질로 일괄 다운로드 진행돼.")
            self.download_btn.setEnabled(True)
            return

        self.status_label.setText("포맷 조회 중...")
        self.fetch_btn.setEnabled(False)

        self._fetch_thread = QThread()
        worker = FetchWorker(url)
        worker.moveToThread(self._fetch_thread)
        self._fetch_thread.started.connect(worker.run)
        worker.done.connect(self._on_fetch_done)
        worker.error.connect(self._on_fetch_error)
        worker.done.connect(self._fetch_thread.quit)
        worker.error.connect(self._fetch_thread.quit)
        self._fetch_thread.finished.connect(self._fetch_thread.deleteLater)
        self._fetch_worker = worker  # 참조 유지 (GC 방지)
        self._fetch_thread.start()

    def _on_fetch_done(self, title: str, formats: list):
        self.formats = formats
        for f in formats:
            self.format_list.addItem(f.label())
        self.status_label.setText(f"제목: {title}  (화질 선택 후 다운로드 눌러줘)")
        self.fetch_btn.setEnabled(True)
        self.download_btn.setEnabled(True)

    def _on_fetch_error(self, msg: str):
        self.status_label.setText("조회 실패")
        self._log(f"[에러] {msg}")
        self.fetch_btn.setEnabled(True)

    # ------------------------------------------------------------------
    # 다운로드
    # ------------------------------------------------------------------
    def on_download(self):
        url = self.url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "입력 필요", "URL을 입력해줘.")
            return

        audio_only = self.radio_audio.isChecked()
        playlist = is_playlist_url(url)

        format_id = None
        if not audio_only and not playlist and self.format_list.currentRow() >= 0:
            format_id = self.formats[self.format_list.currentRow()].format_id

        self.download_btn.setEnabled(False)
        self.fetch_btn.setEnabled(False)
        self.progress_bar.setValue(0)

        self._download_thread = QThread()
        worker = DownloadWorker(url, audio_only, format_id, playlist)
        worker.moveToThread(self._download_thread)
        self._download_thread.started.connect(worker.run)
        worker.progress.connect(lambda pct: self.progress_bar.setValue(int(pct)))
        worker.log.connect(self._log)
        worker.done.connect(self._on_download_done)
        worker.error.connect(self._on_download_error)
        worker.done.connect(self._download_thread.quit)
        worker.error.connect(self._download_thread.quit)
        self._download_thread.finished.connect(self._download_thread.deleteLater)
        self._download_worker = worker  # 참조 유지 (GC 방지)
        self._download_thread.start()

    def _on_download_done(self):
        self.status_label.setText("완료.")
        self._log("다운로드 완료.")
        self.download_btn.setEnabled(True)
        self.fetch_btn.setEnabled(True)

    def _on_download_error(self, msg: str):
        self.status_label.setText("다운로드 실패")
        self._log(f"[에러] {msg}")
        self.download_btn.setEnabled(True)
        self.fetch_btn.setEnabled(True)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setFont(QFont(FONT_FAMILY, 10))
    app.setStyleSheet(qdarkstyle.load_stylesheet(qt_api="pyqt6"))
    window = YtdlQtGUI()
    window.show()
    sys.exit(app.exec())

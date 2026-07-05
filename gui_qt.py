"""
gui_qt.py
YouTube 다운로더 GUI (PyQt6 + qdarkstyle 다크테마) - 큐(대기열) 방식.

- URL을 여러 줄 붙여넣으면 한번에 대기열에 쌓임 (화질은 1080p 이하 자동 정책: webm 우선 -> 30fps 우선)
- URL 한 줄만 입력하면 화질 후보를 직접 골라서 추가 가능
- 대기열은 순차 처리(동시 다운로드 없음), 실패 시 자동 재시도(최대 2회)
- 완료되면 대기열 카드에서 사라지고, 아래 "완료 내역" 표로 이동
- 완료 내역 표: 편집 불가, 우클릭으로 성공 항목은 "폴더 열기", 실패 항목은 "대기열에 다시 추가"
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path

import qdarkstyle
from PyQt6.QtCore import QObject, Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFont, QFontDatabase
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
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
    download_auto,
    download_playlist,
    download_single,
    is_playlist_url,
    list_formats,
)

MAX_RETRIES = 2  # 최초 시도 포함 총 3번 시도
RETRY_WAIT_SECONDS = 3


def _pick_korean_font() -> str:
    preferred = [
        "Malgun Gothic",
        "NanumGothic",
        "NanumGothicCoding",
        "Noto Sans CJK KR",
        "Noto Sans KR",
    ]
    available = set(QFontDatabase.families())
    for name in preferred:
        if name in available:
            return name
    return QApplication.font().family()


def _fmt_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f}{unit}"
        size /= 1024
    return f"{size:.0f}TB"


def _fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    if m:
        return f"{m}분 {s}초"
    return f"{s}초"


@dataclass
class QueueItem:
    id: int
    url: str
    audio_only: bool
    is_playlist: bool
    format_id: str | None
    label: str  # 화면 표시용 (처음엔 URL 일부 -> 다운로드 시작되면 영상 제목으로 갱신)
    status: str = "대기중"
    progress: float = 0.0


# ---------------------------------------------------------------------------
# 화질 선택 모달
# ---------------------------------------------------------------------------

class FormatChooserDialog(QDialog):
    def __init__(self, parent, title: str, formats: list):
        super().__init__(parent)
        self.setWindowTitle("화질 선택")
        self.setFixedSize(480, 380)
        self.chosen_format_id = None
        self.formats = formats

        layout = QVBoxLayout(self)
        title_label = QLabel(f"제목: {title}")
        title_label.setWordWrap(True)
        layout.addWidget(title_label)

        self.list_widget = QListWidget()
        for f in formats:
            self.list_widget.addItem(f.label())
        if formats:
            self.list_widget.setCurrentRow(0)
        layout.addWidget(self.list_widget)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("취소")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        confirm_btn = QPushButton("선택")
        confirm_btn.clicked.connect(self._on_confirm)
        btn_row.addWidget(confirm_btn)
        layout.addLayout(btn_row)

    def _on_confirm(self):
        row = self.list_widget.currentRow()
        if row < 0:
            QMessageBox.warning(self, "선택 필요", "화질을 선택해줘.")
            return
        self.chosen_format_id = self.formats[row].format_id
        self.accept()


# ---------------------------------------------------------------------------
# 백그라운드 워커
# ---------------------------------------------------------------------------

class FetchWorker(QObject):
    done = pyqtSignal(str, str, list)  # url, title, formats
    error = pyqtSignal(str)

    def __init__(self, url: str):
        super().__init__()
        self.url = url

    def run(self):
        try:
            title, formats = list_formats(self.url)
            self.done.emit(self.url, title, formats)
        except Exception as e:
            self.error.emit(str(e))


class QueueWorker(QObject):
    progress = pyqtSignal(int, float)  # item_id, pct
    title_known = pyqtSignal(int, str)  # item_id, 영상 제목
    item_started = pyqtSignal(int)
    item_retrying = pyqtSignal(int, int)  # item_id, 몇 번째 재시도인지
    item_done = pyqtSignal(int, dict)
    item_error = pyqtSignal(int, dict)
    all_idle = pyqtSignal()

    def __init__(self, get_next_item):
        super().__init__()
        self._get_next_item = get_next_item

    def _attempt_download(self, item: QueueItem, hook) -> dict:
        """한 번의 다운로드 시도. 성공하면 표에 넣을 info dict 반환, 실패하면 예외 발생."""
        start = time.time()
        if item.is_playlist:
            download_playlist(
                item.url, audio_only=item.audio_only, max_height=1080, progress_hook=hook
            )
            elapsed = time.time() - start
            return {
                "title": f"재생목록 ({item.label})",
                "quality": "1080p 이하 자동(webm/30fps 우선)",
                "size": "-",
                "path": "downloads/ (재생목록별 폴더)",
                "time_or_status": _fmt_duration(elapsed),
                "success": True,
            }
        elif item.format_id:
            result = download_single(
                item.url, format_id=item.format_id, audio_only=item.audio_only, progress_hook=hook
            )
            elapsed = time.time() - start
            return {
                "title": result["title"],
                "quality": "직접 선택",
                "size": _fmt_size(result["filesize"]),
                "path": result["filepath"],
                "time_or_status": _fmt_duration(elapsed),
                "success": True,
            }
        else:
            result = download_auto(
                item.url, audio_only=item.audio_only, max_height=1080, progress_hook=hook
            )
            elapsed = time.time() - start
            quality_label = "음원(mp3)" if item.audio_only else "1080p 이하 자동(webm/30fps 우선)"
            return {
                "title": result["title"],
                "quality": quality_label,
                "size": _fmt_size(result["filesize"]),
                "path": result["filepath"],
                "time_or_status": _fmt_duration(elapsed),
                "success": True,
            }

    def run(self):
        while True:
            item = self._get_next_item()
            if item is None:
                break

            self.item_started.emit(item.id)
            title_captured = False

            def hook(d, _id=item.id):
                nonlocal title_captured
                if d.get("status") == "downloading":
                    total = d.get("total_bytes") or d.get("total_bytes_estimate")
                    downloaded = d.get("downloaded_bytes", 0)
                    if total:
                        self.progress.emit(_id, downloaded / total * 100)
                    if not title_captured:
                        info_dict = d.get("info_dict") or {}
                        title = info_dict.get("title")
                        if title:
                            title_captured = True
                            self.title_known.emit(_id, title)

            last_exc = None
            for attempt in range(MAX_RETRIES + 1):
                try:
                    info = self._attempt_download(item, hook)
                    self.item_done.emit(item.id, info)
                    last_exc = None
                    break
                except Exception as e:
                    last_exc = e
                    if attempt < MAX_RETRIES:
                        self.item_retrying.emit(item.id, attempt + 1)
                        time.sleep(RETRY_WAIT_SECONDS)
                    continue

            if last_exc is not None:
                self.item_error.emit(item.id, {
                    "title": item.label, "quality": "-", "size": "-",
                    "path": "-", "time_or_status": f"실패({MAX_RETRIES + 1}회 시도): {last_exc}",
                    "success": False,
                })

        self.all_idle.emit()


# ---------------------------------------------------------------------------
# 완료 내역 카드 (표 대신 리스트 아이템 형태)
# ---------------------------------------------------------------------------

class CompletedItemWidget(QFrame):
    def __init__(self, info: dict, meta: dict, on_open_folder, on_retry):
        super().__init__()
        self.meta = meta

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        top_row = QHBoxLayout()
        icon = "✔" if info.get("success") else "✖"
        title_label = QLabel(f"{icon}  {info['title']}")
        title_label.setStyleSheet("font-weight: bold;")
        title_label.setWordWrap(True)
        top_row.addWidget(title_label, stretch=1)

        if info.get("success"):
            btn = QPushButton("폴더 열기")
            btn.clicked.connect(lambda: on_open_folder(meta["filepath"]))
        else:
            btn = QPushButton("다시 추가")
            btn.clicked.connect(lambda: on_retry(meta))
        top_row.addWidget(btn)
        layout.addLayout(top_row)

        if info.get("success"):
            subtitle = f"{info['quality']} · {info['size']} · {info['time_or_status']}"
        else:
            subtitle = info["time_or_status"]
        subtitle_label = QLabel(subtitle)
        subtitle_label.setStyleSheet("color: #999999; font-size: 11px;")
        subtitle_label.setWordWrap(True)
        layout.addWidget(subtitle_label)

        self.setFrameShape(QFrame.Shape.StyledPanel)


# ---------------------------------------------------------------------------
# 메인 윈도우
# ---------------------------------------------------------------------------

class YtdlQtGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YouTube 다운로더 (Qt)")
        self.setFixedSize(640, 700)

        self.items: dict[int, QueueItem] = {}
        self.pending_queue: list[int] = []
        self.is_processing = False
        self._item_counter = 0
        self._fetch_thread = None
        self._queue_thread = None

        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        layout.addWidget(QLabel("URL (한 줄만 입력 = 화질 직접 선택 / 여러 줄 = 1080p 이하 자동, webm·30fps 우선)"))

        self.url_edit = QTextEdit()
        self.url_edit.setFixedHeight(80)
        layout.addWidget(self.url_edit)

        row_add = QHBoxLayout()
        self.radio_video = QRadioButton("영상 (mp4)")
        self.radio_audio = QRadioButton("음원 (mp3)")
        self.radio_video.setChecked(True)
        row_add.addWidget(self.radio_video)
        row_add.addWidget(self.radio_audio)
        row_add.addStretch()
        self.add_btn = QPushButton("대기열에 추가")
        self.add_btn.clicked.connect(self.on_add)
        row_add.addWidget(self.add_btn)
        layout.addLayout(row_add)

        layout.addWidget(QLabel("대기열"))
        self.queue_list = QListWidget()
        self.queue_list.setFixedHeight(140)
        layout.addWidget(self.queue_list)

        self.current_progress = QProgressBar()
        self.current_progress.setRange(0, 100)
        layout.addWidget(self.current_progress)

        layout.addWidget(QLabel("완료 내역"))
        self.completed_list = QListWidget()
        self.completed_list.setSpacing(4)
        layout.addWidget(self.completed_list, stretch=1)

    # ------------------------------------------------------------------
    def _render_queue(self):
        self.queue_list.clear()
        active_ids = [iid for iid in self.pending_queue if self.items[iid].status != "완료"]
        if not active_ids:
            self.queue_list.addItem("대기열이 비어있어.")
            self.current_progress.setValue(0)
            return
        for iid in active_ids:
            item = self.items[iid]
            icon = "▶" if item.status.startswith(("다운로드중", "재시도중")) else "⏸"
            self.queue_list.addItem(f"{icon} {item.label}  [{item.status}]")

    # ------------------------------------------------------------------
    # URL 추가
    # ------------------------------------------------------------------
    def on_add(self):
        raw = self.url_edit.toPlainText().strip()
        if not raw:
            QMessageBox.warning(self, "입력 필요", "URL을 입력해줘.")
            return

        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if not lines:
            return

        audio_only = self.radio_audio.isChecked()

        if len(lines) == 1:
            self._add_single_with_choice(lines[0], audio_only)
        else:
            for url in lines:
                self._enqueue(url, audio_only, format_id=None, forced_auto=True)
            self.url_edit.clear()
            self._render_queue()
            self._start_processing_if_idle()

    def _add_single_with_choice(self, url: str, audio_only: bool):
        if audio_only or is_playlist_url(url):
            self._enqueue(url, audio_only, format_id=None, forced_auto=True)
            self.url_edit.clear()
            self._render_queue()
            self._start_processing_if_idle()
            return

        self.add_btn.setEnabled(False)
        self._fetch_thread = QThread()
        worker = FetchWorker(url)
        worker.moveToThread(self._fetch_thread)
        self._fetch_thread.started.connect(worker.run)
        worker.done.connect(self._on_fetch_done)
        worker.error.connect(self._on_fetch_error)
        worker.done.connect(self._fetch_thread.quit)
        worker.error.connect(self._fetch_thread.quit)
        self._fetch_thread.finished.connect(self._fetch_thread.deleteLater)
        self._fetch_worker = worker
        self._fetch_thread.start()

    def _on_fetch_done(self, url: str, title: str, formats: list):
        self.add_btn.setEnabled(True)
        if not formats:
            QMessageBox.warning(self, "조회 실패", "사용 가능한 화질을 찾지 못했어.")
            return
        dialog = FormatChooserDialog(self, title, formats)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.chosen_format_id:
            self._enqueue(
                url, self.radio_audio.isChecked(),
                format_id=dialog.chosen_format_id, forced_auto=False,
            )
            self.url_edit.clear()
            self._render_queue()
            self._start_processing_if_idle()

    def _on_fetch_error(self, msg: str):
        self.add_btn.setEnabled(True)
        QMessageBox.critical(self, "조회 실패", msg)

    def _enqueue(self, url: str, audio_only: bool, format_id: str | None, forced_auto: bool):
        self._item_counter += 1
        iid = self._item_counter
        playlist = is_playlist_url(url)
        label = url.split("v=")[-1][:20] if "v=" in url else url[-24:]
        item = QueueItem(
            id=iid,
            url=url,
            audio_only=audio_only,
            is_playlist=playlist,
            format_id=None if (forced_auto or playlist) else format_id,
            label=label,
        )
        self.items[iid] = item
        self.pending_queue.append(iid)

    # ------------------------------------------------------------------
    # 큐 순차 처리
    # ------------------------------------------------------------------
    def _get_next_item(self):
        for iid in self.pending_queue:
            if self.items[iid].status == "대기중":
                return self.items[iid]
        return None

    def _start_processing_if_idle(self):
        if self.is_processing:
            return
        self.is_processing = True
        self._queue_thread = QThread()
        worker = QueueWorker(self._get_next_item)
        worker.moveToThread(self._queue_thread)
        self._queue_thread.started.connect(worker.run)
        worker.item_started.connect(self._on_item_started)
        worker.title_known.connect(self._on_title_known)
        worker.progress.connect(self._on_progress)
        worker.item_retrying.connect(self._on_item_retrying)
        worker.item_done.connect(self._on_item_done)
        worker.item_error.connect(self._on_item_error)
        worker.all_idle.connect(self._on_all_idle)
        worker.all_idle.connect(self._queue_thread.quit)
        self._queue_thread.finished.connect(self._queue_thread.deleteLater)
        self._queue_worker = worker
        self._queue_thread.start()

    def _on_item_started(self, iid: int):
        self.items[iid].status = "다운로드중"
        self.current_progress.setValue(0)
        self._render_queue()

    def _on_title_known(self, iid: int, title: str):
        if iid in self.items:
            self.items[iid].label = title
            self._render_queue()

    def _on_progress(self, iid: int, pct: float):
        if iid in self.items:
            self.items[iid].progress = pct
            self.current_progress.setValue(int(pct))

    def _on_item_retrying(self, iid: int, attempt_no: int):
        if iid in self.items:
            self.items[iid].status = f"재시도중({attempt_no}/{MAX_RETRIES})"
            self._render_queue()

    def _add_completed_item(self, info: dict, item: QueueItem):
        meta = {
            "success": info.get("success", False),
            "filepath": info.get("path", ""),
            "url": item.url,
            "audio_only": item.audio_only,
            "format_id": item.format_id,
        }
        widget = CompletedItemWidget(info, meta, self._open_folder, self._retry_from_table)
        list_item = QListWidgetItem()
        list_item.setSizeHint(widget.sizeHint())
        self.completed_list.addItem(list_item)
        self.completed_list.setItemWidget(list_item, widget)

    def _on_item_done(self, iid: int, info: dict):
        self.items[iid].status = "완료"
        self._add_completed_item(info, self.items[iid])
        self._render_queue()

    def _on_item_error(self, iid: int, info: dict):
        self.items[iid].status = "완료"
        self._add_completed_item(info, self.items[iid])
        self._render_queue()

    def _on_all_idle(self):
        self.is_processing = False

    def _open_folder(self, filepath: str):
        folder = str(Path(filepath).parent) if filepath and filepath != "-" else "downloads"
        if not Path(folder).exists():
            QMessageBox.warning(self, "폴더 없음", f"경로를 찾을 수 없어: {folder}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _retry_from_table(self, meta: dict):
        self._enqueue(
            meta["url"], meta["audio_only"],
            format_id=meta["format_id"], forced_auto=(meta["format_id"] is None),
        )
        self._render_queue()
        self._start_processing_if_idle()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    korean_font = _pick_korean_font()
    app.setFont(QFont(korean_font, 10))
    app.setStyleSheet(qdarkstyle.load_stylesheet(qt_api="pyqt6"))
    window = YtdlQtGUI()
    window.show()
    sys.exit(app.exec())

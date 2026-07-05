"""
gui_tkinter.py
YouTube 다운로더 GUI (Tkinter + ttkbootstrap 다크테마) - 큐(대기열) 방식.

- URL을 여러 줄 붙여넣으면 한번에 대기열에 쌓임 (화질은 1080p 이하 자동 정책: webm 우선 -> 30fps 우선)
- URL 한 줄만 입력하면 화질 후보를 직접 골라서 추가 가능
- 대기열은 순차 처리(동시 다운로드 없음)
- 완료되면 대기열 카드에서 사라지고, 아래 "완료 내역" 표로 이동
"""

from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from tkinter import messagebox

import ttkbootstrap as ttk

from core.downloader import (
    download_auto,
    download_playlist,
    download_single,
    is_playlist_url,
    list_formats,
)

FONT_UI = None
FONT_MONO = None


def _pick_korean_font() -> str:
    preferred = [
        "Malgun Gothic",
        "NanumGothic",
        "NanumGothicCoding",
        "Noto Sans CJK KR",
        "Noto Sans KR",
    ]
    available = set(tkfont.families())
    for name in preferred:
        if name in available:
            return name
    return "TkDefaultFont"


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
    format_id: str | None  # 수동 선택 시에만 값 있음
    label: str  # 화면에 표시할 이름
    status: str = "대기중"  # 대기중 / 다운로드중 / 완료
    progress: float = 0.0


# ---------------------------------------------------------------------------
# 화질 선택 모달 (URL 한 줄만 추가할 때)
# ---------------------------------------------------------------------------

class FormatChooserDialog(ttk.Toplevel):
    def __init__(self, parent, title: str, formats: list):
        super().__init__(parent)
        self.title("화질 선택")
        self.geometry("480x360")
        self.resizable(False, False)
        self.chosen_format_id = None
        self.formats = formats

        ttk.Label(self, text=f"제목: {title}", font=FONT_UI, wraplength=440).pack(
            padx=10, pady=(10, 6), anchor="w"
        )

        self.listbox = tk.Listbox(self, font=FONT_MONO, bg="#222222", fg="#e8e8e8")
        self.listbox.pack(fill="both", expand=True, padx=10)
        for f in formats:
            self.listbox.insert("end", f.label())
        if formats:
            self.listbox.selection_set(0)

        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", padx=10, pady=10)
        ttk.Button(btn_row, text="선택", command=self._on_confirm, bootstyle="success").pack(
            side="right"
        )
        ttk.Button(btn_row, text="취소", command=self.destroy, bootstyle="secondary").pack(
            side="right", padx=(0, 8)
        )

        self.transient(parent)
        self.grab_set()

    def _on_confirm(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showwarning("선택 필요", "화질을 선택해줘.")
            return
        self.chosen_format_id = self.formats[sel[0]].format_id
        self.destroy()


# ---------------------------------------------------------------------------
# 메인 윈도우
# ---------------------------------------------------------------------------

class YtdlGUI(ttk.Window):
    def __init__(self):
        super().__init__(themename="darkly")
        self.title("YouTube 다운로더")
        self.geometry("640x680")
        self.resizable(False, False)

        global FONT_UI, FONT_MONO
        korean_font = _pick_korean_font()
        FONT_UI = (korean_font, 10)
        FONT_MONO = (korean_font, 10)
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(name).configure(family=korean_font, size=10)
            except tk.TclError:
                pass

        self.msg_queue: queue.Queue = queue.Queue()
        self.items: dict[int, QueueItem] = {}
        self.pending_queue: list[int] = []
        self.is_processing = False
        self._item_counter = 0

        self._build_widgets()
        self.after(100, self._poll_queue)

    # ------------------------------------------------------------------
    def _build_widgets(self):
        pad = {"padx": 10, "pady": 6}

        ttk.Label(
            self,
            text="URL (한 줄만 입력 = 화질 직접 선택 / 여러 줄 = 1080p 이하 자동, webm·30fps 우선)",
            font=FONT_UI,
            bootstyle="secondary",
        ).pack(fill="x", padx=10, pady=(10, 0), anchor="w")

        self.url_text = tk.Text(
            self, height=4, font=FONT_UI, bg="#222222", fg="#e8e8e8",
            insertbackground="#e8e8e8", highlightthickness=0, borderwidth=0,
        )
        self.url_text.pack(fill="x", padx=10, pady=(4, 6))

        row_add = ttk.Frame(self)
        row_add.pack(fill="x", **pad)
        self.audio_only_var = tk.BooleanVar(value=False)
        ttk.Radiobutton(row_add, text="영상 (mp4)", variable=self.audio_only_var, value=False).pack(
            side="left"
        )
        ttk.Radiobutton(row_add, text="음원 (mp3)", variable=self.audio_only_var, value=True).pack(
            side="left", padx=(10, 0)
        )
        self.add_btn = ttk.Button(
            row_add, text="대기열에 추가", command=self._on_add, bootstyle="primary"
        )
        self.add_btn.pack(side="right")

        ttk.Label(self, text="대기열", font=FONT_UI, bootstyle="secondary").pack(
            fill="x", padx=10, pady=(6, 0), anchor="w"
        )
        self.queue_frame = ttk.Frame(self)
        self.queue_frame.pack(fill="x", padx=10, pady=(4, 6))

        ttk.Label(self, text="완료 내역", font=FONT_UI, bootstyle="secondary").pack(
            fill="x", padx=10, pady=(6, 0), anchor="w"
        )
        columns = ("title", "quality", "size", "path", "time")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=10)
        self.tree.heading("title", text="제목")
        self.tree.heading("quality", text="화질")
        self.tree.heading("size", text="용량")
        self.tree.heading("path", text="저장 경로")
        self.tree.heading("time", text="소요시간/상태")
        self.tree.column("title", width=180)
        self.tree.column("quality", width=90)
        self.tree.column("size", width=70)
        self.tree.column("path", width=190)
        self.tree.column("time", width=90)
        self.tree.pack(fill="both", expand=True, padx=10, pady=(4, 10))

    # ------------------------------------------------------------------
    def _render_queue(self):
        for child in self.queue_frame.winfo_children():
            child.destroy()

        active_ids = [iid for iid in self.pending_queue if self.items[iid].status != "완료"]
        if not active_ids:
            ttk.Label(self.queue_frame, text="대기열이 비어있어.", font=FONT_UI, bootstyle="secondary").pack(
                anchor="w"
            )
            return

        for iid in active_ids:
            item = self.items[iid]
            card = ttk.Frame(self.queue_frame, bootstyle="secondary")
            card.pack(fill="x", pady=3)

            icon = "▶" if item.status == "다운로드중" else "⏸"
            top = ttk.Frame(card)
            top.pack(fill="x")
            ttk.Label(top, text=f"{icon} {item.label}", font=FONT_UI).pack(side="left")
            ttk.Label(top, text=f"[{item.status}]", font=FONT_UI, bootstyle="info").pack(side="right")

            if item.status == "다운로드중":
                pbar = ttk.Progressbar(card, mode="determinate", maximum=100, value=item.progress)
                pbar.pack(fill="x", pady=(2, 0))

    # ------------------------------------------------------------------
    # URL 추가
    # ------------------------------------------------------------------
    def _on_add(self):
        raw = self.url_text.get("1.0", "end").strip()
        if not raw:
            messagebox.showwarning("입력 필요", "URL을 입력해줘.")
            return

        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if not lines:
            return

        audio_only = self.audio_only_var.get()

        if len(lines) == 1:
            self._add_single_with_choice(lines[0], audio_only)
        else:
            for url in lines:
                self._enqueue(url, audio_only, format_id=None, forced_auto=True)
            self.url_text.delete("1.0", "end")
            self._render_queue()
            self._start_processing_if_idle()

    def _add_single_with_choice(self, url: str, audio_only: bool):
        if audio_only or is_playlist_url(url):
            self._enqueue(url, audio_only, format_id=None, forced_auto=True)
            self.url_text.delete("1.0", "end")
            self._render_queue()
            self._start_processing_if_idle()
            return

        self.add_btn.config(state="disabled")

        def worker():
            try:
                title, formats = list_formats(url)
                self.msg_queue.put(("show_chooser", url, title, formats))
            except Exception as e:
                self.msg_queue.put(("fetch_error", str(e)))

        threading.Thread(target=worker, daemon=True).start()

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
    def _start_processing_if_idle(self):
        if self.is_processing:
            return
        self.is_processing = True
        threading.Thread(target=self._process_queue_worker, daemon=True).start()

    def _process_queue_worker(self):
        while True:
            next_id = None
            for iid in self.pending_queue:
                if self.items[iid].status == "대기중":
                    next_id = iid
                    break
            if next_id is None:
                break

            item = self.items[next_id]
            item.status = "다운로드중"
            self.msg_queue.put(("refresh",))
            start = time.time()

            def hook(d, _id=next_id):
                if d.get("status") == "downloading":
                    total = d.get("total_bytes") or d.get("total_bytes_estimate")
                    downloaded = d.get("downloaded_bytes", 0)
                    if total:
                        self.msg_queue.put(("progress", _id, downloaded / total * 100))

            try:
                if item.is_playlist:
                    download_playlist(
                        item.url, audio_only=item.audio_only, max_height=1080, progress_hook=hook
                    )
                    elapsed = time.time() - start
                    self.msg_queue.put((
                        "done", next_id,
                        {"title": f"재생목록 ({item.label})",
                         "quality": "1080p 이하 자동(webm/30fps 우선)",
                         "size": "-",
                         "path": "downloads/ (재생목록별 폴더)",
                         "time_or_status": _fmt_duration(elapsed)},
                    ))
                elif item.format_id:
                    result = download_single(
                        item.url, format_id=item.format_id, audio_only=item.audio_only,
                        progress_hook=hook,
                    )
                    elapsed = time.time() - start
                    self.msg_queue.put((
                        "done", next_id,
                        {"title": result["title"],
                         "quality": "직접 선택",
                         "size": _fmt_size(result["filesize"]),
                         "path": result["filepath"],
                         "time_or_status": _fmt_duration(elapsed)},
                    ))
                else:
                    result = download_auto(
                        item.url, audio_only=item.audio_only, max_height=1080,
                        progress_hook=hook,
                    )
                    elapsed = time.time() - start
                    quality_label = "음원(mp3)" if item.audio_only else "1080p 이하 자동(webm/30fps 우선)"
                    self.msg_queue.put((
                        "done", next_id,
                        {"title": result["title"],
                         "quality": quality_label,
                         "size": _fmt_size(result["filesize"]),
                         "path": result["filepath"],
                         "time_or_status": _fmt_duration(elapsed)},
                    ))
            except Exception as e:
                self.msg_queue.put((
                    "error_item", next_id,
                    {"title": item.label, "quality": "-", "size": "-",
                     "path": "-", "time_or_status": f"실패: {e}"},
                ))

        self.msg_queue.put(("idle",))

    # ------------------------------------------------------------------
    # 메시지 큐 처리 (백그라운드 -> UI)
    # ------------------------------------------------------------------
    def _poll_queue(self):
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                kind = msg[0]

                if kind == "show_chooser":
                    _, url, title, formats = msg
                    self.add_btn.config(state="normal")
                    if not formats:
                        messagebox.showwarning("조회 실패", "사용 가능한 화질을 찾지 못했어.")
                        continue
                    dialog = FormatChooserDialog(self, title, formats)
                    self.wait_window(dialog)
                    if dialog.chosen_format_id:
                        self._enqueue(
                            url, self.audio_only_var.get(),
                            format_id=dialog.chosen_format_id, forced_auto=False,
                        )
                        self.url_text.delete("1.0", "end")
                        self._render_queue()
                        self._start_processing_if_idle()

                elif kind == "fetch_error":
                    self.add_btn.config(state="normal")
                    messagebox.showerror("조회 실패", msg[1])

                elif kind == "refresh":
                    self._render_queue()

                elif kind == "progress":
                    _, iid, pct = msg
                    if iid in self.items:
                        self.items[iid].progress = pct
                        self._render_queue()

                elif kind == "done":
                    _, iid, info = msg
                    self.items[iid].status = "완료"
                    self.tree.insert(
                        "", "end",
                        values=(info["title"], info["quality"], info["size"], info["path"], info["time_or_status"]),
                    )
                    self._render_queue()

                elif kind == "error_item":
                    _, iid, info = msg
                    self.items[iid].status = "완료"
                    self.tree.insert(
                        "", "end",
                        values=(info["title"], info["quality"], info["size"], info["path"], info["time_or_status"]),
                    )
                    self._render_queue()

                elif kind == "idle":
                    self.is_processing = False
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)


if __name__ == "__main__":
    app = YtdlGUI()
    app.mainloop()

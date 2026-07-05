"""
gui_tkinter.py
YouTube 다운로더 GUI (Tkinter + ttkbootstrap 다크테마).

core/downloader.py 로직을 그대로 재사용하고, 화면만 씌운 얇은 레이어.
ttkbootstrap 설치 필요: pip install ttkbootstrap (requirements.txt에 포함됨)
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox

import ttkbootstrap as ttk

from core.downloader import (
    download_playlist,
    download_single,
    is_playlist_url,
    list_formats,
)

# 한글이 깨지지 않는 폰트로 통일 (Windows 기본 한글 폰트)
FONT_UI = ("Malgun Gothic", 10)
FONT_MONO = ("Malgun Gothic", 10)


class YtdlGUI(ttk.Window):
    def __init__(self):
        super().__init__(themename="darkly")  # ttkbootstrap 다크테마
        self.title("YouTube 다운로더")
        self.geometry("560x480")
        self.resizable(False, False)

        self.formats = []  # list_formats로 조회된 후보들
        self.msg_queue: queue.Queue = queue.Queue()

        self._build_widgets()
        self.after(100, self._poll_queue)

    # ------------------------------------------------------------------
    # 화면 구성
    # ------------------------------------------------------------------
    def _build_widgets(self):
        pad = {"padx": 10, "pady": 6}

        # URL 입력
        frm_url = ttk.Frame(self)
        frm_url.pack(fill="x", **pad)
        ttk.Label(frm_url, text="URL", font=FONT_UI).pack(side="left")
        self.url_entry = ttk.Entry(frm_url, font=FONT_UI)
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(8, 8))
        self.fetch_btn = ttk.Button(frm_url, text="조회", command=self._on_fetch)
        self.fetch_btn.pack(side="left")

        # 영상 / 음원 선택
        frm_type = ttk.Frame(self)
        frm_type.pack(fill="x", **pad)
        self.audio_only_var = tk.BooleanVar(value=False)
        ttk.Radiobutton(
            frm_type, text="영상 (mp4)", variable=self.audio_only_var, value=False
        ).pack(side="left")
        ttk.Radiobutton(
            frm_type, text="음원 (mp3)", variable=self.audio_only_var, value=True
        ).pack(side="left", padx=(12, 0))

        # 상태/안내 라벨
        self.status_label = ttk.Label(
            self, text="URL을 입력하고 조회를 눌러줘.", font=FONT_UI, bootstyle="secondary"
        )
        self.status_label.pack(fill="x", **pad)

        # 화질 목록 (단일 영상일 때만 채워짐)
        frm_list = ttk.Frame(self)
        frm_list.pack(fill="both", expand=True, padx=10)
        self.format_listbox = tk.Listbox(
            frm_list, font=FONT_MONO, bg="#222222", fg="#e8e8e8",
            selectbackground="#375a7f", highlightthickness=0, borderwidth=0,
        )
        self.format_listbox.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(frm_list, command=self.format_listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.format_listbox.config(yscrollcommand=scrollbar.set)

        # 다운로드 버튼 + 진행률
        frm_dl = ttk.Frame(self)
        frm_dl.pack(fill="x", **pad)
        self.download_btn = ttk.Button(
            frm_dl, text="다운로드", command=self._on_download, state="disabled"
        )
        self.download_btn.pack(side="left")
        self.progress = ttk.Progressbar(frm_dl, mode="determinate", maximum=100)
        self.progress.pack(side="left", fill="x", expand=True, padx=(12, 0))

        # 로그 창
        self.log_text = tk.Text(
            self, height=8, state="disabled", font=FONT_MONO,
            bg="#222222", fg="#e8e8e8", insertbackground="#e8e8e8",
            highlightthickness=0, borderwidth=0,
        )
        self.log_text.pack(fill="both", expand=False, padx=10, pady=(0, 10))

    # ------------------------------------------------------------------
    # 로그/상태 helper
    # ------------------------------------------------------------------
    def _log(self, msg: str):
        self.log_text.config(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _set_status(self, msg: str):
        self.status_label.config(text=msg)

    # ------------------------------------------------------------------
    # 포맷 조회
    # ------------------------------------------------------------------
    def _on_fetch(self):
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("입력 필요", "URL을 입력해줘.")
            return

        self.format_listbox.delete(0, "end")
        self.download_btn.config(state="disabled")
        self.formats = []

        if is_playlist_url(url):
            self._set_status("재생목록으로 인식됨. 1080p 이하 최고화질로 일괄 다운로드 진행돼.")
            self.download_btn.config(state="normal")
            return

        self._set_status("포맷 조회 중...")
        self.fetch_btn.config(state="disabled")

        def worker():
            try:
                title, formats = list_formats(url)
                self.msg_queue.put(("fetch_done", title, formats))
            except Exception as e:
                self.msg_queue.put(("fetch_error", str(e)))

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------
    # 다운로드
    # ------------------------------------------------------------------
    def _on_download(self):
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("입력 필요", "URL을 입력해줘.")
            return

        audio_only = self.audio_only_var.get()
        self.download_btn.config(state="disabled")
        self.fetch_btn.config(state="disabled")
        self.progress["value"] = 0

        def hook(d):
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                downloaded = d.get("downloaded_bytes", 0)
                if total:
                    pct = downloaded / total * 100
                    self.msg_queue.put(("progress", pct))
            elif d.get("status") == "finished":
                self.msg_queue.put(("progress", 100))
                self.msg_queue.put(("log", "다운로드된 파일 병합/후처리 중..."))

        def worker():
            try:
                if is_playlist_url(url):
                    self.msg_queue.put(("log", "재생목록 다운로드 시작..."))
                    download_playlist(
                        url, audio_only=audio_only, max_height=1080, progress_hook=hook
                    )
                else:
                    format_id = None
                    if not audio_only and self.format_listbox.curselection():
                        idx = self.format_listbox.curselection()[0]
                        format_id = self.formats[idx].format_id
                    self.msg_queue.put(("log", "다운로드 시작..."))
                    download_single(
                        url, format_id=format_id, audio_only=audio_only, progress_hook=hook
                    )
                self.msg_queue.put(("done", None))
            except Exception as e:
                self.msg_queue.put(("error", str(e)))

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------
    # 백그라운드 스레드 -> UI 갱신 (스레드 안전하게 큐로 처리)
    # ------------------------------------------------------------------
    def _poll_queue(self):
        try:
            while True:
                item = self.msg_queue.get_nowait()
                kind = item[0]

                if kind == "fetch_done":
                    _, title, formats = item
                    self.formats = formats
                    for f in formats:
                        self.format_listbox.insert("end", f.label())
                    self._set_status(f"제목: {title}  (화질 선택 후 다운로드 눌러줘)")
                    self.fetch_btn.config(state="normal")
                    self.download_btn.config(state="normal")

                elif kind == "fetch_error":
                    self._set_status("조회 실패")
                    self._log(f"[에러] {item[1]}")
                    self.fetch_btn.config(state="normal")

                elif kind == "progress":
                    self.progress["value"] = item[1]

                elif kind == "log":
                    self._log(item[1])

                elif kind == "done":
                    self._set_status("완료.")
                    self._log("다운로드 완료.")
                    self.download_btn.config(state="normal")
                    self.fetch_btn.config(state="normal")

                elif kind == "error":
                    self._set_status("다운로드 실패")
                    self._log(f"[에러] {item[1]}")
                    self.download_btn.config(state="normal")
                    self.fetch_btn.config(state="normal")
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)


if __name__ == "__main__":
    app = YtdlGUI()
    app.mainloop()

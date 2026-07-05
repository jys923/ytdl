"""
core/downloader.py
yt-dlp를 감싸는 다운로드 엔진.
CLI든 나중에 GUI든 이 모듈만 호출하면 됨.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import imageio_ffmpeg
import yt_dlp

DOWNLOAD_DIR = "downloads"

# ffmpeg를 별도 설치/PATH 등록 없이 imageio-ffmpeg가 받아둔 바이너리를 그대로 사용
FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()


# ---------------------------------------------------------------------------
# 공통 유틸
# ---------------------------------------------------------------------------

def is_playlist_url(url: str) -> bool:
    """URL에 재생목록 파라미터가 있는지 (list=) 로 판단."""
    return "list=" in url or "/playlist" in url


@dataclass
class FormatInfo:
    format_id: str
    ext: str
    resolution: str
    fps: str
    filesize_approx: str
    note: str

    def label(self) -> str:
        size = f"{self.filesize_approx}" if self.filesize_approx else "?"
        return f"{self.resolution:>10}  {self.ext:<5}  {self.fps:>5}fps  {size:>8}  {self.note}"


def _fmt_size(fmt: dict) -> str:
    size = fmt.get("filesize") or fmt.get("filesize_approx")
    if not size:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f}{unit}"
        size /= 1024
    return f"{size:.0f}TB"


# ---------------------------------------------------------------------------
# 단일 영상: 포맷 목록 조회
# ---------------------------------------------------------------------------

def list_formats(url: str) -> tuple[str, list[FormatInfo]]:
    """영상 제목과, 화질/포맷 후보 목록을 반환.

    비디오+오디오가 합쳐진(progressive) 포맷과, 화질별 대표 포맷만 간추려서 보여줌.
    """
    ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    title = info.get("title", "unknown")
    formats = info.get("formats", [])

    # 비디오 트랙이 있는 것만 (음원 전용 코덱은 별도 옵션에서 처리)
    candidates = []
    seen_keys = set()
    for f in formats:
        if f.get("vcodec") in (None, "none"):
            continue
        height = f.get("height")
        res = f"{height}p" if height else (f.get("resolution") or "?")
        fps = int(f["fps"]) if f.get("fps") else 0
        # 해상도+확장자+fps가 모두 같아야 중복으로 취급 (30fps/60fps 등 다 보여주기 위함)
        key = (res, f.get("ext"), fps)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        candidates.append(
            FormatInfo(
                format_id=f["format_id"],
                ext=f.get("ext", "?"),
                resolution=res,
                fps=str(fps) if fps else "-",
                filesize_approx=_fmt_size(f),
                note="video+audio" if f.get("acodec") not in (None, "none") else "video only",
            )
        )

    # 해상도 높은 순 -> 같은 해상도면 fps 높은 순 정렬 (숫자 추출 실패시 맨 뒤로)
    def sort_key(fi: FormatInfo):
        m = re.match(r"(\d+)", fi.resolution)
        height = int(m.group(1)) if m else -1
        fps_num = int(fi.fps) if fi.fps.isdigit() else -1
        return (height, fps_num)

    candidates.sort(key=sort_key, reverse=True)
    return title, candidates


# ---------------------------------------------------------------------------
# 다운로드 실행
# ---------------------------------------------------------------------------

def download_single(
    url: str,
    format_id: str | None,
    audio_only: bool,
    progress_hook=None,
) -> None:
    """단일 영상 다운로드. format_id가 None이면 audio_only 여부로 결정.

    progress_hook: yt-dlp progress_hooks 형식의 콜백 (dict를 인자로 받음). GUI 진행률 표시용.
    """
    outtmpl = f"{DOWNLOAD_DIR}/%(title)s.%(ext)s"

    if audio_only:
        opts = {
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "ffmpeg_location": FFMPEG_PATH,
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
            ],
        }
    else:
        # 선택한 video-only 포맷이면 오디오 트랙 자동 병합
        fmt = f"{format_id}+bestaudio/best" if format_id else "bestvideo+bestaudio/best"
        opts = {
            "format": fmt,
            "outtmpl": outtmpl,
            "merge_output_format": "mp4",
            "ffmpeg_location": FFMPEG_PATH,
            # 사람이 만든 자막만, 있으면 소프트섭으로 영상에 내장 (하드섭 아님 -> 나중에 추출 가능)
            "writesubtitles": True,
            "writeautomaticsub": False,
            "subtitleslangs": ["ko", "en"],
            "postprocessors": [{"key": "FFmpegEmbedSubtitle"}],
        }

    if progress_hook:
        opts["progress_hooks"] = [progress_hook]

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])


def download_playlist(
    url: str,
    audio_only: bool,
    max_height: int | None = 1080,
    progress_hook=None,
) -> None:
    """재생목록 일괄 다운로드.

    max_height: 이 값 이하 화질 중 최고화질 (None이면 제한 없음, 최고화질)
    progress_hook: yt-dlp progress_hooks 형식의 콜백. GUI 진행률 표시용.
    """
    outtmpl = f"{DOWNLOAD_DIR}/%(playlist_title)s/%(playlist_index)s - %(title)s.%(ext)s"

    if audio_only:
        opts = {
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "ignoreerrors": True,
            "ffmpeg_location": FFMPEG_PATH,
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
            ],
        }
    else:
        if max_height:
            fmt = f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]"
        else:
            fmt = "bestvideo+bestaudio/best"
        opts = {
            "format": fmt,
            "outtmpl": outtmpl,
            "merge_output_format": "mp4",
            "ignoreerrors": True,
            "ffmpeg_location": FFMPEG_PATH,
            "writesubtitles": True,
            "writeautomaticsub": False,
            "subtitleslangs": ["ko", "en"],
            "postprocessors": [{"key": "FFmpegEmbedSubtitle"}],
        }

    if progress_hook:
        opts["progress_hooks"] = [progress_hook]

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

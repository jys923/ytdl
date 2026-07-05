"""
cli.py
YouTube 다운로더 CLI 진입점.

사용법:
    python cli.py

흐름:
    1. URL 입력
    2. 재생목록이면 -> 영상/음원 선택 후 1080p 이하 최고화질로 일괄 다운로드
    3. 단일 영상이면 -> 영상/음원 선택 후, 영상이면 화질 후보 보여주고 선택 -> 다운로드
"""

import sys

from core.downloader import (
    download_playlist,
    download_single,
    is_playlist_url,
    list_formats,
)


def ask_choice(prompt: str, options: list[str]) -> int:
    """번호 선택 프롬프트. 1-based index 반환."""
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt}")
    while True:
        raw = input(f"{prompt} > ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw)
        print("잘못된 입력이야. 다시.")


def main() -> None:
    url = input("URL 입력: ").strip()
    if not url:
        print("URL이 비어있어.")
        sys.exit(1)

    audio_choice = ask_choice("영상 / 음원 중 선택", ["영상 (mp4)", "음원 (mp3)"])
    audio_only = audio_choice == 2

    if is_playlist_url(url):
        print("\n재생목록으로 인식됨. 1080p 이하 최고화질로 일괄 다운로드 진행할게.")
        download_playlist(url, audio_only=audio_only, max_height=1080)
        print("\n재생목록 다운로드 완료.")
        return

    if audio_only:
        print("\n음원으로 다운로드 시작...")
        download_single(url, format_id=None, audio_only=True)
        print("\n완료.")
        return

    # 단일 영상 + 화질 선택
    print("\n포맷 조회 중...")
    title, formats = list_formats(url)
    if not formats:
        print("사용 가능한 비디오 포맷을 찾지 못했어.")
        sys.exit(1)

    print(f"\n제목: {title}")
    labels = [f.label() for f in formats]
    idx = ask_choice("화질 선택", labels)
    chosen = formats[idx - 1]

    print(f"\n{chosen.resolution} ({chosen.ext}) 다운로드 시작...")
    download_single(url, format_id=chosen.format_id, audio_only=False)
    print("\n완료.")


if __name__ == "__main__":
    main()

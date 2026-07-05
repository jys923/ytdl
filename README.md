# YouTube Downloader (개인 소장용)

yt-dlp 기반 YouTube 다운로더. CLI 코어 엔진 위에 얇은 진입점을 올린 구조로,
나중에 GUI를 붙여도 `core/` 로직을 그대로 재사용할 수 있게 설계함.

## 요구 사항

- Python 3.10 이상
- ffmpeg는 별도 설치 필요 없음. `imageio-ffmpeg` 패키지가 pip 설치 시 바이너리를 자동으로 받아오고, 코드에서 그 경로를 yt-dlp에 직접 넘겨줌.

## 설치 (venv 사용)

```bash
sudo apt update && sudo apt install python3 python3-pip python3-venv -y

# 1. 프로젝트 폴더로 이동
cd ytdl

# 2. 가상환경 생성
python3 -m venv .venv

# 3. 가상환경 활성화
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 4. 의존성 설치
pip install -r requirements.txt
```

## 실행 방법

**venv가 활성화된 상태**에서 실행해야 함 (터미널 프롬프트 앞에 `(venv)` 표시 확인).

CLI로 실행:
```bash
python cli.py
```

GUI로 실행 (Tkinter 버전 — ttkbootstrap 다크테마 적용):
```bash
python gui_tkinter.py
```

GUI로 실행 (PyQt6 버전 — qdarkstyle 다크테마 적용):
```bash
python gui_qt.py
```

두 GUI 모두 다크테마가 기본 적용되어 있고, 한글이 깨지지 않도록 폰트를
"Malgun Gothic"(Windows 기본 한글 폰트)으로 고정해둠. Windows가 아닌 환경에서는
이 폰트가 없을 수 있어서, 그 경우 시스템 기본 폰트로 자동 대체됨.

Tkinter는 Linux/WSL 환경에서 기본 파이썬에 안 딸려오는 경우가 있어서, 실행 시
`ModuleNotFoundError: No module named 'tkinter'` 에러가 나면 아래로 설치:
```bash
sudo apt install python3-tk
```
(Windows 네이티브 파이썬은 보통 기본 포함.)

wsl에서 한글 깨질때
퐅트가 없어서 그래
```bash
sudo apt update
sudo apt install fonts-nanum -y
```

가상환경을 나가려면 `deactivate` 입력.

## 사용 흐름

### CLI (`cli.py`)
1. URL 입력
2. 영상(mp4) / 음원(mp3) 선택
3. **재생목록**이면 → 1080p 이하 최고화질로 자동 일괄 다운로드
4. **단일 영상**이면 → 사용 가능한 화질 후보 목록 보여줌 → 번호 선택 → 다운로드

### GUI (`gui_qt.py` — 이후 기능 개발은 Qt 버전 기준으로 진행됨, `gui_tkinter.py`는 이전 기능 상태로 유지)
1. **URL 한 줄만 입력** 후 "대기열에 추가" → 화질 후보 목록이 뜨는 창에서 원하는 화질 직접 선택 → 대기열에 들어감
2. **URL 여러 줄을 한번에 붙여넣기** 후 "대기열에 추가" → 화질 선택 과정 없이 **1080p 이하 최고화질(webm 우선 → 30fps 우선, 용량 최소화 정책)**로 자동 적용되어 대기열에 한꺼번에 들어감
3. **재생목록 URL**도 화질 선택 없이 같은 자동 정책으로 처리됨
4. 대기열은 **동시에 여러 개 받지 않고 순서대로 하나씩** 처리됨. 진행 중인 항목은 진행률이 표시되고, 나머지는 "대기중"으로 카드에 남아있음. 대기열 표시가 처음엔 URL 일부지만, 다운로드가 시작되면 실제 영상 제목으로 자동 갱신됨
5. **다운로드 실패 시 자동 재시도** (최대 2회, 총 3번 시도). 재시도 중엔 대기열에 "재시도중(1/2)" 같은 상태로 표시됨. 그래도 실패하면 완료 내역 표에 실패로 기록됨
6. 다운로드가 끝나면 대기열 카드에서 사라지고, 아래 **완료 내역 리스트**에 카드 형태로 쌓임. 각 카드는:
   - 성공: 제목(굵게) + 화질·용량·소요시간(작은 글씨) + **"폴더 열기"** 버튼 → 클릭하면 저장된 파일이 있는 폴더를 탐색기로 바로 열어줌
   - 실패: 제목 + 실패 사유 + **"다시 추가"** 버튼 → 클릭하면 같은 설정으로 대기열에 재투입
7. 다운로드 진행 중에도 URL을 계속 추가할 수 있음

둘 다 자막(사람이 만든 것만)이 있으면 자동으로 영상에 소프트섭으로 내장됨.

파일명은 영상 제목 그대로 저장되고, `downloads/` 폴더 아래에 생성됨.
재생목록은 `downloads/재생목록이름/번호 - 제목.ext` 형태로 정리됨.

## 프로젝트 구조

```
ytdl/
├── cli.py              # CLI 실행 진입점
├── gui_tkinter.py       # GUI 실행 진입점 (Tkinter, 설치 불필요)
├── gui_qt.py            # GUI 실행 진입점 (PyQt6, pip 설치 필요)
├── core/
│   ├── __init__.py     # core를 패키지로 인식시키는 마커 (내용 없음)
│   └── downloader.py   # yt-dlp 래핑, 실제 다운로드 로직
├── requirements.txt
└── README.md
```

## 주의사항

- 개인 소장 목적으로만 사용. 저작권 있는 콘텐츠의 무단 배포/공유는 금지.

## 배포 방법

이 프로그램을 다른 사람에게 공유하거나 다른 PC로 옮길 때 두 가지 방법이 있음.

### 방법 1. 소스 배포 (지금 이 프로젝트 그대로)

`ytdl/` 폴더 전체(코드 + `requirements.txt`)만 압축해서 공유. 대신 받는 사람도
Python 설치 → venv 생성 → `pip install -r requirements.txt` 과정을 그대로 거쳐야 함.
(위 "설치" 항목 참고)

- 장점: 파일 용량 작음, 코드 수정 자유로움
- 단점: 받는 사람도 파이썬 환경을 세팅할 줄 알아야 함

### 방법 2. 실행파일(.exe)로 빌드해서 배포

파이썬이 없는 사람에게 줄 거면 이 방법이 편함. `PyInstaller`로 파이썬 인터프리터,
yt-dlp, ffmpeg 바이너리까지 전부 파일 하나로 묶어서 더블클릭만으로 실행되게 만듦.

```bash
# venv 활성화된 상태에서
pip install pyinstaller

# 단일 실행파일(.exe)로 빌드
pyinstaller --onefile --name ytdl cli.py
```

빌드가 끝나면 `dist/ytdl.exe` 파일이 생성됨. 이 파일 하나만 공유하면
받는 사람은 파이썬 설치 없이 바로 실행 가능.

주의할 점:
- `--onefile`은 실행할 때마다 내부 압축을 임시 폴더에 풀기 때문에 시작 속도가 조금 느림. 신경 쓰이면 `--onedir`로 빌드하고 폴더째 공유.
- Windows에서 빌드하면 `.exe`가 Windows용으로만 나옴. macOS/Linux용은 각 OS에서 따로 빌드해야 함 (크로스 빌드 불가).
- 실행 시 `downloads/` 폴더는 exe 파일이 있는 위치 기준으로 생성됨.


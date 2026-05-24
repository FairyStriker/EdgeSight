# EdgeSight

NVIDIA Jetson Orin Nano 용 엣지 AI 영상 관제 시스템.
DeepStream(GStreamer) 기반 실시간 객체 탐지/트래킹과 React 기반 관리자 UI를 제공한다.

**입력 소스 3종 지원**: RTSP 스트림 / USB 웹캠 / 영상 파일(MP4, 무한 반복)

---

## 빠른 시작 (TL;DR)

```bash
# 0. 사전 준비: JetPack 6.x (DeepStream 7.x, TensorRT 10.x, CUDA 12.x 포함) 설치된 Jetson
sudo apt install -y ffmpeg python3-gi gstreamer1.0-tools \
    gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly

# 1. 백엔드
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install ultralytics onnx onnxsim  # .pt 자동 변환 기능용 (선택)

# 2. 프론트엔드
cd ../frontend
npm install
npm run build       # backend/main.py 가 frontend/dist 를 자동 서빙

# 3. 실행
cd ../backend
python main.py
# 브라우저: http://<jetson-ip>:8000
```

---

## 시스템 요구사항

| 항목 | 권장 |
|---|---|
| 하드웨어 | NVIDIA Jetson Orin Nano (또는 동급 Jetson 계열) |
| OS / SDK | JetPack 6.x (Ubuntu 22.04 + DeepStream 7.x + TensorRT 10.x) |
| Python | 3.10+ |
| Node.js | 20.x (frontend 빌드용) |
| 메모리 | 8 GB+ |

### 필수 시스템 패키지

```bash
sudo apt update
sudo apt install -y \
    ffmpeg \
    python3-gi python3-gst-1.0 \
    gstreamer1.0-tools gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly \
    sqlite3 curl
```

### DeepStream Python 바인딩 (pyds)

DeepStream SDK 설치본의 wheel 사용:
```bash
pip install /opt/nvidia/deepstream/deepstream/lib/pyds-*.whl
```

(JetPack 6.x 의 DeepStream 7.x 는 pyds wheel을 SDK 디렉토리에 포함)

---

## 프로젝트 구조

```
EdgeSight/
├── backend/
│   ├── main.py                            # FastAPI 진입점 (lifespan, GStreamer pre-load)
│   ├── core/
│   │   ├── database.py                    # SQLAlchemy 모델 + 자동 마이그레이션
│   │   ├── engine.py                      # DeepStream 파이프라인
│   │   ├── shared.py                      # runtime state (frame / meta)
│   │   ├── converter.py                   # .pt → ONNX → engine 변환
│   │   ├── jobs.py                        # 백그라운드 작업 큐
│   │   └── utils.py                       # nvinfer config 생성/관리
│   ├── web/
│   │   ├── routes.py                      # REST + WebSocket + 영상 업로드
│   │   └── auth.py                        # Bearer 토큰 인증
│   ├── configs/                           # nvinfer config / labels (런타임 생성, gitignore)
│   ├── models/                            # 사용자 업로드 모델 (런타임, gitignore)
│   ├── videos/                            # 사용자 업로드 영상 (런타임, gitignore)
│   ├── libnvdsinfer_custom_impl_Yolo.so   # DeepStream-Yolo 후처리 (포함)
│   ├── requirements.txt
│   └── .env.example
└── frontend/
    ├── src/
    │   ├── components/                    # Header, VideoStream, *Modal, ObjectTable
    │   ├── hooks/                         # useStatus(WS), useConfig, useModels
    │   ├── api/                           # client + types
    │   ├── i18n/                          # 한국어/영어
    │   └── styles/
    ├── package.json
    └── vite.config.ts
```

---

## 백엔드 설치 & 실행

### 설치
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### YOLOv8 .pt 자동 변환 기능 사용 시
```bash
# Jetson 용 PyTorch wheel 별도 설치 후
# https://forums.developer.nvidia.com/t/pytorch-for-jetson/
pip install ultralytics onnx onnxsim
```

### 실행
```bash
# 개발 모드 (토큰 인증 비활성)
python main.py

# 프로덕션 (인증 활성화)
export EDGESIGHT_TOKEN="your-secret-token"
python main.py
```

기본 포트 `8000`. 브라우저에서 `http://<jetson-ip>:8000` 접속.

### 환경 변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `EDGESIGHT_TOKEN` | (없음) | 쓰기 엔드포인트 보호용 Bearer 토큰. 미설정 시 인증 비활성 |
| `EDGESIGHT_PORT` | (DB 값) | 서버 포트 |
| `EDGESIGHT_LOG_LEVEL` | `INFO` | 로그 레벨 |
| `EDGESIGHT_DB_URL` | `sqlite:///./edge_system.db` | SQLAlchemy URL |
| `EDGESIGHT_MODEL_DIR` | `./models` | 모델 저장 디렉토리 |
| `EDGESIGHT_CONFIG_DIR` | `./configs` | nvinfer config 디렉토리 |
| `EDGESIGHT_VIDEO_DIR` | `./videos` | 업로드 영상 디렉토리 |
| `EDGESIGHT_CORS_ORIGINS` | `localhost:5173` | 콤마 구분 origin (Vite dev 용) |
| `EDGESIGHT_TRTEXEC` | `/usr/src/tensorrt/bin/trtexec` | trtexec 경로 |
| `EDGESIGHT_PT_EXPORT_SCRIPT` | (없음) | 외부 .pt → ONNX 스크립트 경로 (옵션) |

---

## 프론트엔드 빌드

### 프로덕션 (권장 — 단일 서버 모드)
```bash
cd frontend
npm install
npm run build      # → frontend/dist/
```
이후 `backend/main.py`가 `frontend/dist/`를 자동 서빙. 별도 서버 불필요.

### 개발 (Hot Reload, 백엔드 따로 실행 필요)
```bash
cd frontend
npm run dev        # http://localhost:5173 (api/ws/video_feed 는 :8000 으로 프록시)
```

---

## 사용 가이드

### 1. 첫 실행 시
- 빈 DB가 `backend/edge_system.db` 에 자동 생성됨
- `backend/{models,configs,videos}` 폴더 자동 생성

### 2. 모델 업로드
브라우저 → **모델 관리** 버튼 → 두 가지 방식:
- **`.engine` 직접 업로드** — TensorRT 엔진 파일 + 클래스 이름 입력
- **`.pt` 자동 변환** — YOLOv8 .pt 업로드 시 ONNX → TensorRT 엔진까지 자동 (백그라운드 Job, 모델별 1~10분)

업로드 후 모델 목록에서 **선택** 클릭 → 활성화

### 3. 입력 소스 선택
브라우저 → **시스템 설정** → 입력 소스 종류 선택:

| 종류 | 입력 방법 |
|---|---|
| **RTSP** | `rtsp://user:pass@ip:port/...` 형식 URL |
| **웹캠** | `/dev/video0` 자동 사용 (USB 카메라 사전 연결) |
| **영상 파일** | 파일 업로드 → 자동 H.264 정규화 (1~2분) → 목록에서 선택 → 저장. EOS 시 무한 반복 |

영상 파일은 업로드 시 ffmpeg으로 H.264 main / yuv420p / 고정 GOP로 자동 변환되어 DeepStream 호환성을 보장한다.

---

## API

| Method | Path | 인증 | 설명 |
|---|---|---|---|
| GET | `/api/healthz` | - | 헬스체크 |
| GET | `/api/status` | - | 최신 메타(폴링) |
| WS | `/ws/status` | - | 메타 푸시 (~20Hz) |
| GET | `/video_feed` | - | MJPEG 스트림 |
| GET | `/api/config` | - | 시스템 설정 조회 |
| POST | `/api/config/update` | ✓ | 설정 갱신 (RTSP / 입력 소스 / 영상 선택 등) |
| GET | `/api/model/list` | - | 모델 목록 |
| POST | `/api/model/upload` | ✓ | `.engine` 직접 업로드 |
| POST | `/api/model/upload_pt` | ✓ | `.pt` 자동 변환 (Job) |
| POST | `/api/model/select/{id}` | ✓ | 활성 모델 변경 |
| DELETE | `/api/model/{id}` | ✓ | 모델 삭제 |
| GET | `/api/video/list` | - | 영상 목록 |
| POST | `/api/video/upload` | ✓ | 영상 업로드 + ffmpeg 정규화 (Job) |
| DELETE | `/api/video/{id}` | ✓ | 영상 삭제 |
| GET | `/api/jobs` | - | 변환 작업 목록 |
| GET | `/api/jobs/{id}` | - | 작업 상태 |

---

## 트러블슈팅

### 1. 서버 기동 시 GStreamer plugin segfault
`main.py`가 시작 시 자동으로 `~/.cache/gstreamer-1.0/` 을 정리하고 v4l2 plugin 을 pre-load 한다. 그래도 발생하면:
```bash
rm -rf ~/.cache/gstreamer-1.0
```

### 2. 영상이 빠르게(배속) 재생됨
영상 업로드 시 ffmpeg 정규화가 실패했을 가능성. 변환 Job 상태 확인:
```bash
curl http://localhost:8000/api/jobs
```

### 3. .pt 변환 시 trtexec 못 찾음
```bash
export EDGESIGHT_TRTEXEC=/usr/src/tensorrt/bin/trtexec   # 또는 실제 경로
```

### 4. WebSocket 연결 안 됨 → 우측 패널 비어있음
`uvicorn[standard]` 가 설치 안 된 경우:
```bash
pip install 'uvicorn[standard]'   # websockets 포함
```

### 5. 활성 모델 없을 때
파이프라인은 모델이 활성화될 때까지 대기 상태 — 영상/카메라 화면도 나오지 않음. 모델 업로드 + **선택** 필수.

---

## 라이선스 / 의존성

- `backend/libnvdsinfer_custom_impl_Yolo.so` — [marcoslucianops/DeepStream-Yolo](https://github.com/marcoslucianops/DeepStream-Yolo) (MIT) 빌드본
- DeepStream / TensorRT / CUDA — NVIDIA 라이선스 (Jetson에 사전 설치)

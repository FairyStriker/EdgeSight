# EdgeSight

NVIDIA Jetson Orin Nano용 엣지 AI 영상 관제 시스템.
DeepStream(GStreamer) 기반 실시간 객체 탐지/트래킹과 React 기반 관리자 UI를 제공한다.

YOLOv8 `.pt` 파일을 업로드하면 백엔드가 알아서 DeepStream 호환 ONNX → TensorRT 엔진까지
자동 빌드하고 nvinfer 설정/라벨 파일을 생성해 즉시 사용할 수 있다.

> **검증 환경**: Jetson Orin Nano · JetPack 6 (R36.4.7) · DeepStream 7.1 · Python 3.10

---

## 빠른 시작 (Jetson)

### 0. 사전 준비

| 항목 | 확인 명령 | 비고 |
|---|---|---|
| JetPack | `cat /etc/nv_tegra_release` | R36.x 권장 |
| DeepStream | `cat /opt/nvidia/deepstream/deepstream/version` | 7.1 검증됨 |
| pyds / gi | `python3 -c "import pyds, gi"` | DeepStream SDK 설치본 사용 |
| trtexec | `ls /usr/src/tensorrt/bin/trtexec` | JetPack에 포함 |

### 1. 코드 받기

```bash
cd ~
git clone https://github.com/FairyStriker/EdgeSight.git
cd EdgeSight
```

### 2. 백엔드 의존성 설치

`pyds`, `gi(PyGObject)`가 시스템 패키지로 설치되어 있어야 하므로,
이미 그 패키지들에 접근 가능한 환경(시스템 Python, 또는 `--system-site-packages`로 만든 venv)에서 설치한다.

```bash
cd backend
pip install -r requirements.txt

# .pt 자동 변환 기능을 쓰려면 추가
pip install ultralytics onnx onnxsim
```

### 3. Node.js 설치 + 프론트엔드 빌드

```bash
# Node.js 20 LTS
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

# 프론트엔드 빌드
cd ~/EdgeSight/frontend
npm install
npm run build      # → frontend/dist/ 생성
```

### 4. 백엔드 실행

```bash
cd ~/EdgeSight/backend
python main.py
```

`Uvicorn running on http://0.0.0.0:8000` 로그가 뜨면 정상.

### 5. 접속

```bash
hostname -I    # Jetson IP 확인
```

PC 브라우저에서 `http://<jetson-ip>:8000` 접속.

### 6. 첫 사용

1. **⚙️ 시스템 설정** → **RTSP 주소** 입력 후 저장
   (기본값 `0`은 USB 카메라용. RTSP면 `rtsp://...` 형식으로 변경)
2. **📦 모델 관리** 모달에서 모델 업로드:
   - **`.engine 직접 업로드`** 탭 — 이미 빌드된 TensorRT 엔진
   - **`.pt 자동 변환`** 탭 — YOLOv8 .pt 업로드 (수 분 소요, 진행률 표시)
3. 업로드된 모델의 **선택** 버튼 → 영상 + 객체 테이블 표시 시작

---

## 인증 (선택)

쓰기 엔드포인트(설정 변경, 모델 업로드/삭제)를 보호하려면 환경변수로 토큰을 설정한다.

```bash
export EDGESIGHT_TOKEN="아무거나-긴-랜덤-문자열"
python main.py
```

UI의 시스템 설정에서 동일 토큰을 입력하면 이후 요청 헤더에 자동 첨부된다.
환경변수가 비어있으면 인증은 비활성(개발 모드)이다.

추가 환경변수는 [`backend/.env.example`](backend/.env.example) 참고.

---

## 폴더 구조

```
EdgeSight/
├── backend/                       # FastAPI + DeepStream + SQLite
│   ├── main.py                    # 엔트리 포인트 (lifespan + SPA 서빙)
│   ├── core/
│   │   ├── database.py            # AIModel, SystemConfig
│   │   ├── shared.py              # frame/meta 공유 상태 (frame_seq)
│   │   ├── engine.py              # DeepStream 파이프라인 + AIEngine 스레드
│   │   ├── utils.py               # nvinfer config/label 생성·삭제
│   │   ├── converter.py           # .pt → DS 호환 ONNX → TensorRT engine
│   │   └── jobs.py                # 비동기 작업 추적 (in-memory)
│   ├── web/
│   │   ├── routes.py              # REST + WebSocket
│   │   └── auth.py                # Bearer 토큰 인증
│   ├── configs/                   # nvinfer 설정/라벨 (런타임 생성)
│   ├── models/                    # 업로드된 .pt/.onnx/.engine
│   ├── libnvdsinfer_custom_impl_Yolo.so   # DeepStream-Yolo 커스텀 후처리
│   └── requirements.txt
├── frontend/                      # React + Vite + TypeScript
│   ├── src/
│   │   ├── components/            # Header, VideoStream, StatusPanel, Modal 등
│   │   ├── hooks/                 # useStatus(WS), useConfig, useModels, useJobs
│   │   ├── api/                   # client + types
│   │   ├── i18n/                  # ko / en 사전
│   │   └── styles/                # global.css
│   └── package.json
├── REFERENCE_ANALYSIS.md          # 원본 demo 분석 리포트
└── README.md
```

---

## 주요 API

| Method | Path | 인증 | 설명 |
|---|---|---|---|
| GET  | `/api/healthz` | – | 헬스체크 |
| GET  | `/api/status`  | – | 최신 메타(폴링용) |
| WS   | `/ws/status`   | – | 메타 푸시 (~20Hz, 변화 시점만) |
| GET  | `/video_feed`  | – | MJPEG 스트림 |
| GET  | `/api/config`  | – | 현재 시스템 설정 |
| POST | `/api/config/update` | ✓ | 설정 갱신 |
| GET  | `/api/model/list` | – | 모델 목록 |
| POST | `/api/model/upload`    | ✓ | `.engine` 직접 업로드 |
| POST | `/api/model/upload_pt` | ✓ | `.pt` 업로드 → ONNX → engine 자동 빌드 |
| POST | `/api/model/select/{id}` | ✓ | 활성 모델 변경 |
| DELETE | `/api/model/{id}`      | ✓ | 모델 삭제 |
| GET  | `/api/jobs`         | – | 변환 작업 목록 |
| GET  | `/api/jobs/{id}`    | – | 단일 작업 상태 |

---

## .pt 자동 변환 동작 흐름

```
사용자 .pt 업로드
   ↓ backend/models/{name}.pt 저장
DeepStream 호환 ONNX export (자체 구현 또는 외부 스크립트)
   ↓ backend/models/{name}.onnx
trtexec FP16 빌드
   ↓ backend/models/{name}.engine
nvinfer config + 라벨 파일 생성
   ↓ backend/configs/config_infer_{name}.txt
   ↓ backend/configs/labels_{name}.txt
DB(AIModel) 등록 → UI 모델 목록 갱신
```

업로드 시 클래스 라벨은 `.pt` 파일의 메타데이터(`model.names`)에서 자동 추출된다.

| 모델 | ONNX export | trtexec FP16 (Orin Nano) |
|---|---|---|
| YOLOv8n | ~10초 | ~1~2분 |
| YOLOv8s | ~15초 | ~2~3분 |
| YOLOv8m | ~25초 | ~3~5분 |
| YOLOv8l | ~40초 | ~5~10분 |

---

## 트러블슈팅

| 증상 | 대처 |
|---|---|
| `couldn't find element 'nvinfer'` | DeepStream 환경 미활성. `source /opt/nvidia/deepstream/deepstream/scripts/setup.sh` 후 재실행 |
| 영상이 검은 화면 | RTSP URL 확인. 인증 필요 시 `rtsp://user:pass@host/path` |
| 첫 실행 시 파이프라인 에러 반복 | RTSP 미설정 상태(기본값 `0`). UI 시스템 설정에서 주소 입력하면 멈춤 |
| `pip install ultralytics` 충돌 | Jetson용 PyTorch wheel 먼저 설치 필요 (NVIDIA 공식 가이드 참조) |
| trtexec 못 찾음 | `EDGESIGHT_TRTEXEC` 환경변수로 경로 지정 |

---

## 개발 모드 (Hot Reload)

프론트엔드를 수정하며 작업할 때:

```bash
# 터미널 1 — 백엔드
cd backend && python main.py

# 터미널 2 — Vite dev 서버 (5173 포트, /api·/ws·/video_feed 자동 프록시)
cd frontend && npm run dev
```

브라우저에서 `http://localhost:5173` 접속.

---

## 라이선스 / 출처

- ONNX export 출력 헤드 로직: marcoslucianops/[DeepStream-Yolo](https://github.com/marcoslucianops/DeepStream-Yolo) (MIT License) 참고
- 원본 데모 분석은 [`REFERENCE_ANALYSIS.md`](REFERENCE_ANALYSIS.md) 참조

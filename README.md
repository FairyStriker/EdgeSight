# EdgeSight

NVIDIA Jetson Orin Nano용 엣지 AI 영상 관제 시스템.
DeepStream(GStreamer) 기반 실시간 객체 탐지/트래킹과 React 기반 관리자 UI를 제공한다.

## 구조

```
EdgeSight/
├── backend/             # FastAPI + DeepStream + SQLite
│   ├── main.py
│   ├── core/            # database, shared state, GStreamer engine, utils
│   ├── web/             # REST + WebSocket + auth
│   ├── configs/         # nvinfer config / 라벨 (런타임 생성)
│   ├── models/          # 업로드된 .engine 파일
│   └── requirements.txt
├── frontend/            # React + Vite + TypeScript
│   ├── src/
│   │   ├── components/  # Header, VideoStream, StatusPanel, *Modal
│   │   ├── hooks/       # useStatus(WS), useConfig, useModels
│   │   ├── api/         # client + types
│   │   ├── i18n/        # ko/en 사전
│   │   └── styles/      # global.css
│   └── package.json
└── REFERENCE_ANALYSIS.md  # 원본 demo 분석 리포트
```

## 백엔드 (Jetson)

### 설치

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# pyds, PyGObject는 DeepStream SDK / apt 설치본 사용
```

### 실행

```bash
# 개발 모드
EDGESIGHT_LOG_LEVEL=DEBUG uvicorn main:app --reload

# 프로덕션 (인증 활성화)
export EDGESIGHT_TOKEN="your-secret-token"
python main.py
```

| 환경변수 | 설명 |
|---|---|
| `EDGESIGHT_TOKEN` | 쓰기 엔드포인트 보호용 Bearer 토큰. 미설정 시 인증 비활성(개발 모드) |
| `EDGESIGHT_PORT` | 서버 포트 (미설정 시 DB의 `server_port`) |
| `EDGESIGHT_LOG_LEVEL` | 로그 레벨 (기본 `INFO`) |
| `EDGESIGHT_DB_URL` | SQLAlchemy URL (기본 `sqlite:///./edge_system.db`) |
| `EDGESIGHT_CORS_ORIGINS` | 콤마 구분 origin 목록 (Vite dev server용) |

## 프론트엔드

### 개발 서버 (Hot Reload)

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173
```

Vite가 `/api`, `/ws`, `/video_feed` 를 백엔드(`http://localhost:8000`)로 프록시한다.

### 프로덕션 빌드

```bash
cd frontend
npm run build   # → frontend/dist/
```

이후 `backend/main.py`가 `frontend/dist`를 자동으로 마운트하여 단일 서버에서 서빙한다.

## API

| Method | Path | 인증 | 설명 |
|---|---|---|---|
| GET | `/api/healthz` | - | 헬스체크 |
| GET | `/api/status` | - | 최신 메타(폴링용) |
| WS  | `/ws/status` | - | 메타 푸시 (~20Hz, 변화 시점만) |
| GET | `/video_feed` | - | MJPEG 스트림 |
| GET | `/api/config` | - | 현재 시스템 설정 |
| POST | `/api/config/update` | ✓ | 설정 갱신 |
| GET | `/api/model/list` | - | 모델 목록 |
| POST | `/api/model/upload` | ✓ | 모델 업로드 (.engine 직접) |
| POST | `/api/model/upload_pt` | ✓ | YOLOv8 .pt 업로드 → ONNX 자동 변환 (비동기 Job 반환) |
| POST | `/api/model/select/{id}` | ✓ | 활성 모델 변경 |
| DELETE | `/api/model/{id}` | ✓ | 모델 삭제 |
| GET | `/api/jobs` | - | 변환 작업 목록 |
| GET | `/api/jobs/{id}` | - | 단일 작업 상태 |

## 원본 demo 대비 변경/수정 사항

원본(`D:/works/demo`) 대비 다음을 적용:

### Critical 수정
- **C1** [engine.py] RTSP 비교를 정수 → 문자열로 통일 (DB 저장 형식과 일치)
- **C2** [routes.py] `SystemConfig` None 가드 (NPE 방지)
- **C3** [database.py] `language` 컬럼 자동 마이그레이션(`ALTER TABLE IF NOT EXISTS`)
- **C4** [routes.py] 업로드 파일명 `os.path.basename` 적용 (path traversal 방지)
- **C5** [auth.py] Bearer 토큰 인증 (쓰기 엔드포인트 한정)

### Major 개선
- **M1** [engine.py] 트래커 설정 절대경로 (`/opt/nvidia/deepstream/...`)
- **M2** [engine.py] 파이프라인 재시작 락(`_restart_lock`)으로 동기화
- **M3** [main.py] FastAPI lifespan + 시그널 핸들러로 graceful shutdown
- **M4** [shared.py] `frame_seq`/`meta_seq` 도입 — byte 비교 제거
- **M5** [routes.py] `language` 변경 시 `state`에도 반영
- **M6** [routes.py] 업로드 부분 실패 시 파일/config 정리
- **M7** [VideoStream.tsx] 스트림 끊김 시 자동 재연결 (1.5초 백오프)
- **M8** [routes.py + useStatus.ts] WebSocket 푸시로 100ms 폴링 대체

### 기타
- 로깅 표준화 (`print` → `logging`)
- Jetson 외 환경에서도 import 가능하도록 `gi/pyds` 가드
- 정적 파일 SPA fallback (React Router 도입 시 대비)

### 신규 기능
- **YOLOv8 .pt 자동 변환** — `/api/model/upload_pt` + 백그라운드 Job
  - .pt → DeepStream 호환 ONNX → TensorRT FP16 .engine → config + label까지 한 번에
  - DeepStream-Yolo (MIT License) 의 출력 헤드 로직 자체 구현
  - 외부 공식 스크립트 사용도 옵션 지원
- **Job 추적 시스템** — `/api/jobs`, in-memory + thread-safe + 동시 변환 1개 제한
- **모델 관리 UI 탭** — `.engine 직접` / `.pt 자동 변환` 분리, 단계별 진행률 표시

## YOLOv8 .pt 자동 변환 사용법

UI의 **모델 관리 → `.pt 자동 변환` 탭**에서 .pt 파일과 클래스 목록을 업로드하면
백그라운드에서 다음 단계가 자동 수행되고, 진행률이 같은 모달의 **변환 작업** 패널에 표시된다.

### 동작 흐름 (전 과정 백엔드에서 수행)

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
DB(AIModel)에 등록 → 모델 목록 갱신
```

`.engine` 파일이 업로드 시점에 직접 빌드되므로, 모델 활성화 시 즉시 추론이 시작된다
(nvinfer가 별도로 engine 빌드를 하지 않음).

### 의존성 설치 (Jetson)

```bash
# 1) Jetson에 NVIDIA 제공 PyTorch wheel 설치
#    https://forums.developer.nvidia.com/t/pytorch-for-jetson/

# 2) 변환 의존성
pip install ultralytics onnx onnxsim
```

`trtexec`은 JetPack 표준 설치본을 사용한다(`/usr/src/tensorrt/bin/trtexec`).
경로가 다르면 `EDGESIGHT_TRTEXEC` 환경변수로 override.

### ONNX 출력 형식

자체 구현된 export는 marcoslucianops/DeepStream-Yolo (MIT License) 의
`utils/export_yoloV8.py` 와 동일한 출력 텐서 형식을 따른다:

| 텐서 | 형상 | 내용 |
|---|---|---|
| `boxes` | `[1, num_anchors, 4]` | cx, cy, w, h |
| `scores` | `[1, num_anchors, num_classes]` | per-class confidence |

이 두 출력은 `libnvdsinfer_custom_impl_Yolo.so`의 `NvDsInferParseYolo` 후처리에서 NMS 처리된다.

### 외부 스크립트 사용 (옵션)

자체 export가 호환되지 않는 모델 변형(예: yolov8-pose, custom head)에는
공식 [DeepStream-Yolo](https://github.com/marcoslucianops/DeepStream-Yolo) 스크립트를 사용:

```bash
export EDGESIGHT_PT_EXPORT_SCRIPT=/opt/DeepStream-Yolo/utils/export_yoloV8.py
```

설정 시 자체 export 대신 해당 스크립트가 호출된다 (`-w <pt> --opset 12 --size 640`).

### 변환 시간 가이드

| 모델 | ONNX export | trtexec FP16 (Orin Nano) |
|---|---|---|
| YOLOv8n | ~10초 | ~1~2분 |
| YOLOv8s | ~15초 | ~2~3분 |
| YOLOv8m | ~25초 | ~3~5분 |
| YOLOv8l | ~40초 | ~5~10분 |

## 다음 작업 후보

- 이벤트 이력 DB 저장 / ROI 카운팅 / 다중 카메라
- systemd unit, Docker 이미지
- Prometheus 메트릭 + Grafana

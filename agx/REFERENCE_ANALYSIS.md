# 프로그램 분석 리포트

> 작성일: 2026-05-07
> 대상: `D:/works/demo` (Jetson Orin Nano 엣지 AI 영상 관제 시스템)
> 목적: 코드 전수 분석 후 업그레이드 작업 준비를 위한 베이스라인 정리

---

## 1. 개요

NVIDIA Jetson Orin Nano 위에서 동작하는 **엣지 AI 영상 관제 시스템**.
DeepStream(GStreamer) 파이프라인으로 RTSP/웹캠 영상을 받아 YOLOv8 TensorRT 엔진으로 실시간 추론·트래킹하고, FastAPI 기반 단일 페이지 웹 UI로 모델 관리·설정·실시간 모니터링을 제공한다.

### 핵심 특징

- **온디바이스 추론**: 클라우드 의존 없이 Jetson GPU(`nvinfer`)에서 직접 추론
- **모델 핫스왑**: 웹 UI에서 `.engine` 파일 업로드 후 즉시 활성화 가능
- **자동 재구성**: 신뢰도/IoU/RTSP 변경 시 파이프라인 자동 재시작
- **트래킹 포함**: `nvtracker`(IOU)로 객체 ID 유지
- **다국어**: 한국어/영어 i18n
- **MJPEG 스트리밍**: 별도 플러그인 없이 브라우저 `<img>` 로 라이브 시청

---

## 2. 시스템 아키텍처

### 디렉토리 구조

```
demo/
├── main.py                          # 진입점 (FastAPI + Engine 부팅)
├── edge_system.db                   # SQLite (모델/설정 영속화)
├── libnvdsinfer_custom_impl_Yolo.so # YOLO 후처리 커스텀 라이브러리
├── core/
│   ├── database.py                  # SQLAlchemy 모델 (AIModel, SystemConfig)
│   ├── shared.py                    # 런타임 상태 (frame/meta + lock)
│   ├── engine.py                    # DeepStream 파이프라인 + 설정 감시 스레드
│   └── utils.py                     # nvinfer config·label 파일 생성/수정/삭제
├── web/
│   ├── routes.py                    # REST API + MJPEG 스트림
│   └── templates/index.html         # SPA UI (100ms polling)
├── configs/                         # 모델별 nvinfer config + 라벨 파일
│   ├── config_infer_*.txt
│   └── labels_*.txt
└── models/                          # TensorRT engine 파일들 (.engine)
    ├── yolov8n_fp16.engine
    ├── yolov8s/m/l_fp16.engine
    ├── cocov8n.engine
    └── swindino.engine
```

### 데이터 플로우

```
[Camera/RTSP]
     ↓
uridecodebin → nvstreammux(1280x720) → nvinfer(YOLOv8) → nvtracker(IOU)
     ↓                                       ↓
 nvvideoconvert → nvdsosd → nvvideoconvert → jpegenc → appsink
     ↓                                                       ↓
   (probe: meta 추출)                              state.set_frame(JPEG)
     ↓                                                       ↓
   state.set_meta({fps, count, objects})         /video_feed (MJPEG)
                          ↓                                  ↓
                    /api/status (JSON, 100ms polling)    <img> 태그
```

### 컴포넌트 책임

| 모듈 | 책임 | 핵심 객체 |
|---|---|---|
| `main.py` | 부팅 (DB init → 설정 로드 → AIEngine 스레드 → uvicorn) | `app`, `engine` |
| `core/database.py` | DB 스키마 / 세션 팩토리 | `AIModel`, `SystemConfig` |
| `core/shared.py` | 스레드 간 공유 상태 (생산자: engine, 소비자: routes) | `RuntimeState`(전역 `state`) |
| `core/engine.py` | GStreamer 파이프라인 + 설정 변경 감지 후 재시작 | `DeepStreamPipeline`, `AIEngine` |
| `core/utils.py` | nvinfer config 파일 생성/수정/삭제 | `create_engine_config`, `update_deepstream_config` |
| `web/routes.py` | HTTP API (모델 CRUD, 설정 업데이트, 영상 스트림) | `router` |
| `web/templates/index.html` | 단일 페이지 UI (영상 + 메타 테이블 + 모달 2개) | (Vanilla JS) |

---

## 3. 기술 스택

| 영역 | 기술 |
|---|---|
| 디바이스 | NVIDIA Jetson Orin Nano (Linux ARM64) |
| 추론 | NVIDIA DeepStream + TensorRT engine + YOLOv8 |
| 미디어 | GStreamer 1.0 (`uridecodebin`, `nvstreammux`, `nvinfer`, `nvtracker`, `nvdsosd`, `jpegenc`) |
| 트래커 | NvDsTracker (IOU 알고리즘, 시스템 설치본 사용) |
| 웹 서버 | FastAPI + Uvicorn |
| 템플릿 | Jinja2 |
| DB | SQLite + SQLAlchemy ORM |
| 프론트엔드 | Vanilla HTML/CSS/JS (프레임워크 없음) |
| 영상 송출 | MJPEG (multipart/x-mixed-replace) |
| Python 바인딩 | `pyds` (DeepStream metadata 접근) |

---

## 4. 동작 흐름

### 부팅 시퀀스

1. `main.py` → FastAPI 앱 생성, 라우터 등록
2. `init_db()` → SQLite 테이블 생성
3. `load_settings()` → DB에서 `SystemConfig` 로드 → `state.config` 갱신
4. `AIEngine().start()` → 백그라운드 스레드 시작
5. `AIEngine.run()` → 내부에 `DeepStreamPipeline.run_loop()` 별도 스레드 시작 + 설정 감시 루프 진입
6. `uvicorn.run()` → 메인 스레드에서 HTTP 서버 기동

### 프레임 처리 사이클

1. `appsink` 새 샘플 콜백 → JPEG 바이트 → `state.set_frame()`
2. `nvosd` sink pad probe → batch metadata 순회 → 객체 리스트 생성 → `state.set_meta()`
3. 클라이언트 `/video_feed` 제너레이터 → `state.get_frame()` 반복 yield
4. 클라이언트 100ms마다 `/api/status` GET → `state.get_meta()` 반환

### 설정 변경 사이클

1. UI에서 설정 저장 → `/api/config/update` → DB 커밋 + `state.update_config()`
2. `AIEngine.run()` 의 1초 주기 감시 루프가 변화 감지
3. `update_deepstream_config()` 로 nvinfer txt 파일 수정 (conf, iou)
4. `pipeline_wrapper.stop_loop()` → 메인루프 종료
5. `run_loop()` 의 while True가 다시 파이프라인 생성·시작

---

## 5. 코드 분석 (파일별)

### `main.py` (37줄)
- 깔끔하고 단순. 설정 로드 → 엔진 시작 → uvicorn.
- **개선점**: graceful shutdown 핸들러 부재. SIGTERM 시 GStreamer 파이프라인 정리 안 됨.
- 주석 처리된 로그 옵션 보존 (운영 시 참고용으로 둔 듯).

### `core/database.py` (35줄)
- `AIModel`, `SystemConfig` 두 테이블만. 모델은 `active_model_id`로 1:N 관계.
- **개선점**: `language` 컬럼이 후추가됐는데 마이그레이션 코드 없음 → 기존 DB 파일은 컬럼 누락 시 에러.

### `core/shared.py` (44줄)
- `frame_lock` / `meta_lock` 으로 스레드 안전성 확보.
- 단일 인스턴스 `state` 전역 공유.
- **개선점**: 프레임 시퀀스 번호 없음 → 라우트에서 동일 프레임 검출을 byte 비교로 함(비효율).

### `core/engine.py` (234줄) — 핵심 모듈
- `DeepStreamPipeline._create_pipeline()`: 9개 GStreamer 엘리먼트를 명령형으로 연결. **파이프라인 그래프가 가장 중요한 부분**.
- `_probe_callback()`: nvosd sink에서 batch metadata 추출 → 객체 리스트 구성. 매 프레임 호출되므로 성능 민감.
- `_update_fps()`: 1초 윈도우 슬라이딩 FPS 계산.
- `AIEngine.run()`: 1초 주기로 4개 설정값(model/rtsp/conf/iou) 비교 → 변경 시 파이프라인 재시작.

#### 의도적 설계 vs 잠재 이슈

| 항목 | 현재 | 비고 |
|---|---|---|
| 트래커 설정 파일 | `'config_tracker_IOU.txt'` (상대경로) | Jetson DeepStream SDK 시스템 설치본 사용 의도. **CWD가 프로젝트 루트일 때만 동작**. systemd 등록 시 깨질 위험 → 절대경로(`/opt/nvidia/deepstream/deepstream/samples/configs/deepstream-app/config_tracker_IOU.yml`)로 수정 권장. |
| 트래커 해상도 | 640x384 고정 | 트레이드오프 의도, 변경 안 해도 무방 |
| streammux 해상도 | 1280x720 고정 | 추론 입력 표준화 |
| RTSP 입력 분기 | `if rtsp == 0:` (정수 비교) | DB에는 `"0"` 문자열 저장 → **분기 사망. v4l2 웹캠 경로 미도달 가능성** |
| 파이프라인 재시작 동기화 | `stop_loop()` 후 즉시 `last_cfg.update` | config 파일 쓰기와 새 파이프라인 시작 사이 경합 가능성 |

### `core/utils.py` (157줄)
- 텍스트 템플릿 기반 nvinfer config 생성. 절대경로 사용 양호.
- `update_deepstream_config()`: 주석(`#`)된 라인 보존하면서 conf/iou만 교체. 견고함.
- `delete_generated_files()`: 라벨 파일 경로를 config에서 역참조해서 삭제. 좋은 패턴.

### `web/routes.py` (136줄)
- 7개 엔드포인트. Depends 주입으로 DB 세션 처리 표준적.
- `video_feed` 제너레이터: `time.sleep(0.01)` 폴링 방식. 부하 낮지만 비효율.
- 동일 프레임 검출: `f == last_frame` (전체 byte 비교) → 큰 JPEG일수록 비용 증가.
- `upload_model`: 파일명 검증 없음(path traversal 가능), UNIQUE 충돌 시 500.
- `del_model`: `c.active_model_id` 접근 시 `c`가 None이면 NPE.
- `update_cfg`: `language` 인자 받지만 `state` 반영 안 함.

### `web/templates/index.html` (266줄)
- Vanilla JS 단일 파일. 의존성 없음.
- 100ms 폴링 (`setInterval`) — 초당 10회 HTTP 요청. WebSocket으로 대체 가능.
- 영상 `<img onerror="...">` 만 있고 자동 재연결 없음.
- i18n은 클라이언트 사이드 사전(`i18n` 객체) 방식.
- 모달 2개(설정/모델 관리) 인라인.

---

## 6. 발견된 이슈

### Critical (실서비스에 영향)

| # | 위치 | 내용 | 우선순위 |
|---|---|---|---|
| C1 | [core/engine.py:25](core/engine.py:25) | 웹캠 분기(`if rtsp == 0`) 사망 — DB는 `"0"` 문자열 저장 → `uri` 미정의 시 `AttributeError` | 높음 |
| C2 | [web/routes.py:111](web/routes.py:111) | `SystemConfig` 미존재 시 `c.active_model_id` NPE | 높음 |
| C3 | [core/database.py](core/database.py) | `language` 컬럼 마이그레이션 없음 — 기존 DB는 SELECT 시 OperationalError 가능 | 높음 |
| C4 | [web/routes.py:57](web/routes.py:57) | 업로드 파일명 검증 없음 → path traversal (예: `../../etc/passwd.engine`) | 높음 (보안) |
| C5 | 전역 | 인증/인가 전무 — 누구나 모델 업로드/삭제, RTSP 변경 가능 | 높음 (보안) |

### Major (고치면 견고해짐)

| # | 위치 | 내용 |
|---|---|---|
| M1 | [core/engine.py:49](core/engine.py:49) | 트래커 config 상대경로 — CWD 의존. 시스템 절대경로(`/opt/nvidia/...`)로 변경 권장 |
| M2 | [core/engine.py:217](core/engine.py:217) | 파이프라인 재시작과 config 파일 쓰기 사이 동기화 부재 (경합조건 가능) |
| M3 | [main.py:32](main.py:32) | graceful shutdown 부재 — Ctrl+C 시 GStreamer 정리 안 됨 |
| M4 | [web/routes.py:35](web/routes.py:35) | MJPEG 동일 프레임 검출이 byte 비교 — 시퀀스 번호로 대체 |
| M5 | [web/routes.py:50](web/routes.py:50) | `language` 변경이 `state`에 반영 안 됨 |
| M6 | [web/routes.py:57](web/routes.py:57) | 업로드 실패 시 부분 상태 잔존 — 파일은 저장됐는데 DB 커밋 실패하는 케이스 정리 |
| M7 | [web/templates/index.html:76](web/templates/index.html:76) | `video_feed` 끊김 시 자동 재연결 없음 |
| M8 | [web/templates/index.html:197](web/templates/index.html:197) | 100ms 폴링 → WebSocket 푸시로 대체 가능 |

### Minor / Cosmetic

| # | 위치 | 내용 |
|---|---|---|
| m1 | [web/routes.py:35](web/routes.py:35) | `f ==last_frame` 공백 오타 (동작은 함) |
| m2 | [core/engine.py](core/engine.py) | `print()` → `logging` 모듈로 표준화 |
| m3 | [web/templates/index.html:188](web/templates/index.html:188) | 헤더 타이틀과 `document.title` 문구 불일치 ("관제 모니터링" vs "Jetson 스마트 관제") |
| m4 | 전역 | README, 배포 가이드 부재 |
| m5 | [configs/](configs/) | 절대경로(`/home/risenano02/...`)가 박혀있음 → 다른 사용자 환경에서 재사용 불가. 단, `create_engine_config()`로 신규 생성 시는 OK |

---

## 7. 완성도 향상 제안 (우선순위 순)

### Phase 1 — 안정화 (1~2일)
1. Critical 5건 수정
2. Major M1~M3 수정 (트래커 절대경로, 재시작 동기화, graceful shutdown)
3. `print()` → `logging` 으로 일괄 교체
4. 간단한 README 작성

### Phase 2 — UX 개선 (2~3일)
5. WebSocket 기반 메타 푸시 (100ms 폴링 제거)
6. 영상 스트림 자동 재연결
7. 업로드/삭제 권한(간단한 토큰 또는 Basic Auth)
8. 헬스체크 엔드포인트(`/healthz`, `/readyz`)

### Phase 3 — 기능 확장 (1~2주)
9. **이벤트 이력 DB 저장** (감지 클래스별 카운트, 시간대 분포)
10. **이벤트 트리거 클립 녹화** (특정 클래스 감지 시 N초 보존)
11. **ROI / 가상 라인 카운팅** (라인 크로싱)
12. **다중 카메라** 지원 (`nvstreammux batch>1`)
13. **트래커 선택** UI (IOU / NvDCF / NvDeepSORT)
14. **Webhook / 알림** (특정 이벤트 발생 시)

### Phase 4 — 운영화
15. systemd unit / Docker 이미지
16. 설정 백업·복원 (DB + configs)
17. Prometheus 메트릭 + Grafana 대시보드
18. HTTPS (nginx 리버스 프록시 가이드)
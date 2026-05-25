# EdgeSight Multi-Channel (AGX Orin)

NVIDIA **Jetson AGX Orin** 용 **다채널** 엣지 AI 영상 관제 시스템.
DeepStream(GStreamer) 의 batched 추론 + `nvstreamdemux` 기반 채널별 출력으로
**최대 8채널**을 동시에 처리한다. React 기반 관리자 UI 포함.

> 🚧 **상태**: agx (단일 채널) 버전을 베이스로 다채널 확장 진행 중.
> 현재 단계: **프론트엔드 다채널 UI + Mock 모드 완료** / 백엔드 작업 대기.

## 단일 채널(`../agx/`) 대비 변경점

| 영역 | agx (단일) | multi (이 폴더) |
|---|---|---|
| 입력 | 1 source | **N source** (RTSP/USB/video 혼용 가능) |
| 파이프라인 | streammux(batch=1) → infer → tracker → osd → enc | streammux(batch=N) → infer → tracker → **demux** → 채널별 osd/enc |
| 출력 | `/video_feed` 단일 MJPEG | `/video_feed/{channel_id}` 채널별 MJPEG |
| 메타 | `/ws/status` 단일 객체 | `/ws/status` `{channels: {id: meta}}` |
| 설정 모델 | `SystemConfig`에 `rtsp_url/input_source/video_filename` | **`Channel` 테이블** 별도, SystemConfig 는 전역 설정만 |

**default 2 채널, 최대 8 채널**. 채널 수는 웹 UI의 "📺 채널 관리" 모달에서 추가/삭제로 조절.

---

## 🖥️ GUI 단독 확인 모드 (백엔드 없이)

백엔드 다채널 리팩토링이 끝나기 전에 **프론트엔드만 미리 확인**할 수 있다.
브라우저에서 모든 동작(채널 추가/삭제, 그리드 전환, 모달 등)을 실제처럼 체험 가능.

```bash
cd multi/frontend
npm install
npm run dev:mock
# → http://localhost:5173
```

`VITE_USE_MOCK=true` 환경변수가 설정되어, 모든 API 호출이 in-memory mock 으로 라우팅된다.
화면 상단에 주황색 `MOCK 모드` 배너가 표시되어 일반 모드와 구분된다.

### Mock 모드 동작
- 채널 2개 기본 (RTSP 예시 URL)
- canvas 로 그린 가짜 프레임 (채널 ID/이름/입력 소스 배지/박스 오버레이)
- 객체는 시뮬레이션으로 천천히 움직임 (10Hz 갱신)
- 채널 추가/삭제/편집 모두 동작 (in-memory)
- 새로고침 시 초기 상태로 리셋

> Mock 데이터 정의: `src/api/mock.ts`

---

## 빠른 시작 (실 백엔드)

```bash
# 0. 사전 준비: JetPack 6.x (DeepStream 7.x, TensorRT 10.x, CUDA 12.x 포함) 설치된 Jetson
sudo apt install -y ffmpeg python3-gi gstreamer1.0-tools \
    gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly

# 1. 백엔드 (※ 다채널 백엔드 작업 진행 후 동작 가능)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

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
| 하드웨어 | NVIDIA Jetson AGX Orin (32GB 또는 64GB 권장 — 8채널 처리) |
| OS / SDK | JetPack 6.x (Ubuntu 22.04 + DeepStream 7.x + TensorRT 10.x) |
| Python | 3.10+ |
| Node.js | 20.x (frontend 빌드용) |

### 채널 수별 권장 환경 (예측치, 실측 필요)

| 채널 수 | 720p YOLOv8n INT8 | 비고 |
|---|---|---|
| 2 | ✅ 여유 | 권장 기본 |
| 4 | ✅ 안정적 | NVENC/NVJPG 여유 |
| 8 | ⚠️ 모델/입력 해상도에 따라 | AGX Orin 64GB 권장 |

---

## 프론트엔드 구조 (다채널 부분)

```
frontend/src/
├── api/
│   ├── types.ts         # Channel, MultiChannelStatus 등 신규 타입
│   ├── client.ts        # USE_MOCK 토글로 real/mock 라우팅
│   └── mock.ts          # ★ 백엔드 미존재 시 모킹 (channels CRUD, 메타 시뮬, canvas 프레임)
├── components/
│   ├── ChannelGrid.tsx  # ★ 채널 수에 따라 자동 그리드 레이아웃
│   ├── ChannelTile.tsx  # ★ 채널 1개 = 비디오 + 오버레이
│   ├── ChannelsModal.tsx # ★ 채널 CRUD UI
│   ├── ConfigModal.tsx  # ※ 입력 소스 필드 제거 (채널 모달로 이전)
│   ├── Header.tsx       # 채널 수 배지 + 채널 관리 버튼 추가
│   ├── StatusPanel.tsx  # 선택된 채널의 상세 표시
│   └── ModelModal.tsx   # (변경 없음)
└── hooks/
    ├── useChannels.ts   # ★ 신규 — 채널 CRUD wrapper
    └── useStatus.ts     # MultiChannelStatus 반환 (채널별 메타 dict)
```

---

## 백엔드 작업 (TODO)

| 단계 | 파일 | 작업 |
|---|---|---|
| DB | `core/database.py` | `Channel` 테이블 추가, 기존 SystemConfig 마이그레이션 |
| 상태 | `core/shared.py` | `frames` / `metas` 를 channel_id 키 dict 로 |
| 파이프라인 | `core/engine.py` | N source → batched streammux → **nvstreamdemux** → 채널별 osd/enc/appsink |
| API | `web/routes.py` | `/api/channels` CRUD, `/video_feed/{channel_id}`, multi-channel WS |
| 후처리 | `core/utils.py` | nvinfer config의 `batch-size` 동적 갱신 |

---

## 라이선스 / 의존성

- `backend/libnvdsinfer_custom_impl_Yolo.so` — [marcoslucianops/DeepStream-Yolo](https://github.com/marcoslucianops/DeepStream-Yolo) (MIT) 빌드본
- DeepStream / TensorRT / CUDA — NVIDIA 라이선스 (Jetson에 사전 설치)

# EdgeSight

NVIDIA Jetson 시리즈용 엣지 AI 영상 관제 시스템.
DeepStream(GStreamer) 기반 실시간 객체 탐지/트래킹과 React 기반 관리자 UI를 제공한다.

## 디바이스별 폴더

| 폴더 | 대상 디바이스 | 상태 |
|---|---|---|
| [`nano/`](nano/) | **Jetson Orin Nano** | ✅ 검증됨 (JetPack 6.x · DeepStream 7.1 · Python 3.10) |
| [`agx/`](agx/)   | **Jetson AGX Orin** | 🚧 nano 기반으로 시작, AGX 특화 진행 예정 |

각 폴더의 `README.md` 안에 디바이스별 설치/실행 가이드가 들어 있다.

```bash
# Jetson Orin Nano
cd nano && cat README.md

# Jetson AGX Orin
cd agx && cat README.md
```

## 공통 기능

- FastAPI 백엔드 + React 프론트엔드 + DeepStream 파이프라인
- 입력 소스 3종: RTSP / USB 웹캠 / 영상 파일(무한 반복)
- YOLOv8 `.pt` 자동 변환 (DeepStream 호환 ONNX → TensorRT FP16 engine)
- WebSocket 기반 실시간 메타데이터 푸시
- Bearer 토큰 인증 (선택)
- 한국어 / 영어 UI

## 두 디바이스의 차이 (계획)

| 항목 | Nano (현재) | AGX (예정) |
|---|---|---|
| 동시 카메라 | 1 ch | 다중 ch (`nvstreammux batch>1`) |
| 모델 크기 | YOLOv8n / s 중심 | YOLOv8m / l / x 가능 |
| 정밀도 | FP16 | FP16 / INT8 옵션 |
| 트래커 | IOU | NvDCF / NvDeepSORT 선택 |

> AGX 특화 변경은 `agx/` 폴더 내부에서 점진적으로 진행된다. 두 폴더의 공통 변경사항은 동기화하여 적용한다.

## 폴더 구조

```
EdgeSight/
├── nano/                 # Jetson Orin Nano용 (검증된 베이스라인)
│   ├── backend/
│   ├── frontend/
│   ├── README.md
│   └── REFERENCE_ANALYSIS.md
├── agx/                  # Jetson AGX Orin용
│   ├── backend/
│   ├── frontend/
│   ├── README.md
│   └── REFERENCE_ANALYSIS.md
├── README.md             # (이 파일) 디바이스 선택 가이드
└── .gitignore            # 양쪽 폴더 모두 적용되는 공통 패턴
```

## 라이선스 / 출처

- `*/backend/libnvdsinfer_custom_impl_Yolo.so` — [marcoslucianops/DeepStream-Yolo](https://github.com/marcoslucianops/DeepStream-Yolo) (MIT)
- DeepStream / TensorRT / CUDA — NVIDIA 라이선스 (Jetson SDK 사전 설치)

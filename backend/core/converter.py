"""YOLOv8 .pt → DeepStream 호환 ONNX → TensorRT .engine 변환 파이프라인.

ultralytics 패키지를 선택적 의존성으로 사용한다 (.pt 업로드 기능에만 필요).

- ONNX export 출력 형식은 marcoslucianops/DeepStream-Yolo (MIT License) 의
  utils/export_yoloV8.py 와 동일하다 (boxes / scores 분리 텐서).
  → libnvdsinfer_custom_impl_Yolo.so 의 NvDsInferParseYolo 후처리와 호환.
- TensorRT 엔진 빌드는 Jetson 표준 trtexec 명령을 subprocess 로 호출한다.
- EDGESIGHT_PT_EXPORT_SCRIPT 환경변수가 설정되면 외부 스크립트(예: 공식
  export_yoloV8.py)를 우선 사용한다.
- EDGESIGHT_TRTEXEC 로 trtexec 실행파일 경로를 override 할 수 있다.
"""

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from shutil import which
from typing import Callable, Optional, Tuple

logger = logging.getLogger(__name__)

ProgressCB = Optional[Callable[[int, str], None]]


# ----- 가용성 체크 -----

def is_ultralytics_available() -> bool:
    try:
        import ultralytics  # noqa: F401
        return True
    except Exception:
        return False


def find_trtexec() -> Optional[str]:
    """trtexec 실행파일 경로 탐색. 환경변수 > 표준 경로 > PATH 순."""
    env = os.environ.get("EDGESIGHT_TRTEXEC")
    if env and os.path.exists(env):
        return env

    standard = "/usr/src/tensorrt/bin/trtexec"
    if os.path.exists(standard):
        return standard

    found = which("trtexec")
    return found if found else None


# ----- 외부 스크립트 호출 (옵션) -----

def _custom_export_script() -> Optional[str]:
    p = os.environ.get("EDGESIGHT_PT_EXPORT_SCRIPT")
    if p and os.path.exists(p):
        return p
    return None


def _run_custom_export(
    script_path: str,
    pt_path: str,
    imgsz: int,
    opset: int,
) -> str:
    """공식 DeepStream-Yolo export_yoloV8.py 등 외부 스크립트로 ONNX 생성."""
    cmd = [
        sys.executable,
        script_path,
        "-w", pt_path,
        "--opset", str(opset),
        "--size", str(imgsz),
    ]
    logger.info("외부 export 스크립트: %s", " ".join(cmd))
    work_dir = os.path.dirname(pt_path) or "."
    result = subprocess.run(
        cmd, cwd=work_dir, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        tail = (result.stderr.strip() or result.stdout.strip())[-800:]
        raise RuntimeError(f"export 스크립트 실패 (rc={result.returncode}): {tail}")

    candidate = str(Path(pt_path).with_suffix(".onnx"))
    if not os.path.exists(candidate):
        raise RuntimeError(f"ONNX 생성 결과 없음: {candidate}")
    return os.path.abspath(candidate)


# ----- 자체 구현 DeepStream 호환 ONNX export -----

def _export_to_deepstream_onnx(pt_path: str, onnx_path: str, imgsz: int, opset: int) -> str:
    """YOLOv8 .pt → DeepStream-Yolo 호환 ONNX (자체 구현).

    출력 텐서:
      - boxes:  [1, num_anchors, 4]   (cx, cy, w, h)
      - scores: [1, num_anchors, num_classes]

    참고: marcoslucianops/DeepStream-Yolo (MIT License) utils/export_yoloV8.py
    의 출력 헤드 재구성 로직과 동일.
    """
    if not is_ultralytics_available():
        raise RuntimeError(
            "ultralytics 미설치 — `pip install ultralytics` 후 재시도하세요."
        )

    import torch
    from copy import deepcopy
    from ultralytics import YOLO

    class _DSOutput(torch.nn.Module):
        def forward(self, x):
            # x: [batch, 4 + num_classes, num_anchors]
            x = x.transpose(1, 2)  # → [batch, num_anchors, 4 + num_classes]
            boxes = x[:, :, :4]
            scores = x[:, :, 4:]
            return boxes, scores

    yolo = YOLO(pt_path)
    inner = deepcopy(yolo.model).float()
    inner.eval()

    # ultralytics Detect 헤드를 export 모드로 전환 (logits raw 출력)
    for m in inner.modules():
        if hasattr(m, "export"):
            m.export = True
            m.format = "onnx"
        if hasattr(m, "inplace"):
            m.inplace = False
        if hasattr(m, "dynamic"):
            m.dynamic = False

    wrapped = torch.nn.Sequential(inner, _DSOutput())
    wrapped.eval()

    dummy = torch.zeros(1, 3, imgsz, imgsz)

    with torch.no_grad():
        torch.onnx.export(
            wrapped,
            dummy,
            onnx_path,
            verbose=False,
            opset_version=opset,
            do_constant_folding=True,
            input_names=["input"],
            output_names=["boxes", "scores"],
        )

    # 단순화 (선택)
    try:
        import onnx
        try:
            import onnxsim
        except ImportError:
            onnxsim = None
        if onnxsim is not None:
            m = onnx.load(onnx_path)
            simp, ok = onnxsim.simplify(m)
            if ok:
                onnx.save(simp, onnx_path)
                logger.info("ONNX 단순화 완료")
    except Exception as e:
        logger.warning("ONNX 단순화 단계 건너뜀: %s", e)

    return os.path.abspath(onnx_path)


# ----- TensorRT engine 빌드 -----

def build_engine_from_onnx(
    onnx_path: str,
    engine_path: str,
    fp16: bool = True,
    workspace_mib: int = 2048,
) -> str:
    """trtexec subprocess 로 ONNX → TensorRT engine 직렬화.

    수 분 소요될 수 있다 (모델 크기, 디바이스 성능에 따라).
    """
    trtexec = find_trtexec()
    if not trtexec:
        raise RuntimeError(
            "trtexec 실행파일을 찾을 수 없습니다. "
            "Jetson 표준 경로(/usr/src/tensorrt/bin/trtexec) 또는 "
            "EDGESIGHT_TRTEXEC 환경변수로 경로를 지정하세요."
        )

    cmd = [
        trtexec,
        f"--onnx={os.path.abspath(onnx_path)}",
        f"--saveEngine={os.path.abspath(engine_path)}",
        f"--memPoolSize=workspace:{workspace_mib}",
    ]
    if fp16:
        cmd.append("--fp16")

    logger.info("trtexec 빌드 시작: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)

    # 일부 trtexec 버전은 --memPoolSize 미지원 → --workspace 로 재시도
    if result.returncode != 0 and "memPoolSize" in (result.stderr or ""):
        logger.warning("--memPoolSize 미지원 — --workspace 옵션으로 재시도")
        cmd = [
            trtexec,
            f"--onnx={os.path.abspath(onnx_path)}",
            f"--saveEngine={os.path.abspath(engine_path)}",
            f"--workspace={workspace_mib}",
        ]
        if fp16:
            cmd.append("--fp16")
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)

    if result.returncode != 0:
        tail = (result.stderr.strip() or result.stdout.strip())[-1200:]
        raise RuntimeError(f"trtexec 실패 (rc={result.returncode}): {tail}")

    if not os.path.exists(engine_path):
        raise RuntimeError(f"engine 파일이 생성되지 않았습니다: {engine_path}")

    logger.info("TensorRT engine 빌드 완료: %s", engine_path)
    return os.path.abspath(engine_path)


# ----- 통합 파이프라인 -----

def convert_pt_to_engine(
    pt_path: str,
    output_dir: str,
    imgsz: int = 640,
    opset: int = 12,
    fp16: bool = True,
    workspace_mib: int = 2048,
    progress_cb: ProgressCB = None,
) -> Tuple[str, str]:
    """전체 파이프라인: .pt → DeepStream 호환 .onnx → TensorRT .engine.

    Returns: (onnx_path, engine_path) — 둘 다 절대경로.
    progress_cb(progress: int, message: str) 로 단계별 진행률 보고.
    """
    if not os.path.exists(pt_path):
        raise FileNotFoundError(pt_path)

    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    name_no_ext = os.path.splitext(os.path.basename(pt_path))[0]
    onnx_path = os.path.join(output_dir, f"{name_no_ext}.onnx")
    engine_path = os.path.join(output_dir, f"{name_no_ext}.engine")

    def _report(p: int, msg: str):
        if progress_cb:
            progress_cb(p, msg)

    # 1) PT → ONNX
    custom_script = _custom_export_script()
    if custom_script:
        _report(15, "외부 export 스크립트로 ONNX 생성 중")
        produced = _run_custom_export(custom_script, pt_path, imgsz, opset)
    else:
        _report(15, "DeepStream 호환 ONNX export 중")
        produced = _export_to_deepstream_onnx(pt_path, onnx_path, imgsz, opset)

    # 결과를 onnx_path 위치로 정규화
    if os.path.abspath(produced) != onnx_path:
        shutil.move(produced, onnx_path)

    _report(45, "ONNX 변환 완료, TensorRT engine 빌드 시작 (수 분 소요)")

    # 2) ONNX → TensorRT engine
    build_engine_from_onnx(
        onnx_path, engine_path, fp16=fp16, workspace_mib=workspace_mib
    )

    _report(95, "engine 빌드 완료")
    return os.path.abspath(onnx_path), os.path.abspath(engine_path)

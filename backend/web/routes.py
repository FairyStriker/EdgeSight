import asyncio
import logging
import os
import shutil
import time

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from core.converter import convert_pt_to_engine
from core.database import AIModel, SessionLocal, SystemConfig
from core.jobs import Job, job_manager
from core.shared import state
from core.utils import create_engine_config, delete_generated_files
from web.auth import require_token

logger = logging.getLogger(__name__)
router = APIRouter()

MODEL_DIR = os.environ.get("EDGESIGHT_MODEL_DIR", "./models")
CONFIG_DIR = os.environ.get("EDGESIGHT_CONFIG_DIR", "./configs")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ----- 메타/스트림 -----

@router.get("/api/status")
def status():
    meta, seq = state.get_meta()
    return {**meta, "seq": seq}


@router.get("/api/healthz")
def healthz():
    return {"status": "ok"}


@router.get("/video_feed")
def video():
    def gen():
        # FIX(M4): 바이트 비교 대신 frame_seq 비교
        last_seq = -1
        while True:
            frame, seq = state.get_frame()
            if frame is None or seq == last_seq:
                time.sleep(0.01)
                continue
            yield (
                b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            )
            last_seq = seq

    return StreamingResponse(
        gen(), media_type="multipart/x-mixed-replace; boundary=frame"
    )


@router.websocket("/ws/status")
async def ws_status(websocket: WebSocket):
    """메타데이터 푸시 — meta_seq 변화 시점에만 송출."""
    await websocket.accept()
    last_seq = -1
    try:
        while True:
            meta, seq = state.get_meta()
            if seq != last_seq:
                await websocket.send_json({**meta, "seq": seq})
                last_seq = seq
            await asyncio.sleep(0.05)  # 최대 20Hz
    except WebSocketDisconnect:
        return
    except Exception as e:
        logger.warning("WS 종료: %s", e)
        try:
            await websocket.close()
        except Exception:
            pass


# ----- 설정 -----

@router.get("/api/config")
def get_config(db: Session = Depends(get_db)):
    c = db.query(SystemConfig).first()
    if c is None:
        return {}
    return {
        "rtsp_url": c.rtsp_url,
        "conf_threshold": c.conf_threshold,
        "iou_threshold": c.iou_threshold,
        "server_port": c.server_port,
        "language": c.language,
        "active_model_id": c.active_model_id,
    }


@router.post("/api/config/update", dependencies=[Depends(require_token)])
async def update_cfg(
    rtsp: str = Form(...),
    conf: float = Form(...),
    iou: float = Form(...),
    port: int = Form(...),
    language: str = Form(...),
    db: Session = Depends(get_db),
):
    c = db.query(SystemConfig).first()
    if c is None:
        raise HTTPException(500, "기본 설정 행이 없습니다.")
    c.rtsp_url = rtsp
    c.conf_threshold = conf
    c.iou_threshold = iou
    c.server_port = port
    c.language = language
    db.commit()

    state.update_config("rtsp_url", rtsp)
    state.update_config("conf", conf)
    state.update_config("iou", iou)
    # FIX(M5): language도 state에 반영
    state.update_config("language", language)
    return {"status": "ok"}


# ----- 모델 -----

@router.get("/api/model/list")
def model_list(db: Session = Depends(get_db)):
    ms = db.query(AIModel).order_by(AIModel.uploaded_at.desc()).all()
    cfg = db.query(SystemConfig).first()
    return {
        "active_model_id": cfg.active_model_id if cfg else None,
        "models": [
            {
                "id": m.id,
                "filename": m.filename,
                "uploaded_at": m.uploaded_at.strftime("%Y-%m-%d %H:%M"),
            }
            for m in ms
        ],
    }


@router.post("/api/model/upload", dependencies=[Depends(require_token)])
async def upload_model(
    file: UploadFile = File(...),
    class_names: str = Form(...),
    db: Session = Depends(get_db),
):
    if not file.filename or not file.filename.endswith(".engine"):
        raise HTTPException(400, "확장자는 .engine 이어야 합니다.")

    # FIX(C4): path traversal 방지
    safe_name = os.path.basename(file.filename)
    if safe_name != file.filename or "/" in safe_name or "\\" in safe_name:
        raise HTTPException(400, "허용되지 않는 파일명입니다.")

    os.makedirs(MODEL_DIR, exist_ok=True)
    os.makedirs(CONFIG_DIR, exist_ok=True)

    # 동일 파일명 중복 검사 (UNIQUE 제약 충돌을 사용자에게 친절히 전달)
    existing = db.query(AIModel).filter(AIModel.filename == safe_name).first()
    if existing:
        raise HTTPException(409, "동일한 파일명이 이미 존재합니다.")

    model_path = os.path.abspath(os.path.join(MODEL_DIR, safe_name))
    generated_config_path = None
    try:
        with open(model_path, "wb+") as buffer:
            shutil.copyfileobj(file.file, buffer)

        current_config = db.query(SystemConfig).first()
        cur_conf = current_config.conf_threshold if current_config else 0.25
        cur_iou = current_config.iou_threshold if current_config else 0.45

        generated_config_path, _ = create_engine_config(
            safe_name, MODEL_DIR, CONFIG_DIR, class_names, cur_conf, cur_iou
        )

        new_model = AIModel(
            filename=safe_name,
            filepath=model_path,
            config_filepath=generated_config_path,
        )
        db.add(new_model)
        db.commit()
        return {"status": "success"}
    except Exception as e:
        # FIX(M6): 부분 실패 시 정리
        logger.exception("모델 업로드 실패: %s", e)
        if os.path.exists(model_path):
            try:
                os.remove(model_path)
            except Exception:
                pass
        if generated_config_path:
            delete_generated_files(generated_config_path)
        raise HTTPException(500, "업로드 중 오류가 발생했습니다.") from e


@router.post("/api/model/select/{mid}", dependencies=[Depends(require_token)])
def sel_model(mid: int, db: Session = Depends(get_db)):
    m = db.query(AIModel).filter(AIModel.id == mid).first()
    if not m:
        raise HTTPException(404, "모델을 찾을 수 없습니다.")
    c = db.query(SystemConfig).first()
    # FIX(C2): SystemConfig 미존재 NPE 가드
    if c is None:
        raise HTTPException(500, "기본 설정 행이 없습니다.")
    c.active_model_id = m.id
    db.commit()
    state.update_config("config_path", m.config_filepath)
    return {"status": "ok"}


def _extract_class_names_from_pt(pt_path: str) -> str:
    """.pt 파일의 model.names 메타데이터에서 클래스 이름을 추출해 콤마 문자열로 반환."""
    try:
        import torch
        ckpt = torch.load(pt_path, map_location="cpu", weights_only=False)
        m = ckpt.get("model") or ckpt.get("ema")
        names = getattr(m, "names", None) if m is not None else None
        if not names:
            return ""
        if isinstance(names, dict):
            ordered = [names[k] for k in sorted(names.keys())]
        else:
            ordered = list(names)
        return ",".join(str(n) for n in ordered)
    except Exception as e:
        logger.warning("pt 클래스 자동 추출 실패: %s", e)
        return ""


@router.post("/api/model/upload_pt", dependencies=[Depends(require_token)])
async def upload_pt(
    file: UploadFile = File(...),
    class_names: str = Form(""),
    imgsz: int = Form(640),
    db: Session = Depends(get_db),
):
    """YOLOv8 .pt 업로드 → ONNX 변환 → 모델 등록 (비동기 작업).

    class_names가 비어있으면 .pt의 model.names 메타데이터에서 자동 추출.
    실제 .engine 파일은 nvinfer가 첫 추론 시 자동으로 빌드한다.
    """
    if not file.filename or not file.filename.endswith(".pt"):
        raise HTTPException(400, "확장자는 .pt 이어야 합니다.")

    safe_name = os.path.basename(file.filename)
    if safe_name != file.filename or "/" in safe_name or "\\" in safe_name:
        raise HTTPException(400, "허용되지 않는 파일명입니다.")

    name_no_ext = os.path.splitext(safe_name)[0]
    engine_filename = f"{name_no_ext}.engine"

    existing = db.query(AIModel).filter(AIModel.filename == engine_filename).first()
    if existing:
        raise HTTPException(409, "동일한 모델 이름이 이미 존재합니다.")

    os.makedirs(MODEL_DIR, exist_ok=True)
    os.makedirs(CONFIG_DIR, exist_ok=True)

    pt_path = os.path.abspath(os.path.join(MODEL_DIR, safe_name))
    with open(pt_path, "wb+") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # class_names 미제공 시 .pt 메타데이터에서 자동 추출
    if not class_names.strip():
        auto_names = _extract_class_names_from_pt(pt_path)
        if not auto_names:
            os.remove(pt_path)
            raise HTTPException(
                400,
                ".pt 파일에서 클래스 이름을 추출할 수 없습니다. class_names를 직접 입력해주세요.",
            )
        class_names = auto_names
        logger.info("class_names 자동 추출: %s", class_names)

    job = job_manager.create("pt_to_engine", safe_name)

    def do_convert(job: Job):
        bg_db = SessionLocal()
        generated_config_path = None
        onnx_path = None
        engine_path = None
        try:
            def report(p: int, msg: str):
                job_manager.update(job.id, progress=p, message=msg)

            report(10, "PT 저장 완료, 변환 준비")

            # 1) .pt → DeepStream 호환 .onnx → TensorRT .engine
            onnx_path, engine_path = convert_pt_to_engine(
                pt_path,
                MODEL_DIR,
                imgsz=imgsz,
                progress_cb=report,
            )

            # 2) nvinfer config + 라벨 파일 생성
            report(96, "config / 라벨 파일 생성 중")
            cfg = bg_db.query(SystemConfig).first()
            cur_conf = cfg.conf_threshold if cfg else 0.25
            cur_iou = cfg.iou_threshold if cfg else 0.45

            generated_config_path, _ = create_engine_config(
                engine_filename,
                MODEL_DIR,
                CONFIG_DIR,
                class_names,
                cur_conf,
                cur_iou,
                onnx_path=onnx_path,  # 재빌드 시 fallback
            )

            # 3) DB 등록
            report(99, "DB 등록 중")
            new_model = AIModel(
                filename=engine_filename,
                filepath=engine_path,
                config_filepath=generated_config_path,
            )
            bg_db.add(new_model)
            bg_db.commit()
            bg_db.refresh(new_model)

            job_manager.update(
                job.id,
                status="completed",
                progress=100,
                message="변환 완료 — engine/config/label 모두 생성됨",
                model_id=new_model.id,
            )
        except Exception as e:
            # 부분 결과 정리
            for p in (pt_path, onnx_path, engine_path, generated_config_path):
                if p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass
            job_manager.update(job.id, status="failed", error=str(e))
        finally:
            bg_db.close()

    job_manager.run_async(job, do_convert)
    return {"job_id": job.id}


@router.get("/api/jobs")
def list_jobs():
    return {"jobs": job_manager.list()}


@router.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    j = job_manager.get(job_id)
    if not j:
        raise HTTPException(404, "작업을 찾을 수 없습니다.")
    return j.to_dict()


@router.delete("/api/model/{mid}", dependencies=[Depends(require_token)])
def del_model(mid: int, db: Session = Depends(get_db)):
    c = db.query(SystemConfig).first()
    # FIX(C2): SystemConfig None 가드
    if c is not None and c.active_model_id == mid:
        raise HTTPException(400, "현재 활성화된 모델은 삭제할 수 없습니다.")

    m = db.query(AIModel).filter(AIModel.id == mid).first()
    if m:
        if m.filepath and os.path.exists(m.filepath):
            try:
                os.remove(m.filepath)
                logger.info("엔진 파일 삭제: %s", m.filepath)
            except Exception as e:
                logger.warning("엔진 파일 삭제 실패: %s", e)

        if m.config_filepath:
            delete_generated_files(m.config_filepath)

        db.delete(m)
        db.commit()
    return {"status": "ok"}

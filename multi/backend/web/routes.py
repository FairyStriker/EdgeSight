import asyncio
import logging
import os
import shutil
import subprocess
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
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.converter import convert_pt_to_engine
from core.database import (
    MAX_CHANNELS,
    AIModel,
    Channel,
    DemoVideo,
    SessionLocal,
    SystemConfig,
    channels_to_dicts,
)
from core.jobs import Job, job_manager
from core.shared import state
from core.utils import create_engine_config, delete_generated_files
from web.auth import require_token

logger = logging.getLogger(__name__)
router = APIRouter()

MODEL_DIR = os.environ.get("EDGESIGHT_MODEL_DIR", "./models")
CONFIG_DIR = os.environ.get("EDGESIGHT_CONFIG_DIR", "./configs")
VIDEO_DIR = os.environ.get("EDGESIGHT_VIDEO_DIR", "./videos")

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".m4v"}
ALLOWED_INPUT_SOURCES = {"rtsp", "usb", "video"}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _refresh_state_channels(db: Session) -> list[dict]:
    """DB → state.config['channels'] 동기화. 엔진 감시 루프가 차이를 감지해 재시작."""
    chs = db.query(Channel).order_by(Channel.position.asc(), Channel.id.asc()).all()
    snapshot = channels_to_dicts(chs)
    state.set_channels(snapshot)
    return snapshot


# ========== 메타 / 스트림 ==========

@router.get("/api/status")
def status():
    """모든 채널의 최신 메타 스냅샷 (폴링용)."""
    metas, seq = state.snapshot_metas()
    return {"channels": metas, "seq": seq}


@router.get("/api/healthz")
def healthz():
    return {"status": "ok"}


@router.get("/video_feed/{channel_id}")
def video(channel_id: int):
    """채널별 MJPEG 스트림."""

    def gen():
        last_seq = -1
        while True:
            frame, seq = state.get_frame(channel_id)
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
    """모든 채널 메타 푸시 — global_meta_seq 변화 시점에만 송출."""
    await websocket.accept()
    last_seq = -1
    try:
        while True:
            metas, seq = state.snapshot_metas()
            if seq != last_seq:
                await websocket.send_json({"channels": metas, "seq": seq})
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


# ========== 시스템 설정 (전역) ==========

@router.get("/api/config")
def get_config(db: Session = Depends(get_db)):
    c = db.query(SystemConfig).first()
    if c is None:
        return {}
    return {
        "conf_threshold": c.conf_threshold,
        "iou_threshold": c.iou_threshold,
        "server_port": c.server_port,
        "language": c.language,
        "active_model_id": c.active_model_id,
    }


@router.post("/api/config/update", dependencies=[Depends(require_token)])
async def update_cfg(
    conf: float = Form(...),
    iou: float = Form(...),
    port: int = Form(...),
    language: str = Form(...),
    db: Session = Depends(get_db),
):
    c = db.query(SystemConfig).first()
    if c is None:
        raise HTTPException(500, "기본 설정 행이 없습니다.")

    c.conf_threshold = conf
    c.iou_threshold = iou
    c.server_port = port
    c.language = language
    db.commit()

    state.update_config("conf", conf)
    state.update_config("iou", iou)
    state.update_config("language", language)
    return {"status": "ok"}


# ========== 채널 CRUD ==========

class ChannelIn(BaseModel):
    name: str = Field(default="Channel", max_length=100)
    input_source: str = Field(default="rtsp")
    source_uri: str = Field(default="")
    video_filename: str | None = None
    enabled: bool = True


class ChannelPatch(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    input_source: str | None = None
    source_uri: str | None = None
    video_filename: str | None = None
    enabled: bool | None = None
    position: int | None = None


class ReorderIn(BaseModel):
    ids: list[int]


def _channel_to_response(c: Channel) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "input_source": c.input_source,
        "source_uri": c.source_uri or "",
        "video_filename": c.video_filename,
        "enabled": bool(c.enabled),
        "position": c.position,
    }


def _validate_channel_input(
    db: Session,
    input_source: str,
    video_filename: str | None,
):
    if input_source not in ALLOWED_INPUT_SOURCES:
        raise HTTPException(400, f"input_source 값이 잘못되었습니다: {input_source}")
    if input_source == "video":
        if not video_filename:
            raise HTTPException(400, "video 모드에는 video_filename 이 필요합니다.")
        v = db.query(DemoVideo).filter(DemoVideo.filename == video_filename).first()
        if v is None:
            raise HTTPException(404, "선택한 영상이 존재하지 않습니다.")


@router.get("/api/channels")
def list_channels(db: Session = Depends(get_db)):
    chs = db.query(Channel).order_by(Channel.position.asc(), Channel.id.asc()).all()
    return {
        "channels": [_channel_to_response(c) for c in chs],
        "max_channels": MAX_CHANNELS,
    }


@router.post("/api/channels", dependencies=[Depends(require_token)])
def create_channel(body: ChannelIn, db: Session = Depends(get_db)):
    n = db.query(Channel).count()
    if n >= MAX_CHANNELS:
        raise HTTPException(
            400, f"최대 {MAX_CHANNELS}개 채널까지만 추가할 수 있습니다."
        )
    _validate_channel_input(db, body.input_source, body.video_filename)

    ch = Channel(
        name=body.name.strip() or "Channel",
        input_source=body.input_source,
        source_uri=(body.source_uri or "").strip() if body.input_source != "video" else "",
        video_filename=body.video_filename if body.input_source == "video" else None,
        enabled=body.enabled,
        position=n,
    )
    db.add(ch)
    db.commit()
    db.refresh(ch)
    _refresh_state_channels(db)
    return _channel_to_response(ch)


@router.put("/api/channels/{channel_id}", dependencies=[Depends(require_token)])
def update_channel(
    channel_id: int, patch: ChannelPatch, db: Session = Depends(get_db)
):
    ch = db.query(Channel).filter(Channel.id == channel_id).first()
    if ch is None:
        raise HTTPException(404, "채널을 찾을 수 없습니다.")

    new_src = patch.input_source if patch.input_source is not None else ch.input_source
    new_video = patch.video_filename if patch.video_filename is not None else ch.video_filename
    _validate_channel_input(db, new_src, new_video if new_src == "video" else None)

    if patch.name is not None:
        ch.name = patch.name.strip() or ch.name
    if patch.input_source is not None:
        ch.input_source = patch.input_source
    if patch.source_uri is not None:
        ch.source_uri = patch.source_uri.strip()
    if patch.video_filename is not None:
        ch.video_filename = patch.video_filename
    if patch.enabled is not None:
        ch.enabled = patch.enabled
    if patch.position is not None and patch.position >= 0:
        ch.position = patch.position

    # video 모드가 아니면 video_filename 비우기, video 모드면 source_uri 비우기
    if ch.input_source != "video":
        ch.video_filename = None
    else:
        ch.source_uri = ""

    db.commit()
    db.refresh(ch)
    _refresh_state_channels(db)
    # 채널 비활성/소스 변경 시 잔여 프레임 정리
    state.drop_frame(ch.id)
    state.drop_meta(ch.id)
    return _channel_to_response(ch)


@router.delete("/api/channels/{channel_id}", dependencies=[Depends(require_token)])
def delete_channel(channel_id: int, db: Session = Depends(get_db)):
    n = db.query(Channel).count()
    if n <= 1:
        raise HTTPException(400, "채널은 최소 1개 이상 유지해야 합니다.")
    ch = db.query(Channel).filter(Channel.id == channel_id).first()
    if ch is None:
        raise HTTPException(404, "채널을 찾을 수 없습니다.")
    deleted_pos = ch.position
    db.delete(ch)
    # position 압축 (deleted_pos 이후 채널의 position -1)
    later = (
        db.query(Channel)
        .filter(Channel.position > deleted_pos)
        .order_by(Channel.position.asc())
        .all()
    )
    for c in later:
        c.position -= 1
    db.commit()

    state.drop_frame(channel_id)
    state.drop_meta(channel_id)
    _refresh_state_channels(db)
    return {"status": "ok"}


@router.post("/api/channels/reorder", dependencies=[Depends(require_token)])
def reorder_channels(body: ReorderIn, db: Session = Depends(get_db)):
    id_set = set(body.ids)
    chs = db.query(Channel).filter(Channel.id.in_(id_set)).all()
    if len(chs) != len(id_set):
        raise HTTPException(400, "존재하지 않는 채널 ID 가 포함되어 있습니다.")
    by_id = {c.id: c for c in chs}
    for pos, ch_id in enumerate(body.ids):
        by_id[ch_id].position = pos
    db.commit()
    _refresh_state_channels(db)
    return {"status": "ok"}


# ========== 데모 영상 ==========

def _gst_nvenc_normalize(src_path: str, dst_path: str) -> None:
    """AGX NVENC 하드웨어 인코더로 영상 정규화 (nvv4l2h264enc)."""
    src_uri = "file://" + os.path.abspath(src_path)
    out_path = os.path.abspath(dst_path)
    cmd = [
        "gst-launch-1.0", "-e",
        "uridecodebin", f"uri={src_uri}",
        "!",
        "nvvideoconvert",
        "!",
        "video/x-raw(memory:NVMM),format=NV12",
        "!",
        "nvv4l2h264enc",
        "maxperf-enable=1",
        "profile=2",            # main profile
        "iframeinterval=30",
        "!",
        "h264parse",
        "!",
        "qtmux",
        "!",
        "filesink", f"location={out_path}",
    ]
    logger.info("GStreamer NVENC 정규화 시작: %s -> %s", src_path, out_path)
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        tail = (result.stderr.strip() or result.stdout.strip())[-1200:]
        raise RuntimeError(f"GStreamer NVENC 변환 실패 (rc={result.returncode}): {tail}")
    if not os.path.exists(dst_path):
        raise RuntimeError(f"GStreamer NVENC 변환 결과 없음: {dst_path}")


def _ffmpeg_normalize(src_path: str, dst_path: str) -> None:
    cmd = [
        "ffmpeg", "-y", "-i", src_path,
        "-c:v", "libx264",
        "-profile:v", "main",
        "-level", "4.1",
        "-pix_fmt", "yuv420p",
        "-g", "30", "-keyint_min", "30",
        "-an",
        dst_path,
    ]
    logger.info("ffmpeg 정규화 시작: %s -> %s", src_path, dst_path)
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        tail = (result.stderr.strip() or result.stdout.strip())[-1200:]
        raise RuntimeError(f"ffmpeg 변환 실패 (rc={result.returncode}): {tail}")
    if not os.path.exists(dst_path):
        raise RuntimeError(f"ffmpeg 변환 결과 없음: {dst_path}")


def _normalize_video(src_path: str, dst_path: str) -> str:
    """AGX: NVENC 우선, 실패 시 ffmpeg/libx264 fallback."""
    try:
        _gst_nvenc_normalize(src_path, dst_path)
        return "NVENC (nvv4l2h264enc)"
    except Exception as e:
        logger.warning("NVENC 실패 → ffmpeg fallback: %s", e)
        if os.path.exists(dst_path):
            try:
                os.remove(dst_path)
            except Exception:
                pass
        _ffmpeg_normalize(src_path, dst_path)
        return "libx264 (CPU, fallback)"


@router.get("/api/video/list")
def video_list(db: Session = Depends(get_db)):
    vs = db.query(DemoVideo).order_by(DemoVideo.uploaded_at.desc()).all()
    return {
        "videos": [
            {
                "id": v.id,
                "filename": v.filename,
                "uploaded_at": v.uploaded_at.strftime("%Y-%m-%d %H:%M"),
            }
            for v in vs
        ]
    }


@router.post("/api/video/upload", dependencies=[Depends(require_token)])
async def upload_video(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(400, "파일이 비어있습니다.")
    safe_name = os.path.basename(file.filename)
    if safe_name != file.filename or "/" in safe_name or "\\" in safe_name:
        raise HTTPException(400, "허용되지 않는 파일명입니다.")

    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in VIDEO_EXTS:
        raise HTTPException(400, f"허용되지 않는 확장자입니다: {ext}")

    base_name = os.path.splitext(safe_name)[0]
    final_filename = base_name + ".mp4"
    if db.query(DemoVideo).filter(DemoVideo.filename == final_filename).first():
        raise HTTPException(409, "동일한 영상 파일명이 이미 존재합니다.")

    os.makedirs(VIDEO_DIR, exist_ok=True)
    tmp_path = os.path.abspath(os.path.join(VIDEO_DIR, "_uploading_" + safe_name))
    final_path = os.path.abspath(os.path.join(VIDEO_DIR, final_filename))

    with open(tmp_path, "wb+") as buffer:
        shutil.copyfileobj(file.file, buffer)

    job = job_manager.create("video_normalize", final_filename)

    def do_convert(job: Job):
        bg_db = SessionLocal()
        try:
            def report(p: int, msg: str):
                job_manager.update(job.id, progress=p, message=msg)

            report(10, "업로드 완료, 정규화 시작 (NVENC 우선)")
            encoder_used = _normalize_video(tmp_path, final_path)
            report(85, f"변환 완료 ({encoder_used}), 원본 정리")

            try:
                os.remove(tmp_path)
            except Exception:
                pass

            report(95, "DB 등록 중")
            bg_db.add(DemoVideo(filename=final_filename, filepath=final_path))
            bg_db.commit()

            job_manager.update(
                job.id, status="completed", progress=100,
                message="정규화 + 등록 완료",
            )
        except Exception as e:
            logger.exception("영상 변환 실패: %s", e)
            for p in (tmp_path, final_path):
                if p and os.path.exists(p):
                    try: os.remove(p)
                    except Exception: pass
            job_manager.update(job.id, status="failed", error=str(e))
        finally:
            bg_db.close()

    job_manager.run_async(job, do_convert)
    return {"job_id": job.id}


@router.delete("/api/video/{vid}", dependencies=[Depends(require_token)])
def del_video(vid: int, db: Session = Depends(get_db)):
    v = db.query(DemoVideo).filter(DemoVideo.id == vid).first()
    if not v:
        raise HTTPException(404, "영상을 찾을 수 없습니다.")

    # 현재 사용 중인 채널이 있으면 video_filename NULL 처리
    affected = (
        db.query(Channel)
        .filter(Channel.input_source == "video", Channel.video_filename == v.filename)
        .all()
    )
    for ch in affected:
        ch.video_filename = None
        logger.info("영상 삭제로 채널 %s video_filename 해제", ch.id)
    if affected:
        db.commit()
        _refresh_state_channels(db)

    if v.filepath and os.path.exists(v.filepath):
        try:
            os.remove(v.filepath)
        except Exception as e:
            logger.warning("영상 파일 삭제 실패: %s", e)

    db.delete(v)
    db.commit()
    return {"status": "ok"}


# ========== 모델 ==========

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

    safe_name = os.path.basename(file.filename)
    if safe_name != file.filename or "/" in safe_name or "\\" in safe_name:
        raise HTTPException(400, "허용되지 않는 파일명입니다.")

    os.makedirs(MODEL_DIR, exist_ok=True)
    os.makedirs(CONFIG_DIR, exist_ok=True)

    if db.query(AIModel).filter(AIModel.filename == safe_name).first():
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

        db.add(AIModel(
            filename=safe_name,
            filepath=model_path,
            config_filepath=generated_config_path,
        ))
        db.commit()
        return {"status": "success"}
    except Exception as e:
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
    if c is None:
        raise HTTPException(500, "기본 설정 행이 없습니다.")
    c.active_model_id = m.id
    db.commit()
    state.update_config("config_path", m.config_filepath)
    return {"status": "ok"}


def _extract_class_names_from_pt(pt_path: str) -> str:
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
    if not file.filename or not file.filename.endswith(".pt"):
        raise HTTPException(400, "확장자는 .pt 이어야 합니다.")

    safe_name = os.path.basename(file.filename)
    if safe_name != file.filename or "/" in safe_name or "\\" in safe_name:
        raise HTTPException(400, "허용되지 않는 파일명입니다.")

    name_no_ext = os.path.splitext(safe_name)[0]
    engine_filename = f"{name_no_ext}.engine"

    if db.query(AIModel).filter(AIModel.filename == engine_filename).first():
        raise HTTPException(409, "동일한 모델 이름이 이미 존재합니다.")

    os.makedirs(MODEL_DIR, exist_ok=True)
    os.makedirs(CONFIG_DIR, exist_ok=True)

    pt_path = os.path.abspath(os.path.join(MODEL_DIR, safe_name))
    with open(pt_path, "wb+") as buffer:
        shutil.copyfileobj(file.file, buffer)

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

            onnx_path, engine_path = convert_pt_to_engine(
                pt_path,
                MODEL_DIR,
                imgsz=imgsz,
                progress_cb=report,
            )

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
                onnx_path=onnx_path,
            )

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

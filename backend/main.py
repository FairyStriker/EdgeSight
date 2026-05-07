import logging
import os
import signal
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from core.database import SessionLocal, SystemConfig, ensure_default_config, init_db
from core.engine import AIEngine
from core.shared import state
from web.routes import router

logging.basicConfig(
    level=os.environ.get("EDGESIGHT_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("edgesight")

BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


def load_settings() -> int:
    cfg = ensure_default_config()
    state.update_config("rtsp_url", cfg.rtsp_url)
    state.update_config("conf", cfg.conf_threshold)
    state.update_config("iou", cfg.iou_threshold)
    state.update_config("language", cfg.language)
    if cfg.active_model:
        state.update_config("config_path", cfg.active_model.config_filepath)
    return cfg.server_port


engine_thread: AIEngine | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global engine_thread
    init_db()
    load_settings()

    if not os.environ.get("EDGESIGHT_TOKEN"):
        logger.warning(
            "EDGESIGHT_TOKEN 미설정 — 쓰기 엔드포인트 인증이 비활성화됩니다(개발 모드)."
        )

    engine_thread = AIEngine()
    engine_thread.start()
    logger.info("AIEngine 시작")

    try:
        yield
    finally:
        # FIX(M3): graceful shutdown — 엔진/파이프라인 정리
        logger.info("종료 신호 수신 — 엔진 정리 중")
        if engine_thread is not None:
            engine_thread.shutdown()
            engine_thread.join(timeout=5)
        logger.info("종료 완료")


app = FastAPI(title="EdgeSight", lifespan=lifespan)

# 개발 시 Vite dev server(5173)에서 호출하는 경우를 위한 CORS
allowed_origins = os.environ.get(
    "EDGESIGHT_CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173",
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in allowed_origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


# 빌드된 React 정적 파일 서빙 (단일 서버 모드)
if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/")
    async def index():
        return FileResponse(FRONTEND_DIST / "index.html")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        # API/WS/스트림 경로는 위쪽 router에서 처리됨. 나머지는 SPA로 fallback.
        target = FRONTEND_DIST / full_path
        if target.is_file():
            return FileResponse(target)
        return FileResponse(FRONTEND_DIST / "index.html")
else:
    logger.warning(
        "frontend/dist 가 없습니다 — `cd frontend && npm run build` 후 다시 실행하세요."
    )


def _install_signal_handlers():
    def handler(signum, _frame):
        logger.info("시그널 %s 수신", signum)
        # uvicorn이 lifespan을 통해 cleanup 호출하도록 SIGINT/SIGTERM 기본 동작 사용
        sys.exit(0)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, handler)
        except Exception:
            pass


if __name__ == "__main__":
    _install_signal_handlers()
    # FIX: lifespan 진입 전에 port를 읽어야 하므로 DB 초기화를 먼저 수행
    init_db()
    db = SessionLocal()
    try:
        cfg = db.query(SystemConfig).first()
        port = cfg.server_port if cfg else 8000
    finally:
        db.close()
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("EDGESIGHT_PORT", port)),
        access_log=False,
    )

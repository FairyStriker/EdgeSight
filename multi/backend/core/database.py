import logging
import os
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import declarative_base, joinedload, relationship, sessionmaker

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("EDGESIGHT_DB_URL", "sqlite:///./edge_system.db")

# 다채널 상한 — 8 이상으로 늘리려면 환경변수로 오버라이드.
# 프론트엔드에 그대로 노출되어 +채널 버튼 비활성 기준이 된다.
MAX_CHANNELS = int(os.environ.get("EDGESIGHT_MAX_CHANNELS", "8"))

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class AIModel(Base):
    __tablename__ = "ai_models"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, unique=True, index=True)
    filepath = Column(String)
    config_filepath = Column(String, nullable=True)
    uploaded_at = Column(DateTime, default=datetime.now)


class SystemConfig(Base):
    """전역 설정. input_source / rtsp_url / video_filename 은 Channel 로 이전됨.
    기존 DB의 옛 컬럼은 SQLite 한계상 그대로 남지만 ORM 정의에서는 제거되어
    더 이상 읽기/쓰기 되지 않는다."""

    __tablename__ = "system_config"
    id = Column(Integer, primary_key=True, index=True)
    language = Column(String, default="ko")
    server_port = Column(Integer, default=8000)
    conf_threshold = Column(Float, default=0.25)
    iou_threshold = Column(Float, default=0.45)
    active_model_id = Column(Integer, ForeignKey("ai_models.id"), nullable=True)
    active_model = relationship("AIModel")


class Channel(Base):
    """입력 채널 1개 = 1개의 source.
    DeepStream nvstreammux 의 sink_{i} 패드에 매핑된다 (i = enabled 채널 정렬 순서)."""

    __tablename__ = "channels"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String, default="Channel")
    # rtsp | usb | video
    input_source = Column(String, default="rtsp")
    # RTSP URL 또는 USB device 경로(/dev/video0). video 모드에서는 빈 문자열.
    source_uri = Column(String, default="")
    # video 모드 시 demo_videos.filename 참조 (ffmpeg 정규화 후의 .mp4)
    video_filename = Column(String, nullable=True)
    enabled = Column(Boolean, default=True)
    position = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)


class DemoVideo(Base):
    __tablename__ = "demo_videos"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, unique=True, index=True)
    filepath = Column(String)
    uploaded_at = Column(DateTime, default=datetime.now)


def _ensure_columns():
    """가벼운 마이그레이션 — 누락된 컬럼만 ALTER TABLE 로 보충."""
    inspector = inspect(engine)
    tables = inspector.get_table_names()

    if "system_config" in tables:
        cols = {c["name"] for c in inspector.get_columns("system_config")}
        with engine.begin() as conn:
            if "language" not in cols:
                logger.warning("system_config.language 추가")
                conn.execute(
                    text("ALTER TABLE system_config ADD COLUMN language VARCHAR DEFAULT 'ko'")
                )


def init_db():
    Base.metadata.create_all(bind=engine)
    _ensure_columns()


def ensure_default_config():
    """SystemConfig 행이 없으면 기본값으로 한 줄 생성.
    session 종료 후 active_model 관계 접근을 위해 joinedload + expunge."""
    db = SessionLocal()
    try:
        cfg = (
            db.query(SystemConfig)
            .options(joinedload(SystemConfig.active_model))
            .first()
        )
        if cfg is None:
            cfg = SystemConfig()
            db.add(cfg)
            db.commit()
            db.refresh(cfg)
        db.expunge(cfg)
        return cfg
    finally:
        db.close()


def ensure_default_channels():
    """채널이 0개면 기본 채널을 생성.

    1) 기존 단일 채널 DB(`system_config.rtsp_url` / `input_source` / `video_filename`)에
       값이 있으면 그 값으로 Channel 1개 자동 마이그레이션.
    2) 그렇지 않으면 기본 2채널(빈 RTSP) 생성.
    """
    db = SessionLocal()
    try:
        if db.query(Channel).count() > 0:
            return

        legacy = _try_read_legacy_config()
        if legacy and (legacy.get("rtsp_url") or legacy.get("video_filename")):
            ch = Channel(
                name="Channel 1",
                input_source=legacy.get("input_source") or "rtsp",
                source_uri=legacy.get("rtsp_url") or "",
                video_filename=legacy.get("video_filename"),
                enabled=True,
                position=0,
            )
            db.add(ch)
            db.commit()
            logger.info("기존 단일 채널 설정에서 채널 자동 마이그레이션")
        else:
            for i in range(2):
                db.add(
                    Channel(
                        name=f"Channel {i + 1}",
                        input_source="rtsp",
                        source_uri="",
                        enabled=True,
                        position=i,
                    )
                )
            db.commit()
            logger.info("기본 2채널 생성 (빈 RTSP)")
    finally:
        db.close()


def _try_read_legacy_config() -> dict | None:
    """`system_config` 의 옛 컬럼(rtsp_url 등)을 raw SQL 로 읽기 시도.
    컬럼이 없거나 행이 없으면 None 반환."""
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT rtsp_url, input_source, video_filename "
                    "FROM system_config LIMIT 1"
                )
            ).fetchone()
        if not row:
            return None
        return {
            "rtsp_url": row[0],
            "input_source": row[1],
            "video_filename": row[2],
        }
    except Exception:
        return None


def channels_to_dicts(channels: list[Channel]) -> list[dict]:
    """Channel ORM → 엔진/프론트가 사용하는 직렬화 형태."""
    return [
        {
            "id": c.id,
            "name": c.name,
            "input_source": c.input_source,
            "source_uri": c.source_uri or "",
            "video_filename": c.video_filename,
            "enabled": bool(c.enabled),
            "position": c.position,
        }
        for c in channels
    ]


def load_channels_sorted() -> list[dict]:
    """현재 채널을 position 정렬해 dict 리스트로 반환."""
    db = SessionLocal()
    try:
        chs = db.query(Channel).order_by(Channel.position.asc(), Channel.id.asc()).all()
        return channels_to_dicts(chs)
    finally:
        db.close()

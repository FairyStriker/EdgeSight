import logging
import os
from datetime import datetime

from sqlalchemy import (
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
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("EDGESIGHT_DB_URL", "sqlite:///./edge_system.db")

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
    __tablename__ = "system_config"
    id = Column(Integer, primary_key=True, index=True)
    language = Column(String, default="ko")
    server_port = Column(Integer, default=8000)
    rtsp_url = Column(String, default="0")
    conf_threshold = Column(Float, default=0.25)
    iou_threshold = Column(Float, default=0.45)
    active_model_id = Column(Integer, ForeignKey("ai_models.id"), nullable=True)
    active_model = relationship("AIModel")


def _ensure_columns():
    """기존 DB가 신규 컬럼(language)을 누락한 경우를 대비한 가벼운 마이그레이션."""
    inspector = inspect(engine)
    if "system_config" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("system_config")}
    with engine.begin() as conn:
        if "language" not in cols:
            logger.warning("system_config.language 컬럼이 없어 추가합니다.")
            conn.execute(text("ALTER TABLE system_config ADD COLUMN language VARCHAR DEFAULT 'ko'"))


def init_db():
    Base.metadata.create_all(bind=engine)
    _ensure_columns()


def ensure_default_config():
    """SystemConfig 행이 없으면 기본값으로 한 줄 생성."""
    db = SessionLocal()
    try:
        cfg = db.query(SystemConfig).first()
        if cfg is None:
            cfg = SystemConfig()
            db.add(cfg)
            db.commit()
            db.refresh(cfg)
        return cfg
    finally:
        db.close()

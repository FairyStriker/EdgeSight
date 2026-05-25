import threading


_EMPTY_META = {
    "timestamp": "--:--:--",
    "fps": 0.0,
    "count": 0,
    "objects": [],
}


class RuntimeState:
    """엔진 스레드(생산자)와 HTTP/WebSocket 핸들러(소비자)가 공유하는 런타임 상태.

    다채널: 프레임/메타가 채널 ID 키 dict 로 보관된다.
    """

    def __init__(self):
        self.is_running = True
        # 전역 설정: conf/iou/language/모델 + 채널 리스트.
        # channels 는 [{id, name, input_source, source_uri, video_filename, enabled, position}, ...]
        self.config: dict = {
            "iou": 0.45,
            "conf": 0.25,
            "config_path": None,
            "language": "ko",
            "channels": [],
        }

        # 채널별 latest_frame / latest_meta
        self.frames: dict[int, bytes] = {}
        self.frame_seqs: dict[int, int] = {}
        self.frame_lock = threading.Lock()

        self.metas: dict[int, dict] = {}
        self.meta_seqs: dict[int, int] = {}
        # WebSocket 이 전체 스냅샷 변화를 한 번에 감지하기 위한 전역 seq.
        # 어떤 채널이든 set_meta 될 때마다 1 증가.
        self.global_meta_seq: int = 0
        self.meta_lock = threading.Lock()

    # ---------- config helpers ----------

    def update_config(self, key, value):
        self.config[key] = value

    def set_channels(self, channels: list[dict]):
        self.config["channels"] = list(channels)

    def get_channels(self) -> list[dict]:
        return list(self.config.get("channels", []))

    # ---------- frame ----------

    def set_frame(self, channel_id: int, frame_bytes: bytes):
        with self.frame_lock:
            self.frames[channel_id] = frame_bytes
            self.frame_seqs[channel_id] = self.frame_seqs.get(channel_id, 0) + 1

    def get_frame(self, channel_id: int):
        with self.frame_lock:
            return self.frames.get(channel_id), self.frame_seqs.get(channel_id, 0)

    def drop_frame(self, channel_id: int):
        """채널 삭제/재시작 시 잔여 프레임 정리."""
        with self.frame_lock:
            self.frames.pop(channel_id, None)
            self.frame_seqs.pop(channel_id, None)

    # ---------- meta ----------

    def set_meta(self, channel_id: int, meta_data: dict):
        with self.meta_lock:
            self.metas[channel_id] = meta_data
            self.meta_seqs[channel_id] = self.meta_seqs.get(channel_id, 0) + 1
            self.global_meta_seq += 1

    def get_meta(self, channel_id: int):
        with self.meta_lock:
            return (
                self.metas.get(channel_id, _EMPTY_META),
                self.meta_seqs.get(channel_id, 0),
            )

    def snapshot_metas(self) -> tuple[dict[int, dict], int]:
        """모든 채널의 최신 메타를 한 번에 가져온다 (WS 전송용).
        반환: ({channel_id: meta}, global_meta_seq)."""
        with self.meta_lock:
            return dict(self.metas), self.global_meta_seq

    def drop_meta(self, channel_id: int):
        with self.meta_lock:
            self.metas.pop(channel_id, None)
            self.meta_seqs.pop(channel_id, None)


state = RuntimeState()

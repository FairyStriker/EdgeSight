import threading


class RuntimeState:
    """엔진 스레드(생산자)와 HTTP/WebSocket 핸들러(소비자)가 공유하는 런타임 상태."""

    def __init__(self):
        self.is_running = True
        self.config = {
            "iou": 0.45,
            "conf": 0.25,
            "rtsp_url": "0",
            "config_path": None,
            "language": "ko",
            "input_source": "rtsp",     # "rtsp" | "usb" | "video"
            "video_filename": None,
        }

        self.latest_frame: bytes | None = None
        self.frame_seq: int = 0
        self.frame_lock = threading.Lock()

        self.latest_meta = {
            "timestamp": "--:--:--",
            "fps": 0.0,
            "count": 0,
            "objects": [],
        }
        self.meta_seq: int = 0
        self.meta_lock = threading.Lock()

    def update_config(self, key, value):
        self.config[key] = value

    def set_frame(self, frame_bytes: bytes):
        with self.frame_lock:
            self.latest_frame = frame_bytes
            self.frame_seq += 1

    def get_frame(self):
        with self.frame_lock:
            return self.latest_frame, self.frame_seq

    def set_meta(self, meta_data: dict):
        with self.meta_lock:
            self.latest_meta = meta_data
            self.meta_seq += 1

    def get_meta(self):
        with self.meta_lock:
            return self.latest_meta, self.meta_seq


state = RuntimeState()

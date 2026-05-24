"""인메모리 백그라운드 작업 추적기.

PT → ONNX 변환과 같이 시간이 걸리는 작업을 비동기로 실행하면서
HTTP 클라이언트가 진행 상황을 폴링/구독할 수 있도록 상태를 보관한다.
"""

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Literal, Optional

logger = logging.getLogger(__name__)

JobStatus = Literal["pending", "running", "completed", "failed"]


@dataclass
class Job:
    id: str
    job_type: str
    filename: str
    status: JobStatus = "pending"
    progress: int = 0
    message: str = ""
    error: Optional[str] = None
    model_id: Optional[int] = None
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.job_type,
            "filename": self.filename,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "error": self.error,
            "model_id": self.model_id,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


class JobManager:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        # 동시 변환은 1개만 — GPU 충돌과 RAM 폭주 방지
        self._convert_lock = threading.Lock()

    def create(self, job_type: str, filename: str) -> Job:
        with self._lock:
            job = Job(id=uuid.uuid4().hex[:12], job_type=job_type, filename=filename)
            self._jobs[job.id] = job
            return job

    def update(self, job_id: str, **fields) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            for k, v in fields.items():
                if hasattr(job, k):
                    setattr(job, k, v)
            if fields.get("status") in ("completed", "failed"):
                job.completed_at = time.time()

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[dict]:
        with self._lock:
            return [
                j.to_dict()
                for j in sorted(
                    self._jobs.values(),
                    key=lambda j: j.created_at,
                    reverse=True,
                )
            ]

    def has_active(self) -> bool:
        with self._lock:
            return any(
                j.status in ("pending", "running") for j in self._jobs.values()
            )

    def prune_old(self, keep_seconds: int = 3600) -> None:
        cutoff = time.time() - keep_seconds
        with self._lock:
            for jid in [
                jid
                for jid, j in self._jobs.items()
                if j.completed_at and j.completed_at < cutoff
            ]:
                del self._jobs[jid]

    def run_async(self, job: Job, fn: Callable[[Job], None]) -> None:
        """fn(job)을 백그라운드 스레드에서 실행한다.

        fn 내부에서 ``self.update(job.id, ...)`` 로 진행률을 보고할 수 있다.
        예외가 발생하면 자동으로 status=failed, error=str(e) 로 마킹된다.
        """

        def runner():
            with self._convert_lock:
                try:
                    self.update(job.id, status="running", progress=5, message="시작")
                    fn(job)
                    if self.get(job.id) and self.get(job.id).status == "running":
                        self.update(
                            job.id,
                            status="completed",
                            progress=100,
                            message="완료",
                        )
                except Exception as e:
                    logger.exception("Job %s 실패: %s", job.id, e)
                    self.update(job.id, status="failed", error=str(e))

        threading.Thread(target=runner, daemon=True, name=f"job-{job.id}").start()


job_manager = JobManager()

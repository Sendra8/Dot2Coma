"""Cola de trabajos en segundo plano (uno a la vez) con progreso consultable."""
from __future__ import annotations

import queue
import threading
import traceback
import uuid
from typing import Callable


class Job:
    def __init__(self, kind: str, project_id: str, fn: Callable[["Job"], None]):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.project_id = project_id
        self.fn = fn
        self.state = "en cola"   # en cola | en curso | hecho | error | cancelado
        self.stage = ""
        self.progress = 0.0
        self.error = ""
        self.cancel = threading.Event()

    def report(self, stage: str, frac: float) -> None:
        self.stage = stage
        self.progress = max(0.0, min(1.0, frac))

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "project_id": self.project_id, "state": self.state,
                "stage": self.stage, "progress": round(self.progress, 4), "error": self.error}


class JobRunner:
    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self._q: queue.Queue[Job] = queue.Queue()
        threading.Thread(target=self._loop, daemon=True, name="jobs").start()

    def submit(self, kind: str, project_id: str, fn: Callable[[Job], None]) -> Job:
        job = Job(kind, project_id, fn)
        self.jobs[job.id] = job
        self._q.put(job)
        return job

    def active_for(self, project_id: str) -> list[Job]:
        return [j for j in self.jobs.values() if j.project_id == project_id and j.state in ("en cola", "en curso")]

    def _loop(self) -> None:
        while True:
            job = self._q.get()
            if job.cancel.is_set():
                job.state = "cancelado"
                continue
            job.state = "en curso"
            try:
                job.fn(job)
                job.state = "cancelado" if job.cancel.is_set() else "hecho"
            except Exception as e:  # noqa: BLE001 - se muestra al usuario
                if job.cancel.is_set() or type(e).__name__ == "Cancelled":
                    job.state = "cancelado"
                else:
                    job.state = "error"
                    job.error = str(e) or type(e).__name__
                    traceback.print_exc()

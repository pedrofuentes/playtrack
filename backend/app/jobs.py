from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Literal, Sequence

from .tracking import TrackFrame


JobState = Literal["queued", "running", "completed", "failed"]
JobReporter = Callable[[float, str, TrackFrame], None]
JobWorker = Callable[[JobReporter], Sequence[TrackFrame]]
TrackCompletion = Callable[[str, Sequence[TrackFrame]], None]
ProgressReporter = Callable[[float, str], None]
ProgressWorker = Callable[[str, ProgressReporter], None]
ProgressCompletion = Callable[[str], None]


class JobNotFoundError(KeyError):
    def __init__(self) -> None:
        super().__init__("Tracking job not found")

    def __str__(self) -> str:
        return str(self.args[0])


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    job_id: str
    state: JobState
    progress: float
    message: str
    track: tuple[TrackFrame, ...]
    version: int

    def to_dict(self) -> dict[str, object]:
        return {
            "jobId": self.job_id,
            "state": self.state,
            "progress": self.progress,
            "message": self.message,
            "track": [frame.to_dict() for frame in self.track],
        }


@dataclass(slots=True)
class _Job:
    job_id: str
    state: JobState = "queued"
    progress: float = 0.0
    message: str = "Queued"
    track: dict[int, TrackFrame] = field(default_factory=dict)
    version: int = 0


class JobRegistry:
    """Thread-safe in-memory tracking job registry with versioned updates."""

    def __init__(self) -> None:
        self._jobs: dict[str, _Job] = {}
        self._condition = threading.Condition(threading.RLock())

    def submit(self, worker: JobWorker, *, on_completed: TrackCompletion | None = None) -> str:
        job_id = self._create_job()
        thread = threading.Thread(
            target=self._run_worker,
            args=(job_id, worker, on_completed),
            name=f"findme-track-{job_id[:8]}",
            daemon=True,
        )
        thread.start()
        return job_id

    def submit_progress(
        self,
        worker: ProgressWorker,
        *,
        completion_message: str,
        on_completed: ProgressCompletion | None = None,
    ) -> str:
        job_id = self._create_job()
        thread = threading.Thread(
            target=self._run_progress_worker,
            args=(job_id, worker, completion_message, on_completed),
            name=f"findme-job-{job_id[:8]}",
            daemon=True,
        )
        thread.start()
        return job_id

    def restore_completed(self, job_id: str, track: Sequence[TrackFrame]) -> None:
        with self._condition:
            self._jobs[job_id] = _Job(
                job_id=job_id,
                state="completed",
                progress=1.0,
                message="Tracking complete",
                track={frame.frame_idx: frame for frame in track},
                version=1,
            )
            self._condition.notify_all()

    def remove(self, job_id: str) -> None:
        with self._condition:
            self._jobs.pop(job_id, None)
            self._condition.notify_all()

    def get(self, job_id: str) -> JobSnapshot:
        with self._condition:
            return self._snapshot(self._get_job(job_id))

    def wait_for_update(
        self, job_id: str, after_version: int, timeout: float = 30.0
    ) -> JobSnapshot:
        with self._condition:
            job = self._get_job(job_id)
            self._condition.wait_for(
                lambda: job.version > after_version
                or job.state in ("completed", "failed"),
                timeout=timeout,
            )
            return self._snapshot(job)

    def wait_until_terminal(self, job_id: str, timeout: float) -> JobSnapshot:
        deadline = time.monotonic() + timeout
        snapshot = self.get(job_id)
        while snapshot.state not in ("completed", "failed"):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Tracking job did not finish in time")
            snapshot = self.wait_for_update(
                job_id, snapshot.version, timeout=remaining
            )
        return snapshot

    def _run_worker(self, job_id: str, worker: JobWorker, on_completed: TrackCompletion | None) -> None:
        self._set_state(job_id, "running", 0.0, "Starting tracker")

        def report(progress: float, message: str, frame: TrackFrame) -> None:
            with self._condition:
                job = self._get_job(job_id)
                job.progress = min(max(float(progress), job.progress), 1.0)
                job.message = message
                job.track[frame.frame_idx] = frame
                job.version += 1
                self._condition.notify_all()

        try:
            result = worker(report)
        except Exception as exc:
            self._set_state(job_id, "failed", None, str(exc) or type(exc).__name__)
            return

        with self._condition:
            job = self._get_job(job_id)
            job.track = {frame.frame_idx: frame for frame in result}
            job.state = "completed"
            job.progress = 1.0
            job.message = "Tracking complete"
            job.version += 1
            self._condition.notify_all()
        if on_completed is not None:
            try:
                on_completed(job_id, result)
            except Exception:
                # A damaged catalog must not make an otherwise complete tracker fail.
                pass

    def _run_progress_worker(
        self,
        job_id: str,
        worker: ProgressWorker,
        completion_message: str,
        on_completed: ProgressCompletion | None,
    ) -> None:
        self._set_state(job_id, "running", 0.0, "Starting export")

        def report(progress: float, message: str) -> None:
            with self._condition:
                job = self._get_job(job_id)
                job.progress = min(max(float(progress), job.progress), 1.0)
                job.message = message
                job.version += 1
                self._condition.notify_all()

        try:
            worker(job_id, report)
        except Exception as exc:
            self._set_state(job_id, "failed", None, str(exc) or type(exc).__name__)
            return
        if on_completed is not None:
            try:
                on_completed(job_id)
            except Exception:
                pass
        self._set_state(job_id, "completed", 1.0, completion_message)

    def _create_job(self) -> str:
        job_id = uuid.uuid4().hex
        with self._condition:
            self._jobs[job_id] = _Job(job_id=job_id)
        return job_id

    def _set_state(
        self,
        job_id: str,
        state: JobState,
        progress: float | None,
        message: str,
    ) -> None:
        with self._condition:
            job = self._get_job(job_id)
            job.state = state
            if progress is not None:
                job.progress = progress
            job.message = message
            job.version += 1
            self._condition.notify_all()

    def _get_job(self, job_id: str) -> _Job:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise JobNotFoundError() from exc

    @staticmethod
    def _snapshot(job: _Job) -> JobSnapshot:
        return JobSnapshot(
            job_id=job.job_id,
            state=job.state,
            progress=job.progress,
            message=job.message,
            track=tuple(job.track[index] for index in sorted(job.track)),
            version=job.version,
        )

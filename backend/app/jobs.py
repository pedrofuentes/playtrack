from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Literal, Sequence

from .tracking import TrackFrame


JobState = Literal["queued", "running", "completed", "failed", "canceled"]
JobKind = Literal["track", "export"]
JobReporter = Callable[[float, str, TrackFrame], None]
JobWorker = Callable[[JobReporter], Sequence[TrackFrame]]
TrackCompletion = Callable[[str, Sequence[TrackFrame]], None]
ProgressReporter = Callable[[float, str], None]
ProgressWorker = Callable[[str, ProgressReporter], None]
ProgressCompletion = Callable[[str], None]
_TERMINAL_STATES = frozenset({"completed", "failed", "canceled"})


class JobNotFoundError(KeyError):
    def __init__(self) -> None:
        super().__init__("Tracking job not found")

    def __str__(self) -> str:
        return str(self.args[0])


class JobQueueFullError(RuntimeError):
    def __init__(self, kind: JobKind) -> None:
        super().__init__(f"The {kind} queue is full; try again after a job finishes")
        self.kind = kind


class JobRegistryClosedError(RuntimeError):
    pass


class _JobCanceled(Exception):
    pass


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
    kind: JobKind
    state: JobState = "queued"
    progress: float = 0.0
    message: str = "Queued"
    track: dict[int, TrackFrame] = field(default_factory=dict)
    version: int = 0
    resources: frozenset[str] = field(default_factory=frozenset)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    terminal_at: str | None = None
    cancel_requested: bool = False
    committing: bool = False


@dataclass(frozen=True, slots=True)
class _Task:
    job_id: str
    kind: JobKind
    worker: JobWorker | ProgressWorker
    completion_message: str
    on_completed: TrackCompletion | ProgressCompletion | None


class JobRegistry:
    """Bounded, persistent job scheduler with one daemon worker per job kind."""

    def __init__(
        self,
        *,
        library: Any | None = None,
        queue_capacity: int = 2,
        terminal_retention: int = 100,
        worker_idle_timeout: float = 1.0,
    ) -> None:
        if queue_capacity < 0:
            raise ValueError("queue_capacity cannot be negative")
        if terminal_retention < 0:
            raise ValueError("terminal_retention cannot be negative")
        self._library = library
        self._queue_capacity = queue_capacity
        self._terminal_retention = terminal_retention
        self._worker_idle_timeout = worker_idle_timeout
        self._jobs: dict[str, _Job] = {}
        self._pending: dict[JobKind, deque[_Task]] = {
            "track": deque(),
            "export": deque(),
        }
        self._workers: dict[JobKind, threading.Thread | None] = {
            "track": None,
            "export": None,
        }
        self._condition = threading.Condition(threading.RLock())
        self._closed = False
        self._rehydrate()

    def submit(
        self,
        worker: JobWorker,
        *,
        on_completed: TrackCompletion | None = None,
        resources: set[str] | frozenset[str] = frozenset(),
    ) -> str:
        return self._submit_task(
            kind="track",
            worker=worker,
            completion_message="Tracking complete",
            on_completed=on_completed,
            resources=resources,
        )

    def submit_progress(
        self,
        worker: ProgressWorker,
        *,
        completion_message: str,
        on_completed: ProgressCompletion | None = None,
        resources: set[str] | frozenset[str] = frozenset(),
    ) -> str:
        return self._submit_task(
            kind="export",
            worker=worker,
            completion_message=completion_message,
            on_completed=on_completed,
            resources=resources,
        )

    def restore_completed(self, job_id: str, track: Sequence[TrackFrame]) -> None:
        self._restore_terminal(
            job_id,
            kind="track",
            track=track,
            message="Tracking complete",
        )

    def restore_progress_completed(
        self, job_id: str, *, completion_message: str
    ) -> None:
        self._restore_terminal(
            job_id,
            kind="export",
            track=(),
            message=completion_message,
        )

    def cancel(self, job_id: str) -> JobSnapshot:
        with self._condition:
            job = self._get_job(job_id)
            if job.state in _TERMINAL_STATES:
                return self._snapshot(job)
            if job.committing:
                job.message = "Finishing durable save; cancellation is no longer possible"
                job.version += 1
                job.updated_at = _now()
                self._persist_or_fail_locked(job)
                self._condition.notify_all()
                return self._snapshot(job)
            if job.state == "queued":
                pending = self._pending[job.kind]
                self._pending[job.kind] = deque(
                    task for task in pending if task.job_id != job_id
                )
                self._transition_locked(
                    job,
                    state="canceled",
                    progress=None,
                    message="Canceled before starting",
                )
                self._enforce_retention_locked()
                self._condition.notify_all()
                return self._snapshot(job)
            job.cancel_requested = True
            job.message = "Cancellation requested"
            job.version += 1
            job.updated_at = _now()
            self._persist_or_fail_locked(job)
            self._condition.notify_all()
            return self._snapshot(job)

    def remove(self, job_id: str, *, persist: bool = True) -> None:
        with self._condition:
            job = self._jobs.get(job_id)
            if job is not None and job.state not in _TERMINAL_STATES:
                raise RuntimeError("Cannot remove an active job")
            self._jobs.pop(job_id, None)
            if persist and self._library is not None:
                self._library.remove_job(job_id)
            self._condition.notify_all()

    def active_resources(self) -> set[str]:
        with self._condition:
            return {
                resource
                for job in self._jobs.values()
                if job.state in ("queued", "running")
                for resource in job.resources
            }

    def is_resource_active(self, resource: str) -> bool:
        return resource in self.active_resources()

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
                or job.state in _TERMINAL_STATES,
                timeout=timeout,
            )
            return self._snapshot(job)

    def wait_until_terminal(self, job_id: str, timeout: float) -> JobSnapshot:
        deadline = time.monotonic() + timeout
        snapshot = self.get(job_id)
        while snapshot.state not in _TERMINAL_STATES:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Tracking job did not finish in time")
            snapshot = self.wait_for_update(
                job_id, snapshot.version, timeout=remaining
            )
        return snapshot

    def close(self) -> None:
        with self._condition:
            self._closed = True
            queued = [task.job_id for tasks in self._pending.values() for task in tasks]
            for job_id in queued:
                job = self._jobs.get(job_id)
                if job is not None and job.state == "queued":
                    self._transition_locked(
                        job,
                        state="canceled",
                        progress=None,
                        message="Canceled during backend shutdown",
                    )
            for pending in self._pending.values():
                pending.clear()
            for job in self._jobs.values():
                if job.state == "running" and not job.committing:
                    job.cancel_requested = True
            self._enforce_retention_locked()
            self._condition.notify_all()

    def _submit_task(
        self,
        *,
        kind: JobKind,
        worker: JobWorker | ProgressWorker,
        completion_message: str,
        on_completed: TrackCompletion | ProgressCompletion | None,
        resources: set[str] | frozenset[str],
    ) -> str:
        with self._condition:
            if self._closed:
                raise JobRegistryClosedError("The job scheduler is shutting down")
            active_count = sum(
                job.kind == kind and job.state in ("queued", "running")
                for job in self._jobs.values()
            )
            if active_count >= self._queue_capacity + 1:
                raise JobQueueFullError(kind)
            job_id = uuid.uuid4().hex
            job = _Job(
                job_id=job_id,
                kind=kind,
                resources=frozenset(resources) | {f"job:{job_id}"},
            )
            self._jobs[job_id] = job
            try:
                self._persist_locked(job)
            except Exception:
                self._jobs.pop(job_id, None)
                raise
            self._pending[kind].append(
                _Task(
                    job_id=job_id,
                    kind=kind,
                    worker=worker,
                    completion_message=completion_message,
                    on_completed=on_completed,
                )
            )
            self._ensure_worker_locked(kind)
            self._condition.notify_all()
            return job_id

    def _ensure_worker_locked(self, kind: JobKind) -> None:
        worker = self._workers[kind]
        if worker is not None and worker.is_alive():
            return
        worker = threading.Thread(
            target=self._worker_loop,
            args=(kind,),
            name=f"findme-{kind}-worker",
            daemon=True,
        )
        self._workers[kind] = worker
        worker.start()

    def _worker_loop(self, kind: JobKind) -> None:
        while True:
            with self._condition:
                ready = self._condition.wait_for(
                    lambda: bool(self._pending[kind]) or self._closed,
                    timeout=self._worker_idle_timeout,
                )
                if self._closed and not self._pending[kind]:
                    self._workers[kind] = None
                    return
                if not ready and not self._pending[kind]:
                    self._workers[kind] = None
                    return
                if not self._pending[kind]:
                    continue
                task = self._pending[kind].popleft()
                job = self._jobs.get(task.job_id)
                if job is None or job.state != "queued":
                    continue
                self._transition_locked(
                    job,
                    state="running",
                    progress=0.0,
                    message=("Starting tracker" if kind == "track" else "Starting export"),
                )
                if job.state != "running":
                    self._enforce_retention_locked()
                    continue
            self._run_task(task)

    def _run_task(self, task: _Task) -> None:
        try:
            if task.kind == "track":
                self._run_track_task(task)
            else:
                self._run_export_task(task)
        except _JobCanceled:
            self._finish_canceled(task.job_id)
        except Exception as exc:
            with self._condition:
                canceled = bool(
                    (job := self._jobs.get(task.job_id))
                    and job.cancel_requested
                )
            if canceled:
                self._finish_canceled(task.job_id)
            else:
                self._finish_failed(task.job_id, str(exc) or type(exc).__name__)

    def _run_track_task(self, task: _Task) -> None:
        worker = task.worker

        def report(progress: float, message: str, frame: TrackFrame) -> None:
            with self._condition:
                job = self._get_job(task.job_id)
                if job.cancel_requested:
                    raise _JobCanceled()
                job.progress = min(max(float(progress), job.progress), 1.0)
                job.message = message
                job.track[frame.frame_idx] = frame
                if job.progress < 1.0:
                    job.version += 1
                    job.updated_at = _now()
                    self._condition.notify_all()

        result = worker(report)  # type: ignore[arg-type]
        with self._condition:
            job = self._get_job(task.job_id)
            if job.cancel_requested:
                raise _JobCanceled()
            job.track = {frame.frame_idx: frame for frame in result}
            job.committing = task.on_completed is not None
        if task.on_completed is not None:
            try:
                task.on_completed(task.job_id, result)  # type: ignore[call-arg]
            except Exception as exc:
                raise RuntimeError(
                    f"Could not save completed track: {str(exc) or type(exc).__name__}"
                ) from exc
        self._finish_completed(task.job_id, task.completion_message)

    def _run_export_task(self, task: _Task) -> None:
        worker = task.worker

        def report(progress: float, message: str) -> None:
            with self._condition:
                job = self._get_job(task.job_id)
                if job.cancel_requested:
                    raise _JobCanceled()
                job.progress = min(max(float(progress), job.progress), 1.0)
                job.message = message
                job.version += 1
                job.updated_at = _now()
                self._condition.notify_all()

        worker(task.job_id, report)  # type: ignore[call-arg]
        with self._condition:
            job = self._get_job(task.job_id)
            if job.cancel_requested:
                raise _JobCanceled()
            job.committing = task.on_completed is not None
        if task.on_completed is not None:
            try:
                task.on_completed(task.job_id)  # type: ignore[call-arg]
            except Exception as exc:
                raise RuntimeError(
                    f"Could not save completed job: {str(exc) or type(exc).__name__}"
                ) from exc
        self._finish_completed(task.job_id, task.completion_message)

    def _finish_completed(self, job_id: str, message: str) -> None:
        with self._condition:
            job = self._get_job(job_id)
            job.committing = False
            self._transition_locked(
                job, state="completed", progress=1.0, message=message
            )
            self._enforce_retention_locked()
            self._condition.notify_all()

    def _finish_failed(self, job_id: str, message: str) -> None:
        with self._condition:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.committing = False
            self._transition_locked(
                job, state="failed", progress=None, message=message
            )
            self._enforce_retention_locked()
            self._condition.notify_all()

    def _finish_canceled(self, job_id: str) -> None:
        with self._condition:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.committing = False
            self._transition_locked(
                job,
                state="canceled",
                progress=None,
                message="Canceled",
            )
            self._enforce_retention_locked()
            self._condition.notify_all()

    def _restore_terminal(
        self,
        job_id: str,
        *,
        kind: JobKind,
        track: Sequence[TrackFrame],
        message: str,
    ) -> None:
        now = _now()
        with self._condition:
            existing = self._jobs.get(job_id)
            created_at = existing.created_at if existing is not None else now
            job = _Job(
                job_id=job_id,
                kind=kind,
                state="completed",
                progress=1.0,
                message=message,
                track={frame.frame_idx: frame for frame in track},
                version=(existing.version + 1 if existing is not None else 1),
                created_at=created_at,
                updated_at=now,
                terminal_at=now,
            )
            self._jobs[job_id] = job
            self._persist_locked(job)
            self._enforce_retention_locked()
            self._condition.notify_all()

    def _transition_locked(
        self,
        job: _Job,
        *,
        state: JobState,
        progress: float | None,
        message: str,
    ) -> None:
        job.state = state
        if progress is not None:
            job.progress = progress
        job.message = message
        job.version += 1
        job.updated_at = _now()
        if state in _TERMINAL_STATES:
            job.terminal_at = job.updated_at
            job.resources = frozenset()
        self._persist_or_fail_locked(job)
        self._condition.notify_all()

    def _persist_or_fail_locked(self, job: _Job) -> bool:
        try:
            self._persist_locked(job)
            return True
        except Exception as exc:
            now = _now()
            job.state = "failed"
            job.message = (
                f"Could not persist job state: {str(exc) or type(exc).__name__}"
            )
            job.version += 1
            job.updated_at = now
            job.terminal_at = now
            job.resources = frozenset()
            job.committing = False
            try:
                self._persist_locked(job)
            except Exception:
                pass
            self._condition.notify_all()
            return False

    def _persist_locked(self, job: _Job) -> None:
        if self._library is None:
            return
        self._library.save_job(
            job_id=job.job_id,
            kind=job.kind,
            state=job.state,
            progress=job.progress,
            message=job.message,
            track=tuple(job.track[index] for index in sorted(job.track)),
            resources=tuple(job.resources),
            version=job.version,
            created_at=job.created_at,
            updated_at=job.updated_at,
            terminal_at=job.terminal_at,
        )

    def _enforce_retention_locked(self) -> None:
        terminal = sorted(
            (job for job in self._jobs.values() if job.state in _TERMINAL_STATES),
            key=lambda job: (job.terminal_at or "", job.updated_at, job.job_id),
            reverse=True,
        )
        for job in terminal[self._terminal_retention :]:
            self._jobs.pop(job.job_id, None)
        if self._library is not None:
            self._library.prune_terminal_jobs(self._terminal_retention)

    def _rehydrate(self) -> None:
        if self._library is None:
            return
        now = _now()
        for saved in self._library.load_jobs():
            kind = saved["kind"]
            state = saved["state"]
            if kind not in ("track", "export") or state not in {
                "queued",
                "running",
                "completed",
                "failed",
                "canceled",
            }:
                continue
            if state in ("queued", "running"):
                state = "failed"
                message = "Interrupted by backend restart"
                terminal_at = now
                resources = frozenset()
                version = int(saved["version"]) + 1
            else:
                message = str(saved["message"])
                terminal_at = saved["terminalAt"]
                resources = frozenset()
                version = int(saved["version"])
            job = _Job(
                job_id=str(saved["jobId"]),
                kind=kind,
                state=state,
                progress=float(saved["progress"]),
                message=message,
                track={frame.frame_idx: frame for frame in saved["track"]},
                version=version,
                resources=resources,
                created_at=str(saved["createdAt"]),
                updated_at=now if state == "failed" else str(saved["updatedAt"]),
                terminal_at=terminal_at,
            )
            self._jobs[job.job_id] = job
            if saved["state"] in ("queued", "running"):
                self._persist_locked(job)
        self._enforce_retention_locked()

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


def _now() -> str:
    return datetime.now(UTC).isoformat()

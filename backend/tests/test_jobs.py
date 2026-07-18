from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from app.jobs import JobNotFoundError, JobQueueFullError, JobRegistry
from app.library import LibraryStore
from app.tracking import TrackFrame


def frame(frame_idx: int) -> TrackFrame:
    return TrackFrame(
        frame_idx=frame_idx,
        box=(10, 20, 30, 40),
        center=(20.0, 30.0),
        lost=False,
    )


def test_registry_runs_worker_and_keeps_sorted_partial_track() -> None:
    registry = JobRegistry()

    def worker(report: object) -> list[TrackFrame]:
        report(0.5, "Halfway", frame(2))
        report(0.75, "More", frame(1))
        return [frame(2), frame(1)]

    job_id = registry.submit(worker)
    snapshot = registry.wait_until_terminal(job_id, timeout=2)

    assert snapshot.state == "completed"
    assert snapshot.progress == 1.0
    assert snapshot.message == "Tracking complete"
    assert [item.frame_idx for item in snapshot.track] == [1, 2]
    assert snapshot.version >= 4


def test_registry_uses_playtrack_worker_names() -> None:
    registry = JobRegistry()
    started = threading.Event()
    release = threading.Event()

    def worker(_report: object) -> list[TrackFrame]:
        started.set()
        assert release.wait(timeout=2)
        return []

    job_id = registry.submit(worker)
    assert started.wait(timeout=2)
    try:
        names = {thread.name for thread in threading.enumerate()}
        assert "playtrack-track-worker" in names
        assert "findme-track-worker" not in names
    finally:
        release.set()
        registry.wait_until_terminal(job_id, timeout=2)


def test_registry_exposes_failure_without_losing_partial_results() -> None:
    registry = JobRegistry()

    def worker(report: object) -> list[TrackFrame]:
        report(0.25, "Started", frame(0))
        raise RuntimeError("predictor failed")

    job_id = registry.submit(worker)
    snapshot = registry.wait_until_terminal(job_id, timeout=2)

    assert snapshot.state == "failed"
    assert snapshot.message == "predictor failed"
    assert [item.frame_idx for item in snapshot.track] == [0]


def test_registry_rejects_unknown_jobs() -> None:
    registry = JobRegistry()

    try:
        registry.get("missing")
    except JobNotFoundError as exc:
        assert str(exc) == "Tracking job not found"
    else:
        raise AssertionError("Expected JobNotFoundError")


def test_registry_runs_progress_only_export_worker() -> None:
    registry = JobRegistry()
    calls: list[tuple[str, float, str]] = []

    def worker(job_id: str, report: object) -> None:
        report(0.25, "Exporting frame 1")
        calls.append((job_id, 0.25, "Exporting frame 1"))
        report(1.0, "Exporting frame 4")

    job_id = registry.submit_progress(worker, completion_message="Export complete")
    snapshot = registry.wait_until_terminal(job_id, timeout=2)

    assert calls == [(job_id, 0.25, "Exporting frame 1")]
    assert snapshot.state == "completed"
    assert snapshot.progress == 1.0
    assert snapshot.message == "Export complete"
    assert snapshot.track == ()


def test_tracking_job_does_not_complete_before_persistence_callback() -> None:
    registry = JobRegistry()
    persistence_started = threading.Event()
    release_persistence = threading.Event()

    def persist(_job_id: str, _track: object) -> None:
        persistence_started.set()
        assert release_persistence.wait(timeout=2)

    job_id = registry.submit(lambda _report: [frame(0)], on_completed=persist)
    assert persistence_started.wait(timeout=2)

    pending = registry.get(job_id)
    assert pending.state == "running"
    assert pending.message != "Tracking complete"

    release_persistence.set()
    completed = registry.wait_until_terminal(job_id, timeout=2)
    assert completed.state == "completed"
    assert completed.message == "Tracking complete"


def test_tracking_persistence_failure_makes_job_failed() -> None:
    registry = JobRegistry()

    def fail_persistence(_job_id: str, _track: object) -> None:
        raise OSError("library is read-only")

    job_id = registry.submit(
        lambda _report: [frame(0)], on_completed=fail_persistence
    )
    snapshot = registry.wait_until_terminal(job_id, timeout=2)

    assert snapshot.state == "failed"
    assert snapshot.message == "Could not save completed track: library is read-only"


def test_registry_reports_resources_only_while_jobs_are_active() -> None:
    registry = JobRegistry()
    release = threading.Event()
    job_id = registry.submit(
        lambda _report: (release.wait(timeout=2), [frame(0)])[1],
        resources={"video:v1", "cache"},
    )
    assert registry.active_resources() == {
        "video:v1",
        "cache",
        f"job:{job_id}",
    }
    assert registry.is_resource_active(f"job:{job_id}")
    release.set()
    assert registry.wait_until_terminal(job_id, timeout=2).state == "completed"
    assert registry.active_resources() == set()


def test_track_queue_allows_one_running_and_two_waiting() -> None:
    registry = JobRegistry(queue_capacity=2)
    release = threading.Event()
    running = threading.Event()
    active = 0
    max_active = 0
    lock = threading.Lock()

    def worker(_report: object) -> list[TrackFrame]:
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        running.set()
        assert release.wait(timeout=2)
        with lock:
            active -= 1
        return [frame(0)]

    identifiers = [registry.submit(worker) for _ in range(3)]
    assert running.wait(timeout=1)
    with pytest.raises(JobQueueFullError):
        registry.submit(worker)

    release.set()
    assert all(
        registry.wait_until_terminal(job_id, timeout=2).state == "completed"
        for job_id in identifiers
    )
    assert max_active == 1


def test_track_and_export_queues_run_independently() -> None:
    registry = JobRegistry()
    release = threading.Event()
    track_running = threading.Event()
    export_running = threading.Event()

    track_id = registry.submit(
        lambda _report: (
            track_running.set(),
            release.wait(timeout=2),
            [frame(0)],
        )[2]
    )
    export_id = registry.submit_progress(
        lambda _job_id, _report: (
            export_running.set(),
            release.wait(timeout=2),
        ),
        completion_message="Export complete",
    )

    assert track_running.wait(timeout=1)
    assert export_running.wait(timeout=1)
    release.set()
    assert registry.wait_until_terminal(track_id, timeout=2).state == "completed"
    assert registry.wait_until_terminal(export_id, timeout=2).state == "completed"


def test_canceling_queued_job_frees_capacity_without_running_worker() -> None:
    registry = JobRegistry(queue_capacity=1)
    release = threading.Event()
    running = threading.Event()
    queued_called = False

    first = registry.submit(
        lambda _report: (running.set(), release.wait(timeout=2), [frame(0)])[2]
    )
    assert running.wait(timeout=1)

    def queued(_report: object) -> list[TrackFrame]:
        nonlocal queued_called
        queued_called = True
        return [frame(1)]

    second = registry.submit(queued)
    with pytest.raises(JobQueueFullError):
        registry.submit(queued)

    canceled = registry.cancel(second)
    replacement = registry.submit(lambda _report: [frame(2)])
    release.set()

    assert canceled.state == "canceled"
    assert registry.wait_until_terminal(first, timeout=2).state == "completed"
    assert registry.wait_until_terminal(replacement, timeout=2).state == "completed"
    assert queued_called is False


def test_running_cancellation_is_cooperative_and_holds_resources_until_exit() -> None:
    registry = JobRegistry()
    first_report = threading.Event()
    continue_worker = threading.Event()

    def worker(report: object) -> list[TrackFrame]:
        report(0.25, "Started", frame(0))
        first_report.set()
        assert continue_worker.wait(timeout=2)
        report(0.5, "Continuing", frame(1))
        return [frame(0), frame(1)]

    job_id = registry.submit(worker, resources={"video:v1"})
    assert first_report.wait(timeout=1)
    requested = registry.cancel(job_id)

    assert requested.state == "running"
    assert registry.is_resource_active("video:v1")
    continue_worker.set()
    terminal = registry.wait_until_terminal(job_id, timeout=2)
    assert terminal.state == "canceled"
    assert not registry.is_resource_active("video:v1")


def test_terminal_retention_is_bounded() -> None:
    registry = JobRegistry(terminal_retention=2)
    identifiers = []
    for index in range(3):
        job_id = registry.submit(lambda _report, index=index: [frame(index)])
        assert registry.wait_until_terminal(job_id, timeout=2).state == "completed"
        identifiers.append(job_id)

    with pytest.raises(JobNotFoundError):
        registry.get(identifiers[0])
    assert registry.get(identifiers[1]).state == "completed"
    assert registry.get(identifiers[2]).state == "completed"


def test_terminal_jobs_rehydrate_from_sqlite(tmp_path: Path) -> None:
    library = LibraryStore(tmp_path / "data")
    registry = JobRegistry(library=library)
    job_id = registry.submit(lambda _report: [frame(3)])
    completed = registry.wait_until_terminal(job_id, timeout=2)

    restarted = JobRegistry(library=library)
    restored = restarted.get(job_id)

    assert completed.state == "completed"
    assert restored.state == "completed"
    assert restored.track == (frame(3),)


def test_active_job_is_marked_failed_after_restart(tmp_path: Path) -> None:
    library = LibraryStore(tmp_path / "data")
    library.save_job(
        job_id="interrupted",
        kind="track",
        state="running",
        progress=0.5,
        message="Tracking",
        track=[frame(0)],
        resources=["video:v1"],
        version=2,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:01:00+00:00",
        terminal_at=None,
    )

    restarted = JobRegistry(library=library)
    restored = restarted.get("interrupted")

    assert restored.state == "failed"
    assert restored.message == "Interrupted by backend restart"
    assert restarted.active_resources() == set()
    assert library.load_jobs()[0]["state"] == "failed"


def test_state_persistence_failure_fails_job_and_releases_resources() -> None:
    class FlakyLibrary:
        def __init__(self) -> None:
            self.calls = 0

        def load_jobs(self) -> list[object]:
            return []

        def save_job(self, **_kwargs: object) -> None:
            self.calls += 1
            if self.calls == 2:
                raise OSError("database is read-only")

        def prune_terminal_jobs(self, _retention: int) -> list[str]:
            return []

    registry = JobRegistry(library=FlakyLibrary())
    job_id = registry.submit(
        lambda _report: [frame(0)], resources={"video:v1"}
    )

    terminal = registry.wait_until_terminal(job_id, timeout=2)

    assert terminal.state == "failed"
    assert terminal.message == "Could not persist job state: database is read-only"
    assert registry.active_resources() == set()


def test_cancel_persistence_failure_keeps_lease_until_worker_exits() -> None:
    class FlakyLibrary:
        def __init__(self) -> None:
            self.calls = 0

        def load_jobs(self) -> list[object]:
            return []

        def save_job(self, **_kwargs: object) -> None:
            self.calls += 1
            if self.calls == 3:
                raise OSError("database is read-only")

        def prune_terminal_jobs(self, _retention: int) -> list[str]:
            return []

    registry = JobRegistry(library=FlakyLibrary())
    started = threading.Event()
    release = threading.Event()

    def worker(report: object) -> list[TrackFrame]:
        started.set()
        assert release.wait(timeout=2)
        report(0.5, "Continuing", frame(0))
        return [frame(0)]

    job_id = registry.submit(worker, resources={"video:v1"})
    assert started.wait(timeout=1)

    failed_cancel = registry.cancel(job_id)

    assert failed_cancel.state == "failed"
    assert registry.is_resource_active("video:v1")
    release.set()
    deadline = time.monotonic() + 2
    while registry.is_resource_active("video:v1") and time.monotonic() < deadline:
        time.sleep(0.01)
    assert registry.get(job_id).state == "canceled"
    assert not registry.is_resource_active("video:v1")

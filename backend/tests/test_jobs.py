from __future__ import annotations

import threading

from app.jobs import JobNotFoundError, JobRegistry
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

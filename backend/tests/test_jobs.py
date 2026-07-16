from __future__ import annotations

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

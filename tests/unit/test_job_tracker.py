from datetime import UTC, datetime, timedelta

from stunsail_agent.jobs import JobTracker
from stunsail_agent.store import AgentStore

T0 = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)


def status(state, filename="cube.gcode", **stats):
    return {"print_stats": {"state": state, "filename": filename, **stats}}


def setup():
    store = AgentStore(":memory:")
    return store, JobTracker(store)


def types(emitted):
    return [event_type for event_type, _ in emitted]


def test_full_lifecycle_finalises_once():
    store, tracker = setup()
    assert tracker.observe(status("standby", filename=""), T0) == []
    assert types(tracker.observe(status("printing"), T0)) == ["job.started"]
    assert tracker.observe(status("printing", filament_used=10.0), T0) == []
    assert types(tracker.observe(status("paused"), T0)) == ["job.paused"]
    assert types(tracker.observe(status("printing"), T0)) == ["job.resumed"]
    done = tracker.observe(status("complete", filament_used=1234.5, print_duration=600.0), T0)
    assert types(done) == ["job.completed"]
    assert tracker.observe(status("complete"), T0) == []
    assert tracker.observe(status("standby", filename=""), T0) == []
    (job,) = store.list_jobs()
    assert job["state"] == "completed" and job["filament_used_mm"] == 1234.5


def test_stale_terminal_state_at_startup_is_ignored():
    store, tracker = setup()
    assert tracker.observe(status("complete"), T0) == []
    assert store.list_jobs() == []


def test_cancel_and_error():
    for raw, event in (("cancelled", "job.cancelled"), ("error", "job.errored")):
        _, tracker = setup()
        tracker.observe(status("printing"), T0)
        assert types(tracker.observe(status(raw), T0)) == [event]


def test_standby_during_job_is_interrupted():
    store, tracker = setup()
    tracker.observe(status("printing"), T0)
    assert types(tracker.observe(status("standby", filename=""), T0)) == ["job.interrupted"]
    assert store.active_job() is None


def test_new_file_while_active_interrupts_previous_job():
    store, tracker = setup()
    tracker.observe(status("printing", filename="a.gcode"), T0)
    emitted = tracker.observe(status("printing", filename="b.gcode"), T0)
    assert types(emitted) == ["job.interrupted", "job.started"]
    assert store.active_job()["filename"] == "b.gcode"


def test_reconcile_uses_history_for_job_finished_during_outage():
    store, tracker = setup()
    tracker.observe(status("printing"), T0)
    history = [
        {
            "filename": "cube.gcode",
            "status": "completed",
            "end_time": (T0 + timedelta(minutes=30)).timestamp(),
            "filament_used": 999.0,
            "print_duration": 1700.0,
        }
    ]
    emitted = tracker.reconcile(status("standby", filename=""), history, T0 + timedelta(hours=1))
    assert types(emitted) == ["job.completed"]
    (job,) = store.list_jobs()
    assert job["end_source"] == "history" and job["filament_used_mm"] == 999.0


def test_reconcile_without_history_marks_interrupted():
    store, tracker = setup()
    tracker.observe(status("printing"), T0)
    assert types(tracker.reconcile(status("standby", filename=""), [], T0)) == ["job.interrupted"]


def test_reconcile_leaves_still_running_job_alone():
    store, tracker = setup()
    tracker.observe(status("printing"), T0)
    assert tracker.reconcile(status("printing"), [], T0) == []
    assert store.active_job() is not None

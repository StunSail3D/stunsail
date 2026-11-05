import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator

from stunsail_agent.collector import Collector
from stunsail_agent.source import Discovery, StatusUpdate, select_observed_objects
from stunsail_agent.store import AgentStore
from stunsail_moonraker import MoonrakerConnectionError

SCHEMA = json.loads(
    (
        Path(__file__).parents[2]
        / "packages/shared-models/contracts/agent/v1/event-envelope.schema.json"
    ).read_text()
)


def print_stats(state, filename="cube.gcode", **extra):
    return {"print_stats": {"state": state, "filename": filename, **extra}}


class ScriptedSource:
    """Plays a fixed list of updates, then fails like a lost connection (or hangs)."""

    def __init__(self, snapshot, updates, history=(), then_hang=False):
        self._snapshot = snapshot
        self._updates = updates
        self._history = list(history)
        self._then_hang = then_hang
        self.closed = False

    async def open(self):
        return Discovery(
            {"state": "ready", "software_version": "v0"},
            {"moonraker_version": "v0.9"},
            ["print_stats", "extruder", "heater_bed", "fan"],
            ["print_stats", "extruder", "heater_bed", "fan"],
        )

    async def snapshot(self):
        return self._snapshot

    async def history(self, limit):
        return self._history

    async def updates(self):
        for update in self._updates:
            await asyncio.sleep(0)
            yield update
        if self._then_hang:
            await asyncio.sleep(3600)
        raise MoonrakerConnectionError("lost")

    async def close(self):
        self.closed = True


def event_types(store):
    return [e["event_type"] for e in store.list_events("agent-1")]


def test_select_observed_objects_only_uses_available_objects():
    available = ["print_stats", "extruder", "fan", "heater_fan hotend_fan", "toolhead", "mcu"]
    assert select_observed_objects(available) == [
        "print_stats",
        "extruder",
        "fan",
        "heater_fan hotend_fan",
    ]


def test_job_events_and_samples_are_persisted_and_valid():
    store = AgentStore(":memory:")
    collector = Collector(store, "agent-1", sample_interval=0.01)
    source = ScriptedSource(
        {"extruder": {"temperature": 20.0}, **print_stats("standby", filename="")},
        [
            StatusUpdate("status", print_stats("printing")),
            StatusUpdate("status", {"extruder": {"temperature": 200.0}}),
            StatusUpdate("status", print_stats("complete", filament_used=500.0)),
        ],
        then_hang=True,
    )

    async def scenario():
        stop = asyncio.Event()
        task = asyncio.create_task(collector.run_forever(lambda: source, stop))
        await asyncio.sleep(0.2)
        stop.set()
        await task

    asyncio.run(scenario())
    types = event_types(store)
    assert types[0] == "connection.established"
    assert {"job.started", "job.completed"} <= set(types)
    (job,) = store.list_jobs()
    assert job["state"] == "completed" and job["filament_used_mm"] == 500.0
    assert source.closed
    validator = Draft202012Validator(SCHEMA)
    events = store.list_events("agent-1")
    for envelope in events:
        validator.validate(envelope)
    sequences = [e["sequence"] for e in events]
    assert sequences == sorted(set(sequences))
    assert store.count("samples") > 0


def test_reconnect_marks_gap_and_state_survives_restart(tmp_path):
    db = tmp_path / "buffer.db"
    store = AgentStore(db)
    first = Collector(store, "agent-1", sample_interval=0.01)
    running = ScriptedSource(
        print_stats("printing"), [StatusUpdate("status", print_stats("printing"))], then_hang=True
    )

    async def first_run():
        stop = asyncio.Event()
        task = asyncio.create_task(first.run_forever(lambda: running, stop))
        await asyncio.sleep(0.1)
        stop.set()
        await task

    asyncio.run(first_run())
    samples_before = store.count("samples")
    assert samples_before > 0
    store.close()

    # Simulated service restart: new store handle and collector over the same file.
    store = AgentStore(db)
    assert store.count("samples") == samples_before
    assert store.active_job() is not None
    second = Collector(
        store,
        "agent-1",
        sample_interval=0.01,
        clock=lambda: datetime.now(UTC).replace(microsecond=0),
    )
    history = [
        {
            "filename": "cube.gcode",
            "status": "completed",
            "end_time": datetime.now(UTC).timestamp() + 5,
            "filament_used": 42.0,
        }
    ]
    after = ScriptedSource(print_stats("standby", filename=""), [], history=history, then_hang=True)

    async def second_run():
        stop = asyncio.Event()
        task = asyncio.create_task(second.run_forever(lambda: after, stop))
        await asyncio.sleep(0.1)
        stop.set()
        await task

    asyncio.run(second_run())
    types = event_types(store)
    assert types.count("connection.established") == 2
    assert types.count("job.started") == 1
    assert types.count("job.completed") == 1
    (job,) = store.list_jobs()
    assert job["end_source"] == "history" and job["filament_used_mm"] == 42.0


def test_retries_after_connection_loss_with_backoff():
    store = AgentStore(":memory:")
    collector = Collector(store, "agent-1", sample_interval=0.01, delays=lambda: iter([0.01] * 100))
    sources = []

    def factory():
        source = ScriptedSource(print_stats("standby", filename=""), [])
        sources.append(source)
        return source

    async def scenario():
        stop = asyncio.Event()
        task = asyncio.create_task(collector.run_forever(factory, stop))
        await asyncio.sleep(0.3)
        stop.set()
        await task

    asyncio.run(scenario())
    assert len(sources) > 2
    assert event_types(store).count("connection.lost") >= 2

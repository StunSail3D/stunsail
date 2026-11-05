"""Command line entry point: run, discover, report."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys

from .collector import Collector
from .config import load_config
from .source import MoonrakerSource
from .store import AgentStore


async def _run(config_path: str) -> None:
    config = load_config(config_path)
    store = AgentStore(config.buffer_path)
    collector = Collector(
        store, store.agent_id(config.agent_id), sample_interval=config.sample_interval
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows event loops
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    try:
        await collector.run_forever(lambda: MoonrakerSource(config.moonraker), stop)
    finally:
        store.close()


async def _discover(config_path: str) -> None:
    config = load_config(config_path)
    source = MoonrakerSource(config.moonraker)
    try:
        discovery = await source.open()
        snapshot = await source.snapshot()
    finally:
        await source.close()
    print(
        json.dumps(
            {
                "printer_info": discovery.printer_info,
                "moonraker_version": discovery.server_info.get("moonraker_version"),
                "available_objects": discovery.objects,
                "observed_objects": discovery.observed,
                "snapshot": snapshot,
            },
            indent=2,
        )
    )


def _report(config_path: str) -> None:
    config = load_config(config_path)
    store = AgentStore(config.buffer_path)
    jobs = store.list_jobs()
    print(f"events={store.count('events')} samples={store.count('samples')} jobs={len(jobs)}")
    for job in jobs:
        print(
            f"{job['started_at']}  {job['state']:<11} {job['filename']}  "
            f"samples={store.sample_count_for_job(job['job_id'])}  "
            f"filament_mm={job['filament_used_mm']}  duration_s={job['print_duration_s']}  "
            f"ended={job['ended_at']} ({job['end_source']})"
        )
    store.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stunsail-agent")
    parser.add_argument("command", choices=["run", "discover", "report"])
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if args.command == "report":
        _report(args.config)
    else:
        asyncio.run(_run(args.config) if args.command == "run" else _discover(args.config))
    return 0


if __name__ == "__main__":
    sys.exit(main())

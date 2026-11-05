"""Command line entry point: run, discover, report."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys

from stunsail_cost_engine import calculate_cost, integrate_energy, load_energy_config

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


def _energy_report(config_path: str, energy_path: str) -> None:
    config = load_config(config_path)
    profile, tariffs = load_energy_config(energy_path)
    store = AgentStore(config.buffer_path)
    print(
        f"profile={profile.name} v{profile.version} "
        f"({'meter-calibrated' if profile.calibrated_against_meter else 'ESTIMATED, uncalibrated'})"
    )
    for job in store.list_jobs():
        energy = integrate_energy(store.job_samples(job["job_id"]), profile)
        cost = calculate_cost(energy.intervals, tariffs)
        priced = f"{cost.total:.2f} {cost.currency}" if cost.currency else "no tariff"
        print(
            f"{job['started_at']}  {job['state']:<11} {job['filename']}\n"
            f"    energy={energy.kwh:.4f} kWh  avg={energy.average_w:.0f} W  "
            f"cost={priced}  coverage={energy.coverage:.0%} "
            f"(uncovered {energy.uncovered_s:.0f}s, invalid samples {energy.invalid_samples})"
            + (f"  UNCOSTED={cost.uncosted_kwh:.4f} kWh" if cost.uncosted_kwh else "")
        )
    store.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stunsail-agent")
    parser.add_argument("command", choices=["run", "discover", "report", "energy-report"])
    parser.add_argument("--config", required=True)
    parser.add_argument("--energy", help="energy profile/tariff YAML (energy-report)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if args.command == "report":
        _report(args.config)
    elif args.command == "energy-report":
        if not args.energy:
            parser.error("energy-report requires --energy")
        _energy_report(args.config, args.energy)
    else:
        asyncio.run(_run(args.config) if args.command == "run" else _discover(args.config))
    return 0


if __name__ == "__main__":
    sys.exit(main())

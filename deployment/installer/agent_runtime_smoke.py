#!/usr/bin/env python3
"""Check candidate Agent configuration and a copied buffer without network access."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from stunsail_agent.config import load_config
from stunsail_agent.store import MIGRATIONS, AgentStore


def check(config_file: Path, buffer: Path, agent: str) -> None:
    config = load_config(config_file)
    if config.agent_id != agent:
        raise ValueError("Agent configuration identity does not match the backup")
    if config.buffer_path != f"/var/lib/stunsail/agent/{agent}/buffer.db":
        raise ValueError("Agent buffer path does not match the backup")
    with sqlite3.connect(buffer.as_uri() + "?mode=ro", uri=True) as db:
        version = db.execute("PRAGMA user_version").fetchone()[0]
    if version > len(MIGRATIONS):
        raise ValueError("Agent buffer schema is newer than the candidate supports")
    store = AgentStore(buffer)
    try:
        store.agent_id(agent)
        store.pending_counts()
        store.undelivered_events(agent, 100)
        store.undelivered_samples(100)
        store.list_jobs()
    finally:
        store.close()
    with sqlite3.connect(buffer.as_uri() + "?mode=ro", uri=True) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("Agent rehearsal buffer failed SQLite integrity check")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("buffer", type=Path)
    parser.add_argument("agent")
    args = parser.parse_args()
    check(args.config, args.buffer, args.agent)
    print(f"Candidate Agent configuration and buffer checks passed: {args.agent}")


if __name__ == "__main__":
    main()

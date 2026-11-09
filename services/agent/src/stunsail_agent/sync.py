"""Delivers buffered samples and events to Core with at-least-once semantics."""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import timedelta

import httpx

from .store import AgentStore, utcnow

log = logging.getLogger(__name__)

BATCH = 500


class Syncer:
    def __init__(
        self,
        store: AgentStore,
        agent_id: str,
        client: httpx.AsyncClient,
        *,
        interval: float = 5.0,
        max_backoff: float = 60.0,
        retention_days: float = 7.0,
    ) -> None:
        self.store = store
        self.agent_id = agent_id
        self.client = client
        self.interval = interval
        self.max_backoff = max_backoff
        self.retention = timedelta(days=retention_days)

    async def sync_once(self) -> bool:
        """Send one batch. Returns True when something was sent and acknowledged."""
        samples = self.store.undelivered_samples(BATCH)
        through = None
        if samples:
            # Events past the batch wait, so Core never sees a job end before its samples.
            through = self.store.next_undelivered_sample_time(samples[-1]["sequence"])
            if through is not None:
                through = samples[-1]["observed_at"]
        events = self.store.undelivered_events(self.agent_id, BATCH, through)
        if not samples and not events:
            return False
        response = await self.client.post(
            f"/agents/{self.agent_id}/sync", json={"samples": samples, "events": events}
        )
        response.raise_for_status()
        ack = response.json()
        if not isinstance(ack, dict):
            raise ValueError("invalid sync acknowledgement: expected an object")
        event_ids = ack.get("accepted_event_ids")
        sample_sequences = ack.get("accepted_sample_sequences")
        if (
            not isinstance(event_ids, list)
            or not all(isinstance(item, str) for item in event_ids)
            or not isinstance(sample_sequences, list)
            or not all(type(item) is int for item in sample_sequences)
            or len(event_ids) != len(set(event_ids))
            or len(sample_sequences) != len(set(sample_sequences))
            or not set(event_ids).issubset({event["event_id"] for event in events})
            or not set(sample_sequences).issubset({sample["sequence"] for sample in samples})
            or not (event_ids or sample_sequences)
        ):
            raise ValueError("invalid sync acknowledgement: unexpected or missing identifiers")
        self.store.mark_delivered(event_ids, sample_sequences)
        self.store.prune_delivered_samples(utcnow() - self.retention)
        return True

    async def drain(self) -> None:
        while await self.sync_once():
            pass

    async def run_forever(self, stop: asyncio.Event) -> None:
        failures = 0
        while not stop.is_set():
            delay = self.interval
            try:
                if await self.sync_once():
                    failures = 0
                    continue
                failures = 0
            except (httpx.HTTPError, ValueError, KeyError) as error:
                failures += 1
                delay = min(self.max_backoff, self.interval * 2**failures)
                delay *= random.uniform(0.5, 1.0)
                log.warning("sync failed (%s); retrying in %.1fs", error, delay)
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
            except TimeoutError:
                pass

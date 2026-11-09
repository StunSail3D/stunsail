import asyncio

import httpx
import pytest
import yaml

from stunsail_agent.config import ConfigError, load_config
from stunsail_agent.store import AgentStore, utcnow
from stunsail_agent.sync import Syncer


def write_config(tmp_path, *, mode=None, core_url=None, ca_file=None):
    settings = {
        "agent": {
            "local_buffer_url": "sqlite:///buffer.db",
            "moonraker": {"instances": [{"name": "one", "url": "http://localhost:7125"}]},
        }
    }
    if mode is not None:
        settings["deployment_mode"] = mode
    if core_url is not None:
        settings["agent"]["core_url"] = core_url
    if ca_file is not None:
        settings["agent"]["core_ca_file"] = ca_file
    path = tmp_path / "agent.yaml"
    path.write_text(yaml.safe_dump(settings), encoding="utf-8")
    return path


def test_agent_only_requires_https_and_accepts_custom_ca(tmp_path):
    with pytest.raises(ConfigError, match="requires.*HTTPS"):
        load_config(write_config(tmp_path, mode="agent_only"))
    with pytest.raises(ConfigError, match="requires.*HTTPS"):
        load_config(write_config(tmp_path, mode="agent_only", core_url="http://core:8000"))
    cfg = load_config(
        write_config(tmp_path, mode="agent_only", core_url="https://core:8443", ca_file="ca.pem")
    )
    assert cfg.core_url == "https://core:8443/api/v1"
    assert cfg.core_ca_file == "ca.pem"
    assert load_config(write_config(tmp_path, core_url="http://localhost:8000")).core_url == (
        "http://localhost:8000/api/v1"
    )


@pytest.mark.parametrize(
    "url",
    [
        "ftp://host",
        "https://user:password@host",
        "https://host/?x=1",
        "https://host/#x",
        "https://host:invalid",
        "https://host:0",
        "https:///missing",
    ],
)
def test_invalid_core_urls_are_rejected(tmp_path, url):
    with pytest.raises(ConfigError, match="core_url"):
        load_config(write_config(tmp_path, core_url=url))


def test_custom_ca_requires_https(tmp_path):
    with pytest.raises(ConfigError, match="requires an HTTPS"):
        load_config(write_config(tmp_path, core_url="http://host", ca_file="ca.pem"))


def test_buffer_refuses_new_identity_and_keeps_data(tmp_path):
    path = tmp_path / "buffer.db"
    store = AgentStore(path)
    assert store.agent_id("printer-1") == "printer-1"
    store.append_event("printer-1", "test", utcnow(), {})
    store.close()
    store = AgentStore(path)
    with pytest.raises(ValueError, match="buffer belongs to agent"):
        store.agent_id("printer-2")
    assert store.agent_id() == "printer-1"
    assert store.pending_counts() == (1, 0)
    store.close()


@pytest.mark.parametrize(
    "ack",
    [
        {},
        {"accepted_event_ids": [], "accepted_sample_sequences": []},
        {"accepted_event_ids": ["unknown"], "accepted_sample_sequences": []},
        {"accepted_event_ids": [], "accepted_sample_sequences": [True]},
        {"accepted_event_ids": [], "accepted_sample_sequences": [1, 1]},
        {"accepted_event_ids": [], "accepted_sample_sequences": [999]},
    ],
)
def test_bad_acknowledgement_never_discards_buffered_data(ack):
    store = AgentStore(":memory:")
    store.append_event("a", "test", utcnow(), {})
    store.append_sample(utcnow(), None, "ok", {})

    async def run():
        async def handler(request):
            return httpx.Response(200, json=ack, request=request)

        async with httpx.AsyncClient(
            base_url="https://core/api/v1", transport=httpx.MockTransport(handler)
        ) as client:
            with pytest.raises(ValueError, match="invalid sync acknowledgement"):
                await Syncer(store, "a", client).sync_once()

    asyncio.run(run())
    assert store.pending_counts() == (1, 1)
    store.close()


def test_partial_acknowledgement_marks_only_sent_identifiers():
    store = AgentStore(":memory:")
    store.append_sample(utcnow(), None, "ok", {})
    store.append_sample(utcnow(), None, "ok", {})

    async def run():
        async def handler(request):
            return httpx.Response(
                200,
                json={"accepted_event_ids": [], "accepted_sample_sequences": [1]},
                request=request,
            )

        async with httpx.AsyncClient(
            base_url="https://core/api/v1", transport=httpx.MockTransport(handler)
        ) as client:
            assert await Syncer(store, "a", client).sync_once()

    asyncio.run(run())
    assert store.pending_counts() == (0, 1)
    assert [sample["sequence"] for sample in store.undelivered_samples(10)] == [2]
    store.close()

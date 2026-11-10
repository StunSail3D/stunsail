import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stunsail_api.app import create_app
from stunsail_core.settings import CoreSettings

INSTALLER = Path(__file__).resolve().parents[2] / "deployment" / "installer"
sys.path.insert(0, str(INSTALLER))
try:
    import configure
    import register_local_agent
finally:
    sys.path.remove(str(INSTALLER))


@pytest.mark.skipif(os.name != "posix", reason="registration requires POSIX file permissions")
def test_standalone_registration_token_authenticates_against_real_core(
    db_url, tmp_path, monkeypatch
):
    config, token, admin = configure.build_configuration(
        "standalone", "printer-1", "http://localhost:7125", "http://127.0.0.1:8000", ""
    )
    bundle = tmp_path / "bundle"
    configure.write_bundle(bundle, config, token, admin)
    client = TestClient(create_app(CoreSettings(db_url, admin)))

    class Response:
        def __init__(self, response):
            self.status = response.status_code
            self.content = response.content

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size):
            return self.content[:size]

    class Opener:
        def open(self, request, timeout):
            response = client.post(
                "/api/v1/agents",
                content=request.data,
                headers=dict(request.header_items()),
            )
            return Response(response)

    monkeypatch.setattr(register_local_agent.urllib.request, "build_opener", lambda *args: Opener())
    register_local_agent.register(bundle)
    agent_token = (bundle / "agent.env").read_text().strip().partition("=")[2]
    response = client.post(
        "/api/v1/agents/printer-1/sync",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={"events": [], "samples": []},
    )
    assert response.status_code == 200
    assert response.json()["accepted_event_ids"] == []

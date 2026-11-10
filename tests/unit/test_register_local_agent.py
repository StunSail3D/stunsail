import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

INSTALLER = Path(__file__).resolve().parents[2] / "deployment" / "installer"
sys.path.insert(0, str(INSTALLER))
try:
    import configure
    import register_local_agent
finally:
    sys.path.remove(str(INSTALLER))


@unittest.skipUnless(os.name == "posix", "requires POSIX ownership and permissions")
class LocalRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.bundle = Path(self.temporary.name) / "bundle"
        config, token, admin = configure.build_configuration(
            "standalone", "printer-1", "http://localhost:7125", "http://127.0.0.1:8000", ""
        )
        configure.write_bundle(self.bundle, config, token, admin)
        self.admin = admin
        self.requests = []
        requests = self.requests
        admin_token = self.admin

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(
                    (
                        self.path,
                        self.headers.get("Authorization"),
                        json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
                    )
                )
                if self.path == "/redirect":
                    self.send_response(307)
                    self.send_header("Location", "/captured")
                    self.end_headers()
                    return
                if self.headers.get("Authorization") != f"Bearer {admin_token}":
                    self.send_error(401)
                    return
                self.send_response(201)
                self.end_headers()
                self.wfile.write(b'{"agent_id":"printer-1","token":"token_123456789012345"}')

            def log_message(self, format, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=self.server.serve_forever)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}/api/v1/agents"

    def test_registers_and_saves_token_privately_without_overwriting_existing_token(self):
        with patch.object(register_local_agent, "CORE_URL", self.endpoint):
            register_local_agent.register(self.bundle)
            self.assertEqual(
                (self.bundle / "agent.env").read_text(),
                "STUNSAIL_AGENT_TOKEN=token_123456789012345\n",
            )
            self.assertEqual((self.bundle / "agent.env").stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                register_local_agent.register(self.bundle)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0][0], "/api/v1/agents")
        self.assertEqual(self.requests[0][2], {"agent_id": "printer-1", "name": "printer-1"})
        self.assertFalse((self.bundle / ".agent.env.pending").exists())

    def test_unsafe_permissions_and_symlinks_are_rejected_before_registration(self):
        (self.bundle / "core.env").chmod(0o644)
        with self.assertRaisesRegex(ValueError, "0600"):
            register_local_agent.register(self.bundle)
        self.assertEqual(self.requests, [])
        (self.bundle / "core.env").chmod(0o600)
        (self.bundle / "agent.env").unlink()
        (self.bundle / "agent.env").symlink_to(self.bundle / "core.env")
        with self.assertRaisesRegex(ValueError, "regular"):
            register_local_agent.register(self.bundle)
        self.assertEqual(self.requests, [])

    def test_pending_file_blocks_registration(self):
        pending = self.bundle / ".agent.env.pending"
        pending.write_text("existing", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            register_local_agent.register(self.bundle)
        self.assertEqual(pending.read_text(), "existing")
        self.assertEqual(self.requests, [])

    def test_redirect_is_not_followed_and_empty_token_is_preserved(self):
        endpoint = f"http://127.0.0.1:{self.server.server_port}/redirect"
        with patch.object(register_local_agent, "CORE_URL", endpoint):
            with self.assertRaises(register_local_agent.urllib.error.HTTPError):
                register_local_agent.register(self.bundle)
        self.assertEqual([request[0] for request in self.requests], ["/redirect"])
        self.assertEqual((self.bundle / "agent.env").read_text(), register_local_agent.EMPTY_ENV)
        self.assertFalse((self.bundle / ".agent.env.pending").exists())

    def test_changed_agent_env_retains_received_token_for_recovery(self):
        original_read = register_local_agent.read_private
        count = 0

        def changed(path):
            nonlocal count
            result = original_read(path)
            if path.name == "agent.env":
                count += 1
                if count == 2:
                    return ("changed", result[1])
            return result

        with (
            patch.object(register_local_agent, "CORE_URL", self.endpoint),
            patch.object(register_local_agent, "read_private", changed),
            self.assertRaisesRegex(RuntimeError, "retained in pending"),
        ):
            register_local_agent.register(self.bundle)
        self.assertIn("token_123456789012345", (self.bundle / ".agent.env.pending").read_text())
        self.assertEqual((self.bundle / "agent.env").read_text(), register_local_agent.EMPTY_ENV)


if __name__ == "__main__":
    unittest.main()

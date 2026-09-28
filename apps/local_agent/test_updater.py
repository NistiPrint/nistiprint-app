import hashlib
import json
import os
import subprocess
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import agent
import updater


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        with updater.LOCK:
            updater.RELEASE = None
            updater.STATE.update(status="checking", available_version=None, error=None)

    @patch("updater.urlopen")
    def test_current_and_new_version(self, opened):
        opened.return_value.__enter__.return_value.geturl.return_value = "https://example.com/latest.json"
        for version, expected in [(updater.VERSION, "current"), ("99.0.0", "available")]:
            opened.return_value.__enter__.return_value.read.return_value = json.dumps({
                "version": version, "url": "https://example.com/agent.exe", "sha256": "a" * 64,
            }).encode()
            self.assertEqual(updater.check()["status"], expected)

    @patch("updater.urlopen")
    def test_interrupted_download_and_wrong_hash(self, opened):
        opened.return_value.__enter__.return_value.geturl.return_value = "https://example.com/new.exe"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "new.exe"
            opened.return_value.__enter__.return_value.read.side_effect = OSError("disconnected")
            with self.assertRaises(OSError):
                updater._download({"url": "https://example.com/new.exe", "sha256": "a" * 64}, target)
            opened.return_value.__enter__.return_value.read.side_effect = [b"content", b""]
            with self.assertRaisesRegex(ValueError, "Hash"):
                updater._download({"url": "https://example.com/new.exe", "sha256": "a" * 64}, target)

    def test_unauthorized_origin_cannot_install(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), agent.AgentHandler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            request = Request(f"http://127.0.0.1:{server.server_port}/updates/install",
                              data=b"{}", headers={"Origin": "https://other.example"})
            with patch("updater.install") as install:
                with self.assertRaises(HTTPError) as error:
                    urlopen(request)
                self.assertEqual(error.exception.code, 403)
                install.assert_not_called()
        finally:
            server.shutdown()
            server.server_close()

    def test_restart_endpoint_stops_the_running_agent(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), agent.AgentHandler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            browser_request = Request(
                f"http://127.0.0.1:{server.server_port}/restart", data=b"{}", method="POST",
                headers={"Origin": "https://app.nistiprint.neolabs.com.br"},
            )
            with self.assertRaises(HTTPError) as error:
                urlopen(browser_request, timeout=3)
            self.assertEqual(error.exception.code, 403)
            request = Request(f"http://127.0.0.1:{server.server_port}/restart",
                              data=b"{}", method="POST")
            with urlopen(request, timeout=3) as response:
                self.assertEqual(response.status, 202)
                self.assertEqual(json.loads(response.read())["status"], "restarting")
            worker.join(timeout=3)
            self.assertFalse(worker.is_alive(), "The server should stop for a replacement instance")
        finally:
            if worker.is_alive():
                server.shutdown()
                worker.join(timeout=2)
            server.server_close()

    @unittest.skipUnless(os.name == "nt", "Windows only")
    @patch("agent.subprocess.run")
    @patch("agent._local_agent_request")
    def test_identifies_versioned_agent_executable_on_listener_port(self, opened, run):
        opened.return_value = (200, json.dumps({
            "status": "online", "port": 8181,
        }).encode())
        run.side_effect = [
            Mock(returncode=0, stderr="", stdout=(
                " TCP    127.0.0.1:8181         0.0.0.0:0              LISTENING       4321\n"
            )),
            Mock(returncode=0, stderr="", stdout=json.dumps({
                "Id": 4321, "ProcessName": "NistiPrintAgent-1.1.1",
            })),
        ]
        processes = agent._legacy_agent_processes()
        self.assertEqual(processes, [{"Id": 4321, "ProcessName": "NistiPrintAgent-1.1.1"}])

    @unittest.skipUnless(os.name == "nt", "Windows only")
    def test_installer_restores_previous_executable_when_new_one_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            current = folder / "NistiPrintAgent.exe"
            staged = folder / "new.exe"
            log = folder / "agent.log"
            current.write_bytes(b"previous executable")
            expected = hashlib.sha256(current.read_bytes()).hexdigest()
            staged.write_bytes(b"invalid executable")
            result = subprocess.run([
                "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", str(Path(__file__).parent / "install_update.ps1"),
                "-Current", str(current), "-Staged", str(staged), "-ProcessId", "99999999",
                "-Port", "8181", "-ExpectedVersion", "99.0.0", "-Log", str(log),
            ], timeout=20, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(hashlib.sha256(current.read_bytes()).hexdigest(), expected)
            self.assertIn("Restaurando", log.read_text(encoding="cp1252"))


if __name__ == "__main__":
    unittest.main()

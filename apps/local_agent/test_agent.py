import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from agent import AgentHandler, MappingStore, print_direct


class MappingStoreTests(unittest.TestCase):
    def test_save_get_delete_is_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            store = MappingStore(Path(directory) / "maps.json")
            mapping = {"sku": "ABC", "file_path": "C:\\a.pdf", "printer_name": "Printer"}
            store.save("ABC", mapping)
            self.assertEqual(store.get("ABC"), mapping)
            artwork = {"artwork_id": "art-1", "file_path": "C:\\pair.pdf", "printer_name": "Printer"}
            store.save("arte:art-1", artwork)
            self.assertEqual(store.get("", artwork_id="art-1"), artwork)
            self.assertIsNone(store.get("", artwork_id="missing"))
            self.assertTrue(store.delete("ABC"))
            self.assertIsNone(store.get("ABC"))


class FallbackTests(unittest.TestCase):
    @patch("agent.open_file")
    @patch("agent.print_direct", side_effect=RuntimeError("unsupported"))
    def test_fallback_contract_dependencies_are_separate(self, _direct, opened):
        try:
            print_direct("missing", "printer", 1)
        except FileNotFoundError:
            pass
        opened.assert_not_called()


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), AgentHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, headers=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request("GET", path, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.read().decode("utf-8")
        finally:
            connection.close()

    def test_dashboard_is_served_locally(self):
        status, body = self.request("/dashboard")
        self.assertEqual(status, 200)
        self.assertIn("Agente local", body)
        self.assertIn("/logs", body)
        self.assertEqual(self.request("/dashboard", {"Host": "other.example"})[0], 403)

    def test_logs_are_bounded_and_reject_cross_origin_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            log_file = Path(directory) / "agent.log"
            log_file.write_text("".join(f"linha {i}\n" for i in range(300)), encoding="utf-8")
            with patch("agent.LOG_FILE", log_file):
                status, body = self.request("/logs")
                self.assertEqual(status, 200)
                lines = json.loads(body)["lines"]
                self.assertEqual(len(lines), 200)
                self.assertEqual(lines[0], "linha 100")
                self.assertEqual(lines[-1], "linha 299")
                self.assertEqual(self.request("/logs", {"Origin": "https://app.nistiprint.neolabs.com.br"})[0], 403)


if __name__ == "__main__":
    unittest.main()

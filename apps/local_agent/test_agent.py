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
            self.assertEqual(json.loads((Path(directory) / "maps.json").read_text(encoding="utf-8")), {"arte:art-1": artwork})

    def test_clear_removes_all_mappings_without_touching_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mapped_file = root / "product.pdf"
            mapped_file.write_bytes(b"PDF content")
            store = MappingStore(root / "maps.json")
            store.save("SKU-1", {"file_path": str(mapped_file)})
            store.save("arte:art-1", {"file_path": str(mapped_file)})

            self.assertEqual(store.clear(), 2)
            self.assertEqual(store.all(), {})
            self.assertEqual(json.loads((root / "maps.json").read_text(encoding="utf-8")), {})
            self.assertEqual(mapped_file.read_bytes(), b"PDF content")
            self.assertEqual(store.clear(), 0)


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

    def request(self, path, headers=None, method="GET"):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request(method, path, headers=headers or {})
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

    def test_delete_routes_remove_individual_and_all_only_from_local_dashboard(self):
        with tempfile.TemporaryDirectory() as directory:
            store = MappingStore(Path(directory) / "maps.json")
            store.save("SKU-1", {"file_path": "C:\\product.pdf"})
            store.save("arte:art-1", {"file_path": "C:\\artwork.pdf"})
            with patch("agent.STORE", store):
                status, body = self.request("/mappings/arte%3Aart-1", method="DELETE")
                self.assertEqual(status, 200)
                self.assertTrue(json.loads(body)["success"])
                self.assertEqual(set(store.all()), {"SKU-1"})

                external_headers = {"Origin": "https://app.nistiprint.neolabs.com.br"}
                status, _ = self.request("/mappings", external_headers, method="DELETE")
                self.assertEqual(status, 403)
                self.assertEqual(set(store.all()), {"SKU-1"})
                wrong_host_headers = {
                    "Host": "other.example",
                    "Origin": f"http://127.0.0.1:{self.server.server_port}",
                }
                status, _ = self.request("/mappings", wrong_host_headers, method="DELETE")
                self.assertEqual(status, 403)
                self.assertEqual(set(store.all()), {"SKU-1"})

                local_headers = {"Origin": f"http://127.0.0.1:{self.server.server_port}"}
                status, body = self.request("/mappings", local_headers, method="DELETE")
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body)["removed_count"], 1)
                self.assertEqual(store.all(), {})


if __name__ == "__main__":
    unittest.main()

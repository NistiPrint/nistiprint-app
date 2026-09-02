import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent import MappingStore, print_direct, unc_path_for


class MappingStoreTests(unittest.TestCase):
    def test_save_get_delete_is_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            store = MappingStore(Path(directory) / "maps.json")
            mapping = {"sku": "ABC", "file_path": "C:\\a.pdf", "printer_name": "Printer"}
            store.save("ABC", mapping)
            saved = store.get("ABC")
            self.assertEqual(saved["sku"], mapping["sku"])
            self.assertTrue(saved["stale"])
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


class PathTests(unittest.TestCase):
    @patch("agent.os.name", "posix")
    def test_local_path_has_no_unc_equivalent(self):
        self.assertIsNone(unc_path_for("/tmp/arte.pdf"))


if __name__ == "__main__":
    unittest.main()
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask
from routes.local_agent_releases import local_agent_releases_bp


class LocalAgentReleasesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        app = Flask(__name__)
        app.register_blueprint(local_agent_releases_bp)
        self.client = app.test_client()

    def test_manifest_and_executable_are_downloadable(self):
        (self.root / "latest.json").write_text('{"version":"1.1.0"}', encoding="utf-8")
        (self.root / "NistiPrintAgent-1.1.0.exe").write_bytes(b"exe")
        with patch.dict("os.environ", {"NISTIPRINT_AGENT_RELEASE_DIR": str(self.root)}):
            manifest = self.client.get("/api/v2/local-agent/releases/latest.json")
            executable = self.client.get("/api/v2/local-agent/releases/NistiPrintAgent-1.1.0.exe")
        self.assertEqual(manifest.status_code, 200)
        self.assertEqual(manifest.json["version"], "1.1.0")
        self.assertEqual(manifest.headers["Cache-Control"], "no-store")
        self.assertEqual(executable.status_code, 200)
        self.assertEqual(executable.data, b"exe")
        self.assertIn("attachment", executable.headers["Content-Disposition"])
        manifest.close()
        executable.close()

    def test_other_files_are_not_exposed(self):
        (self.root / "secret.txt").write_text("secret")
        with patch.dict("os.environ", {"NISTIPRINT_AGENT_RELEASE_DIR": str(self.root)}):
            response = self.client.get("/api/v2/local-agent/releases/secret.txt")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()

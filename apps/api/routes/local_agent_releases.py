"""Arquivos públicos de release do agente local."""

import os
import re
from pathlib import Path

from flask import Blueprint, abort, send_from_directory


local_agent_releases_bp = Blueprint("local_agent_releases", __name__)


@local_agent_releases_bp.get("/api/v2/local-agent/releases/<path:filename>")
def download_agent_release(filename):
    release_dir = os.environ.get("NISTIPRINT_AGENT_RELEASE_DIR")
    if not release_dir or not (
        filename == "latest.json" or re.fullmatch(r"NistiPrintAgent-\d+\.\d+\.\d+\.exe", filename)
    ):
        abort(404)
    directory = Path(release_dir)
    if not directory.is_dir():
        abort(404)
    response = send_from_directory(directory, filename, as_attachment=filename.endswith(".exe"))
    if filename == "latest.json":
        response.headers["Cache-Control"] = "no-store"
    return response

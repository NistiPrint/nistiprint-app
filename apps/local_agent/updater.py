"""Consulta e preparação de releases do agente Windows."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

try:
    from .version import VERSION
except ImportError:
    from version import VERSION

logger = logging.getLogger("NistiPrintAgent")
MANIFEST_URL = os.environ.get(
    "NISTIPRINT_AGENT_MANIFEST_URL",
    "https://app.nistiprint.neolabs.com.br/api/v2/local-agent/releases/latest.json",
)
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "NistiPrint"
CHECK_INTERVAL = 60 * 60
MAX_DOWNLOAD = 150 * 1024 * 1024
LOCK = threading.RLock()
STATE = {"status": "checking", "version": VERSION, "available_version": None, "error": None}
RELEASE = None


def _version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise ValueError("Versão inválida no manifesto")
    return tuple(map(int, value.split(".")))


def _https_url(value):
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("Release deve usar HTTPS")
    return value


def snapshot():
    with LOCK:
        return dict(STATE)


def check():
    global RELEASE
    try:
        with urlopen(_https_url(MANIFEST_URL), timeout=10) as response:
            _https_url(response.geturl())
            raw = response.read(16 * 1024 + 1)
        if len(raw) > 16 * 1024:
            raise ValueError("Manifesto muito grande")
        release = json.loads(raw)
        version = release["version"]
        _version_tuple(version)
        _https_url(release["url"])
        if not re.fullmatch(r"[0-9a-fA-F]{64}", release["sha256"]):
            raise ValueError("SHA-256 inválido no manifesto")
        available = _version_tuple(version) > _version_tuple(VERSION)
        with LOCK:
            RELEASE = release if available else None
            STATE.update(status="available" if available else "current",
                         available_version=version if available else None, error=None)
    except Exception as error:
        logger.warning("Falha ao verificar atualização: %s", error)
        with LOCK:
            STATE.update(status="error", error=str(error))
    return snapshot()


def _download(release, destination):
    digest = hashlib.sha256()
    size = 0
    with urlopen(_https_url(release["url"]), timeout=30) as response, destination.open("wb") as output:
        _https_url(response.geturl())
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_DOWNLOAD:
                raise ValueError("Executável excede o limite permitido")
            output.write(chunk)
            digest.update(chunk)
    if digest.hexdigest().lower() != release["sha256"].lower():
        raise ValueError("Hash do executável não confere com o manifesto")


def install(server):
    if os.name != "nt" or not getattr(sys, "frozen", False):
        raise RuntimeError("Atualização disponível apenas no executável Windows")
    with LOCK:
        if STATE["status"] != "available" or RELEASE is None:
            raise RuntimeError("Nenhuma atualização disponível")
        release = dict(RELEASE)
        STATE.update(status="downloading", error=None)
    staged = DATA_DIR / "update" / f'NistiPrintAgent-{release["version"]}.exe'
    staged.parent.mkdir(parents=True, exist_ok=True)
    try:
        _download(release, staged)
        current = Path(sys.executable).resolve()
        if not os.access(current.parent, os.W_OK):
            raise PermissionError("A pasta do agente não permite gravação")
        helper_source = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "install_update.ps1"
        helper = staged.parent / "install_update.ps1"
        shutil.copyfile(helper_source, helper)
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(helper), "-Current", str(current), "-Staged", str(staged),
             "-ProcessId", str(os.getpid()), "-Port", str(server.server_port),
             "-ExpectedVersion", release["version"], "-Log", str(DATA_DIR / "agent.log")],
            creationflags=subprocess.CREATE_NO_WINDOW,
            close_fds=True,
        )
        with LOCK:
            STATE["status"] = "installing"
        threading.Thread(target=server.shutdown, daemon=True).start()
        return snapshot()
    except Exception as error:
        staged.unlink(missing_ok=True)
        logger.exception("Falha ao preparar atualização")
        with LOCK:
            STATE.update(status="error", error=str(error))
        raise


def start_checks():
    def loop():
        while True:
            check()
            threading.Event().wait(CHECK_INTERVAL)
    threading.Thread(target=loop, name="agent-update-check", daemon=True).start()

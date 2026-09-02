"""Servidor local usado pela aplicação web para mapear e imprimir arquivos.

O processo deve escutar somente em loopback. Não recebe caminhos no endpoint
de impressão: o caminho sempre vem do mapa local previamente configurado.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tkinter import Tk, filedialog
from urllib.parse import unquote, urlparse

HOST = "127.0.0.1"
PORT = int(os.environ.get("NISTIPRINT_AGENT_PORT", "8181"))
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "NistiPrint"
MAP_FILE = DATA_DIR / "mappings.json"
LOG_FILE = DATA_DIR / "agent.log"
DATA_DIR.mkdir(parents=True, exist_ok=True)
MAX_COPIES = 999
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
# Controle de acesso: allowlist de Origin, sem token.
#
# A versao com token gerava um segredo ALEATORIO POR MAQUINA e o frontend lia um
# unico valor de build (VITE_LOCAL_AGENT_TOKEN): na pratica todo mundo tomava
# 401. E a "solucao" de usar o mesmo token em todas as maquinas publicaria o
# segredo em texto claro no bundle servido a qualquer visitante, porque
# variaveis VITE_ vao para o JS.
#
# Fica a allowlist, que e a protecao que de fato funciona sem digitacao: o
# agente so responde a origens declaradas, e a resposta deixou de espelhar o
# Origin de quem pergunta. A allowlist PRECISA ser configurada em producao —
# `NISTIPRINT_AGENT_ORIGINS` com a URL do app. O default cobre so o dev local.
ALLOWED_ORIGINS = {
    origin.strip().rstrip("/")
    for origin in os.environ.get(
        "NISTIPRINT_AGENT_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(LOG_FILE, encoding="utf-8")],
)
logger = logging.getLogger("NistiPrintAgent")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def unc_path_for(path: str) -> str | None:
    """Retorna a forma UNC quando o Windows fornece uma unidade de rede."""
    if os.name != "nt" or len(path) < 2 or path[1] != ":":
        return None
    drive = path[0]
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         f"(Get-PSDrive {drive}).DisplayRoot"],
        capture_output=True, text=True, check=False, timeout=5, creationflags=NO_WINDOW,
    )
    root = result.stdout.strip()
    if not root.startswith("\\\\"):
        return None
    return root.rstrip("\\/") + path[2:].replace("/", "\\")


class MappingStore:
    def __init__(self, path: Path = MAP_FILE):
        self.path = path
        self.lock = threading.RLock()

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def all(self) -> dict:
        with self.lock:
            data = self._read()
            for mapping in data.values():
                mapping["stale"] = not Path(mapping.get("file_path", "")).is_file()
            return data

    def get(self, sku: str) -> dict | None:
        return self.all().get(sku)

    def save(self, sku: str, mapping: dict) -> dict:
        with self.lock:
            data = self._read()
            data[sku] = {**mapping, "product_id": mapping.get("product_id"), "updated_at": mapping.get("updated_at", _now())}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix="mappings-", suffix=".json", dir=self.path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as output:
                    json.dump(data, output, ensure_ascii=False, indent=2)
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return mapping

    def delete(self, sku: str) -> bool:
        with self.lock:
            data = self._read()
            existed = data.pop(sku, None) is not None
            if existed:
                self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return existed


def list_printers() -> list[str]:
    if os.name != "nt":
        return []
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", "Get-Printer | Select-Object -ExpandProperty Name"],
        capture_output=True, text=True, check=False, timeout=10, creationflags=NO_WINDOW,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def choose_file() -> str:
    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    selected = filedialog.askopenfilename(title="Selecione o arquivo do produto")
    root.destroy()
    return selected


def print_direct(path: str, printer: str, copies: int) -> None:
    if not Path(path).is_file():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
    if os.name != "nt":
        raise RuntimeError("Impressão direta está disponível somente no Windows")
    def ps_string(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    command = f"Start-Process -FilePath {ps_string(path)} -Verb PrintTo -ArgumentList {ps_string(printer)} -Wait"
    for _ in range(copies):
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, check=False, timeout=120, creationflags=NO_WINDOW,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "O Windows recusou a impressão direta")


def open_file(path: str) -> None:
    if not Path(path).is_file():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
    if os.name != "nt":
        raise RuntimeError("Abertura padrão está disponível somente no Windows")
    os.startfile(path)  # type: ignore[attr-defined]


STORE = MappingStore()


class AgentHandler(BaseHTTPRequestHandler):
    server_version = "NistiPrintAgent/1.0"

    def _send(self, status: int, payload: dict | list):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        origin = self.headers.get("Origin", "")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        """Origem declarada na allowlist.

        Requisicao sem cabecalho Origin (curl, script local) e recusada: o
        agente existe para o app, e uma origem que nao se identifica nao tem
        como ser conferida.
        """
        origem = (self.headers.get("Origin") or "").strip().rstrip("/")
        return bool(origem) and origem in ALLOWED_ORIGINS

    def do_OPTIONS(self):
        self._send(204, {})

    def _json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            return self._send(200, {"success": True, "status": "online", "port": PORT})
        if not self._authorized():
            return self._send(403, {"error": "Origem não autorizada para este agente"})
        if path == "/printers":
            return self._send(200, {"printers": list_printers()})
        if path == "/mappings":
            return self._send(200, {"mappings": STORE.all()})
        if path.startswith("/mappings/"):
            sku = unquote(path.removeprefix("/mappings/"))
            mapping = STORE.get(sku)
            return self._send(200, mapping) if mapping else self._send(404, {"error": "SKU não mapeado"})
        return self._send(404, {"error": "Rota não encontrada"})

    def do_POST(self):
        path = urlparse(self.path).path
        if not self._authorized():
            return self._send(403, {"error": "Origem não autorizada para este agente"})
        try:
            data = self._json()
            sku = str(data.get("sku", "")).strip()
            if path == "/coverage":
                skus = [str(value).strip() for value in data.get("skus", []) if str(value).strip()]
                mappings = STORE.all()
                mapped = [value for value in skus if value in mappings and not mappings[value].get("stale")]
                stale = [value for value in skus if value in mappings and mappings[value].get("stale")]
                return self._send(200, {"mapped": mapped, "missing": [value for value in skus if value not in mappings], "stale": stale})
            if path == "/mappings":
                file_path = str(data.get("file_path", "")).strip()
                printer = str(data.get("printer_name", "")).strip()
                if not sku or not file_path or not printer:
                    return self._send(400, {"error": "sku, file_path e printer_name são obrigatórios"})
                if not Path(file_path).is_file():
                    return self._send(400, {"error": "Arquivo não encontrado"})
                mapping = {"sku": sku, "product_id": data.get("product_id"), "file_path": file_path,
                           "unc_path": unc_path_for(file_path), "printer_name": printer, "updated_at": _now()}
                return self._send(200, {"success": True, "mapping": STORE.save(sku, mapping)})
            if path == "/map-file":
                if not sku:
                    return self._send(400, {"error": "sku é obrigatório"})
                selected = choose_file()
                if not selected:
                    return self._send(200, {"success": False, "status": "cancelled"})
                return self._send(200, {"success": True, "status": "file_selected", "file_path": selected})
            if path == "/print":
                mapping = STORE.get(sku)
                if not mapping:
                    return self._send(404, {"error": "SKU não mapeado"})
                copies = max(1, min(int(data.get("copies", 1)), MAX_COPIES))
                try:
                    print_direct(mapping["file_path"], mapping["printer_name"], copies)
                    return self._send(200, {"success": True, "status": "printed", "copies": copies, "printer_name": mapping["printer_name"]})
                except Exception as direct_error:
                    try:
                        open_file(mapping["file_path"])
                        return self._send(200, {"success": True, "status": "file_opened", "message": "Impressão direta falhou; o arquivo foi aberto para impressão manual.", "direct_print_error": str(direct_error)})
                    except Exception as open_error:
                        return self._send(500, {"success": False, "status": "failed", "direct_print_error": str(direct_error), "open_file_error": str(open_error)})
            return self._send(404, {"error": "Rota não encontrada"})
        except (ValueError, json.JSONDecodeError) as error:
            return self._send(400, {"error": str(error)})

    def do_DELETE(self):
        if not self._authorized():
            return self._send(403, {"error": "Origem não autorizada para este agente"})
        path = urlparse(self.path).path
        if path.startswith("/mappings/"):
            sku = unquote(path.removeprefix("/mappings/"))
            return self._send(200, {"success": STORE.delete(sku)})
        return self._send(404, {"error": "Rota não encontrada"})

    def log_message(self, *_args):
        return


def serve() -> None:
    server = ThreadingHTTPServer((HOST, PORT), AgentHandler)
    server.daemon_threads = True
    logger.info("Agente iniciado com sucesso")
    logger.info("Escutando em http://%s:%s", HOST, PORT)
    logger.info("Mapas locais: %s", MAP_FILE)
    logger.info("Log: %s", LOG_FILE)
    try:
        try:
            from .tray import start_tray
        except ImportError:
            from tray import start_tray
        start_tray(server)
    except ImportError:
        logger.info("Ícone da bandeja indisponível. Instale as dependências de tray do agente para habilitá-lo.")
    except Exception:
        logger.exception("Não foi possível iniciar o ícone da bandeja")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Encerrando agente...")
    finally:
        server.server_close()
        logger.info("Agente encerrado")


if __name__ == "__main__":
    serve()
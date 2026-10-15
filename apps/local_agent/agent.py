"""Servidor local usado pela aplicação web para mapear e imprimir arquivos.

O processo deve escutar somente em loopback. Não recebe caminhos no endpoint
de impressão: o caminho sempre vem do mapa local previamente configurado.
"""

from __future__ import annotations

import json
import sqlite3
import hashlib
import logging
import os
import re
import subprocess
import socket
import sys
import tempfile
import threading
import ctypes
import uuid
import time
import traceback
import platform
from contextlib import closing, contextmanager
from http.client import HTTPConnection
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tkinter import Tk, filedialog
from urllib.parse import parse_qs, unquote, urlparse

try:
    from . import updater
except ImportError:
    import updater

HOST = "127.0.0.1"
PORT = int(os.environ.get("NISTIPRINT_AGENT_PORT", "8181"))
DATA_DIR = Path(os.environ.get("NISTIPRINT_AGENT_DATA_DIR") or
                (Path(os.environ.get("LOCALAPPDATA", Path.home())) / "NistiPrint"))
MAP_FILE = DATA_DIR / "mappings.json"
LOG_FILE = DATA_DIR / "agent.log"
MAX_LOG_BYTES = 64 * 1024
MAX_COPIES = 999
MAX_DIALOG_COPIES = 65535
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
ALLOWED_ORIGINS = {
    value.strip().rstrip("/")
    for value in os.environ.get(
        "NISTIPRINT_ALLOWED_ORIGINS",
        "https://app.nistiprint.neolabs.com.br,http://localhost:5173,http://localhost:5174,http://localhost:3000",
    ).split(",")
    if value.strip()
}
PRINT_JOBS: dict[int, dict] = {}
PRINT_REQUESTS_FILE = DATA_DIR / "print_requests.json"
PRINT_REQUESTS_DB = DATA_DIR / "print_requests.sqlite3"
try:
    PRINT_REQUESTS: dict[str, dict] = json.loads(PRINT_REQUESTS_FILE.read_text(encoding="utf-8"))
except (FileNotFoundError, json.JSONDecodeError):
    PRINT_REQUESTS = {}
for saved_result in PRINT_REQUESTS.values():
    if saved_result.get("job_id") and saved_result.get("printer_name"):
        PRINT_JOBS[int(saved_result["job_id"])] = saved_result
PRINT_LOCK = threading.RLock()


@contextmanager
def _print_journal_connection():
    """Commit or roll back the SQLite unit of work, then always close its handle."""
    with closing(sqlite3.connect(PRINT_REQUESTS_DB, timeout=10)) as db:
        with db:
            yield db


def _init_print_journal() -> None:
    with _print_journal_connection() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""CREATE TABLE IF NOT EXISTS print_requests (
            request_id TEXT PRIMARY KEY, content_hash TEXT NOT NULL, status TEXT NOT NULL,
            result_json TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        for request_id, result in PRINT_REQUESTS.items():
            content_hash = result.get("content_hash") or hashlib.sha256(
                json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            result["content_hash"] = content_hash
            db.execute("INSERT OR IGNORE INTO print_requests VALUES (?, ?, ?, ?, ?)",
                (request_id, content_hash, result.get("status", "RESULTADO_DESCONHECIDO"),
                 json.dumps(result, ensure_ascii=False), _now()))
        rows = db.execute("SELECT request_id, result_json FROM print_requests").fetchall()
        for request_id, raw in rows:
            try:
                result = json.loads(raw)
            except json.JSONDecodeError:
                result = {"success": False, "status": "RESULTADO_DESCONHECIDO", "request_id": request_id}
            if result.get("status") == "ENVIANDO":
                result.update({"success": False, "status": "RESULTADO_DESCONHECIDO",
                               "message": "Agente reiniciado durante o envio; verifique o spooler antes de reimprimir."})
                db.execute("UPDATE print_requests SET status=?, result_json=?, updated_at=? WHERE request_id=?",
                           (result["status"], json.dumps(result, ensure_ascii=False), _now(), request_id))
            PRINT_REQUESTS[request_id] = result


def _save_print_request(request_id: str, content_hash: str, result: dict) -> None:
    PRINT_REQUESTS[request_id] = result
    with _print_journal_connection() as db:
        db.execute("INSERT INTO print_requests VALUES (?, ?, ?, ?, ?) ON CONFLICT(request_id) DO UPDATE SET "
                   "content_hash=excluded.content_hash,status=excluded.status,result_json=excluded.result_json,updated_at=excluded.updated_at",
                   (request_id, content_hash, result.get("status", "RESULTADO_DESCONHECIDO"),
                    json.dumps(result, ensure_ascii=False), _now()))


try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    DATA_DIR = Path(tempfile.gettempdir()) / "NistiPrint"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MAP_FILE = DATA_DIR / "mappings.json"
    LOG_FILE = DATA_DIR / "agent.log"
    PRINT_REQUESTS_FILE = DATA_DIR / "print_requests.json"
    PRINT_REQUESTS_DB = DATA_DIR / "print_requests.sqlite3"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
try:
    logging.getLogger().addHandler(logging.FileHandler(LOG_FILE, encoding="utf-8"))
except OSError:
    # Keep the HTTP service available if a user profile or temp path is read-only.
    pass
logger = logging.getLogger("NistiPrintAgent")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_init_print_journal()


def _recent_log_lines(limit: int = 200) -> list[str]:
    """Read only the end of the log so the dashboard stays responsive."""
    try:
        with LOG_FILE.open("rb") as source:
            source.seek(0, os.SEEK_END)
            size = source.tell()
            source.seek(max(0, size - MAX_LOG_BYTES))
            data = source.read(MAX_LOG_BYTES)
        if size > MAX_LOG_BYTES:
            data = data.partition(b"\n")[2]
        return data.decode("utf-8", errors="replace").splitlines()[-limit:]
    except FileNotFoundError:
        return []


def _save_print_requests() -> None:
    # Compatibilidade para o chamador antigo: a fonte de verdade agora é SQLite.
    with _print_journal_connection() as db:
        for request_id, result in PRINT_REQUESTS.items():
            content_hash = result.get("content_hash") or hashlib.sha256(
                json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            result["content_hash"] = content_hash
            db.execute("INSERT INTO print_requests VALUES (?, ?, ?, ?, ?) ON CONFLICT(request_id) DO UPDATE SET "
                       "status=excluded.status,result_json=excluded.result_json,updated_at=excluded.updated_at",
                       (request_id, content_hash, result.get("status", "RESULTADO_DESCONHECIDO"),
                        json.dumps(result, ensure_ascii=False), _now()))


def _request_running_agent_restart() -> bool:
    """Ask the agent already serving this port to exit before taking over."""
    try:
        status, _ = _local_agent_request("/restart", method="POST", timeout=3)
        return status in (200, 202)
    except Exception:
        return False


def _local_agent_request(path: str, *, method: str = "GET", timeout: float = 2) -> tuple[int, bytes]:
    """Call loopback directly, bypassing workstation HTTP proxy settings."""
    connection = HTTPConnection(HOST, PORT, timeout=timeout)
    try:
        body = b"{}" if method == "POST" else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, response.read(16 * 1024)
    finally:
        connection.close()


def _legacy_agent_processes() -> list[dict] | None:
    """List versioned agent executables listening on the configured local port."""
    if os.name != "nt":
        return None
    try:
        result = subprocess.run(
            ["netstat.exe", "-ano", "-p", "tcp"],
            capture_output=True, text=True, check=False, timeout=8, creationflags=NO_WINDOW,
        )
        if result.returncode != 0:
            logger.error("netstat não conseguiu identificar o listener da porta %s: %s", PORT, result.stderr.strip())
            return None
        endpoint = f"{HOST}:{PORT}".casefold()
        process_ids = set()
        for line in result.stdout.splitlines():
            columns = line.split()
            if len(columns) >= 5 and columns[0].casefold() == "tcp" \
                    and columns[1].casefold() == endpoint and columns[3].casefold() == "listening":
                try:
                    process_ids.add(int(columns[4]))
                except ValueError:
                    continue
        if not process_ids:
            return []
    except Exception:
        logger.exception("Não foi possível consultar a porta do agente")
        return None

    try:
        status, body = _local_agent_request("/health", timeout=2)
        health = json.loads(body) if status == 200 else {}
        if health.get("status") != "online" or int(health.get("port") or 0) != PORT:
            logger.error("A porta %s está ocupada, mas não respondeu como agente NistiPrint", PORT)
            return None
    except (TimeoutError, socket.timeout):
        logger.error("A porta %s está ocupada, mas /health não respondeu no prazo", PORT)
        return None
    except Exception:
        logger.exception("Não foi possível validar o processo que ocupa a porta do agente")
        return None

    try:
        ids = ",".join(str(process_id) for process_id in sorted(process_ids))
        script = (
            f"$ids = @({ids}); Get-Process -Id $ids -ErrorAction SilentlyContinue "
            "| Select-Object Id,ProcessName | ConvertTo-Json -Compress"
        )
        processes_result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, check=False, timeout=8, creationflags=NO_WINDOW,
        )
        if processes_result.returncode != 0 or not processes_result.stdout.strip():
            logger.error("Não foi possível consultar os processos que ocupam a porta %s", PORT)
            return None
        processes = json.loads(processes_result.stdout)
        if isinstance(processes, dict):
            processes = [processes]
        by_id = {int(process.get("Id") or 0): process for process in processes if process.get("Id")}
        if set(by_id) != process_ids:
            logger.error("A lista de processos da porta %s mudou durante a identificação", PORT)
            return None
        for process in processes:
            name = str(process.get("ProcessName") or "")
            if not re.fullmatch(r"NistiPrintAgent(?:-\d+\.\d+\.\d+)?", name, re.IGNORECASE):
                logger.error("A porta %s pertence a outro processo (%s, PID %s); não será encerrado",
                             PORT, name or "desconhecido", process.get("Id"))
                return None
        return processes
    except Exception:
        logger.exception("Não foi possível identificar o processo que ocupa a porta do agente")
        return None


def _replace_legacy_agent() -> bool | None:
    """Stop only a verified older NistiPrint agent that cannot accept restart requests."""
    processes = _legacy_agent_processes()
    if processes is None:
        return False
    if not processes:
        return None
    process_ids = {int(process["Id"]) for process in processes}
    logger.info("Substituindo instância(s) anterior(es) do agente (PID %s)", sorted(process_ids))
    if _request_running_agent_restart():
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            remaining = _legacy_agent_processes()
            if remaining == []:
                return True
            if remaining is None:
                return False
            time.sleep(0.25)

    current_processes = _legacy_agent_processes()
    if current_processes is None:
        return False
    if not current_processes:
        return True
    for process in current_processes:
        process_id = int(process["Id"])
        if process_id not in process_ids:
            logger.error("Um novo processo passou a atender a porta %s; não será encerrado", PORT)
            return False
        result = subprocess.run(
            ["taskkill.exe", "/PID", str(process_id), "/T", "/F"],
            capture_output=True, text=True, check=False, timeout=10, creationflags=NO_WINDOW,
        )
        if result.returncode != 0:
            logger.error("Não foi possível encerrar a instância antiga do agente (PID %s): %s",
                         process_id, result.stderr.strip())
            return False
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        remaining = _legacy_agent_processes()
        if remaining == []:
            return True
        if remaining is None:
            return False
        time.sleep(0.25)
    logger.error("A instância antiga continua atendendo na porta %s", PORT)
    return False


def _acquire_single_instance():
    """Acquire the per-user Windows mutex, handing off from a running copy."""
    if os.name != "nt":
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint
    ctypes.set_last_error(0)
    # Version-scoped names let a new build take over from an older build that
    # adopted the mutex but failed before binding the HTTP port.
    handle = kernel32.CreateMutexW(None, True, f"Local\\NistiPrintAgent-{PORT}-{updater.VERSION}")
    if not handle:
        raise OSError("Não foi possível reservar a instância única do agente")
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        logger.info("Outra instância do agente está aberta; solicitando a substituição")
        _request_running_agent_restart()
        result = kernel32.WaitForSingleObject(handle, 20000)
        if result not in (0, 0x80):  # WAIT_OBJECT_0 / WAIT_ABANDONED
            kernel32.CloseHandle(handle)
            logger.error("A instância aberta não encerrou; o novo agente não será iniciado")
            return False
    return handle


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
            return self._read()

    def get(self, sku: str, product_id: str | int | None = None, artwork_id: str | None = None) -> dict | None:
        data = self.all()
        if artwork_id:
            return data.get(f"arte:{artwork_id}")
        mapping = data.get(sku)
        if mapping:
            return mapping
        if product_id is not None:
            expected = str(product_id)
            matches = [item for item in data.values()
                       if str(item.get("product_id") or "") == expected]
            return max(matches, key=lambda item: item.get("updated_at") or "") if matches else None
        return None

    def save(self, sku: str, mapping: dict) -> dict:
        with self.lock:
            data = self._read()
            data[sku] = mapping
            self._write(data)
            return mapping

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="mappings-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(data, output, ensure_ascii=False, indent=2)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def delete(self, sku: str) -> bool:
        with self.lock:
            data = self._read()
            existed = data.pop(sku, None) is not None
            if existed:
                self._write(data)
            return existed

    def clear(self) -> int:
        with self.lock:
            data = self._read()
            removed = len(data)
            if removed:
                self._write({})
            return removed


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


def _devnames_block(printer: str):
    """Create a DEVNAMES global-memory block preselecting the saved printer."""
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.restype = ctypes.c_void_p
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    values = ["WINSPOOL", printer, "", ""]
    encoded = [value.encode("utf-16-le") + b"\0\0" for value in values]
    offsets = []
    cursor = 8
    for value in encoded:
        offsets.append(cursor // 2)
        cursor += len(value)
    size = cursor
    handle = kernel32.GlobalAlloc(0x0002 | 0x0040, size)  # GMEM_MOVEABLE | GMEM_ZEROINIT
    if not handle:
        raise OSError("Não foi possível preparar o diálogo de impressão")
    address = kernel32.GlobalLock(handle)
    if not address:
        kernel32.GlobalFree(handle)
        raise OSError("Não foi possível preparar a impressora selecionada")
    header = (ctypes.c_ushort * 4)(offsets[0], offsets[1], offsets[2], 0)
    ctypes.memmove(address, header, ctypes.sizeof(header))
    cursor = 8
    for value in encoded:
        ctypes.memmove(address + cursor, value, len(value))
        cursor += len(value)
    kernel32.GlobalUnlock(handle)
    return handle


class _PRINTDLG(ctypes.Structure):
    _fields_ = [
        ("lStructSize", ctypes.c_uint32), ("hwndOwner", ctypes.c_void_p),
        ("hDevMode", ctypes.c_void_p), ("hDevNames", ctypes.c_void_p),
        ("hDC", ctypes.c_void_p), ("Flags", ctypes.c_uint32),
        ("nFromPage", ctypes.c_ushort), ("nToPage", ctypes.c_ushort),
        ("nMinPage", ctypes.c_ushort), ("nMaxPage", ctypes.c_ushort),
        ("nCopies", ctypes.c_ushort), ("hInstance", ctypes.c_void_p),
        ("lCustData", ctypes.c_ssize_t), ("lpfnPrintHook", ctypes.c_void_p),
        ("lpfnSetupHook", ctypes.c_void_p), ("lpPrintTemplateName", ctypes.c_wchar_p),
        ("lpSetupTemplateName", ctypes.c_wchar_p), ("hPrintTemplate", ctypes.c_void_p),
        ("hSetupTemplate", ctypes.c_void_p),
    ]


def _selected_printer(devnames_handle, fallback: str) -> str:
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    address = kernel32.GlobalLock(devnames_handle)
    if not address:
        return fallback
    try:
        offsets = ctypes.cast(address, ctypes.POINTER(ctypes.c_ushort * 4)).contents
        return ctypes.wstring_at(address + offsets[1] * 2) or fallback
    finally:
        kernel32.GlobalUnlock(devnames_handle)


def _print_pdf(path: str, printer: str, copies: int, request_id: str) -> dict:
    """Show the Windows print dialog, render at PDF page size, and return the spooler job id."""
    if os.name != "nt":
        raise RuntimeError("Impressão de PDF está disponível somente no Windows")
    if not Path(path).is_file() or Path(path).suffix.lower() != ".pdf":
        raise FileNotFoundError("A arte associada deve ser um arquivo PDF existente")

    try:
        import pypdfium2 as pdfium
        import win32gui
        import win32print
        from PIL import ImageWin
    except ImportError as error:
        raise RuntimeError("Instale as dependências de impressão PDF do agente local") from error

    copies = max(1, min(int(copies), MAX_DIALOG_COPIES))
    devnames = _devnames_block(printer)
    initial_devnames = devnames
    dialog = _PRINTDLG()
    dialog.lStructSize = ctypes.sizeof(dialog)
    dialog.hDevNames = devnames
    dialog.Flags = 0x00000100 | 0x00000008 | 0x00000004  # PD_RETURNDC | PD_NOPAGENUMS | PD_NOSELECTION
    dialog.nCopies = copies
    try:
        accepted = ctypes.windll.comdlg32.PrintDlgW(ctypes.byref(dialog))
        if not accepted:
            devnames = dialog.hDevNames or devnames
            error_code = ctypes.windll.comdlg32.CommDlgExtendedError()
            if error_code:
                raise OSError(f"O Windows não abriu o diálogo de impressão ({error_code})")
            return {"success": False, "status": "cancelled", "request_id": request_id}

        devnames = dialog.hDevNames or devnames
        selected_printer = _selected_printer(devnames, printer)
        hdc = int(dialog.hDC)
        dpi_x = win32print.GetDeviceCaps(hdc, 88)
        dpi_y = win32print.GetDeviceCaps(hdc, 90)
        printable_width = win32print.GetDeviceCaps(hdc, 8)
        printable_height = win32print.GetDeviceCaps(hdc, 10)
        physical_width = win32print.GetDeviceCaps(hdc, 110)
        physical_height = win32print.GetDeviceCaps(hdc, 111)
        offset_x = win32print.GetDeviceCaps(hdc, 112)
        offset_y = win32print.GetDeviceCaps(hdc, 113)

        document = pdfium.PdfDocument(path)
        dimensions = [document[index].get_size() for index in range(len(document))]
        too_large = any(
            width * dpi_x / 72 > printable_width or height * dpi_y / 72 > printable_height
            for width, height in dimensions
        )
        if too_large:
            answer = ctypes.windll.user32.MessageBoxW(
                None,
                "Uma ou mais páginas excedem a área imprimível da folha. "
                "A impressão em tamanho real poderá cortar as bordas. Deseja continuar?",
                "NistiPrint — conferir tamanho da capa",
                0x00000004 | 0x00000030 | 0x00010000,
            )
            if answer != 6:  # IDYES
                win32gui.DeleteDC(hdc)
                dialog.hDC = None
                return {"success": False, "status": "cancelled_size_warning", "request_id": request_id}

        doc_name = f"NistiPrint-{request_id}"
        current = PRINT_REQUESTS.get(request_id, {})
        request_hash = current.get("content_hash") or hashlib.sha256(request_id.encode("utf-8")).hexdigest()
        _save_print_request(request_id, request_hash, {
            **current, "success": False, "status": "ENVIANDO", "request_id": request_id,
            "message": "Trabalho iniciado no spooler; aguardando confirmação do agente.",
        })
        job_id = win32print.StartDoc(hdc, (doc_name, None, None, 0))
        _save_print_request(request_id, request_hash, {
            **PRINT_REQUESTS.get(request_id, {}), "success": False, "status": "ENVIANDO",
            "request_id": request_id, "job_id": int(job_id), "printer_name": selected_printer,
        })
        try:
            print_copies = int(dialog.nCopies or copies)
            for _ in range(print_copies):
                for page_index, page_size in enumerate(dimensions):
                    page = document[page_index]
                    page_width, page_height = page_size
                    render_scale = min(dpi_x, dpi_y, 600) / 72
                    image = page.render(scale=render_scale, rev_byteorder=True).to_pil().convert("RGB")
                    target_width = round(page_width * dpi_x / 72)
                    target_height = round(page_height * dpi_y / 72)
                    left = round((physical_width - target_width) / 2 - offset_x)
                    top = round((physical_height - target_height) / 2 - offset_y)
                    win32print.StartPage(hdc)
                    ImageWin.Dib(image).draw(hdc, (left, top, left + target_width, top + target_height))
                    win32print.EndPage(hdc)
                    image.close()
            win32print.EndDoc(hdc)
        except Exception:
            try:
                win32print.AbortDoc(hdc)
            except Exception:
                pass
            raise
        finally:
            document.close()

        result = {
            "success": True,
            "status": "queued",
            "request_id": request_id,
            "copies": print_copies,
            "printer_name": selected_printer,
            "job_id": int(job_id),
        }
        PRINT_JOBS[int(job_id)] = {"printer_name": selected_printer, **result}
        return result
    finally:
        if dialog.hDC:
            try:
                import win32gui
                win32gui.DeleteDC(int(dialog.hDC))
            except Exception:
                pass
        handles = {int(handle) for handle in (initial_devnames, dialog.hDevNames, dialog.hDevMode) if handle}
        for handle in handles:
            ctypes.windll.kernel32.GlobalFree(handle)


STORE = MappingStore()


class AgentHandler(BaseHTTPRequestHandler):
    server_version = f"NistiPrintAgent/{updater.VERSION}"

    def _send(self, status: int, payload: dict | list):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        origin = (self.headers.get("Origin") or "").rstrip("/")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-NistiPrint-Agent")
        self.end_headers()
        self.wfile.write(body)

    def _origin_allowed(self):
        origin = self.headers.get("Origin")
        return not origin or origin.rstrip("/") in ALLOWED_ORIGINS or self._local_dashboard_request()

    def _local_dashboard_host(self) -> bool:
        host = self.headers.get("Host", "").lower()
        return host in {
            f"127.0.0.1:{self.server.server_port}",
            f"localhost:{self.server.server_port}",
        } and (not self.headers.get("Origin") or self._local_dashboard_request())

    def _local_dashboard_request(self) -> bool:
        host = self.headers.get("Host", "").lower()
        if host not in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}:
            return False
        origin = self.headers.get("Origin")
        return not origin or origin.rstrip("/").lower() == f"http://{host}"

    def _send_dashboard(self):
        runtime_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
        body = (runtime_dir / "dashboard.html").read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        if not self._origin_allowed():
            return self._send(403, {"error": "Origem do navegador não autorizada"})
        self._send(204, {})

    def _json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def _discard_request_body(self) -> int | None:
        """Consume small POST bodies before an early response closes the socket."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return 400
        if length < 0:
            return 400
        if length > 64 * 1024:
            return 413
        remaining = length
        while remaining:
            chunk = self.rfile.read(min(remaining, 8192))
            if not chunk:
                return 400
            remaining -= len(chunk)
        return None

    def do_GET(self):
        if not self._origin_allowed():
            return self._send(403, {"error": "Origem do navegador não autorizada"})
        path = urlparse(self.path).path
        if path in ("/", "/dashboard", "/logs"):
            if not self._local_dashboard_host():
                return self._send(403, {"error": "Painel disponível somente no endereço local"})
            if path == "/logs":
                return self._send(200, {"lines": _recent_log_lines()})
            return self._send_dashboard()
        if path == "/health":
            return self._send(200, {"success": True, "status": "online", "port": PORT,
                                    "version": updater.VERSION, "update": updater.snapshot(),
                                    "capabilities": ["print_request_journal_sqlite", "request_status_lookup"]})
        if path.startswith("/requests/"):
            request_id = unquote(path.removeprefix("/requests/")).strip()
            result = PRINT_REQUESTS.get(request_id)
            return self._send(200, result) if result else self._send(404, {"error": "Solicitação não encontrada"})
        if path == "/updates/check":
            return self._send(200, updater.check())
        if path == "/printers":
            return self._send(200, {"printers": list_printers()})
        if path == "/mappings":
            return self._send(200, {"mappings": STORE.all()})
        if path.startswith("/mappings/artwork/"):
            artwork_id = unquote(path.removeprefix("/mappings/artwork/"))
            mapping = STORE.get("", artwork_id=artwork_id)
            return self._send(200, mapping) if mapping else self._send(404, {"error": "Arte não mapeada"})
        if path.startswith("/mappings/"):
            sku = unquote(path.removeprefix("/mappings/"))
            product_id = parse_qs(urlparse(self.path).query).get("product_id", [None])[0]
            mapping = STORE.get(sku, product_id)
            return self._send(200, mapping) if mapping else self._send(404, {"error": "SKU não mapeado"})
        if path.startswith("/jobs/"):
            try:
                job_id = int(path.removeprefix("/jobs/"))
            except ValueError:
                return self._send(400, {"error": "ID de trabalho inválido"})
            job = PRINT_JOBS.get(job_id)
            if not job:
                return self._send(404, {"error": "Trabalho não encontrado neste agente"})
            try:
                import win32print
                handle = win32print.OpenPrinter(job["printer_name"])
                try:
                    matches = [row for row in win32print.EnumJobs(handle, 0, 1000, 1) if row.get("JobId") == job_id]
                finally:
                    win32print.ClosePrinter(handle)
                if matches:
                    record = matches[0]
                    status_bits = int(record.get("Status") or 0)
                    states = [
                        (1, "pausado"), (2, "erro"), (8, "preparando"), (16, "imprimindo"),
                        (32, "impressora_offline"), (64, "sem_papel"), (128, "impresso"),
                        (512, "bloqueado"), (1024, "intervencao_necessaria"), (4096, "enviado"),
                    ]
                    state = next((name for bit, name in states if status_bits & bit), "na_fila")
                    return self._send(200, {**job, "queue_status": state,
                        "pages_printed": record.get("PagesPrinted"), "total_pages": record.get("TotalPages")})
                return self._send(200, {**job, "queue_status": "saiu_da_fila"})
            except Exception as error:
                return self._send(200, {**job, "queue_status": "sem_rastreio", "queue_error": str(error)})
        return self._send(404, {"error": "Rota não encontrada"})

    def do_POST(self):
        if not self._origin_allowed():
            self._discard_request_body()
            return self._send(403, {"error": "Origem do navegador não autorizada"})
        path = urlparse(self.path).path
        if path == "/restart":
            if self.headers.get("Origin"):
                return self._send(403, {"error": "Reinício permitido somente ao agente local"})
            # The restart caller sends a JSON body. Consume it before closing
            # this HTTP/1.0 connection; otherwise Windows may reset the socket
            # while the client is reading the 202 response.
            body_error = self._discard_request_body()
            if body_error:
                return self._send(body_error, {"error": "Corpo da solicitação inválido"})
            self._send(202, {"success": True, "status": "restarting"})
            self.wfile.flush()
            threading.Thread(target=self.server.shutdown, name="agent-restart", daemon=True).start()
            return
        if path == "/updates/install":
            try:
                result = updater.install(self.server)
                return self._send(202, result)
            except (RuntimeError, PermissionError, ValueError) as error:
                return self._send(409, {"error": str(error)})
            except Exception:
                logger.exception("Falha ao iniciar instalação")
                return self._send(500, {"error": "Falha ao iniciar instalação; consulte agent.log"})
        try:
            data = self._json()
            sku = str(data.get("sku", "")).strip()
            artwork_id = str(data.get("artwork_id") or "").strip()
            if path == "/mappings":
                file_path = str(data.get("file_path", "")).strip()
                printer = str(data.get("printer_name", "")).strip()
                if not (sku or artwork_id) or not file_path or not printer:
                    return self._send(400, {"error": "sku ou artwork_id, file_path e printer_name são obrigatórios"})
                if not Path(file_path).is_file():
                    return self._send(400, {"error": "Arquivo não encontrado"})
                if artwork_id and Path(file_path).suffix.lower() != ".pdf":
                    return self._send(400, {"error": "A arte deve ser um PDF"})
                key = f"arte:{artwork_id}" if artwork_id else sku
                mapping = {"sku": sku, "artwork_id": artwork_id or None, "product_id": data.get("product_id"), "file_path": file_path,
                           "printer_name": printer, "updated_at": _now()}
                return self._send(200, {"success": True, "mapping": STORE.save(key, mapping)})
            if path == "/map-file":
                if not (sku or artwork_id):
                    return self._send(400, {"error": "sku ou artwork_id é obrigatório"})
                selected = choose_file()
                if not selected:
                    return self._send(200, {"success": False, "status": "cancelled"})
                return self._send(200, {"success": True, "status": "file_selected", "file_path": selected})
            if path == "/print":
                mapping = STORE.get(sku, data.get("product_id"), artwork_id)
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
            if path in ("/print-dialog", "/open"):
                request_id = str(data.get("request_id") or "").strip()
                if not request_id:
                    return self._send(400, {"error": "request_id é obrigatório"})
                if not sku and not data.get("product_id") and not artwork_id:
                    return self._send(400, {"error": "sku, product_id ou artwork_id é obrigatório"})
                mapping = STORE.get(sku, data.get("product_id"), artwork_id)
                if not mapping:
                    return self._send(404, {"error": "SKU não mapeado"})
                with PRINT_LOCK:
                    try:
                        file_stat = Path(mapping["file_path"]).stat()
                    except OSError as error:
                        return self._send(400, {"error": f"Arquivo indisponível: {error}"})
                    request_hash = hashlib.sha256(json.dumps({
                        "path": str(Path(mapping["file_path"]).resolve()),
                        "size": file_stat.st_size, "mtime_ns": file_stat.st_mtime_ns,
                        "printer": mapping["printer_name"], "copies": int(data.get("copies", 1)),
                        "action": path,
                    }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
                    previous = PRINT_REQUESTS.get(request_id)
                    if previous:
                        if previous.get("content_hash") not in (None, request_hash):
                            return self._send(409, {"error": "request_id reutilizado com conteúdo de impressão diferente"})
                        return self._send(200, previous)
                    preparing = {"success": False, "status": "PREPARADO", "request_id": request_id,
                                 "content_hash": request_hash}
                    _save_print_request(request_id, request_hash, preparing)
                    if path == "/open":
                        if Path(mapping["file_path"]).suffix.lower() != ".pdf":
                            _save_print_request(request_id, request_hash, {**preparing, "status": "FALHOU"})
                            return self._send(400, {"error": "A abertura do editor aceita apenas PDF"})
                        open_file(mapping["file_path"])
                        result = {"success": True, "status": "file_opened", "request_id": request_id,
                                  "content_hash": request_hash, "message": "PDF base aberto no editor padrão."}
                    else:
                        try:
                            result = _print_pdf(mapping["file_path"], mapping["printer_name"],
                                                data.get("copies", 1), request_id)
                            result["content_hash"] = request_hash
                        except Exception as error:
                            current = PRINT_REQUESTS.get(request_id, {})
                            state = "RESULTADO_DESCONHECIDO" if current.get("status") == "ENVIANDO" else "FALHOU"
                            result = {"success": False, "status": state, "request_id": request_id,
                                      "content_hash": request_hash, "message": str(error)}
                            _save_print_request(request_id, request_hash, result)
                    if result.get("status") in ("cancelled", "cancelled_size_warning"):
                        result = {**result, "status": "CANCELADO", "content_hash": request_hash}
                    _save_print_request(request_id, request_hash, result)
                    return self._send(200, result)
            return self._send(404, {"error": "Rota não encontrada"})
        except (ValueError, json.JSONDecodeError) as error:
            return self._send(400, {"error": str(error)})

    def do_DELETE(self):
        if not self._origin_allowed():
            return self._send(403, {"error": "Origem do navegador não autorizada"})
        path = urlparse(self.path).path
        if path == "/mappings":
            if not self._local_dashboard_request():
                return self._send(403, {"error": "Limpeza permitida somente pelo painel local"})
            removed = STORE.clear()
            return self._send(200, {"success": True, "removed_count": removed})
        if path.startswith("/mappings/"):
            sku = unquote(path.removeprefix("/mappings/"))
            return self._send(200, {"success": STORE.delete(sku)})
        return self._send(404, {"error": "Rota não encontrada"})

    def log_message(self, *_args):
        return


def serve() -> None:
    if os.name == "nt":
        try:
            windows_version = tuple(int(part) for part in platform.win32_ver()[1].split(".")[:2])
        except (TypeError, ValueError):
            windows_version = ()
        if windows_version and windows_version < (10, 0):
            raise RuntimeError(
                f"Windows {platform.win32_ver()[1]} não é suportado. "
                "O agente exige Windows 10 ou superior."
            )
    mutex = _acquire_single_instance()
    if mutex is False:
        return
    try:
        if os.name == "nt":
            if _replace_legacy_agent() is False:
                logger.error("O agente anterior não pôde ser substituído; nenhuma nova bandeja será iniciada")
                return
        server = ThreadingHTTPServer((HOST, PORT), AgentHandler)
        server.daemon_threads = True
        logger.info("Agente iniciado com sucesso")
        logger.info("Escutando em http://%s:%s", HOST, PORT)
        logger.info("Mapas locais: %s", MAP_FILE)
        logger.info("Log: %s", LOG_FILE)
        updater.start_checks()
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
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Encerrando agente...")
    except OSError:
        logger.exception("Não foi possível iniciar o agente; a porta %s pode estar em uso", PORT)
    finally:
        if "server" in locals():
            server.server_close()
            logger.info("Agente encerrado")
        if mutex:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.ReleaseMutex.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.ReleaseMutex(mutex)
            kernel32.CloseHandle(mutex)


def _install_bootstrap_error_logger() -> None:
    """Capture failures that happen before normal application logging starts."""
    data_dir = Path(os.environ.get("NISTIPRINT_AGENT_DATA_DIR") or
                    (Path(os.environ.get("LOCALAPPDATA", Path.home())) / "NistiPrint"))
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        error_file = data_dir / "startup-error.log"
    except Exception:
        error_file = Path(tempfile.gettempdir()) / "NistiPrintAgent-startup-error.log"

    def report(exc_type, exc_value, exc_traceback):
        details = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        try:
            with error_file.open("a", encoding="utf-8") as target:
                target.write(f"\n[{datetime.now(timezone.utc).isoformat()}] Falha ao iniciar agente\n{details}\n")
        except Exception:
            pass
        if sys.stderr:
            try:
                sys.stderr.write(details)
            except Exception:
                pass

    sys.excepthook = report


_install_bootstrap_error_logger()


if __name__ == "__main__":
    try:
        serve()
    except Exception:
        logger.exception("Falha fatal ao iniciar o agente")
        raise

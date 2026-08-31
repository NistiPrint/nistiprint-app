"""Ícone opcional da bandeja do Windows.

Dependências opcionais: pystray e Pillow. O agente continua funcionando sem
elas, mantendo o servidor HTTP e o log normalmente ativos.
"""

from __future__ import annotations

import threading
import webbrowser
import sys
from pathlib import Path


def start_tray(server) -> None:
    import pystray
    from PIL import Image, ImageDraw

    runtime_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    icon_path = runtime_dir / "icon.ico"
    if icon_path.exists():
        image = Image.open(icon_path)
    else:
        image = Image.new("RGBA", (64, 64), "#2563eb")
        draw = ImageDraw.Draw(image)
        draw.text((15, 20), "NP", fill="white")

    def open_web(_icon, _item):
        webbrowser.open(f"http://127.0.0.1:{server.server_port}/health")

    def quit_agent(icon, _item):
        icon.stop()
        server.shutdown()

    icon = pystray.Icon(
        "nistiprint-agent",
        image,
        "NistiPrint - Agente local",
        menu=pystray.Menu(
            pystray.MenuItem("Verificar agente", open_web),
            pystray.MenuItem("Encerrar agente", quit_agent),
        ),
    )
    threading.Thread(target=icon.run, name="nistiprint-tray", daemon=True).start()
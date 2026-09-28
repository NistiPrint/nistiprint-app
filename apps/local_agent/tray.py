"""Ícone opcional da bandeja do Windows.

Dependências opcionais: pystray e Pillow. O agente continua funcionando sem
elas, mantendo o servidor HTTP e o log normalmente ativos.
"""

from __future__ import annotations

import threading
import webbrowser
import sys
from pathlib import Path

try:
    from . import updater
except ImportError:
    import updater


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
        webbrowser.open(f"http://127.0.0.1:{server.server_port}/dashboard")

    def quit_agent(icon, _item):
        icon.stop()
        server.shutdown()

    def check_updates(icon, _item):
        state = updater.check()
        if state["status"] == "available":
            icon.notify(f'Versão {state["available_version"]} disponível. Use "Atualizar agente" para instalar.', "NistiPrint")
        elif state["status"] == "current":
            icon.notify("O agente está atualizado.", "NistiPrint")
        else:
            icon.notify("Não foi possível verificar. Consulte agent.log.", "NistiPrint")

    def install_update(icon, _item):
        try:
            updater.install(server)
            icon.notify("Atualização iniciada.", "NistiPrint")
        except Exception as error:
            icon.notify(str(error), "NistiPrint")

    icon = pystray.Icon(
        "nistiprint-agent",
        image,
        "NistiPrint - Agente local",
        menu=pystray.Menu(
            pystray.MenuItem("Ver painel do agente", open_web),
            pystray.MenuItem("Verificar atualizações", check_updates),
            pystray.MenuItem("Atualizar agente", install_update,
                             enabled=lambda _item: updater.snapshot()["status"] == "available"),
            pystray.MenuItem("Encerrar agente", quit_agent),
        ),
    )
    threading.Thread(target=icon.run, name="nistiprint-tray", daemon=True).start()

"""Punto de entrada: `python -m callbridge` (o CallBridge.exe).

Abre la interfaz en una ventana de escritorio (pywebview). Con --browser, o si
pywebview no está instalado, la abre en el navegador predeterminado.
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import webbrowser

from werkzeug.serving import make_server

from .server import create_app

FILE_TYPES = {
    "gguf": ("Modelos GGUF (*.gguf)", "Todos los archivos (*.*)"),
    "audio": ("Audio (*.wav;*.mp3;*.m4a;*.ogg;*.opus;*.flac;*.webm)", "Todos los archivos (*.*)"),
    "folder": None,
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _ensure_streams() -> None:
    """En el .exe sin consola stdout/stderr son None: se redirigen a un log."""
    if sys.stdout is None or sys.stderr is None:
        from .config import data_dir
        log = open(data_dir() / "callbridge.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log


def _privacy() -> None:
    """Sin telemetría de ninguna librería. El servidor solo escucha en 127.0.0.1."""
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("DO_NOT_TRACK", "1")
    os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
    try:
        import onnxruntime
        onnxruntime.disable_telemetry_events()
    except Exception:  # noqa: BLE001
        pass


def main() -> None:
    _ensure_streams()
    _privacy()
    ap = argparse.ArgumentParser(description="CallBridge – revisión de llamadas")
    ap.add_argument("--browser", action="store_true", help="abrir en el navegador en lugar de ventana propia")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--no-open", action="store_true", help="no abrir nada (solo servidor)")
    args = ap.parse_args()

    webview = None
    if not args.browser and not args.no_open:
        try:
            import webview  # type: ignore
        except ImportError:
            webview = None

    window_ref: dict = {}

    def picker(kind: str):
        win = window_ref.get("w")
        if not win:
            return None
        if kind == "folder":
            res = win.create_file_dialog(webview.FOLDER_DIALOG)
        else:
            res = win.create_file_dialog(webview.OPEN_DIALOG, file_types=FILE_TYPES.get(kind) or ())
        return res[0] if res else None

    app = create_app(file_picker=picker if webview else None)
    port = args.port or _free_port()
    server = make_server("127.0.0.1", port, app, threaded=True)
    url = f"http://127.0.0.1:{port}/"
    print(f"CallBridge en {url}")

    if webview:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        window_ref["w"] = webview.create_window("CallBridge", url, width=1400, height=900, min_size=(900, 600))
        webview.start()
        server.shutdown()
    else:
        if not args.no_open:
            threading.Timer(0.8, lambda: webbrowser.open(url)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()

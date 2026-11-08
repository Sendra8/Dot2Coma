"""Puente de audio móvil <-> PC para usar el móvil como altavoz-micrófono en Teams.

    Teams altavoz  -> "CABLE-A Input"  ==VB-CABLE==> "CABLE-A Output" -> [captura] -> móvil (altavoz/cascos)
    Teams micro    <- "CABLE-B Output" <==VB-CABLE== "CABLE-B Input"  <- [reproduce] <- móvil (micrófono)

Transporte: TCP en 127.0.0.1:<puerto>, llevado al móvil por USB con `adb reverse`.
Nada sale del equipo: la conexión va por el cable USB.

Protocolo (igual en la app Android, ver android/.../Proto.kt):
    trama = tipo (1 byte) | longitud (2 bytes, big-endian) | datos
    tipo 1 = audio PCM 16 bits little-endian, mono, 48 kHz, 10 ms (480 muestras)
    tipo 2 = control JSON UTF-8 ({"t": "hello" | "state" | "rec" | "mute" ...})
    tipo 3 = ping

Grabación: FLAC estéreo 48 kHz, izquierda = micrófono del móvil ("Yo"), derecha = audio de Teams (remoto).
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

import numpy as np

RATE = 48000
FRAME = 480                      # 10 ms
T_AUDIO, T_CTRL, T_PING = 1, 2, 3
PROTO_VERSION = 1
APP_PACKAGE = "io.github.sendra8.callbridge"


# --------------------------------------------------------------------------- #
# Tramas
# --------------------------------------------------------------------------- #

def pack(kind: int, payload: bytes) -> bytes:
    return struct.pack(">BH", kind, len(payload)) + payload


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("conexión cerrada")
        buf += chunk
    return bytes(buf)


def read_frame(sock: socket.socket) -> tuple[int, bytes]:
    kind, length = struct.unpack(">BH", _recv_exact(sock, 3))
    return kind, _recv_exact(sock, length) if length else b""


# --------------------------------------------------------------------------- #
# Búfer anti-jitter con corrección de deriva de reloj
# --------------------------------------------------------------------------- #

class JitterBuffer:
    """Cola de muestras int16. Rellena con silencio si se vacía y descarta si se acumula.

    Los relojes del móvil y del PC no van exactamente a la misma velocidad: sin
    esto, en una llamada larga el retardo crecería sin límite.
    """

    def __init__(self, target_ms: int = 60, max_ms: int = 200):
        self.target = RATE * target_ms // 1000
        self.max = RATE * max_ms // 1000
        self._buf = np.zeros(0, dtype=np.int16)
        self._lock = threading.Lock()
        self._primed = False
        self.underruns = 0
        self.drops = 0

    def write(self, samples: np.ndarray) -> None:
        with self._lock:
            self._buf = np.concatenate([self._buf, samples])
            if len(self._buf) > self.max:
                self.drops += 1
                self._buf = self._buf[-self.target:]

    def read(self, n: int) -> np.ndarray:
        with self._lock:
            if not self._primed:
                if len(self._buf) < self.target:
                    return np.zeros(n, dtype=np.int16)
                self._primed = True
            if len(self._buf) < n:
                self.underruns += 1
                self._primed = False
                out = np.zeros(n, dtype=np.int16)
                out[: len(self._buf)] = self._buf
                self._buf = np.zeros(0, dtype=np.int16)
                return out
            out, self._buf = self._buf[:n], self._buf[n:]
            return out

    def clear(self) -> None:
        with self._lock:
            self._buf = np.zeros(0, dtype=np.int16)
            self._primed = False

    def __len__(self) -> int:
        return len(self._buf)


def level(x: np.ndarray) -> float:
    """Nivel 0..1 aproximado (pico) para los vúmetros."""
    return float(np.abs(x).max(initial=0)) / 32768.0 if len(x) else 0.0


# --------------------------------------------------------------------------- #
# Dispositivos de audio del PC
# --------------------------------------------------------------------------- #

class SoundDeviceIO:
    """Audio real con sounddevice/PortAudio (WASAPI en Windows)."""

    def __init__(self):
        import sounddevice as sd  # noqa: F401  (falla pronto si no hay PortAudio)
        self.sd = sd
        self.streams: list = []

    def list_devices(self) -> dict:
        sd = self.sd
        apis = sd.query_hostapis()
        out: dict = {"inputs": [], "outputs": []}
        for i, d in enumerate(sd.query_devices()):
            entry = {"index": i, "name": d["name"], "api": apis[d["hostapi"]]["name"]}
            if d["max_input_channels"] > 0:
                out["inputs"].append(entry)
            if d["max_output_channels"] > 0:
                out["outputs"].append(entry)
        return out

    def find(self, name: str, kind: str) -> int:
        """Índice del dispositivo cuyo nombre contiene `name`; prefiere WASAPI (menos latencia)."""
        devs = self.list_devices()["inputs" if kind == "in" else "outputs"]
        cands = [d for d in devs if name.lower() in d["name"].lower()]
        if not cands:
            raise RuntimeError(f"No encuentro el dispositivo «{name}». ¿Está instalado VB-CABLE A+B?")
        cands.sort(key=lambda d: 0 if "WASAPI" in d["api"] else 1 if "DirectSound" in d["api"] else 2)
        return cands[0]["index"]

    def start(self, out_name: str, in_name: str,
              out_cb: Callable[[int], np.ndarray], in_cb: Callable[[np.ndarray], None]) -> None:
        sd = self.sd
        out_idx, in_idx = self.find(out_name, "out"), self.find(in_name, "in")

        def extra(idx):
            api = sd.query_hostapis(sd.query_devices(idx)["hostapi"])["name"]
            return sd.WasapiSettings(auto_convert=True) if "WASAPI" in api and hasattr(sd, "WasapiSettings") else None

        def ocb(outdata, frames, t, status):
            outdata[:, 0] = out_cb(frames)

        def icb(indata, frames, t, status):
            in_cb(indata[:, 0].copy())

        self.streams = [
            sd.OutputStream(device=out_idx, samplerate=RATE, channels=1, dtype="int16", blocksize=FRAME,
                            latency="low", extra_settings=extra(out_idx), callback=ocb),
            sd.InputStream(device=in_idx, samplerate=RATE, channels=1, dtype="int16", blocksize=FRAME,
                           latency="low", extra_settings=extra(in_idx), callback=icb),
        ]
        for s in self.streams:
            s.start()

    def stop(self) -> None:
        for s in self.streams:
            try:
                s.stop()
                s.close()
            except Exception:  # noqa: BLE001
                pass
        self.streams = []


# --------------------------------------------------------------------------- #
# Grabación
# --------------------------------------------------------------------------- #

class Recorder:
    """Escribe FLAC estéreo en un hilo aparte (los callbacks de audio no deben bloquearse)."""

    def __init__(self, path: Path):
        import soundfile as sf
        self.path = path
        self.started = time.time()
        self.frames = 0
        self._q: queue.Queue = queue.Queue()
        self._file = sf.SoundFile(str(path), "w", samplerate=RATE, channels=2, format="FLAC", subtype="PCM_16")
        self._t = threading.Thread(target=self._run, daemon=True, name="recorder")
        self._t.start()

    def push(self, left: np.ndarray, right: np.ndarray) -> None:
        self._q.put(np.stack([left, right], axis=1))
        self.frames += len(left)

    def _run(self) -> None:
        while True:
            block = self._q.get()
            if block is None:
                break
            self._file.write(block)
        self._file.close()

    def close(self) -> None:
        self._q.put(None)
        self._t.join(timeout=10)

    @property
    def seconds(self) -> float:
        return self.frames / RATE


# --------------------------------------------------------------------------- #
# ADB
# --------------------------------------------------------------------------- #

def _no_window() -> dict:
    return {"creationflags": 0x08000000} if os.name == "nt" else {}  # CREATE_NO_WINDOW


def find_adb(configured: str = "") -> str | None:
    cands = [configured] if configured else []
    found = shutil.which("adb")
    if found:
        cands.append(found)
    exe_dir = Path(getattr(sys, "_MEIPASS", Path(sys.argv[0]).resolve().parent))
    name = "adb.exe" if os.name == "nt" else "adb"
    cands += [str(exe_dir / "platform-tools" / name), str(exe_dir.parent / "platform-tools" / name)]
    if os.name == "nt":
        cands += [os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"), r"C:\platform-tools\adb.exe"]
    else:
        cands += [str(Path.home() / "Android/Sdk/platform-tools/adb")]
    return next((c for c in cands if c and os.path.isfile(c)), None)


def run_adb(adb: str, *args: str, timeout: float = 15) -> subprocess.CompletedProcess:
    return subprocess.run([adb, *args], capture_output=True, text=True, timeout=timeout, **_no_window())


def parse_devices(out: str) -> list[dict]:
    devs = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            info = dict(p.split(":", 1) for p in parts[2:] if ":" in p)
            devs.append({"serial": parts[0], "state": parts[1], "model": info.get("model", "").replace("_", " ")})
    return devs


# --------------------------------------------------------------------------- #
# Puente
# --------------------------------------------------------------------------- #

class Bridge:
    def __init__(self, get_settings: Callable[[], dict], recordings_dir: Callable[[], Path],
                 on_recording: Callable[[Path, float], None] | None = None, io_factory=None):
        self.get_settings = get_settings
        self.recordings_dir = recordings_dir
        self.on_recording = on_recording
        self.io_factory = io_factory or SoundDeviceIO
        self.io = None
        self.mic = JitterBuffer(60, 200)       # móvil -> Teams
        self.rec_mic = JitterBuffer(40, 160)   # móvil -> grabación (alineado con el reloj del PC)
        self.running = False
        self.lock = threading.RLock()
        self.sock: socket.socket | None = None
        self.server: socket.socket | None = None
        self.send_q: queue.Queue = queue.Queue(maxsize=50)
        self.recorder: Recorder | None = None
        self.state = {
            "running": False, "adb": None, "adb_error": "", "devices": [], "reverse": False,
            "phone": None, "phone_state": {}, "audio": False, "audio_error": "",
            "mic_level": 0.0, "remote_level": 0.0, "recording": False, "rec_seconds": 0.0,
            "last_recording": None, "port": 0,
        }

    # ------------------------------------------------------------ ciclo de vida
    def start(self) -> None:
        with self.lock:
            if self.running:
                return
            self.running = True
            s = self.get_settings()
            port = int(s.get("bridge_port", 28200))
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server.bind(("127.0.0.1", port))
            self.server.listen(1)
            self.server.settimeout(1.0)
            self.state.update(running=True, port=port)
            for target, name in ((self._accept_loop, "bridge-accept"), (self._adb_loop, "bridge-adb"),
                                 (self._send_loop, "bridge-send")):
                threading.Thread(target=target, daemon=True, name=name).start()

    def stop(self) -> None:
        with self.lock:
            self.running = False
            self._drop_phone()
            if self.server:
                try:
                    self.server.close()
                except OSError:
                    pass
            self.server = None
            self.state.update(running=False, reverse=False)

    # ------------------------------------------------------------------- adb
    def _adb_loop(self) -> None:
        while self.running:
            s = self.get_settings()
            adb = find_adb(s.get("adb_path", ""))
            self.state["adb"] = adb
            if not adb:
                self.state.update(adb_error="No encuentro adb (Android platform-tools). Ver Ajustes → Puente.",
                                  devices=[], reverse=False)
            else:
                try:
                    devs = parse_devices(run_adb(adb, "devices", "-l").stdout)
                    self.state["devices"] = devs
                    ready = [d for d in devs if d["state"] == "device"]
                    if not devs:
                        self.state.update(adb_error="Conecta el móvil por USB.", reverse=False)
                    elif not ready:
                        st = devs[0]["state"]
                        msg = ("Acepta «Permitir depuración USB» en el móvil." if st == "unauthorized"
                               else f"Móvil en estado «{st}».")
                        self.state.update(adb_error=msg, reverse=False)
                    else:
                        port = self.state["port"]
                        serial = ready[0]["serial"]
                        lst = run_adb(adb, "-s", serial, "reverse", "--list").stdout
                        if f"tcp:{port} tcp:{port}" not in lst:
                            r = run_adb(adb, "-s", serial, "reverse", f"tcp:{port}", f"tcp:{port}")
                            if r.returncode != 0:
                                raise RuntimeError(r.stderr.strip() or "adb reverse falló")
                        self.state.update(adb_error="", reverse=True)
                except Exception as e:  # noqa: BLE001
                    self.state.update(adb_error=f"adb: {e}", reverse=False)
            time.sleep(2)

    def install_app(self, apk: Path) -> str:
        adb = find_adb(self.get_settings().get("adb_path", ""))
        if not adb:
            raise RuntimeError("No encuentro adb.")
        r = run_adb(adb, "install", "-r", str(apk), timeout=180)
        if r.returncode != 0 and "INSTALL_FAILED_UPDATE_INCOMPATIBLE" in (r.stdout + r.stderr):
            run_adb(adb, "uninstall", APP_PACKAGE, timeout=60)   # firmada con otra clave: reinstalar
            r = run_adb(adb, "install", str(apk), timeout=180)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout).strip()[-400:])
        run_adb(adb, "shell", "am", "start", "-n", f"{APP_PACKAGE}/.MainActivity")
        return (r.stdout or "").strip()

    # ------------------------------------------------------------- conexión
    def _accept_loop(self) -> None:
        while self.running:
            try:
                conn, _ = self.server.accept()
            except (socket.timeout, OSError):
                continue
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            conn.settimeout(10)
            self._drop_phone()          # una sola conexión a la vez
            self.sock = conn
            threading.Thread(target=self._read_loop, args=(conn,), daemon=True, name="bridge-read").start()

    def _read_loop(self, conn: socket.socket) -> None:
        try:
            while self.running and self.sock is conn:
                kind, data = read_frame(conn)
                if kind == T_AUDIO:
                    x = np.frombuffer(data, dtype="<i2").astype(np.int16)
                    self.mic.write(x)
                    self.rec_mic.write(x)
                    self.state["mic_level"] = max(level(x), self.state["mic_level"] * 0.85)
                elif kind == T_CTRL:
                    self._on_control(json.loads(data.decode("utf-8")))
                elif kind == T_PING:
                    self.send_ctrl({"t": "pong"})
        except (OSError, ConnectionError, ValueError):
            pass
        finally:
            if self.sock is conn:
                self._drop_phone()

    def _on_control(self, msg: dict) -> None:
        t = msg.get("t")
        if t == "hello":
            self.state["phone"] = {"model": msg.get("model", "móvil"), "version": msg.get("v")}
            self.send_ctrl({"t": "hello", "v": PROTO_VERSION, "rate": RATE})
            self._start_audio()
            if self.get_settings().get("bridge_auto_record"):
                self.set_recording(True)
            self._send_state()
        elif t == "state":
            self.state["phone_state"] = {k: v for k, v in msg.items() if k != "t"}
        elif t == "rec":
            self.set_recording(bool(msg.get("on")))

    def _drop_phone(self) -> None:
        sock, self.sock = self.sock, None
        if sock:
            try:
                sock.close()
            except OSError:
                pass
        if self.recorder:
            self.set_recording(False)   # no perder la grabación si se desconecta el cable
        self._stop_audio()
        self.state.update(phone=None, phone_state={}, mic_level=0.0, remote_level=0.0)

    def send_ctrl(self, msg: dict) -> None:
        self._enqueue(pack(T_CTRL, json.dumps(msg).encode("utf-8")))

    def _send_state(self) -> None:
        self.send_ctrl({"t": "state", "rec": self.state["recording"], "rec_s": round(self.state["rec_seconds"]),
                        "audio": self.state["audio"], "audio_error": self.state["audio_error"]})

    def _enqueue(self, frame: bytes) -> None:
        if not self.sock:
            return
        try:
            self.send_q.put_nowait(frame)
        except queue.Full:            # el móvil no da abasto: descartar lo más viejo
            try:
                self.send_q.get_nowait()
                self.send_q.put_nowait(frame)
            except (queue.Empty, queue.Full):
                pass

    def _send_loop(self) -> None:
        last_state = 0.0
        while self.running:
            try:
                frame = self.send_q.get(timeout=0.5)
            except queue.Empty:
                frame = None
            sock = self.sock
            if sock and frame:
                try:
                    sock.sendall(frame)
                except OSError:
                    self._drop_phone()
            if sock and time.time() - last_state > 1:
                last_state = time.time()
                self._send_state()

    # ----------------------------------------------------------------- audio
    def _start_audio(self) -> None:
        s = self.get_settings()
        self._stop_audio()
        self.mic.clear()
        self.rec_mic.clear()
        try:
            self.io = self.io_factory()
            self.io.start(s.get("bridge_to_teams", "CABLE-B Input"), s.get("bridge_from_teams", "CABLE-A Output"),
                          self._out_cb, self._in_cb)
            self.state.update(audio=True, audio_error="")
        except Exception as e:  # noqa: BLE001
            self.io = None
            self.state.update(audio=False, audio_error=str(e))

    def _stop_audio(self) -> None:
        if self.io:
            self.io.stop()
        self.io = None
        self.state["audio"] = False

    def _out_cb(self, frames: int) -> np.ndarray:
        """PortAudio pide audio para el micrófono de Teams."""
        return self.mic.read(frames)

    def _in_cb(self, block: np.ndarray) -> None:
        """Llega audio de Teams (lo que dicen los demás): al móvil y a la grabación."""
        self.state["remote_level"] = max(level(block), self.state["remote_level"] * 0.85)
        for i in range(0, len(block), FRAME):
            self._enqueue(pack(T_AUDIO, block[i:i + FRAME].astype("<i2").tobytes()))
        rec = self.recorder
        if rec:
            rec.push(self.rec_mic.read(len(block)), block)
            self.state["rec_seconds"] = rec.seconds

    # ------------------------------------------------------------- grabación
    def set_recording(self, on: bool) -> None:
        with self.lock:
            if on and not self.recorder:
                if not self.state["audio"]:
                    self.state["audio_error"] = self.state["audio_error"] or "No hay audio activo"
                    return
                d = self.recordings_dir()
                d.mkdir(parents=True, exist_ok=True)
                path = d / time.strftime("llamada-%Y%m%d-%H%M%S.flac")
                self.rec_mic.clear()
                self.recorder = Recorder(path)
                self.state.update(recording=True, rec_seconds=0.0)
            elif not on and self.recorder:
                rec, self.recorder = self.recorder, None
                rec.close()
                self.state.update(recording=False, last_recording=str(rec.path))
                if rec.seconds < 2:
                    rec.path.unlink(missing_ok=True)
                elif self.on_recording:
                    self.on_recording(rec.path, rec.started)
            self._send_state()

    def status(self) -> dict:
        st = dict(self.state)
        st["mic_level"] = round(st["mic_level"], 3)
        st["remote_level"] = round(st["remote_level"], 3)
        st["buffer_ms"] = round(len(self.mic) * 1000 / RATE)
        return st


def recording_name(started: float) -> str:
    return "Llamada " + time.strftime("%Y-%m-%d %H:%M", time.localtime(started))



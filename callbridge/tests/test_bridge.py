"""Puente de audio con un móvil simulado (TCP) y un audio de PC simulado (sin tarjeta de sonido)."""
import json
import socket
import threading
import time

import numpy as np
import pytest

from callbridge import bridge as B

PHONE_HZ, TEAMS_HZ = 440.0, 1000.0


def tone(hz, start, n, amp=8000):
    t = (np.arange(n) + start) / B.RATE
    return (amp * np.sin(2 * np.pi * hz * t)).astype(np.int16)


def peak_hz(x):
    spec = np.abs(np.fft.rfft(x.astype(float)))
    return np.fft.rfftfreq(len(x), 1 / B.RATE)[spec.argmax()]


class FakeIO:
    """Simula PortAudio: cada 10 ms pide audio para Teams y entrega audio de Teams."""
    instances = []

    def __init__(self):
        self.out = []
        self.run = False
        FakeIO.instances.append(self)

    def start(self, out_name, in_name, out_cb, in_cb):
        self.names = (out_name, in_name)
        self.run = True

        def loop():
            k = 0
            nxt = time.perf_counter()
            while self.run:
                self.out.append(out_cb(B.FRAME))
                in_cb(tone(TEAMS_HZ, k * B.FRAME, B.FRAME))
                k += 1
                nxt += B.FRAME / B.RATE
                time.sleep(max(0, nxt - time.perf_counter()))
        threading.Thread(target=loop, daemon=True).start()

    def stop(self):
        self.run = False


class FakePhone:
    def __init__(self, port):
        self.sock = socket.create_connection(("127.0.0.1", port))
        self.received = []
        self.ctrl = []
        self.alive = True
        threading.Thread(target=self._read, daemon=True).start()
        self.send_ctrl({"t": "hello", "v": 1, "model": "Fold de prueba"})
        threading.Thread(target=self._mic, daemon=True).start()

    def send_ctrl(self, msg):
        self.sock.sendall(B.pack(B.T_CTRL, json.dumps(msg).encode()))

    def _mic(self):
        k = 0
        nxt = time.perf_counter()
        while self.alive:
            try:
                self.sock.sendall(B.pack(B.T_AUDIO, tone(PHONE_HZ, k * B.FRAME, B.FRAME).astype("<i2").tobytes()))
            except OSError:
                return
            k += 1
            nxt += 0.01
            time.sleep(max(0, nxt - time.perf_counter()))

    def _read(self):
        try:
            while self.alive:
                kind, data = B.read_frame(self.sock)
                if kind == B.T_AUDIO:
                    self.received.append(np.frombuffer(data, "<i2"))
                elif kind == B.T_CTRL:
                    self.ctrl.append(json.loads(data))
        except (OSError, ConnectionError):
            pass

    def close(self):
        self.alive = False
        self.sock.close()


def wait_for(cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_jitter_buffer_prime_underrun_and_drift():
    jb = B.JitterBuffer(target_ms=20, max_ms=50)
    assert not jb.read(480).any()                        # sin cebar: silencio
    jb.write(np.ones(960, np.int16))
    assert jb.read(480).all()                            # cebado: sale audio
    jb.write(np.ones(48000, np.int16))                   # demasiado retardo acumulado
    assert len(jb) <= jb.target and jb.drops == 1
    jb.read(len(jb))
    jb.read(480)
    assert jb.underruns == 1


def test_frames_roundtrip():
    a, b = socket.socketpair()
    a.sendall(B.pack(B.T_CTRL, b'{"t":"x"}') + B.pack(B.T_AUDIO, b"\x01\x00" * 480))
    assert B.read_frame(b) == (B.T_CTRL, b'{"t":"x"}')
    kind, data = B.read_frame(b)
    assert kind == B.T_AUDIO and len(data) == 960


def test_parse_adb_devices():
    out = ("List of devices attached\n"
           "R5CW123 device usb:1-1 product:q5q model:SM_F946B device:q5q transport_id:1\n"
           "ABC unauthorized usb:1-2 transport_id:2\n")
    d = B.parse_devices(out)
    assert d[0] == {"serial": "R5CW123", "state": "device", "model": "SM F946B"}
    assert d[1]["state"] == "unauthorized"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("CALLBRIDGE_HOME", str(tmp_path))
    monkeypatch.setattr(B, "find_adb", lambda *a: None)  # sin adb en el entorno de pruebas
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    from callbridge import config
    from callbridge.server import create_app
    config.save_settings({"bridge_port": port, "bridge_auto_process": False})
    FakeIO.instances.clear()
    a = create_app(bridge_io_factory=FakeIO)
    a.config["port"] = port
    yield a
    a.config["bridge"].stop()


def test_bridge_full_call_and_recording(app):
    c = app.test_client()
    assert c.post("/api/bridge/start").json["running"]
    assert wait_for(lambda: "adb" in c.get("/api/bridge").json["adb_error"])
    assert c.get("/api/bridge").json["adb"] is None

    phone = FakePhone(app.config["port"])
    assert wait_for(lambda: c.get("/api/bridge").json["audio"])
    st = c.get("/api/bridge").json
    assert st["phone"]["model"] == "Fold de prueba"
    assert FakeIO.instances[-1].names == ("CABLE-B Input", "CABLE-A Output")

    # Audio en ambos sentidos
    assert wait_for(lambda: len(phone.received) > 50)
    assert abs(peak_hz(np.concatenate(phone.received[-40:])) - TEAMS_HZ) < 30   # el móvil oye a Teams
    io = FakeIO.instances[-1]
    assert wait_for(lambda: len(io.out) > 50 and np.concatenate(io.out[-20:]).any())
    assert abs(peak_hz(np.concatenate(io.out[-40:])) - PHONE_HZ) < 30            # Teams oye el micro del móvil

    # Grabar desde el móvil
    phone.send_ctrl({"t": "rec", "on": True})
    assert wait_for(lambda: c.get("/api/bridge").json["recording"])
    time.sleep(3)
    assert wait_for(lambda: any(m.get("t") == "state" and m.get("rec") for m in phone.ctrl))
    phone.send_ctrl({"t": "rec", "on": False})
    assert wait_for(lambda: not c.get("/api/bridge").json["recording"])

    # Se crea la llamada automáticamente
    assert wait_for(lambda: len(c.get("/api/projects").json) == 1)
    proj = c.get("/api/projects").json[0]
    assert proj["name"].startswith("Llamada ")
    from callbridge import config
    import soundfile as sf
    audio_path = config.projects_dir() / proj["id"] / "audio.flac"
    data, sr = sf.read(str(audio_path), dtype="int16")
    assert sr == B.RATE and data.shape[1] == 2 and 2.5 < len(data) / sr < 4
    tail = data[-B.RATE:]
    assert abs(peak_hz(tail[:, 0]) - PHONE_HZ) < 30       # izquierda = Yo (móvil)
    assert abs(peak_hz(tail[:, 1]) - TEAMS_HZ) < 30       # derecha = remoto (Teams)
    assert wait_for(lambda: c.get(f"/api/projects/{proj['id']}").json["duration"] > 2.5)

    # Si se desconecta el cable grabando, la grabación se guarda
    c.post("/api/bridge/record", json={"on": True})
    time.sleep(2.5)
    phone.close()
    assert wait_for(lambda: len(c.get("/api/projects").json) == 2)
    assert wait_for(lambda: not c.get("/api/bridge").json["audio"])

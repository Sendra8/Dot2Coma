"""Prueba de extremo a extremo de la API + pipeline.

Usa la diarización real (sherpa-onnx, descarga ~30 MB de GitHub la primera vez) y un
Whisper falso para no depender de Hugging Face. Se salta si no hay audio de prueba:
    CALLBRIDGE_TEST_WAV=/ruta/a/0-four-speakers-zh.wav pytest tests/test_e2e.py
"""
import io
import os
import subprocess
import time
from types import SimpleNamespace

import pytest

WAV = os.environ.get("CALLBRIDGE_TEST_WAV")
pytestmark = pytest.mark.skipif(not WAV or not os.path.exists(WAV), reason="sin CALLBRIDGE_TEST_WAV")


class FakeWhisper:
    """Devuelve un segmento cada 3 s con palabras de 0,5 s donde hay energía."""

    def transcribe(self, audio, **kw):
        import numpy as np
        sr = 16000
        dur = len(audio) / sr
        segs = []
        t = 0.0
        while t + 3 <= dur:
            words = []
            for k in range(6):
                a, b = t + k * 0.5, t + (k + 1) * 0.5
                if np.abs(audio[int(a * sr):int(b * sr)]).max(initial=0) > 0.02:
                    words.append(SimpleNamespace(start=a, end=b, word=f" w{int(a * 10)}"))
            if words:
                segs.append(SimpleNamespace(start=words[0].start, end=words[-1].end,
                                            text="".join(x.word for x in words), words=words))
            t += 3
        return iter(segs), SimpleNamespace(language="es")


def make_stereo(src, dst):
    # L ("Yo") = primeros 8 s del audio y luego silencio; R ("Remoto") = audio completo
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", src, "-filter_complex",
                    "[0:a]asplit=2[a][b];[a]volume='if(lt(t,8),1,0)':eval=frame[l];"
                    "[l][b]join=inputs=2:channel_layout=stereo[out]", "-map", "[out]", dst], check=True)


def test_full_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("CALLBRIDGE_HOME", str(tmp_path / "home"))
    models = os.environ.get("CALLBRIDGE_TEST_MODELS")
    from callbridge import config, pipeline
    from callbridge.server import create_app
    if models:
        config.save_settings({"models_dir": models})
    monkeypatch.setattr(pipeline, "get_whisper", lambda s, m: FakeWhisper())

    stereo = tmp_path / "llamada.wav"
    make_stereo(WAV, stereo)
    app = create_app()
    c = app.test_client()

    with open(stereo, "rb") as f:
        r = c.post("/api/projects", data={"audio": (io.BytesIO(f.read()), "llamada.wav")},
                   content_type="multipart/form-data")
    assert r.status_code == 201, r.json
    pid = r.json["id"]

    def wait():
        for _ in range(600):
            jobs = c.get(f"/api/projects/{pid}/jobs").json
            if jobs and all(j["state"] not in ("en cola", "en curso") for j in jobs):
                return jobs
            time.sleep(0.2)
        raise AssertionError("timeout")

    jobs = wait()
    assert jobs[-1]["state"] == "hecho", jobs
    p = c.get(f"/api/projects/{pid}").json
    assert p["channels"] == 2 and 50 < p["duration"] < 60
    peaks = c.get(f"/api/projects/{pid}/peaks").json
    assert len(peaks["channels"]) == 2 and len(peaks["channels"][0]) > 2500

    r = c.post(f"/api/projects/{pid}/process", json={"num_speakers": 0})
    assert r.status_code == 200
    jobs = wait()
    assert jobs[-1]["state"] == "hecho", jobs
    p = c.get(f"/api/projects/{pid}").json
    ids = [s["id"] for s in p["speakers"]]
    assert ids[0] == "yo" and len(ids) == 5, ids         # Yo + los 4 hablantes del audio de prueba
    yo = [s for s in p["segments"] if s["speaker"] == "yo"]
    assert yo and all(s["end"] <= 8.5 for s in yo)       # el canal L solo tiene voz en 0-8 s
    remote = {s["speaker"] for s in p["segments"]} - {"yo"}
    assert len(remote) >= 2
    print("hablantes:", ids, "segmentos:", len(p["segments"]))

    # Edición + exportación
    p["speakers"][1]["label"] = "Marta"
    assert c.put(f"/api/projects/{pid}", json=p).json["ok"]
    md = c.post(f"/api/projects/{pid}/export/md").json
    assert "Marta" in md["text"] and os.path.exists(md["path"])
    assert c.get(f"/api/projects/{pid}/audio", headers={"Range": "bytes=0-99"}).status_code == 206
    # Resumen sin modelo configurado => error claro
    c.post(f"/api/projects/{pid}/summary")
    jobs = wait()
    assert jobs[-1]["state"] == "error" and "gguf" in jobs[-1]["error"]

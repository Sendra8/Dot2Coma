"""Servidor local (127.0.0.1) que sirve la interfaz web y la API."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file, send_from_directory

from . import config
from .jobs import JobRunner
from .project import (EXPORTERS, PEAKS_FILE, PROJECT_FILE, empty_project, load_project, new_project_id,
                      save_project)

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".webm", ".mp4", ".mkv", ".wma"}


def _web_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    p = base / "callbridge" / "web"
    return p if p.exists() else Path(__file__).resolve().parent / "web"


def open_path(path: Path) -> None:
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def create_app(file_picker=None) -> Flask:
    """file_picker: callable(kind) -> ruta | None (lo aporta la ventana de escritorio)."""
    app = Flask(__name__, static_folder=None)
    runner = JobRunner()
    app.config["runner"] = runner

    def pdir(pid: str) -> Path:
        if not pid or "/" in pid or "\\" in pid or pid.startswith("."):
            abort(400)
        d = config.projects_dir() / pid
        if not (d / PROJECT_FILE).exists():
            abort(404)
        return d

    # ------------------------------------------------------------------ UI
    @app.get("/")
    def index():
        return send_from_directory(_web_dir(), "index.html")

    @app.get("/web/<path:name>")
    def web(name):
        return send_from_directory(_web_dir(), name)

    # ------------------------------------------------------------ ajustes
    @app.get("/api/settings")
    def get_settings():
        s = config.load_settings()
        s["_projects_dir"] = str(config.projects_dir(s))
        s["_models_dir"] = str(config.models_dir(s))
        s["_has_picker"] = file_picker is not None
        return jsonify(s)

    @app.put("/api/settings")
    def put_settings():
        try:
            return jsonify(config.save_settings(request.get_json(force=True) or {}))
        except (TypeError, ValueError) as e:
            return jsonify({"error": f"Valor no válido: {e}"}), 400

    @app.post("/api/pick")
    def pick():
        if not file_picker:
            return jsonify({"error": "Selector no disponible en modo navegador"}), 501
        kind = (request.get_json(silent=True) or {}).get("kind", "gguf")
        return jsonify({"path": file_picker(kind)})

    # ----------------------------------------------------------- proyectos
    @app.get("/api/projects")
    def list_projects():
        out = []
        for d in config.projects_dir().iterdir():
            if (d / PROJECT_FILE).exists():
                try:
                    p = load_project(d)
                except (OSError, ValueError):
                    continue
                out.append({k: p.get(k) for k in ("id", "name", "created", "duration", "processed")}
                           | {"busy": bool(runner.active_for(p["id"]))})
        out.sort(key=lambda p: p.get("created") or "", reverse=True)
        return jsonify(out)

    @app.post("/api/projects")
    def create_project():
        f = request.files.get("audio")
        src_path = request.form.get("path") or (request.get_json(silent=True) or {}).get("path")
        if f is None and not src_path:
            return jsonify({"error": "Falta el audio"}), 400
        filename = f.filename if f is not None else os.path.basename(src_path)
        ext = Path(filename).suffix.lower()
        if ext not in AUDIO_EXTS:
            return jsonify({"error": f"Formato no soportado: {ext}"}), 400
        name = request.form.get("name") or Path(filename).stem
        pid = new_project_id(name)
        d = config.projects_dir() / pid
        d.mkdir(parents=True)
        audio_name = "audio" + ext
        if f is not None:
            f.save(d / audio_name)
        else:
            shutil.copyfile(src_path, d / audio_name)
        project = empty_project(pid, name, audio_name)
        save_project(d, project)
        _submit_analyze(pid)
        return jsonify(project), 201

    def _submit_analyze(pid: str):
        def run(job):
            from . import pipeline
            d = config.projects_dir() / pid
            p = load_project(d)
            job.report("Analizando audio", 0.1)
            channels, _ = pipeline.probe(d / p["audio"])
            chans = pipeline.load_channels(d / p["audio"], channels >= 2)
            job.report("Calculando forma de onda", 0.6)
            peaks = pipeline.compute_peaks(chans)
            (d / PEAKS_FILE).write_text(json.dumps(peaks), encoding="utf-8")
            p = load_project(d)
            p["channels"] = channels
            p["duration"] = round(len(chans[0]) / pipeline.SR, 3)
            save_project(d, p)
        return runner.submit("analizar", pid, run)

    @app.get("/api/projects/<pid>")
    def get_project(pid):
        return jsonify(load_project(pdir(pid)))

    @app.put("/api/projects/<pid>")
    def put_project(pid):
        d = pdir(pid)
        current = load_project(d)
        data = request.get_json(force=True) or {}
        if not isinstance(data.get("segments", []), list) or not isinstance(data.get("speakers", []), list):
            return jsonify({"error": "Formato no válido"}), 400
        for k in ("name", "speakers", "segments", "summary"):
            if k in data:
                current[k] = data[k]
        save_project(d, current)
        return jsonify({"ok": True})

    @app.delete("/api/projects/<pid>")
    def delete_project(pid):
        d = pdir(pid)
        for j in runner.active_for(pid):
            j.cancel.set()
        shutil.rmtree(d, ignore_errors=True)
        return jsonify({"ok": True})

    @app.get("/api/projects/<pid>/audio")
    def audio(pid):
        d = pdir(pid)
        return send_file(d / load_project(d)["audio"], conditional=True)

    @app.get("/api/projects/<pid>/peaks")
    def peaks(pid):
        f = pdir(pid) / PEAKS_FILE
        if not f.exists():
            return jsonify({"pps": 50, "channels": []})
        return send_file(f, mimetype="application/json")

    @app.post("/api/projects/<pid>/process")
    def process(pid):
        pdir(pid)
        opts = request.get_json(silent=True) or {}
        num = int(opts.get("num_speakers") or 0)
        mix = bool(opts.get("mix_channels"))

        def run(job):
            from . import pipeline
            d = config.projects_dir() / pid
            s = config.load_settings()
            p = load_project(d)
            p, pk = pipeline.process(d / p["audio"], p, s, config.models_dir(s), job.report, job.cancel,
                                     num_speakers=num, mix_channels=mix)
            (d / PEAKS_FILE).write_text(json.dumps(pk), encoding="utf-8")
            fresh = load_project(d)  # conserva nombre/resumen editados mientras procesaba
            p["name"], p["summary"] = fresh.get("name", p["name"]), fresh.get("summary", "")
            save_project(d, p)

        return jsonify(runner.submit("procesar", pid, run).to_dict())

    @app.post("/api/projects/<pid>/summary")
    def summary(pid):
        pdir(pid)

        def run(job):
            from .summarize import summarize
            d = config.projects_dir() / pid
            text = summarize(load_project(d), config.load_settings(), job.report, job.cancel)
            p = load_project(d)
            p["summary"] = text
            save_project(d, p)

        return jsonify(runner.submit("resumen", pid, run).to_dict())

    @app.get("/api/projects/<pid>/jobs")
    def project_jobs(pid):
        jobs = [j.to_dict() for j in runner.jobs.values() if j.project_id == pid]
        return jsonify(jobs[-5:])

    @app.post("/api/jobs/<jid>/cancel")
    def cancel_job(jid):
        j = runner.jobs.get(jid) or abort(404)
        j.cancel.set()
        return jsonify(j.to_dict())

    @app.post("/api/projects/<pid>/export/<fmt>")
    def export(pid, fmt):
        d = pdir(pid)
        if fmt not in EXPORTERS:
            abort(404)
        fn, _, suffix = EXPORTERS[fmt]
        p = load_project(d)
        out_dir = d / "exportado"
        out_dir.mkdir(exist_ok=True)
        safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in p.get("name", "llamada")).strip() or "llamada"
        target = out_dir / f"{safe}{suffix}"
        text = fn(p)
        target.write_text(text, encoding="utf-8")
        return jsonify({"path": str(target), "text": text})

    @app.post("/api/projects/<pid>/open")
    def open_folder(pid):
        d = pdir(pid)
        sub = (request.get_json(silent=True) or {}).get("sub")
        target = d / "exportado" if sub == "exportado" and (d / "exportado").exists() else d
        open_path(target)
        return jsonify({"ok": True})

    return app

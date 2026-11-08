"""Ajustes de la aplicación (JSON en la carpeta de datos del usuario)."""
from __future__ import annotations

import json
import os
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("CALLBRIDGE_HOME")
    if override:
        base = Path(override)
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home())) / "CallBridge"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "callbridge"
    base.mkdir(parents=True, exist_ok=True)
    return base


DEFAULT_SUMMARY_PROMPT = (
    "Eres un asistente que redacta actas de reuniones. A partir de la transcripción "
    "(puede mezclar español e inglés), escribe en español un resumen en Markdown con estas secciones:\n"
    "### Resumen\n(5-10 frases)\n### Decisiones\n(lista)\n### Tareas\n(lista: responsable – tarea – fecha si se menciona)\n"
    "### Temas abiertos\n(lista)\n"
    "Usa los nombres de los hablantes tal como aparecen. No inventes información."
)

DEFAULTS: dict = {
    "allow_downloads": True,            # False => «Solo local»: nunca se conecta a Internet
    "projects_dir": "",                 # vacío => <data_dir>/proyectos
    "models_dir": "",                   # vacío => <data_dir>/modelos
    # Transcripción (faster-whisper)
    "whisper_model": "large-v3-turbo",  # tiny/base/small/medium/large-v3/large-v3-turbo o ruta local
    "whisper_compute_type": "int8",
    "language": "auto",                 # auto | es | en
    "initial_prompt": "Reunión de trabajo en español con partes en inglés.",
    "cpu_threads": 0,                   # 0 => automático
    # Diarización (sherpa-onnx)
    "diar_embedding": "nemo_en_titanet_small.onnx",
    "diar_threshold": 0.85,             # menor => más hablantes (calibrado para TitaNet)
    "echo_ratio_db": -15.0,             # marca 'Yo' como posible eco si su canal es X dB más bajo que el remoto
    # Resumen (llama.cpp / GGUF)
    "gguf_path": "",
    "llm_ctx": 8192,
    "llm_threads": 0,
    "summary_prompt": DEFAULT_SUMMARY_PROMPT,
    # Puente de audio con el móvil
    "bridge_autostart": True,
    "bridge_port": 28200,
    "bridge_to_teams": "CABLE-B Input",     # aquí suena el micro del móvil (en Teams: micrófono «CABLE-B Output»)
    "bridge_from_teams": "CABLE-A Output",  # de aquí sale lo que dicen los demás (en Teams: altavoz «CABLE-A Input»)
    "adb_path": "",
    "bridge_auto_record": False,
    "bridge_auto_process": True,
}


def settings_path() -> Path:
    return data_dir() / "settings.json"


def load_settings() -> dict:
    s = dict(DEFAULTS)
    p = settings_path()
    if p.exists():
        try:
            s.update(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    return s


def save_settings(new: dict) -> dict:
    s = load_settings()
    for k, v in new.items():
        if k not in DEFAULTS:
            continue
        if isinstance(DEFAULTS[k], bool):
            s[k] = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "on", "sí", "si")
        else:
            s[k] = type(DEFAULTS[k])(v)
    settings_path().write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    return s


def projects_dir(s: dict | None = None) -> Path:
    s = s or load_settings()
    p = Path(s["projects_dir"]) if s.get("projects_dir") else data_dir() / "proyectos"
    p.mkdir(parents=True, exist_ok=True)
    return p


def models_dir(s: dict | None = None) -> Path:
    s = s or load_settings()
    p = Path(s["models_dir"]) if s.get("models_dir") else data_dir() / "modelos"
    p.mkdir(parents=True, exist_ok=True)
    return p

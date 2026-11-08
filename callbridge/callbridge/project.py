"""Modelo de datos de un proyecto (una llamada grabada) y exportaciones.

Un proyecto vive en su propia carpeta:
    <proyectos>/<id>/audio.<ext>      audio original (estéreo: L = Yo, R = Remoto)
    <proyectos>/<id>/project.json     transcripción, hablantes, resumen
    <proyectos>/<id>/peaks.json       forma de onda precalculada para la interfaz
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path

PROJECT_FILE = "project.json"
PEAKS_FILE = "peaks.json"
SCHEMA_VERSION = 1

# Paleta de colores para pistas de hablantes (legible en claro y oscuro).
PALETTE = [
    "#2f7ed8", "#e4572e", "#29a36a", "#a05cd6", "#d99a00",
    "#1aa3a3", "#d6457a", "#6b8e23", "#8c6d46", "#5a6acf",
]
ME_ID = "yo"


def speaker_color(index: int) -> str:
    return PALETTE[index % len(PALETTE)]


def new_project_id(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-")[:40] or "llamada"
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{slug}-{uuid.uuid4().hex[:4]}"


def empty_project(pid: str, name: str, audio_file: str) -> dict:
    return {
        "version": SCHEMA_VERSION,
        "id": pid,
        "name": name,
        "audio": audio_file,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "duration": 0.0,
        "channels": 0,
        "speakers": [],
        "segments": [],
        "summary": "",
        "processed": False,
    }


def load_project(folder: Path) -> dict:
    with open(folder / PROJECT_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_project(folder: Path, project: dict) -> None:
    tmp = folder / (PROJECT_FILE + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(project, f, ensure_ascii=False, indent=1)
    os.replace(tmp, folder / PROJECT_FILE)


# --------------------------------------------------------------------------- #
# Utilidades de texto / tiempo
# --------------------------------------------------------------------------- #

def fmt_clock(t: float) -> str:
    t = max(0, int(round(t)))
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def fmt_srt(t: float) -> str:
    ms = max(0, int(round(t * 1000)))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def speaker_labels(project: dict) -> dict[str, str]:
    return {s["id"]: (s.get("label") or s["id"]) for s in project.get("speakers", [])}


def ordered_segments(project: dict) -> list[dict]:
    return sorted(project.get("segments", []), key=lambda s: (s["start"], s["end"]))


def transcript_lines(project: dict, with_time: bool = True) -> list[str]:
    """Líneas tipo "[mm:ss] Nombre: texto", agrupando turnos consecutivos."""
    labels = speaker_labels(project)
    lines: list[str] = []
    last_spk = None
    for seg in ordered_segments(project):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        name = labels.get(seg["speaker"], seg["speaker"])
        if seg["speaker"] == last_spk and lines:
            lines[-1] += " " + text
        else:
            prefix = f"[{fmt_clock(seg['start'])}] " if with_time else ""
            lines.append(f"{prefix}{name}: {text}")
        last_spk = seg["speaker"]
    return lines


# --------------------------------------------------------------------------- #
# Exportaciones
# --------------------------------------------------------------------------- #

def export_txt(project: dict) -> str:
    return "\n\n".join(transcript_lines(project)) + "\n"


def export_md(project: dict, include_summary: bool = True, include_transcript: bool = True) -> str:
    out = [f"# {project.get('name', 'Llamada')}", ""]
    meta = f"*{project.get('created', '')} · duración {fmt_clock(project.get('duration', 0))}*"
    labels = [s.get("label") or s["id"] for s in project.get("speakers", [])]
    if labels:
        meta += f"  \n*Participantes: {', '.join(labels)}*"
    out += [meta, ""]
    if include_summary and project.get("summary", "").strip():
        out += ["## Resumen", "", project["summary"].strip(), ""]
    if include_transcript:
        out += ["## Transcripción", ""]
        for line in transcript_lines(project):
            m = re.match(r"^(\[[^\]]+\]) ([^:]+): (.*)$", line, re.S)
            out.append(f"**{m.group(1)} {m.group(2)}:** {m.group(3)}" if m else line)
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def export_srt(project: dict) -> str:
    labels = speaker_labels(project)
    blocks = []
    i = 0
    for seg in ordered_segments(project):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        i += 1
        name = labels.get(seg["speaker"], seg["speaker"])
        blocks.append(f"{i}\n{fmt_srt(seg['start'])} --> {fmt_srt(seg['end'])}\n{name}: {text}\n")
    return "\n".join(blocks)


EXPORTERS = {
    "md": (export_md, "text/markdown"),
    "txt": (export_txt, "text/plain"),
    "srt": (export_srt, "application/x-subrip"),
}

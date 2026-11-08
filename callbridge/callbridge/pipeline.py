"""Procesado de una grabación: decodificar → transcribir → diarizar → combinar.

Convención de canales en grabaciones estéreo del puente de audio:
    canal izquierdo  (L) = micrófono del móvil  => hablante fijo "Yo"
    canal derecho    (R) = audio que llega de Teams => se diariza en N1, N2, ...
Un audio mono (o estéreo con la opción "mezclar") se diariza entero.
"""
from __future__ import annotations

import math
import tarfile
import threading
import urllib.request
from pathlib import Path
from typing import Callable

import numpy as np

from . import align
from .project import ME_ID, speaker_color

SR = 16000
PEAKS_PER_SEC = 50

SEGMENTATION_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
                    "speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2")
EMBEDDING_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/{name}"

Progress = Callable[[str, float], None]


class Cancelled(Exception):
    pass


# --------------------------------------------------------------------------- #
# Audio
# --------------------------------------------------------------------------- #

def probe(path: Path) -> tuple[int, float]:
    """(canales, duración en segundos)."""
    import av
    with av.open(str(path)) as c:
        st = c.streams.audio[0]
        channels = st.codec_context.channels
        if st.duration is not None and st.time_base is not None:
            dur = float(st.duration * st.time_base)
        elif c.duration is not None:
            dur = c.duration / 1_000_000
        else:
            dur = 0.0
    return channels, dur


def load_channels(path: Path, stereo: bool) -> list[np.ndarray]:
    """Decodifica a float32 16 kHz: [L, R] si stereo, si no [mono]."""
    import av
    layout = "stereo" if stereo else "mono"
    resampler = av.AudioResampler(format="flt", layout=layout, rate=SR)  # 'flt' = intercalado
    chunks: list[np.ndarray] = []
    with av.open(str(path)) as container:
        for frame in container.decode(audio=0):
            frame.pts = None
            for f in resampler.resample(frame):
                chunks.append(f.to_ndarray().reshape(-1))
        for f in resampler.resample(None):
            chunks.append(f.to_ndarray().reshape(-1))
    data = np.concatenate(chunks).astype(np.float32) if chunks else np.zeros(0, np.float32)
    if stereo:
        return [np.ascontiguousarray(data[0::2]), np.ascontiguousarray(data[1::2])]
    return [data]


def compute_peaks(channels: list[np.ndarray], pps: int = PEAKS_PER_SEC) -> dict:
    hop = SR // pps
    out = []
    for ch in channels:
        n = math.ceil(len(ch) / hop)
        padded = np.zeros(n * hop, dtype=np.float32)
        padded[: len(ch)] = np.abs(ch)
        peaks = padded.reshape(n, hop).max(axis=1)
        out.append(np.clip(np.round(peaks * 100), 0, 100).astype(int).tolist())
    return {"pps": pps, "channels": out}


def _rms(x: np.ndarray, t0: float, t1: float) -> float:
    seg = x[int(t0 * SR): int(t1 * SR)]
    return float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0


# --------------------------------------------------------------------------- #
# Modelos
# --------------------------------------------------------------------------- #

def _download(url: str, dest: Path, progress: Progress | None, label: str) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while chunk := r.read(1 << 16):
            f.write(chunk)
            done += len(chunk)
            if progress and total:
                progress(f"Descargando {label}", done / total)
    tmp.replace(dest)


class ModelMissing(RuntimeError):
    pass


def _need_download(allow: bool, what: str, where: Path) -> None:
    if not allow:
        raise ModelMissing(
            f"Falta el modelo {what} en {where}. Está activado «Solo local»: prepara los modelos con "
            f"preparar_modelos.py en otro equipo y copia la carpeta, o permite descargas en Ajustes.")


def ensure_diar_models(models_dir: Path, embedding_name: str, progress: Progress | None = None,
                       allow_download: bool = True) -> tuple[Path, Path]:
    d = models_dir / "diarizacion"
    d.mkdir(parents=True, exist_ok=True)
    seg = d / "pyannote-segmentation-3-0.onnx"
    if not seg.exists():
        _need_download(allow_download, "de segmentación", seg)
        tar_path = d / "segmentation.tar.bz2"
        _download(SEGMENTATION_URL, tar_path, progress, "modelo de segmentación")
        with tarfile.open(tar_path) as tar:
            member = next(m for m in tar.getmembers() if m.name.endswith("/model.onnx"))
            with tar.extractfile(member) as src, open(seg, "wb") as dst:
                dst.write(src.read())
        tar_path.unlink()
    emb = Path(embedding_name)
    if not emb.is_absolute():
        emb = d / embedding_name
        if not emb.exists():
            _need_download(allow_download, "de voz", emb)
            _download(EMBEDDING_URL.format(name=embedding_name), emb, progress, "modelo de voz")
    return seg, emb


_whisper_cache: dict = {}
_whisper_lock = threading.Lock()


def ensure_whisper(name: str, models_dir: Path, allow_download: bool = True) -> str:
    """Ruta local del modelo Whisper. Solo descarga (de Hugging Face) si falta y está permitido.

    Una vez descargado se carga siempre desde la carpeta, sin conectarse a ningún sitio.
    """
    if Path(name).is_dir():
        return name
    d = models_dir / "whisper" / name
    if not (d / "model.bin").exists():
        _need_download(allow_download, f"Whisper «{name}»", d)
        from faster_whisper import download_model
        d.mkdir(parents=True, exist_ok=True)
        download_model(name, output_dir=str(d))
    return str(d)


def get_whisper(settings: dict, models_dir: Path):
    from faster_whisper import WhisperModel
    key = (settings["whisper_model"], settings["whisper_compute_type"], int(settings["cpu_threads"]))
    with _whisper_lock:
        if key not in _whisper_cache:
            _whisper_cache.clear()  # solo un modelo en memoria
            path = ensure_whisper(settings["whisper_model"], models_dir, bool(settings.get("allow_downloads", True)))
            _whisper_cache[key] = WhisperModel(
                path, device="cpu", local_files_only=True,
                compute_type=settings["whisper_compute_type"],
                cpu_threads=int(settings["cpu_threads"]),
            )
        return _whisper_cache[key]


# --------------------------------------------------------------------------- #
# Etapas
# --------------------------------------------------------------------------- #

def transcribe(model, audio: np.ndarray, settings: dict, progress: Progress, label: str,
               cancel: threading.Event) -> list[dict]:
    lang = None if settings.get("language", "auto") == "auto" else settings["language"]
    duration = len(audio) / SR or 1
    segments, info = model.transcribe(
        audio,
        language=lang,
        multilingual=lang is None,          # detecta idioma por segmento (ES/EN mezclados)
        initial_prompt=settings.get("initial_prompt") or None,
        vad_filter=True,
        word_timestamps=True,
        condition_on_previous_text=False,   # evita bucles/alucinaciones en llamadas largas
        beam_size=5,
    )
    out = []
    for s in segments:
        if cancel.is_set():
            raise Cancelled()
        out.append({
            "start": s.start, "end": s.end, "text": s.text,
            "lang": getattr(s, "language", None) or info.language,
            "words": [{"start": w.start, "end": w.end, "word": w.word} for w in (s.words or [])],
        })
        progress(label, min(1.0, s.end / duration))
    return out


def diarize(audio: np.ndarray, seg_model: Path, emb_model: Path, num_speakers: int, threshold: float,
            threads: int, progress: Progress, cancel: threading.Event) -> list[tuple[float, float, int]]:
    import sherpa_onnx
    threads = threads or max(1, (__import__("os").cpu_count() or 4) // 2)
    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(seg_model)),
            num_threads=threads,
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(emb_model), num_threads=threads),
        clustering=sherpa_onnx.FastClusteringConfig(
            num_clusters=num_speakers if num_speakers > 0 else -1, threshold=threshold),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    if not config.validate():
        raise RuntimeError("Configuración de diarización no válida (¿modelos corruptos?)")
    sd = sherpa_onnx.OfflineSpeakerDiarization(config)

    def cb(done: int, total: int) -> int:
        progress("Diarizando hablantes", done / max(1, total))
        return 1 if cancel.is_set() else 0

    result = sd.process(audio, callback=cb).sort_by_start_time()
    if cancel.is_set():
        raise Cancelled()
    return [(r.start, r.end, r.speaker) for r in result]


def process(audio_path: Path, project: dict, settings: dict, models_dir: Path,
            progress: Progress, cancel: threading.Event,
            num_speakers: int = 0, mix_channels: bool = False) -> tuple[dict, dict]:
    """Procesa la grabación y devuelve (proyecto actualizado, peaks)."""
    progress("Leyendo audio", 0)
    channels, duration = probe(audio_path)
    stereo = channels >= 2 and not mix_channels
    chans = load_channels(audio_path, stereo)
    duration = len(chans[0]) / SR or duration
    peaks = compute_peaks(load_channels(audio_path, True) if channels >= 2 and not stereo else chans)

    # Pesos de cada etapa para la barra de progreso global
    stages = (["asr_me", "asr_remote", "diar"] if stereo else ["asr_remote", "diar"])
    weights = {"asr_me": 0.4, "asr_remote": 0.4, "diar": 0.2} if stereo else {"asr_remote": 0.75, "diar": 0.25}
    offset = {}
    acc = 0.05
    for st in stages:
        offset[st] = acc
        acc += weights[st] * 0.95

    def stage_cb(stage: str):
        return lambda label, frac: progress(label, offset[stage] + weights[stage] * 0.95 * frac)

    progress("Preparando modelos (la primera vez se descargan)", 0.02)
    seg_model, emb_model = ensure_diar_models(models_dir, settings["diar_embedding"],
                                              lambda l, f: progress(l, 0.02),
                                              allow_download=bool(settings.get("allow_downloads", True)))
    model = get_whisper(settings, models_dir)

    remote = chans[-1]
    segments: list[dict] = []
    speakers: list[dict] = []

    if stereo:
        me_asr = transcribe(model, chans[0], settings, stage_cb("asr_me"), "Transcribiendo canal 'Yo'", cancel)
        me_segs = align.fixed_speaker(me_asr, ME_ID)
        # Marca posible eco: mi canal muy por debajo del remoto en ese tramo
        for s in me_segs:
            l, r = _rms(chans[0], s["start"], s["end"]), _rms(chans[1], s["start"], s["end"])
            if r > 0 and l > 0 and 20 * math.log10(l / r) < float(settings["echo_ratio_db"]):
                s["flag"] = "posible eco"
        segments += me_segs
        speakers.append({"id": ME_ID, "label": "Yo", "color": speaker_color(0)})

    remote_asr = transcribe(model, remote, settings, stage_cb("asr_remote"),
                            "Transcribiendo canal remoto" if stereo else "Transcribiendo", cancel)
    turns_raw = diarize(remote, seg_model, emb_model, num_speakers, float(settings["diar_threshold"]),
                        int(settings["cpu_threads"]), stage_cb("diar"), cancel)
    turns, labels = align.relabel_by_appearance(turns_raw)
    segments += align.split_by_speaker(remote_asr, turns, default_speaker=labels[0] if labels else "N1")
    for lab in labels or ["N1"]:
        speakers.append({"id": lab, "label": lab, "color": speaker_color(len(speakers))})

    project.update({
        "duration": round(duration, 3),
        "channels": channels,
        "stereo_mode": stereo,
        "speakers": speakers,
        "segments": sorted(segments, key=lambda s: s["start"]),
        "processed": True,
    })
    progress("Terminado", 1.0)
    return project, peaks

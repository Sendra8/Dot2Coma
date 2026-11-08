"""Combina la transcripción (Whisper) con la diarización (turnos de hablante).

Funciones puras, sin dependencias de modelos: fáciles de probar.

- asr_segments: [{"start", "end", "text", "lang", "words": [{"start","end","word"}]}]
- turns:        [(start, end, speaker_id_str)]
"""
from __future__ import annotations

import uuid


def new_seg_id() -> str:
    return "s" + uuid.uuid4().hex[:10]


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def assign_speaker(start: float, end: float, turns: list[tuple[float, float, str]]) -> str | None:
    """Hablante con más solape; si no hay solape, el turno más cercano."""
    if not turns:
        return None
    best, best_ov = None, 0.0
    for t0, t1, spk in turns:
        ov = _overlap(start, end, t0, t1)
        if ov > best_ov:
            best, best_ov = spk, ov
    if best is not None:
        return best
    mid = (start + end) / 2
    return min(turns, key=lambda t: 0 if t[0] <= mid <= t[1] else min(abs(mid - t[0]), abs(mid - t[1])))[2]


def relabel_by_appearance(turns: list[tuple[float, float, int]], prefix: str = "N") -> tuple[list[tuple[float, float, str]], list[str]]:
    """Renombra clusters 0,1,2... a N1, N2... según orden de primera aparición."""
    mapping: dict[int, str] = {}
    out = []
    for t0, t1, spk in sorted(turns, key=lambda t: t[0]):
        if spk not in mapping:
            mapping[spk] = f"{prefix}{len(mapping) + 1}"
        out.append((t0, t1, mapping[spk]))
    return out, list(mapping.values())


def _join_words(words: list[dict]) -> str:
    return "".join(w["word"] for w in words).strip()


def _smooth(labels: list[str], words: list[dict], max_dur: float = 0.6) -> list[str]:
    """Elimina 'parpadeos': una palabra corta aislada asignada a otro hablante."""
    out = list(labels)
    for i in range(1, len(out) - 1):
        if out[i - 1] == out[i + 1] != out[i] and (words[i]["end"] - words[i]["start"]) <= max_dur:
            out[i] = out[i - 1]
    return out


def split_by_speaker(asr_segments: list[dict], turns: list[tuple[float, float, str]],
                     default_speaker: str = "N1") -> list[dict]:
    """Asigna hablante a cada palabra y corta los segmentos ASR en cambios de hablante."""
    result: list[dict] = []
    for seg in asr_segments:
        words = [w for w in seg.get("words") or [] if w.get("word", "").strip()]
        if not words or not turns:
            spk = assign_speaker(seg["start"], seg["end"], turns) or default_speaker
            result.append(_mk(seg, seg["start"], seg["end"], seg.get("text", "").strip(), spk, words))
            continue
        labels = [assign_speaker(w["start"], w["end"], turns) or default_speaker for w in words]
        labels = _smooth(labels, words)
        run_start = 0
        for i in range(1, len(words) + 1):
            if i == len(words) or labels[i] != labels[run_start]:
                chunk = words[run_start:i]
                result.append(_mk(seg, chunk[0]["start"], chunk[-1]["end"], _join_words(chunk), labels[run_start], chunk))
                run_start = i
    return result


def _mk(seg: dict, start: float, end: float, text: str, spk: str, words: list[dict]) -> dict:
    return {
        "id": new_seg_id(),
        "speaker": spk,
        "start": round(float(start), 3),
        "end": round(float(max(end, start + 0.05)), 3),
        "text": text,
        "lang": seg.get("lang"),
        "words": [[round(w["start"], 3), round(w["end"], 3), w["word"]] for w in words],
    }


def fixed_speaker(asr_segments: list[dict], speaker: str) -> list[dict]:
    """Todos los segmentos a un hablante fijo (canal 'Yo')."""
    return [_mk(s, s["start"], s["end"], s.get("text", "").strip(), speaker,
                [w for w in s.get("words") or [] if w.get("word", "").strip()])
            for s in asr_segments if s.get("text", "").strip()]

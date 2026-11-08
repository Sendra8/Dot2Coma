"""Resumen con un modelo GGUF local (llama.cpp vía llama-cpp-python).

Cualquier .gguf con plantilla de chat sirve (Qwen, Llama, Gemma, Mistral...).
Si la transcripción no cabe en el contexto, se resume por bloques y luego se
resumen los resúmenes (map-reduce).
"""
from __future__ import annotations

import os
import threading
from typing import Callable

from .project import transcript_lines

Progress = Callable[[str, float], None]


class Cancelled(Exception):
    pass


def chunk_lines(lines: list[str], count_tokens: Callable[[str], int], budget: int) -> list[str]:
    """Agrupa líneas en bloques de como mucho `budget` tokens (una línea larga se parte)."""
    chunks: list[str] = []
    cur: list[str] = []
    cur_tok = 0
    for line in lines:
        n = count_tokens(line) + 1
        if n > budget and len(line.split()) > 1:  # línea enorme: partir por palabras
            if cur:
                chunks.append("\n".join(cur))
                cur, cur_tok = [], 0
            words = line.split()
            half = len(words) // 2
            for part in (" ".join(words[:half]), " ".join(words[half:])):
                chunks.extend(chunk_lines([part], count_tokens, budget))
            continue
        if cur and cur_tok + n > budget:
            chunks.append("\n".join(cur))
            cur, cur_tok = [], 0
        cur.append(line)
        cur_tok += n
    if cur:
        chunks.append("\n".join(cur))
    return chunks


def summarize(project: dict, settings: dict, progress: Progress, cancel: threading.Event) -> str:
    path = settings.get("gguf_path", "")
    if not path or not os.path.isfile(path):
        raise RuntimeError("Configura la ruta a un modelo .gguf en Ajustes antes de generar el resumen.")
    try:
        from llama_cpp import Llama
    except ImportError as e:
        raise RuntimeError("Falta llama-cpp-python. Instálalo (ver README) para generar resúmenes.") from e

    progress("Cargando modelo de resumen", 0.02)
    n_ctx = int(settings.get("llm_ctx") or 8192)
    llm = Llama(model_path=path, n_ctx=n_ctx, n_threads=int(settings.get("llm_threads") or 0) or None,
                verbose=False)
    system = settings.get("summary_prompt") or ""
    max_out = min(1500, n_ctx // 4)

    def count(t: str) -> int:
        return len(llm.tokenize(t.encode("utf-8"), add_bos=False))

    def ask(user: str, max_tokens: int) -> str:
        if cancel.is_set():
            raise Cancelled()
        r = llm.create_chat_completion(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens, temperature=0.3,
        )
        return r["choices"][0]["message"]["content"].strip()

    lines = transcript_lines(project)
    if not lines:
        raise RuntimeError("La transcripción está vacía.")
    budget = n_ctx - count(system) - max_out - 200
    chunks = chunk_lines(lines, count, budget)

    if len(chunks) == 1:
        progress("Generando resumen", 0.2)
        return ask("Transcripción:\n\n" + chunks[0], max_out)

    partials = []
    for i, ch in enumerate(chunks):
        progress(f"Resumiendo bloque {i + 1}/{len(chunks)}", 0.1 + 0.7 * i / len(chunks))
        partials.append(ask(
            f"Esto es el bloque {i + 1} de {len(chunks)} de una reunión. Extrae de forma concisa "
            f"los puntos tratados, decisiones, tareas (con responsable) y temas abiertos.\n\n{ch}",
            max_out // 2))
    progress("Combinando resúmenes", 0.85)
    joined = "\n\n".join(f"--- Bloque {i + 1} ---\n{p}" for i, p in enumerate(partials))
    while count(joined) > budget and len(partials) > 1:  # reducción adicional si aún no cabe
        partials = [ask("Fusiona estos resúmenes parciales en uno solo:\n\n" + "\n\n".join(partials[i:i + 2]),
                        max_out // 2) for i in range(0, len(partials), 2)]
        joined = "\n\n".join(partials)
    return ask("Estos son resúmenes parciales consecutivos de una misma reunión. "
               "Redacta el resumen final con el formato indicado:\n\n" + joined, max_out)

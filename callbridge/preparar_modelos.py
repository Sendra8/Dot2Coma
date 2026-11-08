"""Descarga los modelos en una carpeta para copiarla a un PC sin acceso a Internet.

Uso (en cualquier equipo con Internet y las dependencias instaladas):
    python preparar_modelos.py --out modelos
    python preparar_modelos.py --out modelos --whisper large-v3-turbo small

Después copia la carpeta «modelos» al PC del trabajo y, en CallBridge → Ajustes,
pon esa ruta en «Carpeta de modelos» y desmarca «Permitir descargar modelos».
Son modelos públicos (no contienen datos tuyos).
"""
import argparse
from pathlib import Path

from callbridge.config import DEFAULTS
from callbridge.pipeline import ensure_diar_models, ensure_whisper


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="modelos", help="carpeta de destino")
    ap.add_argument("--whisper", nargs="+", default=[DEFAULTS["whisper_model"]],
                    help="modelos Whisper (large-v3-turbo, large-v3, medium, small…)")
    ap.add_argument("--voz", default=DEFAULTS["diar_embedding"], help="modelo ONNX de huella de voz para agrupar")
    args = ap.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    print("Diarización…")
    seg, emb = ensure_diar_models(out, args.voz, lambda l, f: print(f"\r  {l}: {f:5.0%}", end=""))
    print(f"\n  {seg}\n  {emb}")
    for name in args.whisper:
        print(f"Whisper {name}… (puede tardar, ~0,8–3 GB)")
        print("  " + ensure_whisper(name, out))
    print(f"\nListo. Copia «{out}» al otro PC y selecciónala en Ajustes → Carpeta de modelos.")


if __name__ == "__main__":
    main()

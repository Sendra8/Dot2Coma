from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import Config
from .pipeline import build


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="whproxy")
    sub = p.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="build a 3-colour printable proxy")
    b.add_argument("name")
    b.add_argument("--out", type=Path, default=Path("output"))
    b.add_argument("--height-mm", type=float, default=100.0)
    b.add_argument("--process-height", type=int, default=320)
    b.add_argument("--black", type=float, default=0.05)
    b.add_argument("--gray", type=float, default=0.15)
    b.add_argument("--surface-color-depth-mm", type=float, default=2.5)
    b.add_argument(
        "--source",
        choices=("network", "offline"),
        default=None,
        help="network hits Algolia + the GW CDN; offline renders synthetic frames",
    )
    b.add_argument(
        "--pair-mode",
        choices=("union", "intersection"),
        default="union",
    )

    args = p.parse_args(argv)

    if args.command == "build":
        base = Config()
        cfg = Config(
            target_height_mm=args.height_mm,
            process_height_px=args.process_height,
            black_fraction=args.black,
            gray_fraction=args.gray,
            surface_color_depth_mm=args.surface_color_depth_mm,
            visual_hull_pair_mode=args.pair_mode,
            source_provider=args.source or base.source_provider,
        )
        result = build(args.name, args.out, cfg)
        manifest = json.loads((result / "manifest.json").read_text(encoding="utf-8"))

        print(manifest["product"]["name"])
        print(f"- query           : {manifest['query']}")
        print(f"- match score     : {manifest['product']['score']}")
        print(f"- 360 folder      : {manifest['spin']['selected_folder']}")
        print(f"- frames          : {manifest['spin']['rows']} x {manifest['spin']['angles']}")
        print(f"- source provider : {manifest['spin']['provider']}")
        size = manifest["mesh"]["bbox_mm"]["size"]
        print(f"- bbox mm         : {size[0]} x {size[1]} x {size[2]}")
        for name, stats in manifest["mesh"]["parts"].items():
            print(f"  · {name:<6} {stats['faces']:>7} faces  {stats['voxels']:>8} voxels")
        print(f"- renders         : {manifest['render']}")
        print(f"- output          : {result}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

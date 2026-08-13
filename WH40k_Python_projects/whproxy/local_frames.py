"""Local-frames source provider.

Takes four cardinal images you already have on disk and feeds them into the
pipeline unchanged. This is the route to a real result when the GW CDN is
unreachable but you can obtain the official turntable frames some other way
(a browser on a machine with egress, an existing download, your own
photographs of the assembled miniature on a white background).

Expected layout, any of .jpg/.jpeg/.png:

    my_frames/
    ├── front.jpg
    ├── left.jpg
    ├── back.jpg
    └── right.jpg

The frames must follow the same convention as the GW sets: white background,
the model centred, and `left`/`right` being true 90 degree turntable steps from
`front` — not a mirrored copy of one another.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from .config import Config
from .models import SpinSet

VIEWS = ("front", "left", "back", "right")
SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")


def find_frames(frames_dir: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    missing: list[str] = []

    for view in VIEWS:
        for suffix in SUFFIXES:
            candidate = frames_dir / f"{view}{suffix}"
            if candidate.exists():
                found[view] = candidate
                break
        else:
            missing.append(view)

    if missing:
        raise RuntimeError(
            f"{frames_dir} is missing cardinal frames: {', '.join(missing)}.\n"
            f"Expected one of {', '.join(SUFFIXES)} for each of "
            f"{', '.join(VIEWS)}."
        )

    return found


def load_cardinals_local(
    cfg: Config,
    spin: SpinSet,
    out_dir: Path,
) -> tuple[dict[str, Path], dict]:
    frames_dir = Path(cfg.frames_dir)
    if not frames_dir.is_dir():
        raise RuntimeError(f"--frames-dir {frames_dir} is not a directory")

    found = find_frames(frames_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    result: dict[str, Path] = {}
    sizes: dict[str, list[int]] = {}
    for view, src in found.items():
        # Normalise to JPEG so the rest of the pipeline sees one format.
        img = Image.open(src).convert("RGB")
        path = out_dir / f"{view}.jpg"
        img.save(path, quality=95)
        result[view] = path
        sizes[view] = [img.width, img.height]

    metadata = {
        "folder": str(frames_dir),
        "rows": 1,
        "angles": 4,
        "cardinal_frames": {v: found[v].name for v in VIEWS},
        "provider": "local-frames",
        "source_sizes": sizes,
    }
    return result, metadata

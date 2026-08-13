from __future__ import annotations

import re
import shutil
from pathlib import Path

import requests

from .config import Config
from .models import SpinSet

GRID_NAME = re.compile(r"^(\d{2})-(\d{2})\.jpg$", re.I)
UA = {"User-Agent": "Mozilla/5.0"}


def frame_url(cfg: Config, spin: SpinSet, filename: str) -> str:
    return (
        f"{cfg.cdn_base}/app/resources/catalog/product/threeSixty/"
        f"{spin.folder}/{filename}"
    )


def probe_frame(cfg: Config, spin: SpinSet, filename: str) -> bool:
    r = requests.get(frame_url(cfg, spin, filename), timeout=20, headers=UA)
    return r.status_code == 200 and r.headers.get("content-type", "").startswith("image/")


def detect_grid(cfg: Config, spin: SpinSet) -> tuple[int, int]:
    """Return `(rows, angles)` for modern `RR-AA.jpg` layouts."""

    # Detect horizontal count first. Most modern models use 12.
    angles = 0
    for col in range(1, 65):
        name = f"01-{col:02d}.jpg"
        if probe_frame(cfg, spin, name):
            angles = col
        elif col > 12:
            break
        elif col > angles + 1:
            break

    if angles < 4 or angles % 4:
        raise RuntimeError(f"Unsupported angular frame count: {angles}")

    rows = 0
    for row in range(1, 10):
        if probe_frame(cfg, spin, f"{row:02d}-01.jpg"):
            rows = row
        else:
            break

    return rows, angles


def cardinal_filenames(angles: int) -> dict[str, str]:
    if angles % 4:
        raise ValueError("angles must be divisible by 4")
    return {
        "front": f"01-{angles:02d}.jpg",
        "left": f"01-{angles // 4:02d}.jpg",
        "back": f"01-{angles // 2:02d}.jpg",
        "right": f"01-{3 * angles // 4:02d}.jpg",
    }


def _validate_payload(data: bytes, content_type: str, url: str) -> None:
    if not content_type.startswith("image/"):
        raise RuntimeError(f"Not an image: {url}")
    if len(data) < 5_000:
        raise RuntimeError(f"Suspiciously small image: {url}")


def download_cardinals(
    cfg: Config,
    spin: SpinSet,
    out_dir: Path,
) -> tuple[dict[str, Path], dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, angles = detect_grid(cfg, spin)
    names = cardinal_filenames(angles)

    cache_root = Path(cfg.cache_dir) / spin.folder
    cache_root.mkdir(parents=True, exist_ok=True)

    result: dict[str, Path] = {}
    for view, filename in names.items():
        path = out_dir / f"{view}.jpg"
        cached = cache_root / filename

        if cached.exists() and cached.stat().st_size >= 5_000:
            shutil.copyfile(cached, path)
            result[view] = path
            continue

        url = frame_url(cfg, spin, filename)
        r = requests.get(url, timeout=30, headers=UA)
        r.raise_for_status()
        _validate_payload(r.content, r.headers.get("content-type", ""), url)

        cached.write_bytes(r.content)
        path.write_bytes(r.content)
        result[view] = path

    metadata = {
        "folder": spin.folder,
        "rows": rows,
        "angles": angles,
        "cardinal_frames": names,
        "provider": "network",
    }
    return result, metadata

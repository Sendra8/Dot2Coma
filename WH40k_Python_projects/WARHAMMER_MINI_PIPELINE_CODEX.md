# Warhammer miniature → 4 views → 3-color simplified proxy → OBJ → 3D preview

## Codex implementation brief

### Goal

Build a deterministic Python pipeline that receives an **approximate Warhammer unit name** and produces:

1. the best matching Games Workshop product;
2. the official 360° image-set folder when available;
3. four cardinal photographs: **front / left / back / right**;
4. simplified 3-color images using **ochre / gray / black**;
5. a simplified volumetric 3D proxy reconstructed from the four silhouettes;
6. a multipart `.obj` + `.mtl` with the same three print colors;
7. an interactive local 3D viewer;
8. rendered views from that viewer;
9. one aggregated preview image to show to the user;
10. a `manifest.json` that makes the whole result reproducible.

The intended UX is:

```text
python -m whproxy build "Norn Emissary"
```

and the user receives:

```text
output/norn_emissary/
├── manifest.json
├── source/
│   ├── front.jpg
│   ├── left.jpg
│   ├── back.jpg
│   └── right.jpg
├── color/
│   ├── front.png
│   ├── left.png
│   ├── back.png
│   ├── right.png
│   └── source_grid.png
├── mesh/
│   ├── model.obj
│   └── model.mtl
├── viewer/
│   └── viewer.html
├── renders/
│   ├── front.png
│   ├── left.png
│   ├── back.png
│   ├── right.png
│   ├── iso.png
│   └── top.png
└── preview.png
```

---

# 1. Validated findings

These points were experimentally validated and should be treated as the starting assumptions.

## 1.1 Do not make direct product-page scraping the primary method

Warhammer product pages can return `405 Method Not Allowed` to automated clients, even from external runners.

The robust route is to query the same **Algolia product catalogue** used by the Warhammer frontend.

Validated frontend catalogue parameters at the time of testing:

```text
application id: M5ZIQZNQ2H
search api key: 92c6a8254f9d34362df8e6d96475e5d8
index: prod-lazarus-product-en-gb
```

These are frontend search credentials, not a private account secret, but they **must be configurable through environment variables** because GW can rotate them or rename the index.

Recommended variables:

```text
GW_ALGOLIA_APP_ID
GW_ALGOLIA_API_KEY
GW_ALGOLIA_INDEX
GW_CDN_BASE
```

Defaults can use the validated values above.

## 1.2 The Algolia `images` field reveals the real 360 folder

Example validated for **Norn Emissary**:

```text
/app/resources/catalog/product/threeSixty/99120106064_TyrNornEmissary2023OTT1360
```

The same product record may contain more than one 360 set because one box can build multiple units, e.g. Norn Emissary and Norn Assimilator.

Therefore the folder itself must also be fuzzy matched against the user's requested unit name.

Example validated for **XV104 Riptide**:

```text
/app/resources/catalog/product/threeSixty/99120113030_Riptide360/
```

The numeric code in the 360 folder does **not necessarily equal the current stock-image SKU**, so never reconstruct the folder from SKU alone when Algolia already exposes it.

## 1.3 The 360 viewer is a sequence of JPGs, not a 3D model

Typical modern format:

```text
01-01.jpg
01-02.jpg
...
01-12.jpg
02-01.jpg
...
03-12.jpg
```

The first number is camera height / row and the second is angular position.

Validated modern sets use 12 horizontal positions. Some older products may expose another layout, so the parser must detect the pattern rather than assume exactly 36 files.

## 1.4 Cardinal mapping

For the horizontal row (`01`) with 12 angular frames, validated on Riptide and Norn:

```text
front = 01-12.jpg
left  = 01-03.jpg
back  = 01-06.jpg
right = 01-09.jpg
```

Generalized for `N` evenly-spaced frames where `N % 4 == 0`:

```text
front = N
left  = N/4
back  = N/2
right = 3N/4
```

Do **not** assume `01-01` is frontal. It is offset by one angular step in the tested sets.

---

# 2. Recommended architecture

```text
whproxy/
├── __init__.py
├── cli.py
├── config.py
├── catalog.py
├── download.py
├── image_pipeline.py
├── reconstruction.py
├── obj_writer.py
├── viewer.py
├── pipeline.py
└── models.py

tests/
├── test_catalog.py
├── test_cardinals.py
├── test_quantization.py
└── test_reconstruction.py
```

Keep every stage independently testable. The pipeline should cache network results and avoid re-downloading already validated images.

---

# 3. Dependencies

Recommended `pyproject.toml` dependencies:

```toml
[project]
requires-python = ">=3.11"
dependencies = [
  "requests>=2.32",
  "rapidfuzz>=3.9",
  "numpy>=2.0",
  "Pillow>=10.0",
  "opencv-python-headless>=4.10",
  "scipy>=1.13",
  "scikit-image>=0.24",
  "trimesh>=4.4",
  "plotly>=5.24",
  "playwright>=1.46",
]
```

Playwright is **not needed to browse Warhammer.com** in the main path. It is used only to render the local self-contained 3D viewer to PNG.

---

# 4. Configuration

`whproxy/config.py`

```python
from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Config:
    algolia_app_id: str = os.getenv("GW_ALGOLIA_APP_ID", "M5ZIQZNQ2H")
    algolia_api_key: str = os.getenv(
        "GW_ALGOLIA_API_KEY",
        "92c6a8254f9d34362df8e6d96475e5d8",
    )
    algolia_index: str = os.getenv(
        "GW_ALGOLIA_INDEX",
        "prod-lazarus-product-en-gb",
    )
    cdn_base: str = os.getenv("GW_CDN_BASE", "https://www.warhammer.com")

    # image processing
    process_height_px: int = 320
    black_fraction: float = 0.05
    gray_fraction: float = 0.15
    min_ochre_fraction: float = 0.50
    white_threshold: int = 242
    min_component_px: int = 40

    # geometry
    target_height_mm: float = 100.0
    surface_color_depth_mm: float = 2.5
    mesh_target_faces_per_part: int = 25_000

    # palette
    ochre_rgb: tuple[int, int, int] = (194, 151, 78)
    gray_rgb: tuple[int, int, int] = (105, 105, 105)
    black_rgb: tuple[int, int, int] = (24, 24, 24)
```

The defaults deliberately use **5% black + 15% gray + 80% ochre**. This follows the preferred quantile approach and automatically satisfies the rule that at least 50% of the foreground remains ochre.

---

# 5. Data models

`whproxy/models.py`

```python
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ProductHit:
    object_id: str
    name: str
    slug: str
    sku: str | None
    images: list[str]
    score: float = 0.0


@dataclass
class SpinSet:
    folder: str
    score: float


@dataclass
class BuildResult:
    query: str
    product: ProductHit
    spin: SpinSet
    out_dir: Path
    source_images: dict[str, Path] = field(default_factory=dict)
    color_images: dict[str, Path] = field(default_factory=dict)
    obj_path: Path | None = None
    mtl_path: Path | None = None
    viewer_path: Path | None = None
    preview_path: Path | None = None
```

---

# 6. Stage A — catalogue search and fuzzy matching

`whproxy/catalog.py`

```python
from __future__ import annotations

import html
import re
from urllib.parse import quote

import requests
from rapidfuzz import fuzz

from .config import Config
from .models import ProductHit, SpinSet


SPIN_RE = re.compile(
    r"/app/resources/catalog/product/threeSixty/([^/?]+)",
    re.I,
)


def normalize(text: str) -> str:
    text = html.unescape(text).lower()
    text = text.replace("t'au", "tau").replace("t’au", "tau")
    text = re.sub(r"[^a-z0-9áéíóúüñ ]+", " ", text)
    return " ".join(text.split())


def similarity(query: str, candidate: str) -> float:
    q = normalize(query)
    c = normalize(candidate)
    return max(
        fuzz.WRatio(q, c),
        fuzz.token_set_ratio(q, c),
        fuzz.token_sort_ratio(q, c),
    )


def _flatten_image_strings(images) -> list[str]:
    result: list[str] = []
    for item in images or []:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            result.extend(v for v in item.values() if isinstance(v, str))
    return list(dict.fromkeys(result))


def query_catalog(query: str, cfg: Config, hits_per_page: int = 30) -> list[ProductHit]:
    url = (
        f"https://{cfg.algolia_app_id}-dsn.algolia.net/1/indexes/"
        f"{cfg.algolia_index}/query"
    )
    headers = {
        "X-Algolia-Application-Id": cfg.algolia_app_id,
        "X-Algolia-API-Key": cfg.algolia_api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "query": query,
        "hitsPerPage": hits_per_page,
        "attributesToRetrieve": [
            "objectID",
            "name",
            "slug",
            "sku",
            "images",
            "productType",
        ],
    }

    r = requests.post(url, headers=headers, json=payload, timeout=30)
    r.raise_for_status()
    data = r.json()

    hits: list[ProductHit] = []
    for h in data.get("hits", []):
        name = h.get("name") or ""
        slug = h.get("slug") or ""
        score = max(similarity(query, name), similarity(query, slug))
        hits.append(
            ProductHit(
                object_id=str(h.get("objectID", "")),
                name=name,
                slug=slug,
                sku=h.get("sku"),
                images=_flatten_image_strings(h.get("images")),
                score=score,
            )
        )

    return sorted(hits, key=lambda h: h.score, reverse=True)


def select_product(
    query: str,
    hits: list[ProductHit],
    min_score: float = 55.0,
    ambiguity_gap: float = 6.0,
) -> ProductHit:
    if not hits:
        raise RuntimeError(f"No catalogue result for {query!r}")

    best = hits[0]
    if best.score < min_score:
        raise RuntimeError(
            f"Best product match too weak: {best.name!r} ({best.score:.1f})"
        )

    if len(hits) > 1 and best.score - hits[1].score < ambiguity_gap:
        raise RuntimeError(
            "Ambiguous product match:\n"
            + "\n".join(f"  {h.score:5.1f} {h.name}" for h in hits[:5])
        )

    return best


def extract_spin_sets(query: str, product: ProductHit) -> list[SpinSet]:
    folders: list[str] = []
    for s in product.images:
        m = SPIN_RE.search(s)
        if m:
            folders.append(m.group(1))

    folders = list(dict.fromkeys(folders))
    result = [SpinSet(folder=f, score=similarity(query, f)) for f in folders]
    return sorted(result, key=lambda s: s.score, reverse=True)


def select_spin_set(query: str, product: ProductHit) -> SpinSet:
    spins = extract_spin_sets(query, product)
    if not spins:
        raise RuntimeError(f"{product.name!r} has no threeSixty set")

    # Important for boxes that build multiple units.
    return spins[0]
```

### Behaviour for ambiguous kits

For a kit containing both:

```text
...TyrNornEmissary2023OTT1360
...TyrNornAssimilator2023OTT1360
```

`"Norn Emissary"` must select the first, while `"Norn Assimilator"` must select the second.

Never silently select a different build merely because the product box is the same.

---

# 7. Stage B — detect layout and download cardinal photographs

`whproxy/download.py`

```python
from __future__ import annotations

import re
from pathlib import Path

import requests

from .config import Config
from .models import SpinSet


GRID_NAME = re.compile(r"^(\d{2})-(\d{2})\.jpg$", re.I)


def frame_url(cfg: Config, spin: SpinSet, filename: str) -> str:
    return (
        f"{cfg.cdn_base}/app/resources/catalog/product/threeSixty/"
        f"{spin.folder}/{filename}"
    )


def probe_frame(cfg: Config, spin: SpinSet, filename: str) -> bool:
    r = requests.get(
        frame_url(cfg, spin, filename),
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0"},
    )
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


def download_cardinals(
    cfg: Config,
    spin: SpinSet,
    out_dir: Path,
) -> tuple[dict[str, Path], dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, angles = detect_grid(cfg, spin)
    names = cardinal_filenames(angles)

    result: dict[str, Path] = {}
    for view, filename in names.items():
        url = frame_url(cfg, spin, filename)
        r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        if not r.headers.get("content-type", "").startswith("image/"):
            raise RuntimeError(f"Not an image: {url}")
        if len(r.content) < 5_000:
            raise RuntimeError(f"Suspiciously small image: {url}")

        path = out_dir / f"{view}.jpg"
        path.write_bytes(r.content)
        result[view] = path

    metadata = {
        "folder": spin.folder,
        "rows": rows,
        "angles": angles,
        "cardinal_frames": names,
    }
    return result, metadata
```

## Network etiquette

- cache successful files;
- do not repeatedly probe the same URL;
- add a small delay if bulk-building many units;
- prefer Algolia metadata over crawling individual product pages.

---

# 8. Stage C — foreground extraction and view normalization

Official turntable images are normally on a white background. Use deterministic image processing first; do not introduce an AI image generator into the reproducible path.

`whproxy/image_pipeline.py`

```python
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .config import Config


PALETTE_NAMES = {0: "ochre", 1: "gray", 2: "black"}


def read_rgb(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"))


def edge_connected_white_background(rgb: np.ndarray, white_threshold: int) -> np.ndarray:
    """Return background mask: near-white pixels connected to an image edge."""
    near_white = np.all(rgb >= white_threshold, axis=2).astype(np.uint8)
    n, labels = cv2.connectedComponents(near_white, connectivity=8)

    touching = set(labels[0, :]) | set(labels[-1, :]) | set(labels[:, 0]) | set(labels[:, -1])
    bg = np.isin(labels, list(touching))
    return bg


def foreground_mask(rgb: np.ndarray, cfg: Config) -> np.ndarray:
    bg = edge_connected_white_background(rgb, cfg.white_threshold)
    fg = (~bg).astype(np.uint8) * 255

    kernel = np.ones((3, 3), np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, kernel, iterations=2)
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, kernel, iterations=1)

    n, labels, stats, _ = cv2.connectedComponentsWithStats(fg, connectivity=8)
    clean = np.zeros_like(fg)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= cfg.min_component_px:
            clean[labels == i] = 255

    return clean.astype(bool)


def crop_to_mask(rgb: np.ndarray, mask: np.ndarray, margin: int = 8):
    ys, xs = np.nonzero(mask)
    if not len(xs):
        raise RuntimeError("No foreground detected")
    x0 = max(0, xs.min() - margin)
    x1 = min(rgb.shape[1], xs.max() + margin + 1)
    y0 = max(0, ys.min() - margin)
    y1 = min(rgb.shape[0], ys.max() + margin + 1)
    return rgb[y0:y1, x0:x1], mask[y0:y1, x0:x1]


def resize_preserve_height(rgb: np.ndarray, mask: np.ndarray, height: int):
    scale = height / rgb.shape[0]
    width = max(1, round(rgb.shape[1] * scale))
    rgb2 = cv2.resize(rgb, (width, height), interpolation=cv2.INTER_AREA)
    mask2 = cv2.resize(mask.astype(np.uint8), (width, height), interpolation=cv2.INTER_NEAREST)
    return rgb2, mask2.astype(bool)


def pad_pair_to_same_width(a_rgb, a_mask, b_rgb, b_mask):
    width = max(a_rgb.shape[1], b_rgb.shape[1])

    def pad(rgb, mask):
        left = (width - rgb.shape[1]) // 2
        right = width - rgb.shape[1] - left
        rgb = cv2.copyMakeBorder(
            rgb, 0, 0, left, right,
            cv2.BORDER_CONSTANT,
            value=(255, 255, 255),
        )
        mask = np.pad(mask, ((0, 0), (left, right)), constant_values=False)
        return rgb, mask

    return (*pad(a_rgb, a_mask), *pad(b_rgb, b_mask))
```

## Coordinate alignment

After normalizing dimensions:

- **mirror `back` horizontally** so its world-X axis agrees with `front`;
- **mirror `right` horizontally** so its world-depth axis agrees with `left`.

This is essential before combining silhouettes into a visual hull.

```python
def align_opposite_views(views: dict[str, tuple[np.ndarray, np.ndarray]]):
    back_rgb, back_mask = views["back"]
    right_rgb, right_mask = views["right"]

    views["back"] = (np.fliplr(back_rgb), np.fliplr(back_mask))
    views["right"] = (np.fliplr(right_rgb), np.fliplr(right_mask))
    return views
```

---

# 9. Stage D — deterministic 3-color simplification

The desired method is percentile/rank based, not arbitrary fixed RGB thresholds.

## Rule

Inside the foreground:

- darkest 5% → **black**;
- next 15% → **gray**;
- remaining 80% → **ochre**.

The exact values are configurable, but ochre must never fall below `min_ochre_fraction`.

This directly implements the idea: **sort the foreground pixels by grayscale darkness and choose the two cut points from rank**.

Add to `image_pipeline.py`:

```python
def quantize_by_rank(
    rgb: np.ndarray,
    fg: np.ndarray,
    cfg: Config,
) -> np.ndarray:
    """
    Class image:
      -1 background
       0 ochre
       1 gray
       2 black
    """
    black_fraction = cfg.black_fraction
    gray_fraction = cfg.gray_fraction

    if black_fraction + gray_fraction > 1.0 - cfg.min_ochre_fraction:
        available = 1.0 - cfg.min_ochre_fraction
        ratio = black_fraction / (black_fraction + gray_fraction)
        black_fraction = available * ratio
        gray_fraction = available * (1.0 - ratio)

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    flat_fg = np.flatnonzero(fg.ravel())

    # Lower luminance = darker. Stable sort gives deterministic ties.
    ordered = flat_fg[np.argsort(gray.ravel()[flat_fg], kind="stable")]

    n = len(ordered)
    n_black = round(n * black_fraction)
    n_gray = round(n * gray_fraction)

    cls = np.full(gray.size, -1, dtype=np.int8)
    cls[flat_fg] = 0
    cls[ordered[:n_black]] = 2
    cls[ordered[n_black:n_black + n_gray]] = 1

    return cls.reshape(gray.shape)


def clean_color_classes(cls: np.ndarray, fg: np.ndarray) -> np.ndarray:
    """Remove tiny salt-and-pepper details without collapsing gray into black."""
    out = cls.copy()
    kernel = np.ones((3, 3), np.uint8)

    # Work independently; never merge the two detail classes.
    for value in (1, 2):
        m = (cls == value).astype(np.uint8) * 255
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, kernel, iterations=1)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, kernel, iterations=1)
        out[(cls == value) & (m == 0)] = 0
        out[m > 0] = value

    out[~fg] = -1
    return out


def colorize_classes(cls: np.ndarray, cfg: Config) -> np.ndarray:
    out = np.full((*cls.shape, 3), 255, dtype=np.uint8)
    out[cls == 0] = cfg.ochre_rgb
    out[cls == 1] = cfg.gray_rgb
    out[cls == 2] = cfg.black_rgb
    return out


def save_color_map(path: Path, cls: np.ndarray, cfg: Config):
    Image.fromarray(colorize_classes(cls, cfg)).save(path)
```

### Important geometry interpretation

The colors are not three floating 2D surfaces.

For 3D printing, they must become **volumetric regions attached to the body**. The reconstruction section below does this by using the color classes only in a finite surface shell and leaving the interior ochre.

---

# 10. Stage E — 3D reconstruction from four silhouettes

## 10.1 Default geometry: visual hull proxy

This is a deliberately simplified proxy, not photogrammetry.

Use:

```text
front + mirrored back → world X/Z silhouette
left + mirrored right → world Y/Z silhouette
```

For a storage/packing proxy, prefer the **union** of opposite silhouettes so appendages are not accidentally lost because of perspective differences:

```text
FB(x,z) = front(x,z) OR back_mirrored(x,z)
LR(y,z) = left(y,z)  OR right_mirrored(y,z)
```

Then:

```text
occupied(x,y,z) = FB(x,z) AND LR(y,z)
```

This is a standard silhouette visual-hull approximation.

It intentionally tends to overestimate rather than underestimate volume, which is preferable for a packing proxy.

## 10.2 Surface colors must have depth

To avoid gray/black becoming floating skins:

1. create the complete occupied volume;
2. calculate the internal Euclidean distance to the nearest exterior voxel;
3. voxels deeper than `surface_color_depth_mm` are forced to ochre;
4. only the outer shell receives gray/black based on the closest cardinal projection;
5. each color is meshed as a real volume.

This makes the model multipart and printable.

`whproxy/reconstruction.py`

```python
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import binary_closing, binary_fill_holes, distance_transform_edt
from skimage.measure import marching_cubes
import trimesh

from .config import Config


@dataclass
class MeshPart:
    name: str
    rgb: tuple[int, int, int]
    mesh: trimesh.Trimesh


def build_visual_hull(
    masks: dict[str, np.ndarray],
) -> np.ndarray:
    front = masks["front"]
    back = masks["back"]       # already mirrored/aligned
    left = masks["left"]
    right = masks["right"]     # already mirrored/aligned

    fb = front | back
    lr = left | right

    # shape conventions:
    # fb: [z, x]
    # lr: [z, y]
    # vol: [z, y, x]
    vol = fb[:, None, :] & lr[:, :, None]
    vol = binary_closing(vol, iterations=1)
    vol = binary_fill_holes(vol)
    return vol.astype(bool)


def build_material_volume(
    occupied: np.ndarray,
    classes: dict[str, np.ndarray],
    voxel_mm: float,
    shell_depth_mm: float,
) -> np.ndarray:
    """
    Result classes:
      -1 outside
       0 ochre
       1 gray
       2 black
    """
    z_size, y_size, x_size = occupied.shape
    out = np.full(occupied.shape, -1, dtype=np.int8)
    out[occupied] = 0

    inside_distance = distance_transform_edt(occupied) * voxel_mm
    shell = occupied & (inside_distance <= shell_depth_mm)

    zz, yy, xx = np.nonzero(shell)

    # Distance to each cardinal side of the bounding grid.
    d_front = yy
    d_back = (y_size - 1) - yy
    d_left = xx
    d_right = (x_size - 1) - xx
    all_d = np.stack([d_front, d_back, d_left, d_right], axis=1)
    nearest = np.argmin(all_d, axis=1)

    sampled = np.zeros(len(xx), dtype=np.int8)

    for i in range(len(xx)):
        z, y, x = zz[i], yy[i], xx[i]
        side = nearest[i]
        if side == 0:
            sampled[i] = max(0, classes["front"][z, x])
        elif side == 1:
            sampled[i] = max(0, classes["back"][z, x])
        elif side == 2:
            sampled[i] = max(0, classes["left"][z, y])
        else:
            sampled[i] = max(0, classes["right"][z, y])

    out[zz, yy, xx] = sampled
    return out


def mesh_binary(mask: np.ndarray, voxel_mm: float) -> trimesh.Trimesh | None:
    if mask.sum() < 8:
        return None

    # pad so marching cubes closes surfaces at boundaries
    padded = np.pad(mask.astype(np.uint8), 1, constant_values=0)
    verts, faces, _, _ = marching_cubes(
        padded,
        level=0.5,
        spacing=(voxel_mm, voxel_mm, voxel_mm),
    )

    # marching_cubes returns z,y,x. Convert to x,y,z.
    verts = verts[:, [2, 1, 0]]
    verts -= voxel_mm

    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
    mesh.remove_unreferenced_vertices()
    trimesh.repair.fix_normals(mesh)
    return mesh


def reconstruct_parts(
    masks: dict[str, np.ndarray],
    classes: dict[str, np.ndarray],
    cfg: Config,
) -> tuple[list[MeshPart], dict]:
    height_px = masks["front"].shape[0]
    voxel_mm = cfg.target_height_mm / height_px

    occupied = build_visual_hull(masks)
    material = build_material_volume(
        occupied,
        classes,
        voxel_mm=voxel_mm,
        shell_depth_mm=cfg.surface_color_depth_mm,
    )

    palette = [
        ("ochre", cfg.ochre_rgb, 0),
        ("gray", cfg.gray_rgb, 1),
        ("black", cfg.black_rgb, 2),
    ]

    parts: list[MeshPart] = []
    for name, rgb, value in palette:
        mesh = mesh_binary(material == value, voxel_mm)
        if mesh is not None:
            parts.append(MeshPart(name=name, rgb=rgb, mesh=mesh))

    meta = {
        "voxel_mm": voxel_mm,
        "volume_shape_zyx": list(occupied.shape),
        "occupied_voxels": int(occupied.sum()),
        "surface_color_depth_mm": cfg.surface_color_depth_mm,
    }
    return parts, meta
```

## 10.3 Optional simplification

After meshing, optionally decimate each part, but never destroy small claws/crest elements simply to reach an aggressive face target.

Pseudo-rule:

```python
if len(mesh.faces) > target_faces:
    try:
        mesh = mesh.simplify_quadric_decimation(target_faces)
    except Exception:
        pass
```

Always retain the original mesh if simplification fails validation.

---

# 11. Stage F — write multipart OBJ + MTL

The `.obj` should contain separate named objects for the three materials so slicers/viewers can distinguish them.

`whproxy/obj_writer.py`

```python
from __future__ import annotations

from pathlib import Path

from .reconstruction import MeshPart


def write_mtl(path: Path, parts: list[MeshPart]):
    lines = []
    for part in parts:
        r, g, b = (c / 255.0 for c in part.rgb)
        lines += [
            f"newmtl {part.name}",
            f"Kd {r:.6f} {g:.6f} {b:.6f}",
            "Ka 0.000000 0.000000 0.000000",
            "Ks 0.050000 0.050000 0.050000",
            "d 1.0",
            "illum 2",
            "",
        ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_obj(path: Path, mtl_path: Path, parts: list[MeshPart]):
    lines = [f"mtllib {mtl_path.name}"]
    vertex_offset = 1

    for part in parts:
        mesh = part.mesh
        lines += ["", f"o {part.name}", f"g {part.name}", f"usemtl {part.name}"]

        for x, y, z in mesh.vertices:
            lines.append(f"v {x:.6f} {y:.6f} {z:.6f}")

        for a, b, c in mesh.faces:
            lines.append(
                f"f {a + vertex_offset} {b + vertex_offset} {c + vertex_offset}"
            )

        vertex_offset += len(mesh.vertices)

    path.write_text("\n".join(lines), encoding="utf-8")
```

This creates one OBJ file with three groups/materials, rather than three unrelated surface overlays.

---

# 12. Stage G — interactive 3D viewer

Use Plotly because it can produce a **self-contained HTML viewer** with no runtime internet dependency.

`whproxy/viewer.py`

```python
from __future__ import annotations

import asyncio
from pathlib import Path

import plotly.graph_objects as go
import plotly.io as pio
from PIL import Image, ImageDraw
from playwright.async_api import async_playwright

from .reconstruction import MeshPart


CAMERAS = {
    "front": dict(eye=dict(x=0.0, y=-2.4, z=0.15), up=dict(x=0, y=0, z=1)),
    "back": dict(eye=dict(x=0.0, y=2.4, z=0.15), up=dict(x=0, y=0, z=1)),
    "left": dict(eye=dict(x=-2.4, y=0.0, z=0.15), up=dict(x=0, y=0, z=1)),
    "right": dict(eye=dict(x=2.4, y=0.0, z=0.15), up=dict(x=0, y=0, z=1)),
    "iso": dict(eye=dict(x=1.7, y=-1.7, z=1.15), up=dict(x=0, y=0, z=1)),
    "top": dict(eye=dict(x=0.0, y=0.0, z=2.7), up=dict(x=0, y=1, z=0)),
}


def make_figure(parts: list[MeshPart], camera=None) -> go.Figure:
    fig = go.Figure()

    for part in parts:
        mesh = part.mesh
        r, g, b = part.rgb
        fig.add_trace(
            go.Mesh3d(
                x=mesh.vertices[:, 0],
                y=mesh.vertices[:, 1],
                z=mesh.vertices[:, 2],
                i=mesh.faces[:, 0],
                j=mesh.faces[:, 1],
                k=mesh.faces[:, 2],
                color=f"rgb({r},{g},{b})",
                flatshading=True,
                name=part.name,
                showscale=False,
                hoverinfo="skip",
            )
        )

    fig.update_layout(
        template="plotly_white",
        margin=dict(l=0, r=0, t=0, b=0),
        showlegend=False,
        scene=dict(
            aspectmode="data",
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            zaxis=dict(visible=False),
            camera=camera or CAMERAS["iso"],
        ),
    )
    return fig


def write_viewer(parts: list[MeshPart], path: Path):
    fig = make_figure(parts, CAMERAS["iso"])
    # include_plotlyjs=True -> fully self-contained local HTML
    pio.write_html(fig, path, include_plotlyjs=True, full_html=True)


async def _capture_html(html_path: Path, png_path: Path):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 900, "height": 900})
        await page.goto(html_path.resolve().as_uri(), wait_until="load")
        await page.wait_for_selector(".plot-container", timeout=15_000)
        await page.locator(".plot-container").screenshot(path=str(png_path))
        await browser.close()


def render_views(parts: list[MeshPart], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {}

    for name, camera in CAMERAS.items():
        html_path = out_dir / f"_{name}.html"
        png_path = out_dir / f"{name}.png"
        pio.write_html(
            make_figure(parts, camera),
            html_path,
            include_plotlyjs=True,
            full_html=True,
        )
        asyncio.run(_capture_html(html_path, png_path))
        html_path.unlink(missing_ok=True)
        result[name] = png_path

    return result


def make_preview_grid(render_paths: dict[str, Path], out_path: Path):
    order = ["front", "left", "back", "right", "iso", "top"]
    cell = 640
    label_h = 42
    canvas = Image.new("RGB", (cell * 3, (cell + label_h) * 2), "white")

    for idx, name in enumerate(order):
        im = Image.open(render_paths[name]).convert("RGB")
        im.thumbnail((cell, cell))
        x0 = (idx % 3) * cell
        y0 = (idx // 3) * (cell + label_h)
        x = x0 + (cell - im.width) // 2
        y = y0 + (cell - im.height) // 2
        canvas.paste(im, (x, y))
        ImageDraw.Draw(canvas).text((x0 + 14, y0 + cell + 8), name.upper(), fill="black")

    canvas.save(out_path, quality=92)
```

### Rendering fallback

If Playwright Chromium is unavailable:

1. still create `viewer.html`;
2. try Plotly/Kaleido;
3. otherwise mark static rendering as failed in the manifest, but do not fail the model generation itself.

---

# 13. Stage H — source-image contact sheet

Before the 3D reconstruction, also create a 2×2 contact sheet of the **actual source cardinal photographs** and another of the **three-color processed views**. This makes debugging orientation mistakes much easier.

Suggested order:

```text
front | left
back  | right
```

Store:

```text
color/source_grid.png
color/color_grid.png
```

Add this reusable helper to `image_pipeline.py`:

```python
def make_contact_sheet(paths: dict[str, Path], out_path: Path, cell: int = 700):
    order = ["front", "left", "back", "right"]
    canvas = Image.new("RGB", (cell * 2, cell * 2), "white")

    for idx, name in enumerate(order):
        im = Image.open(paths[name]).convert("RGB")
        im.thumbnail((cell, cell))
        x0 = (idx % 2) * cell
        y0 = (idx // 2) * cell
        x = x0 + (cell - im.width) // 2
        y = y0 + (cell - im.height) // 2
        canvas.paste(im, (x, y))

    canvas.save(out_path, quality=92)
```

---

# 14. Orchestrator

`whproxy/pipeline.py`

```python
from __future__ import annotations

import json
import re
from pathlib import Path

import cv2
from PIL import Image

from .catalog import query_catalog, select_product, select_spin_set
from .config import Config
from .download import download_cardinals
from .image_pipeline import (
    read_rgb,
    foreground_mask,
    crop_to_mask,
    resize_preserve_height,
    pad_pair_to_same_width,
    quantize_by_rank,
    clean_color_classes,
    save_color_map,
    make_contact_sheet,
)
from .obj_writer import write_mtl, write_obj
from .reconstruction import reconstruct_parts
from .viewer import write_viewer, render_views, make_preview_grid


def slugify(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
    return s or "model"


def _prepare_view(path: Path, cfg: Config):
    rgb = read_rgb(path)
    mask = foreground_mask(rgb, cfg)
    rgb, mask = crop_to_mask(rgb, mask)
    return resize_preserve_height(rgb, mask, cfg.process_height_px)


def build(query: str, output_root: Path, cfg: Config | None = None):
    cfg = cfg or Config()
    out = output_root / slugify(query)
    source_dir = out / "source"
    color_dir = out / "color"
    mesh_dir = out / "mesh"
    viewer_dir = out / "viewer"
    renders_dir = out / "renders"

    for d in (source_dir, color_dir, mesh_dir, viewer_dir, renders_dir):
        d.mkdir(parents=True, exist_ok=True)

    # A. product + 360 set
    hits = query_catalog(query, cfg)
    product = select_product(query, hits)
    spin = select_spin_set(query, product)

    # B. cardinal source images
    source_images, spin_meta = download_cardinals(cfg, spin, source_dir)
    make_contact_sheet(source_images, color_dir / "source_grid.png")

    # C. process each view
    raw = {name: _prepare_view(path, cfg) for name, path in source_images.items()}

    # Pair-wise width normalization.
    f_rgb, f_m, b_rgb, b_m = pad_pair_to_same_width(
        *raw["front"], *raw["back"]
    )
    l_rgb, l_m, r_rgb, r_m = pad_pair_to_same_width(
        *raw["left"], *raw["right"]
    )

    # Align opposite cameras to common world coordinates.
    b_rgb, b_m = cv2.flip(b_rgb, 1), cv2.flip(b_m.astype("uint8"), 1).astype(bool)
    r_rgb, r_m = cv2.flip(r_rgb, 1), cv2.flip(r_m.astype("uint8"), 1).astype(bool)

    views = {
        "front": (f_rgb, f_m),
        "back": (b_rgb, b_m),
        "left": (l_rgb, l_m),
        "right": (r_rgb, r_m),
    }

    masks = {}
    classes = {}
    color_images = {}

    for name, (rgb, mask) in views.items():
        cls = quantize_by_rank(rgb, mask, cfg)
        cls = clean_color_classes(cls, mask)
        path = color_dir / f"{name}.png"
        save_color_map(path, cls, cfg)
        masks[name] = mask
        classes[name] = cls
        color_images[name] = path

    make_contact_sheet(color_images, color_dir / "color_grid.png")

    # D. volumetric proxy + material shell
    parts, mesh_meta = reconstruct_parts(masks, classes, cfg)

    # E. OBJ + MTL
    obj_path = mesh_dir / "model.obj"
    mtl_path = mesh_dir / "model.mtl"
    write_mtl(mtl_path, parts)
    write_obj(obj_path, mtl_path, parts)

    # F. viewer + rendered views
    viewer_path = viewer_dir / "viewer.html"
    write_viewer(parts, viewer_path)
    rendered = render_views(parts, renders_dir)

    preview_path = out / "preview.png"
    make_preview_grid(rendered, preview_path)

    manifest = {
        "query": query,
        "product": {
            "object_id": product.object_id,
            "name": product.name,
            "slug": product.slug,
            "sku": product.sku,
            "score": product.score,
        },
        "spin": spin_meta | {"selected_folder": spin.folder, "score": spin.score},
        "palette": {
            "ochre": cfg.ochre_rgb,
            "gray": cfg.gray_rgb,
            "black": cfg.black_rgb,
        },
        "quantization": {
            "black_fraction": cfg.black_fraction,
            "gray_fraction": cfg.gray_fraction,
            "min_ochre_fraction": cfg.min_ochre_fraction,
        },
        "mesh": mesh_meta,
        "files": {
            "obj": str(obj_path.relative_to(out)),
            "mtl": str(mtl_path.relative_to(out)),
            "viewer": str(viewer_path.relative_to(out)),
            "preview": str(preview_path.relative_to(out)),
        },
    }

    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return out
```

---

# 15. CLI

`whproxy/cli.py`

```python
import argparse
from pathlib import Path

from .config import Config
from .pipeline import build


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build")
    b.add_argument("name")
    b.add_argument("--out", type=Path, default=Path("output"))
    b.add_argument("--height-mm", type=float, default=100.0)
    b.add_argument("--process-height", type=int, default=320)
    b.add_argument("--black", type=float, default=0.05)
    b.add_argument("--gray", type=float, default=0.15)
    b.add_argument("--surface-color-depth-mm", type=float, default=2.5)

    args = p.parse_args()

    if args.command == "build":
        cfg = Config(
            target_height_mm=args.height_mm,
            process_height_px=args.process_height,
            black_fraction=args.black,
            gray_fraction=args.gray,
            surface_color_depth_mm=args.surface_color_depth_mm,
        )
        result = build(args.name, args.out, cfg)
        print(result)


if __name__ == "__main__":
    main()
```

`whproxy/__main__.py`

```python
from .cli import main

main()
```

Usage:

```bash
python -m whproxy build "Norn Emissary"
python -m whproxy build "XV104 Riptide" --height-mm 120
python -m whproxy build "norn emissry" --black 0.05 --gray 0.15
```

---

# 16. Manifest contract

Example structure:

```json
{
  "query": "Norn Emissary",
  "product": {
    "name": "Norn Emissary",
    "sku": "99120106064",
    "score": 100.0
  },
  "spin": {
    "selected_folder": "99120106064_TyrNornEmissary2023OTT1360",
    "rows": 3,
    "angles": 12,
    "cardinal_frames": {
      "front": "01-12.jpg",
      "left": "01-03.jpg",
      "back": "01-06.jpg",
      "right": "01-09.jpg"
    }
  },
  "palette": {
    "ochre": [194, 151, 78],
    "gray": [105, 105, 105],
    "black": [24, 24, 24]
  },
  "quantization": {
    "black_fraction": 0.05,
    "gray_fraction": 0.15,
    "min_ochre_fraction": 0.5
  },
  "mesh": {
    "voxel_mm": 0.3125,
    "surface_color_depth_mm": 2.5
  },
  "files": {
    "obj": "mesh/model.obj",
    "mtl": "mesh/model.mtl",
    "viewer": "viewer/viewer.html",
    "preview": "preview.png"
  }
}
```

The manifest is the source of truth for downstream packing/cubication workflows.

---

# 17. User-facing result

The main output to present to the user is **not** the raw OBJ alone.

Return:

1. `preview.png` — aggregated 3D viewer render;
2. `color/color_grid.png` — 4 processed source views;
3. `mesh/model.obj` + `mesh/model.mtl`;
4. `viewer/viewer.html` — interactive rotation;
5. `manifest.json`.

Recommended response model:

```text
Norn Emissary
- source match: Norn Emissary
- 360: 3 × 12 frames
- OBJ generated: yes
- colors: 80% target ochre / 15% gray / 5% black
- viewer: yes

[preview]
[OBJ]
[interactive viewer]
[manifest]
```

---

# 18. Error handling and fallbacks

## No product match

Return top 5 catalogue candidates with fuzzy scores. Do not guess below the minimum confidence.

## Multiple similar product hits

Require a score gap or explicitly choose based on the 360 folder name.

## Product exists but no `threeSixty`

Fallback order:

```text
1. other image assets in Algolia product record
2. official stock image set
3. optional web image-search provider
4. abort 3D reconstruction if fewer than front+side views are trustworthy
```

Do not silently fabricate missing views.

## Only one useful image

Optional fallback mode: `relief`.

Create a thin vertical standee using the front silhouette with cumulative ochre/gray/black depth layers. This is a fallback only, not the default when four views exist.

## 360 frame numbering differs

Detect actual valid frames by probing URLs. Do not hardcode 3 rows or 12 angles except as an optimization hint.

## White-background segmentation fails

Possible fallback, in order:

1. increase/decrease `white_threshold`;
2. use edge-connected background rather than global white threshold;
3. GrabCut initialized from borders;
4. optional segmentation model as a last resort.

Keep AI segmentation outside the deterministic default path.

---

# 19. Validation rules

A build is successful only if all mandatory checks pass.

## Download validation

```text
4 cardinal source images exist
all are image/*
all > 5 KB
all decode correctly
```

## Color-map validation

For every processed image:

```text
background = white
foreground colors ∈ {ochre, gray, black}
ochre foreground fraction >= configured minimum
black and gray are separate classes
```

The cleaned output must never collapse gray into black.

## Geometry validation

For the assembled multipart model:

```text
at least one mesh part exists
all vertices finite
no zero-area faces after processing
model has non-zero X/Y/Z extents
OBJ references model.mtl
materials are OCHRE / GRAY / BLACK
```

Also log:

```text
bounding box mm
volume estimate
faces per material
connected components per material
```

## Render validation

```text
viewer.html exists
front/left/back/right/iso render files exist
preview.png exists
```

---

# 20. Tests Codex should implement first

## Test 1 — Norn folder resolution

Input:

```text
Norn Emissary
```

Expected selected folder:

```text
99120106064_TyrNornEmissary2023OTT1360
```

The Assimilator folder must not be selected.

## Test 2 — cardinal mapping

For 12 angles:

```python
assert cardinal_filenames(12) == {
    "front": "01-12.jpg",
    "left": "01-03.jpg",
    "back": "01-06.jpg",
    "right": "01-09.jpg",
}
```

## Test 3 — quantile allocation

Given a synthetic grayscale foreground with unique luminance values:

```text
black ≈ 5%
gray ≈ 15%
ochre ≈ 80%
```

## Test 4 — ochre minimum constraint

If configuration asks for too much black+gray, automatically rescale them so:

```text
ochre >= 50%
```

## Test 5 — visual hull dimensions

Synthetic front rectangle + side rectangle should create a rectangular prism with expected extents.

## Test 6 — color shell

The center of a thick synthetic model must remain ochre even if its projected outer pixels are black.

This specifically guards against the earlier failure mode where black/gray behaved as floating or full-depth surfaces.

---

# 21. Performance / quality knobs

Expose these without changing pipeline logic:

```text
process_height_px          default 320
target_height_mm           default 100
black_fraction             default 0.05
gray_fraction              default 0.15
min_ochre_fraction         default 0.50
surface_color_depth_mm     default 2.5
visual_hull_pair_mode      default union; optional intersection
mesh_target_faces_per_part default 25000
```

For quick batch cubication, `process_height_px=192–256` is enough.

For nicer previews, use `320–512`.

---

# 22. Important design choices

## Use source images, not generated replacements

The 3-color image must be derived from the downloaded official views. Generative AI can be used for concept mockups but should not sit inside the production geometry pipeline because it changes silhouette and proportions.

## Prefer conservative geometry

For storage/cubication, slightly overestimating the silhouette is safer than removing limbs or crests.

Therefore default opposite-view merge is `union`.

## Color is a visual/print layer, not the geometry source

Geometry comes from the foreground silhouette masks.

Brightness/detail determines print color, not whether a body region exists.

This prevents dark armor details from punching holes into the model.

## Keep colors volumetric

Gray and black should occupy a shallow volume beneath the visible surface. They should never be zero-thickness planes.

## Preserve provenance

Every model must keep:

```text
query
matched product
fuzzy score
selected 360 folder
source frame names
processing parameters
palette
geometry parameters
```

inside `manifest.json`.

---

# 23. Optional future improvements

Not required for MVP:

### Automatic real-world scale

Search product description / external metadata for base diameter and scale the model from detected base width.

Suggested manifest field:

```json
"scale": {
  "source": "base_diameter",
  "base_mm": 100,
  "confidence": 0.92
}
```

If no trustworthy real dimension exists, keep `target_height_mm` and label scale as normalized.

### Better silhouette reconstruction

Replace simple union visual hull with probabilistic occupancy from all 12 horizontal frames.

This can be substantially better than four-view reconstruction while still using exactly the same official image set.

Concept:

```text
12 silhouettes
→ known 30° camera increments
→ carve voxel volume against every silhouette
→ visual hull from all angular views
```

This should be the preferred V2 because the full 360 sequence is already available after the folder is known.

### All-row reconstruction

If multiple camera heights exist (`01`, `02`, `03`), incorporate them into voxel carving for vertical features and base/top shape.

### 3MF export

For Bambu/Prusa multi-material workflows, `.3mf` is likely more useful than OBJ+MTL because object/material assignment is preserved more reliably.

Keep OBJ as required output but add 3MF later.

### Database/cache

Use SQLite:

```text
query
product objectID
product name
spin folder
frame count
local cache path
last validated
```

Then repeated models cost essentially no network traffic.

---

# 24. Recommended V2: use all 12 angles instead of only 4

The four-cardinal pipeline is the minimum implementation because it is easy to validate and visualize.

However, once `threeSixty/<folder>` is known, all 12 horizontal images can be downloaded at very low additional complexity.

For a genuinely better 3D proxy, Codex should structure the code so `reconstruction.py` can later receive:

```python
views = {
    0: image_01_12,
    30: image_01_01,
    60: image_01_02,
    ...
    330: image_01_11,
}
```

and perform voxel carving from each camera direction.

Do not entangle the reconstruction engine with the fixed `front/left/back/right` API internally. The four cardinal names are primarily for user-facing preview and initial MVP.

---

# 25. Definition of done

Codex should consider the task finished when this works from a clean environment:

```bash
python -m pip install -e .
playwright install chromium
python -m whproxy build "Norn Emissary" --out output
```

and generates, without manual intervention:

```text
output/norn_emissary/manifest.json
output/norn_emissary/source/front.jpg
output/norn_emissary/source/left.jpg
output/norn_emissary/source/back.jpg
output/norn_emissary/source/right.jpg
output/norn_emissary/color/front.png
output/norn_emissary/color/left.png
output/norn_emissary/color/back.png
output/norn_emissary/color/right.png
output/norn_emissary/mesh/model.obj
output/norn_emissary/mesh/model.mtl
output/norn_emissary/viewer/viewer.html
output/norn_emissary/renders/front.png
output/norn_emissary/renders/left.png
output/norn_emissary/renders/back.png
output/norn_emissary/renders/right.png
output/norn_emissary/renders/iso.png
output/norn_emissary/preview.png
```

The same command with:

```bash
python -m whproxy build "XV104 Riptide"
```

must resolve the Riptide 360 set without any unit-specific hardcoded URL.

---

# 26. Codex execution priority

Implement in this order:

```text
1. Config + data models
2. Algolia search + fuzzy match
3. threeSixty folder selection
4. frame detection + cardinal downloads
5. foreground extraction
6. percentile/rank 3-color conversion
7. view alignment
8. visual hull
9. volumetric color shell
10. multipart OBJ/MTL
11. viewer.html
12. static viewer renders
13. preview grid
14. manifest
15. tests
16. caching
```

Do not spend time on direct Warhammer page scraping unless the catalogue path stops working.

The key invariant throughout the project is:

> **The source photographs determine the silhouette; grayscale rank determines the print color; the generated colors must become real 3D volumes attached to a single coherent body.**

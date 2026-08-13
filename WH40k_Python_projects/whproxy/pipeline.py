from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

from .catalog import build_hits, query_catalog, select_product, select_spin_set
from .config import Config
from .models import ProductHit, SpinSet
from .download import download_cardinals
from .image_pipeline import (
    align_opposite_views,
    class_fractions,
    clean_color_classes,
    crop_to_mask,
    foreground_mask,
    make_contact_sheet,
    pad_pair_to_same_width,
    quantize_by_rank,
    read_rgb,
    resize_preserve_height,
    save_color_map,
)
from .obj_writer import write_mtl, write_obj
from .reconstruction import reconstruct_parts
from .viewer import make_preview_grid, render_views, write_viewer


def slugify(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
    return s or "model"


def _prepare_view(path: Path, cfg: Config):
    rgb = read_rgb(path)
    mask = foreground_mask(rgb, cfg)
    rgb, mask = crop_to_mask(rgb, mask)
    return resize_preserve_height(rgb, mask, cfg.process_height_px)


def _resolve_product(query: str, cfg: Config):
    if cfg.source_provider == "local":
        # The frames are already chosen, so there is nothing to search for.
        product = ProductHit(
            object_id="local",
            name=query,
            slug=slugify(query),
            sku=None,
            images=[],
            score=100.0,
        )
        return product, SpinSet(folder=Path(cfg.frames_dir).name or "local", score=100.0), []

    if cfg.source_provider == "offline":
        from .offline import load_catalog_records

        hits = build_hits(query, load_catalog_records())
    else:
        hits = query_catalog(query, cfg)
    product = select_product(query, hits)
    return product, select_spin_set(query, product), hits


def _fetch_cardinals(cfg: Config, spin, source_dir: Path):
    if cfg.source_provider == "local":
        from .local_frames import load_cardinals_local

        return load_cardinals_local(cfg, spin, source_dir)

    if cfg.source_provider == "offline":
        from .offline import download_cardinals_offline

        return download_cardinals_offline(cfg, spin, source_dir)
    return download_cardinals(cfg, spin, source_dir)


def build(query: str, output_root: Path, cfg: Config | None = None) -> Path:
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
    product, spin, hits = _resolve_product(query, cfg)

    # B. cardinal source images
    source_images, spin_meta = _fetch_cardinals(cfg, spin, source_dir)
    make_contact_sheet(source_images, color_dir / "source_grid.png")

    # C. process each view
    raw = {name: _prepare_view(path, cfg) for name, path in source_images.items()}

    # Pair-wise width normalization.
    f_rgb, f_m, b_rgb, b_m = pad_pair_to_same_width(*raw["front"], *raw["back"])
    l_rgb, l_m, r_rgb, r_m = pad_pair_to_same_width(*raw["left"], *raw["right"])

    views = align_opposite_views(
        {
            "front": (f_rgb, f_m),
            "back": (b_rgb, b_m),
            "left": (l_rgb, l_m),
            "right": (r_rgb, r_m),
        }
    )

    masks: dict[str, np.ndarray] = {}
    classes: dict[str, np.ndarray] = {}
    color_images: dict[str, Path] = {}
    fractions: dict[str, dict] = {}

    for name, (rgb, mask) in views.items():
        cls = quantize_by_rank(rgb, mask, cfg)
        cls = clean_color_classes(cls, mask)
        path = color_dir / f"{name}.png"
        save_color_map(path, cls, cfg)
        masks[name] = mask
        classes[name] = cls
        color_images[name] = path
        fractions[name] = {k: round(v, 4) for k, v in class_fractions(cls).items()}

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
    rendered, render_status = render_views(parts, renders_dir)

    preview_path = out / "preview.png"
    if rendered:
        synthetic = spin_meta.get("provider") == "offline-synthetic"
        title = f"{product.name} — 3-colour printable proxy"
        if synthetic:
            title += "   [SYNTHETIC SOURCE FRAMES]"
        make_preview_grid(rendered, preview_path, title=title)
    else:
        preview_path = None

    manifest = {
        "query": query,
        "product": {
            "object_id": product.object_id,
            "name": product.name,
            "slug": product.slug,
            "sku": product.sku,
            "score": round(product.score, 2),
        },
        "runner_up_products": [
            {"name": h.name, "score": round(h.score, 2)} for h in hits[1:4]
        ],
        "spin": spin_meta | {"selected_folder": spin.folder, "score": round(spin.score, 2)},
        "palette": {
            "ochre": list(cfg.ochre_rgb),
            "gray": list(cfg.gray_rgb),
            "black": list(cfg.black_rgb),
        },
        "quantization": {
            "black_fraction": cfg.black_fraction,
            "gray_fraction": cfg.gray_fraction,
            "min_ochre_fraction": cfg.min_ochre_fraction,
            "measured": fractions,
        },
        "processing": {
            "process_height_px": cfg.process_height_px,
            "target_height_mm": cfg.target_height_mm,
            "white_threshold": cfg.white_threshold,
            "min_component_px": cfg.min_component_px,
        },
        "mesh": mesh_meta,
        "render": render_status,
        "files": {
            "obj": str(obj_path.relative_to(out)),
            "mtl": str(mtl_path.relative_to(out)),
            "viewer": str(viewer_path.relative_to(out)),
            "source_grid": "color/source_grid.png",
            "color_grid": "color/color_grid.png",
            "preview": str(preview_path.relative_to(out)) if preview_path else None,
        },
    }

    validate(out, manifest, cfg)

    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return out


def validate(out: Path, manifest: dict, cfg: Config) -> None:
    """Mandatory checks from section 19 of the brief."""
    problems: list[str] = []

    for view in ("front", "left", "back", "right"):
        src = out / "source" / f"{view}.jpg"
        if not src.exists() or src.stat().st_size < 5_000:
            problems.append(f"missing/short source image: {view}")
        if not (out / "color" / f"{view}.png").exists():
            problems.append(f"missing color map: {view}")

        frac = manifest["quantization"]["measured"].get(view, {})
        if frac.get("ochre", 0) < cfg.min_ochre_fraction:
            problems.append(
                f"{view}: ochre {frac.get('ochre')} below minimum {cfg.min_ochre_fraction}"
            )
        if frac.get("gray", 0) <= 0 or frac.get("black", 0) <= 0:
            problems.append(f"{view}: gray/black collapsed into a single class")

    if not manifest["mesh"]["parts"]:
        problems.append("no mesh parts")
    if any(s <= 0 for s in manifest["mesh"]["bbox_mm"]["size"]):
        problems.append("degenerate bounding box")

    obj_text = (out / "mesh" / "model.obj").read_text(encoding="utf-8")
    if "mtllib model.mtl" not in obj_text:
        problems.append("OBJ does not reference model.mtl")
    for name in manifest["mesh"]["parts"]:
        if f"usemtl {name}" not in obj_text:
            problems.append(f"OBJ missing material group: {name}")

    if not (out / "viewer" / "viewer.html").exists():
        problems.append("viewer.html missing")

    if problems:
        raise RuntimeError("Validation failed:\n  - " + "\n  - ".join(problems))

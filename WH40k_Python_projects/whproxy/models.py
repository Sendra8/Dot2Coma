from __future__ import annotations

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

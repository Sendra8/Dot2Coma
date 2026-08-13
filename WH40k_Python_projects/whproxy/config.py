from __future__ import annotations

import os
from dataclasses import dataclass


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
    # Overridable so the search host can be redirected (or pointed at a mock).
    algolia_base: str = os.getenv("GW_ALGOLIA_BASE", "")

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
    visual_hull_pair_mode: str = "union"  # "union" | "intersection"

    # palette
    ochre_rgb: tuple[int, int, int] = (194, 151, 78)
    gray_rgb: tuple[int, int, int] = (105, 105, 105)
    black_rgb: tuple[int, int, int] = (24, 24, 24)

    # provider:
    #   "network" hits Algolia + the GW CDN (the real path)
    #   "local"   reads four cardinal images from `frames_dir`
    #   "offline" renders synthetic stand-in frames (CI / blocked egress only)
    source_provider: str = os.getenv("WHPROXY_SOURCE", "network")
    frames_dir: str = os.getenv("WHPROXY_FRAMES_DIR", "")
    cache_dir: str = os.getenv("WHPROXY_CACHE", ".cache")

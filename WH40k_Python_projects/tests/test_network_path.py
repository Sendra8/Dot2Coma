"""Exercise the real automatic-download path against a local mock host.

These tests import nothing from the offline provider's plumbing: they call
`query_catalog`, `detect_grid`, `download_cardinals` and `build()` exactly as a
run against warhammer.com would, with only the two base URLs redirected.
"""

from __future__ import annotations

import json

from mock_gw import MockGW

from whproxy.catalog import query_catalog, select_product, select_spin_set
from whproxy.config import Config
from whproxy.download import detect_grid, download_cardinals
from whproxy.pipeline import build


def _cfg(mock: MockGW, tmp_path, **kwargs) -> Config:
    return Config(
        algolia_base=mock.base_url,
        cdn_base=mock.base_url,
        cache_dir=str(tmp_path / "cache"),
        **kwargs,
    )


def test_catalog_query_hits_the_search_endpoint(tmp_path):
    with MockGW() as mock:
        cfg = _cfg(mock, tmp_path)
        hits = query_catalog("Norn Emissary", cfg)

        product = select_product("Norn Emissary", hits)
        assert product.name == "Norn Emissary"

        spin = select_spin_set("Norn Emissary", product)
        assert spin.folder == "99120106064_TyrNornEmissary2023OTT1360"

        posts = [p for m, p in mock.requests if m == "POST"]
        assert posts == [f"/1/indexes/{cfg.algolia_index}/query"]


def test_grid_detection_finds_three_by_twelve(tmp_path):
    with MockGW() as mock:
        cfg = _cfg(mock, tmp_path)
        spin = select_spin_set(
            "Norn Emissary",
            select_product("Norn Emissary", query_catalog("Norn Emissary", cfg)),
        )

        assert detect_grid(cfg, spin) == (3, 12)


def test_grid_detection_does_not_download_payloads(tmp_path):
    """Counting frames must use HEAD, not pull a dozen full JPEGs."""
    with MockGW() as mock:
        cfg = _cfg(mock, tmp_path)
        spin = select_spin_set(
            "Norn Emissary",
            select_product("Norn Emissary", query_catalog("Norn Emissary", cfg)),
        )
        detect_grid(cfg, spin)

        methods = [m for m, _ in mock.requests if m in ("GET", "HEAD")]
        assert methods and all(m == "HEAD" for m in methods)


def test_cardinal_download_writes_four_validated_images(tmp_path):
    with MockGW() as mock:
        cfg = _cfg(mock, tmp_path)
        spin = select_spin_set(
            "Norn Emissary",
            select_product("Norn Emissary", query_catalog("Norn Emissary", cfg)),
        )

        paths, meta = download_cardinals(cfg, spin, tmp_path / "source")

        assert set(paths) == {"front", "left", "back", "right"}
        assert all(p.exists() and p.stat().st_size > 5_000 for p in paths.values())
        assert meta["provider"] == "network"
        assert meta["cardinal_frames"]["front"] == "01-12.jpg"
        assert meta["angles"] == 12


def test_second_run_serves_cardinals_from_cache(tmp_path):
    with MockGW() as mock:
        cfg = _cfg(mock, tmp_path)
        spin = select_spin_set(
            "Norn Emissary",
            select_product("Norn Emissary", query_catalog("Norn Emissary", cfg)),
        )

        download_cardinals(cfg, spin, tmp_path / "a")
        first = len([m for m, _ in mock.requests if m == "GET"])

        download_cardinals(cfg, spin, tmp_path / "b")
        second = len([m for m, _ in mock.requests if m == "GET"])

        assert first == 4          # one GET per cardinal on a cold cache
        assert second == first     # warm cache adds none


def test_full_build_over_the_network_path(tmp_path):
    """End to end: name in, manifest + OBJ + viewer out, nothing local-only."""
    with MockGW() as mock:
        cfg = _cfg(mock, tmp_path, process_height_px=72, mesh_target_faces_per_part=4_000)
        out = build("Norn Emissary", tmp_path / "output", cfg)

        manifest = json.loads((out / "manifest.json").read_text())
        assert manifest["spin"]["provider"] == "network"
        assert manifest["spin"]["selected_folder"] == "99120106064_TyrNornEmissary2023OTT1360"
        assert set(manifest["mesh"]["parts"]) == {"ochre", "gray", "black"}

        for rel in ("source/front.jpg", "color/front.png", "mesh/model.obj",
                    "mesh/model.mtl", "viewer/viewer.html"):
            assert (out / rel).exists(), rel

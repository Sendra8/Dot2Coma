import numpy as np

from whproxy.config import Config
from whproxy.reconstruction import build_material_volume, build_visual_hull, reconstruct_parts


def _rect_masks(height=40, width=20, depth=12):
    front = np.zeros((height, width), dtype=bool)
    front[5:35, 4:16] = True          # 30 tall x 12 wide
    side = np.zeros((height, depth), dtype=bool)
    side[5:35, 3:9] = True            # 30 tall x 6 deep
    return {"front": front, "back": front.copy(), "left": side, "right": side.copy()}


def test_visual_hull_extents():
    """Test 5 from the brief: front rect + side rect -> rectangular prism."""
    vol = build_visual_hull(_rect_masks())
    zz, yy, xx = np.nonzero(vol)

    assert (zz.min(), zz.max()) == (5, 34)
    assert (xx.min(), xx.max()) == (4, 15)
    assert (yy.min(), yy.max()) == (3, 8)
    assert vol.sum() == 30 * 12 * 6


def test_union_recovers_appendage_lost_in_one_view():
    masks = _rect_masks()
    masks["front"] = masks["front"].copy()
    masks["back"][10:14, 16:19] = True  # a crest only the back camera saw
    vol_union = build_visual_hull(masks, "union")
    vol_inter = build_visual_hull(masks, "intersection")
    assert vol_union.sum() > vol_inter.sum()


def test_thick_core_stays_ochre():
    """Test 6 from the brief: colour is a shell, never a full-depth surface."""
    size = 40
    occupied = np.zeros((size, size, size), dtype=bool)
    occupied[5:35, 5:35, 5:35] = True

    # every projected pixel is black
    classes = {name: np.full((size, size), 2, dtype=np.int8) for name in
               ("front", "back", "left", "right")}

    material = build_material_volume(occupied, classes, voxel_mm=1.0, shell_depth_mm=2.5)

    assert material[20, 20, 20] == 0          # core is ochre
    assert material[20, 6, 20] == 2           # outer shell took the black class
    assert (material == 0).sum() > 0
    assert (material[~occupied] == -1).all()


def test_reconstruct_parts_produces_three_materials():
    masks = _rect_masks(height=60, width=30, depth=20)
    classes = {}
    for name, mask in masks.items():
        cls = np.full(mask.shape, -1, dtype=np.int8)
        cls[mask] = 0
        h = mask.shape[0]
        cls[(np.arange(h) < h // 3)[:, None] & mask] = 1
        cls[(np.arange(h) < h // 6)[:, None] & mask] = 2
        classes[name] = cls

    parts, meta = reconstruct_parts(masks, classes, Config(process_height_px=60))
    names = {p.name for p in parts}

    assert names == {"ochre", "gray", "black"}
    assert all(np.isfinite(p.mesh.vertices).all() for p in parts)
    assert all(s > 0 for s in meta["bbox_mm"]["size"])
    assert meta["voxel_mm"] > 0

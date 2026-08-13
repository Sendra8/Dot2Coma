from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import trimesh
from scipy.ndimage import binary_closing, binary_fill_holes, distance_transform_edt
from skimage.measure import marching_cubes

from .config import Config


@dataclass
class MeshPart:
    name: str
    rgb: tuple[int, int, int]
    mesh: trimesh.Trimesh


def build_visual_hull(masks: dict[str, np.ndarray], pair_mode: str = "union") -> np.ndarray:
    front = masks["front"]
    back = masks["back"]       # already mirrored/aligned
    left = masks["left"]
    right = masks["right"]     # already mirrored/aligned

    if pair_mode == "intersection":
        fb = front & back
        lr = left & right
    else:
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
    _, y_size, x_size = occupied.shape
    out = np.full(occupied.shape, -1, dtype=np.int8)
    out[occupied] = 0

    inside_distance = distance_transform_edt(occupied) * voxel_mm
    shell = occupied & (inside_distance <= shell_depth_mm)

    zz, yy, xx = np.nonzero(shell)
    if not len(zz):
        return out

    # Distance to each cardinal side of the bounding grid.
    d_front = yy
    d_back = (y_size - 1) - yy
    d_left = xx
    d_right = (x_size - 1) - xx
    nearest = np.argmin(np.stack([d_front, d_back, d_left, d_right], axis=1), axis=1)

    sampled = np.zeros(len(zz), dtype=np.int8)
    # Vectorised per side: each shell voxel takes its color from the cardinal
    # view it is closest to, projected along that view's axis.
    for side, (view, coord) in enumerate(
        (("front", xx), ("back", xx), ("left", yy), ("right", yy))
    ):
        sel = nearest == side
        if not sel.any():
            continue
        sampled[sel] = np.maximum(classes[view][zz[sel], coord[sel]], 0)

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


def simplify(mesh: trimesh.Trimesh, target_faces: int) -> trimesh.Trimesh:
    """Decimate only if it succeeds and keeps the mesh usable."""
    if len(mesh.faces) <= target_faces:
        return mesh
    try:
        reduced = mesh.simplify_quadric_decimation(face_count=target_faces)
    except Exception:
        return mesh
    if reduced is None or len(reduced.faces) < 8 or not np.isfinite(reduced.vertices).all():
        return mesh
    return reduced


def reconstruct_parts(
    masks: dict[str, np.ndarray],
    classes: dict[str, np.ndarray],
    cfg: Config,
) -> tuple[list[MeshPart], dict]:
    height_px = masks["front"].shape[0]
    voxel_mm = cfg.target_height_mm / height_px

    # Image row 0 is the top of the miniature, but voxel z=0 is the ground, so
    # flip vertically before meshing or the model comes out upside down.
    masks = {k: np.ascontiguousarray(v[::-1]) for k, v in masks.items()}
    classes = {k: np.ascontiguousarray(v[::-1]) for k, v in classes.items()}

    occupied = build_visual_hull(masks, cfg.visual_hull_pair_mode)
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
    stats: dict[str, dict] = {}
    for name, rgb, value in palette:
        volume_mask = material == value
        mesh = mesh_binary(volume_mask, voxel_mm)
        if mesh is None:
            continue
        mesh = simplify(mesh, cfg.mesh_target_faces_per_part)
        parts.append(MeshPart(name=name, rgb=rgb, mesh=mesh))
        stats[name] = {
            "voxels": int(volume_mask.sum()),
            "faces": int(len(mesh.faces)),
            "vertices": int(len(mesh.vertices)),
            "components": int(len(mesh.split(only_watertight=False))),
        }

    if not parts:
        raise RuntimeError("Reconstruction produced no mesh parts")

    bounds = np.vstack([p.mesh.bounds for p in parts])
    bbox_min = bounds.min(axis=0).tolist()
    bbox_max = bounds.max(axis=0).tolist()

    meta = {
        "voxel_mm": voxel_mm,
        "volume_shape_zyx": list(occupied.shape),
        "occupied_voxels": int(occupied.sum()),
        "occupied_volume_mm3": float(occupied.sum() * voxel_mm ** 3),
        "surface_color_depth_mm": cfg.surface_color_depth_mm,
        "visual_hull_pair_mode": cfg.visual_hull_pair_mode,
        "bbox_mm": {
            "min": [round(v, 3) for v in bbox_min],
            "max": [round(v, 3) for v in bbox_max],
            "size": [round(b - a, 3) for a, b in zip(bbox_min, bbox_max)],
        },
        "parts": stats,
    }
    return parts, meta

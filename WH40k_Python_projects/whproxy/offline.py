"""Offline source provider.

The production path pulls the official Games Workshop 360 frames from the GW
CDN. When that host is unreachable (sandboxed CI, blocked egress, GW rotating
the catalogue credentials) the whole pipeline downstream of the download stage
still needs something to chew on.

This module renders **synthetic** turntable frames from a procedural voxel
stand-in for the unit. They are deliberately *not* passed off as official
photography: every manifest produced this way carries
`"provider": "offline-synthetic"`, and the preview grid is labelled as a
synthetic proxy.

The frames are geometrically honest turntable views — one voxel model rendered
from four true 90 degree rotations — so silhouette alignment, the visual hull
and the colour shell are all exercised exactly as they would be on real photos.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from .config import Config
from .download import cardinal_filenames
from .models import SpinSet

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "assets" / "offline"
SHAPE = (170, 128, 128)  # z, y, x


# --------------------------------------------------------------------------
# catalogue fixture
# --------------------------------------------------------------------------

@lru_cache(maxsize=1)
def load_catalog_records() -> list[dict]:
    return json.loads((FIXTURE_DIR / "catalog.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# voxel primitives
# --------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _coords():
    z, y, x = np.indices(SHAPE, dtype=np.float32)
    return z, y, x


class VoxelModel:
    def __init__(self):
        self.albedo = np.zeros(SHAPE, dtype=np.uint8)

    def _put(self, mask: np.ndarray, albedo: int):
        self.albedo[mask] = albedo

    def ellipsoid(self, c, r, albedo):
        z, y, x = _coords()
        m = (
            ((z - c[0]) / r[0]) ** 2
            + ((y - c[1]) / r[1]) ** 2
            + ((x - c[2]) / r[2]) ** 2
        ) <= 1.0
        self._put(m, albedo)

    def box(self, c, half, albedo):
        z, y, x = _coords()
        m = (
            (np.abs(z - c[0]) <= half[0])
            & (np.abs(y - c[1]) <= half[1])
            & (np.abs(x - c[2]) <= half[2])
        )
        self._put(m, albedo)

    def cylinder_z(self, z0, z1, c_yx, radius, albedo):
        z, y, x = _coords()
        m = (
            (z >= z0) & (z <= z1)
            & (((y - c_yx[0]) ** 2 + (x - c_yx[1]) ** 2) <= radius ** 2)
        )
        self._put(m, albedo)

    def capsule(self, p0, p1, radius, albedo):
        z, y, x = _coords()
        p0 = np.asarray(p0, dtype=np.float32)
        p1 = np.asarray(p1, dtype=np.float32)
        d = p1 - p0
        denom = float(d @ d) or 1.0
        t = ((z - p0[0]) * d[0] + (y - p0[1]) * d[1] + (x - p0[2]) * d[2]) / denom
        t = np.clip(t, 0.0, 1.0)
        dist2 = (
            (z - (p0[0] + t * d[0])) ** 2
            + (y - (p0[1] + t * d[1])) ** 2
            + (x - (p0[2] + t * d[2])) ** 2
        )
        self._put(dist2 <= radius ** 2, albedo)

def _mx(v: float) -> float:
    return (SHAPE[2] - 1) - v


# --------------------------------------------------------------------------
# archetypes
# --------------------------------------------------------------------------

BODY = 185
PLATE = 150
DARK = 70
TRIM = 110
BASE = 135


def _biped_organic() -> VoxelModel:
    """Tall organic bio-titan: Norn Emissary / Assimilator family."""
    m = VoxelModel()
    m.cylinder_z(0, 6, (64, 64), 40, BASE)
    m.ellipsoid((8, 70, 48), (5, 12, 9), BASE)   # rubble

    for sx in (46, _mx(46)):
        m.capsule((6, 66, sx), (52, 74, sx + (4 if sx < 64 else -4)), 12, BODY)
        m.capsule((52, 74, sx), (78, 62, sx + (6 if sx < 64 else -6)), 10, PLATE)
        m.capsule((6, 66, sx), (6, 50, sx), 7, DARK)  # claws

    m.ellipsoid((88, 64, 64), (22, 18, 21), BODY)      # lower thorax
    m.ellipsoid((112, 62, 64), (20, 16, 18), BODY)     # upper thorax
    m.ellipsoid((116, 74, 64), (26, 11, 27), PLATE)    # carapace
    for dx in (-18, -6, 6, 18):
        m.capsule((134, 78, 64 + dx), (146, 90, 64 + dx * 1.3), 3, DARK)  # crest spines

    m.ellipsoid((114, 46, 64), (10, 13, 9), BODY)      # head
    m.ellipsoid((110, 36, 64), (5, 5, 6), DARK)        # maw

    for sx in (46, _mx(46)):
        outward = -1 if sx < 64 else 1
        shoulder = (118, 58, sx)
        elbow = (96, 34, sx + 12 * outward)
        tip = (58, 24, sx + 20 * outward)
        m.capsule(shoulder, elbow, 8, PLATE)   # upper scything limb
        m.capsule(elbow, tip, 5, TRIM)         # blade
        m.capsule(tip, (48, 30, sx + 22 * outward), 3, DARK)  # tip

    for sx in (56, _mx(56)):
        m.capsule((100, 50, sx), (84, 30, sx + (-6 if sx < 64 else 6)), 5, TRIM)  # feeder arms

    m.capsule((86, 78, 64), (44, 112, 64), 9, BODY)    # tail
    m.capsule((44, 112, 64), (30, 124, 64), 5, DARK)
    return m


def _battlesuit() -> VoxelModel:
    """Heavy reverse-joint battlesuit: XV104 Riptide family."""
    m = VoxelModel()
    m.cylinder_z(0, 5, (64, 64), 36, BASE)

    for sx in (48, _mx(48)):
        m.capsule((5, 74, sx), (42, 52, sx), 10, PLATE)   # shin
        m.capsule((42, 52, sx), (74, 74, sx), 12, BODY)   # thigh
        m.box((6, 66, sx), (5, 14, 9), DARK)              # foot

    m.box((96, 64, 64), (18, 14, 22), BODY)               # torso
    m.box((92, 48, 64), (9, 3, 11), DARK)                 # chest vents
    m.box((104, 84, 64), (16, 9, 19), PLATE)              # jetpack
    m.box((104, 93, 64), (10, 3, 13), DARK)               # thrusters

    for sx in (38, _mx(38)):
        m.ellipsoid((116, 64, sx), (13, 15, 14), PLATE)   # shoulder pods

    m.ellipsoid((116, 55, 64), (6, 7, 7), TRIM)           # sensor head
    m.ellipsoid((104, 62, 20), (22, 6, 17), PLATE)        # shield generator
    m.ellipsoid((104, 62, 20), (11, 8, 8), DARK)
    m.capsule((110, 66, 108), (110, 26, 108), 8, BODY)    # burst cannon
    m.capsule((110, 30, 108), (110, 22, 108), 5, DARK)
    return m


def _tracked_hull() -> VoxelModel:
    """Wide tracked super-heavy: Hekaton Land Fortress family."""
    m = VoxelModel()
    for sx in (20, _mx(20)):
        m.box((18, 64, sx), (15, 30, 11), DARK)           # tracks
        m.box((18, 64, sx), (7, 32, 13), TRIM)            # track guards

    m.box((30, 64, 64), (14, 27, 34), BODY)               # hull
    m.ellipsoid((28, 36, 64), (12, 10, 32), PLATE)        # glacis
    m.box((52, 66, 62), (10, 20, 28), BODY)               # superstructure
    m.box((52, 46, 62), (5, 2, 20), DARK)                 # vision block

    m.cylinder_z(62, 80, (60, 62), 17, PLATE)             # turret
    m.ellipsoid((80, 60, 62), (5, 15, 16), BODY)
    m.capsule((72, 46, 62), (72, 6, 62), 5, TRIM)         # main gun
    m.capsule((72, 10, 62), (72, 4, 62), 7, DARK)         # muzzle brake

    for sx in (34, _mx(34)):
        m.capsule((44, 52, sx), (44, 30, sx), 3, DARK)    # sponsons
    m.capsule((66, 88, 50), (86, 96, 50), 5, DARK)        # exhaust
    m.capsule((66, 88, 74), (86, 96, 74), 5, DARK)
    m.box((44, 84, 64), (6, 6, 24), TRIM)                 # rear plate
    return m


ARCHETYPES = {
    "biped_organic": _biped_organic,
    "battlesuit": _battlesuit,
    "tracked_hull": _tracked_hull,
}


def archetype_for(folder: str) -> str:
    key = folder.lower()
    for token, name in (
        ("norn", "biped_organic"),
        ("tyr", "biped_organic"),
        ("riptide", "battlesuit"),
        ("xv1", "battlesuit"),
        ("hekaton", "tracked_hull"),
        ("votann", "tracked_hull"),
    ):
        if token in key:
            return name
    return "battlesuit"


@lru_cache(maxsize=8)
def _model_for(folder: str) -> np.ndarray:
    return ARCHETYPES[archetype_for(folder)]().albedo


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def _render_orthographic(albedo: np.ndarray, seed: int, out_height: int = 1000) -> Image.Image:
    """Camera at -Y looking towards +Y, orthographic, white studio background."""
    occupied = albedo > 0
    hit = occupied.any(axis=1)                       # [z, x]
    depth = np.argmax(occupied, axis=1).astype(np.float32)  # first surface along y

    zz, xx = np.nonzero(hit)
    surf = albedo[zz, depth[zz, xx].astype(int), xx].astype(np.float32)
    surface = np.zeros(hit.shape, dtype=np.float32)
    surface[zz, xx] = surf

    # Depth-map normals -> lambert shading with a soft key light up-front-left.
    d_filled = np.where(hit, depth, depth[hit].max() if hit.any() else 0.0)
    gz, gx = np.gradient(d_filled)
    # Camera sits at -Y, so a flat facing surface must have normal -Y.
    normal = np.stack([-gz, -np.ones_like(gz), -gx], axis=-1)
    normal /= np.linalg.norm(normal, axis=-1, keepdims=True)

    light = np.array([0.45, -0.80, -0.40], dtype=np.float32)
    light /= np.linalg.norm(light)
    lambert = np.clip(normal @ light, 0.0, 1.0)

    # Cheap ambient occlusion: recessed pixels sit further back than neighbours.
    from scipy.ndimage import uniform_filter

    local = uniform_filter(d_filled, size=9)
    ao = np.clip(1.0 - (d_filled - local) / 14.0, 0.55, 1.15)

    rng = np.random.default_rng(seed)
    grain = rng.normal(0.0, 0.02, size=hit.shape).astype(np.float32)

    value = surface * (0.42 + 0.62 * lambert) * ao * (1.0 + grain)
    value = np.clip(value, 0, 252)

    img = np.full(hit.shape, 255.0, dtype=np.float32)
    img[hit] = value[hit]
    img = np.flipud(img)  # z grows upwards, image rows grow downwards

    frame = Image.fromarray(img.astype(np.uint8)).convert("RGB")
    scale = out_height / frame.height
    frame = frame.resize(
        (max(1, round(frame.width * scale)), out_height), Image.LANCZOS
    )
    # Studio framing: pad to a square white canvas like the GW turntables.
    canvas = Image.new("RGB", (out_height, out_height), (255, 255, 255))
    canvas.paste(frame, ((out_height - frame.width) // 2, 0))
    return canvas


def render_frame(folder: str, angle_index: int, angles: int, out_height: int = 1000) -> Image.Image:
    """Render one turntable frame. `angle_index` is 1-based like `01-XX.jpg`."""
    albedo = _model_for(folder)
    turns = round((angle_index % angles) / angles * 4) % 4
    rotated = np.rot90(albedo, k=turns, axes=(1, 2)).copy()
    return _render_orthographic(rotated, seed=turns + 1, out_height=out_height)


def download_cardinals_offline(
    cfg: Config,
    spin: SpinSet,
    out_dir: Path,
    angles: int = 12,
    rows: int = 3,
) -> tuple[dict[str, Path], dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    names = cardinal_filenames(angles)

    result: dict[str, Path] = {}
    for view, filename in names.items():
        index = int(filename.split("-")[1].split(".")[0])
        img = render_frame(spin.folder, index, angles)
        path = out_dir / f"{view}.jpg"
        img.save(path, quality=94)
        result[view] = path

    metadata = {
        "folder": spin.folder,
        "rows": rows,
        "angles": angles,
        "cardinal_frames": names,
        "provider": "offline-synthetic",
        "archetype": archetype_for(spin.folder),
        "warning": (
            "Frames are procedurally generated stand-ins, NOT official Games "
            "Workshop photography. Re-run with WHPROXY_SOURCE=network for real "
            "source images."
        ),
    }
    return result, metadata

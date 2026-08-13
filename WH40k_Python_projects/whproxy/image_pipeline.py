from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from .config import Config

PALETTE_NAMES = {0: "ochre", 1: "gray", 2: "black"}


def read_rgb(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"))


def edge_connected_white_background(rgb: np.ndarray, white_threshold: int) -> np.ndarray:
    """Return background mask: near-white pixels connected to an image edge."""
    near_white = np.all(rgb >= white_threshold, axis=2).astype(np.uint8)
    _, labels = cv2.connectedComponents(near_white, connectivity=8)

    touching = set(labels[0, :]) | set(labels[-1, :]) | set(labels[:, 0]) | set(labels[:, -1])
    touching.discard(0)  # label 0 is the non-white region, never background by itself
    return np.isin(labels, list(touching))


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


def align_opposite_views(views: dict[str, tuple[np.ndarray, np.ndarray]]):
    """Mirror `back` and `right` so all four views share one world frame."""
    back_rgb, back_mask = views["back"]
    right_rgb, right_mask = views["right"]

    views["back"] = (np.ascontiguousarray(np.fliplr(back_rgb)), np.fliplr(back_mask))
    views["right"] = (np.ascontiguousarray(np.fliplr(right_rgb)), np.fliplr(right_mask))
    return views


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


def class_fractions(cls: np.ndarray) -> dict[str, float]:
    fg = cls >= 0
    total = int(fg.sum())
    if not total:
        return {"ochre": 0.0, "gray": 0.0, "black": 0.0}
    return {
        "ochre": float((cls == 0).sum()) / total,
        "gray": float((cls == 1).sum()) / total,
        "black": float((cls == 2).sum()) / total,
    }


def make_contact_sheet(paths: dict[str, Path], out_path: Path, cell: int = 700):
    order = ["front", "left", "back", "right"]
    canvas = Image.new("RGB", (cell * 2, cell * 2), "white")
    draw = ImageDraw.Draw(canvas)

    for idx, name in enumerate(order):
        im = Image.open(paths[name]).convert("RGB")
        im.thumbnail((cell - 24, cell - 48))
        x0 = (idx % 2) * cell
        y0 = (idx // 2) * cell
        x = x0 + (cell - im.width) // 2
        y = y0 + (cell - im.height) // 2
        canvas.paste(im, (x, y))
        draw.text((x0 + 16, y0 + 14), name.upper(), fill="black")

    canvas.save(out_path, quality=92)

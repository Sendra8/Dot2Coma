import numpy as np

from whproxy.config import Config
from whproxy.image_pipeline import class_fractions, clean_color_classes, quantize_by_rank


def _gradient_patch(n_side=100):
    """Foreground with unique luminance values so ranks are unambiguous."""
    values = np.linspace(0, 255, n_side * n_side).reshape(n_side, n_side)
    rgb = np.repeat(values[:, :, None], 3, axis=2).astype(np.uint8)
    fg = np.ones((n_side, n_side), dtype=bool)
    return rgb, fg


def test_rank_allocation_matches_configured_quantiles():
    """Test 3 from the brief."""
    rgb, fg = _gradient_patch()
    cls = quantize_by_rank(rgb, fg, Config())
    frac = class_fractions(cls)

    assert abs(frac["black"] - 0.05) < 0.005
    assert abs(frac["gray"] - 0.15) < 0.005
    assert abs(frac["ochre"] - 0.80) < 0.005


def test_darkest_pixels_become_black():
    rgb, fg = _gradient_patch()
    cls = quantize_by_rank(rgb, fg, Config())
    gray = rgb[:, :, 0]
    assert gray[cls == 2].max() <= gray[cls == 1].min()
    assert gray[cls == 1].max() <= gray[cls == 0].min()


def test_ochre_minimum_is_enforced():
    """Test 4 from the brief: too much black+gray gets rescaled."""
    rgb, fg = _gradient_patch()
    cfg = Config(black_fraction=0.30, gray_fraction=0.60, min_ochre_fraction=0.50)
    frac = class_fractions(quantize_by_rank(rgb, fg, cfg))

    assert frac["ochre"] >= 0.50
    # the black:gray ratio is preserved while being squeezed into 50%
    assert abs(frac["black"] / (frac["black"] + frac["gray"]) - 1 / 3) < 0.01


def test_background_stays_background():
    rgb, fg = _gradient_patch()
    fg[:10, :] = False
    cls = quantize_by_rank(rgb, fg, Config())
    assert (cls[:10, :] == -1).all()


def test_cleaning_never_collapses_gray_into_black():
    rgb, fg = _gradient_patch()
    cls = quantize_by_rank(rgb, fg, Config())
    cleaned = clean_color_classes(cls, fg)
    assert (cleaned == 1).any()
    assert (cleaned == 2).any()
    assert (cleaned[~fg] == -1).all()

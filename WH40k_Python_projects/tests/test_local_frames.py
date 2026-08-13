import numpy as np
import pytest
from PIL import Image

from whproxy.config import Config
from whproxy.local_frames import find_frames, load_cardinals_local
from whproxy.models import SpinSet


def _write_frames(directory, suffix=".jpg", views=("front", "left", "back", "right")):
    directory.mkdir(parents=True, exist_ok=True)
    for i, view in enumerate(views):
        arr = np.full((80, 60, 3), 255, dtype=np.uint8)
        arr[20:60, 15:45] = 90 + i * 10
        Image.fromarray(arr).save(directory / f"{view}{suffix}")
    return directory


def test_finds_frames_in_any_supported_format(tmp_path):
    _write_frames(tmp_path / "jpg", ".jpg")
    _write_frames(tmp_path / "png", ".png")

    assert set(find_frames(tmp_path / "jpg")) == {"front", "left", "back", "right"}
    assert set(find_frames(tmp_path / "png")) == {"front", "left", "back", "right"}


def test_missing_view_is_reported_by_name(tmp_path):
    _write_frames(tmp_path, views=("front", "left", "back"))
    with pytest.raises(RuntimeError, match="right"):
        find_frames(tmp_path)


def test_frames_are_normalised_to_jpeg(tmp_path):
    frames = _write_frames(tmp_path / "src", ".png")
    cfg = Config(source_provider="local", frames_dir=str(frames))

    paths, meta = load_cardinals_local(cfg, SpinSet("src", 100.0), tmp_path / "out")

    assert set(paths) == {"front", "left", "back", "right"}
    assert all(p.suffix == ".jpg" and p.exists() for p in paths.values())
    assert meta["provider"] == "local-frames"
    assert meta["angles"] == 4

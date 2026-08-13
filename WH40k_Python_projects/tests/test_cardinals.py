import pytest

from whproxy.download import cardinal_filenames


def test_twelve_angles():
    """Test 2 from the brief."""
    assert cardinal_filenames(12) == {
        "front": "01-12.jpg",
        "left": "01-03.jpg",
        "back": "01-06.jpg",
        "right": "01-09.jpg",
    }


def test_generalises_to_other_counts():
    assert cardinal_filenames(24) == {
        "front": "01-24.jpg",
        "left": "01-06.jpg",
        "back": "01-12.jpg",
        "right": "01-18.jpg",
    }


def test_rejects_non_multiple_of_four():
    with pytest.raises(ValueError):
        cardinal_filenames(10)

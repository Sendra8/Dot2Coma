from whproxy.catalog import build_hits, select_product, select_spin_set
from whproxy.offline import load_catalog_records

NORN_BOX = {
    "objectID": "x",
    "name": "Norn Emissary",
    "slug": "tyranids-norn-emissary",
    "sku": "99120106064",
    "images": [
        "/app/resources/catalog/product/threeSixty/99120106064_TyrNornAssimilator2023OTT1360/01-12.jpg",
        "/app/resources/catalog/product/threeSixty/99120106064_TyrNornEmissary2023OTT1360/01-12.jpg",
    ],
}


def test_norn_emissary_selects_emissary_folder():
    """Test 1 from the brief: the Assimilator folder must not win."""
    product = build_hits("Norn Emissary", [NORN_BOX])[0]
    spin = select_spin_set("Norn Emissary", product)
    assert spin.folder == "99120106064_TyrNornEmissary2023OTT1360"


def test_norn_assimilator_selects_assimilator_folder():
    product = build_hits("Norn Assimilator", [NORN_BOX])[0]
    spin = select_spin_set("Norn Assimilator", product)
    assert spin.folder == "99120106064_TyrNornAssimilator2023OTT1360"


def test_fuzzy_typo_still_resolves_product():
    hits = build_hits("norn emissry", load_catalog_records())
    assert select_product("norn emissry", hits).name == "Norn Emissary"


def test_riptide_and_hekaton_resolve():
    for query, expected_folder in (
        ("XV104 Riptide", "99120113030_Riptide360"),
        ("Hekaton Land Fortress", "99120118002_LoVHekatonLandFortress360"),
    ):
        hits = build_hits(query, load_catalog_records())
        product = select_product(query, hits)
        assert select_spin_set(query, product).folder == expected_folder


def test_weak_match_is_rejected():
    hits = build_hits("zzz nonexistent unit", load_catalog_records())
    try:
        select_product("zzz nonexistent unit", hits)
    except RuntimeError as exc:
        assert "too weak" in str(exc) or "Ambiguous" in str(exc)
    else:
        raise AssertionError("expected a rejection")

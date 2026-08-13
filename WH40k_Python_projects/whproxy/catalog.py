from __future__ import annotations

import html
import re

import requests
from rapidfuzz import fuzz

from .config import Config
from .models import ProductHit, SpinSet

SPIN_RE = re.compile(
    r"/app/resources/catalog/product/threeSixty/([^/?]+)",
    re.I,
)


class UnreachableSource(RuntimeError):
    """Raised when the search host or the image CDN cannot be reached."""

    def __init__(self, url: str, cause: Exception):
        self.url = url
        self.cause = cause
        super().__init__(
            f"Could not reach {url}\n"
            f"  {type(cause).__name__}: {cause}\n\n"
            "The automatic download needs outbound HTTPS to both\n"
            "  www.warhammer.com\n"
            "  <app-id>-dsn.algolia.net\n"
            "A 403 on the CONNECT means an egress policy is blocking them rather\n"
            "than the hosts being down.\n\n"
            "Options:\n"
            "  - allow those two hosts, then re-run unchanged\n"
            "  - fetch the four turntable frames yourself and pass\n"
            "      --frames-dir <dir>   (front/left/back/right)\n"
            "  - --source offline for a synthetic stand-in that does NOT\n"
            "    resemble the real unit (CI and plumbing checks only)"
        )


def normalize(text: str) -> str:
    text = html.unescape(text).lower()
    text = text.replace("t'au", "tau").replace("t’au", "tau")
    text = re.sub(r"[^a-z0-9áéíóúüñ ]+", " ", text)
    return " ".join(text.split())


def similarity(query: str, candidate: str) -> float:
    q = normalize(query)
    c = normalize(candidate)
    return max(
        fuzz.WRatio(q, c),
        fuzz.token_set_ratio(q, c),
        fuzz.token_sort_ratio(q, c),
    )


def _flatten_image_strings(images) -> list[str]:
    result: list[str] = []
    for item in images or []:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            result.extend(v for v in item.values() if isinstance(v, str))
    return list(dict.fromkeys(result))


def query_catalog(query: str, cfg: Config, hits_per_page: int = 30) -> list[ProductHit]:
    base = cfg.algolia_base or f"https://{cfg.algolia_app_id}-dsn.algolia.net"
    url = f"{base.rstrip('/')}/1/indexes/{cfg.algolia_index}/query"
    headers = {
        "X-Algolia-Application-Id": cfg.algolia_app_id,
        "X-Algolia-API-Key": cfg.algolia_api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "query": query,
        "hitsPerPage": hits_per_page,
        "attributesToRetrieve": [
            "objectID",
            "name",
            "slug",
            "sku",
            "images",
            "productType",
        ],
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        r.raise_for_status()
    except requests.RequestException as exc:
        raise UnreachableSource(url, exc) from exc
    data = r.json()

    return build_hits(query, data.get("hits", []))


def build_hits(query: str, raw_hits: list[dict]) -> list[ProductHit]:
    """Score and sort raw Algolia records. Split out so it is testable offline."""
    hits: list[ProductHit] = []
    for h in raw_hits:
        name = h.get("name") or ""
        slug = h.get("slug") or ""
        score = max(similarity(query, name), similarity(query, slug))
        hits.append(
            ProductHit(
                object_id=str(h.get("objectID", "")),
                name=name,
                slug=slug,
                sku=h.get("sku"),
                images=_flatten_image_strings(h.get("images")),
                score=score,
            )
        )

    return sorted(hits, key=lambda h: h.score, reverse=True)


def select_product(
    query: str,
    hits: list[ProductHit],
    min_score: float = 55.0,
    ambiguity_gap: float = 6.0,
) -> ProductHit:
    if not hits:
        raise RuntimeError(f"No catalogue result for {query!r}")

    best = hits[0]
    if best.score < min_score:
        raise RuntimeError(
            f"Best product match too weak: {best.name!r} ({best.score:.1f})\n"
            + "\n".join(f"  {h.score:5.1f} {h.name}" for h in hits[:5])
        )

    if len(hits) > 1 and best.score - hits[1].score < ambiguity_gap:
        raise RuntimeError(
            "Ambiguous product match:\n"
            + "\n".join(f"  {h.score:5.1f} {h.name}" for h in hits[:5])
        )

    return best


def extract_spin_sets(query: str, product: ProductHit) -> list[SpinSet]:
    folders: list[str] = []
    for s in product.images:
        m = SPIN_RE.search(s)
        if m:
            folders.append(m.group(1))

    folders = list(dict.fromkeys(folders))
    result = [SpinSet(folder=f, score=similarity(query, _folder_words(f))) for f in folders]
    return sorted(result, key=lambda s: s.score, reverse=True)


def _folder_words(folder: str) -> str:
    """Turn `99120106064_TyrNornEmissary2023OTT1360` into `Tyr Norn Emissary`.

    Fuzzy matching a raw CamelCase blob against `Norn Emissary` scores badly and
    barely separates Emissary from Assimilator, so split it into words first and
    drop the numeric SKU / marketing suffixes.
    """
    body = folder.split("_", 1)[-1]
    body = re.sub(r"\d+", " ", body)
    body = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", body)
    words = [w for w in body.split() if w.upper() not in {"OTT", "360"}]
    return " ".join(words)


def select_spin_set(query: str, product: ProductHit) -> SpinSet:
    spins = extract_spin_sets(query, product)
    if not spins:
        raise RuntimeError(f"{product.name!r} has no threeSixty set")

    # Important for boxes that build multiple units.
    return spins[0]

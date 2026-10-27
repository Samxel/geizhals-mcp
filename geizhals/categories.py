"""The Geizhals category tree shipped in data/categories.json."""

import json
import logging
import unicodedata
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def fold(s: str) -> str:
    """Lowercase and strip diacritics, so "Grafikkarte" and "GRAFIKKARTE" match."""
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()


def _norm(s: str) -> str:
    return "".join(fold(s).split())


def _load_categories() -> list[dict]:
    path = Path(__file__).parent.parent / "data" / "categories.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("categories.json not found -- list_categories disabled")
        return []


_CATEGORIES = _load_categories()


def _cat_code(node: dict) -> Optional[str]:
    """The `cat` id is the code a category-listing request needs."""
    idd = node.get("id") or {}
    return idd.get("cat")


def _walk_categories(nodes, trail, trail_de, out):
    for nd in nodes:
        label = nd.get("title") or ""
        label_de = nd.get("title_de") or label
        path = trail + [label]
        path_de = trail_de + [label_de]
        out.append((nd, " / ".join(path), " / ".join(path_de)))
        _walk_categories(nd.get("childs", []), path, path_de, out)


def _category_paths() -> dict[str, dict[str, list[str]]]:
    """lang -> code -> label path. search_product ignores `lang` and always
    labels at/de hits in German, so hits and facets are named from the shipped
    tree instead, which also lets a category listing name its category the same
    way a search hit does."""
    flat: list = []
    _walk_categories(_CATEGORIES, [], [], flat)
    paths: dict[str, dict[str, list[str]]] = {"en": {}, "de": {}}
    for node, path, path_de in flat:
        code = _cat_code(node)
        if code:
            paths["en"].setdefault(code, path.split(" / "))
            paths["de"].setdefault(code, path_de.split(" / "))
    return paths


CATEGORY_PATH = _category_paths()


def search(query: Optional[str]) -> list[dict]:
    """Every browseable category whose English or German path contains `query`
    (all of them without one), each code once."""
    flat: list = []
    _walk_categories(_CATEGORIES, [], [], flat)
    seen: set = set()
    canonical = []
    for node, path, path_de in flat:
        code = _cat_code(node)
        if not code or code in seen:
            continue
        seen.add(code)
        canonical.append((code, node.get("title"), node.get("title_de"), path, path_de))
    q = _norm(query) if query else None
    return [{"code": code, "name": name, "name_de": name_de, "path": path}
            for code, name, name_de, path, path_de in canonical
            if not q or q in _norm(path) or q in _norm(path_de)]

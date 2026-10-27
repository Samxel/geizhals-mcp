"""Telling a model or an ad title apart from the products that merely resemble
it: token matching, sibling-variant filtering and category detection."""

import re
from typing import Optional

from geizhals import api, summaries
from geizhals.categories import fold

_TOKEN_RE = re.compile(r"[a-z0-9]+")
# Ad titles fuse the series and the model number ("RTX5070", "GTX1080"); Geizhals
# always spaces them. Split those so the two sides are comparable.
_FUSED_RE = re.compile(r"^([a-z]{2,4})(\d{3,5})$")

# Words a marketplace ad title carries but a Geizhals product name never does.
# Dropping them is what makes the token overlap between the two comparable.
_AD_NOISE = {
    "neu", "neuwertig", "gebraucht", "defekt", "ovp", "originalverpackt", "verpackung",
    "rechnung", "garantie", "gewahrleistung", "versand", "abholung", "selbstabholung",
    "reserviert", "verkauft", "vb", "fixpreis", "np", "wie", "sehr", "gut", "guter",
    "zustand", "wenig", "kaum", "benutzt", "genutzt", "gunstig", "verkaufe", "verkauf",
    "biete", "inkl", "und", "mit", "fur", "der", "die", "das", "eur", "euro", "stk",
    "neuwertiger", "top", "voll", "funktionsfahig", "originalverpackung",
    "ich", "mein", "meine", "meinen", "zu", "von", "nur", "privat", "privatverkauf",
    "tausch", "inklusive", "ungeoffnet", "versiegelt", "neupreis", "kaufbeleg",
}

# Tokens that separate one model from its sibling. A candidate that carries one
# the query does not (or the other way round) is a different product, not a
# near miss -- "4070" vs "4070 Ti" vs "4070 Super".
_VARIANT_TOKENS = {"ti", "super", "xt", "xtx", "pro", "max", "plus", "ultra", "mini", "le"}

# An uncategorised hit is one shop's marketplace feed, not a Geizhals product
# page: mostly prebuilt PCs and bundles whose long names spell out the very card
# or phone being matched, so they cover every query word and would otherwise
# score like the product itself.
UNCATEGORISED_FACTOR = 0.6

# What a match needs to be acted on; the rest of a search hit is a get_product
# call away once the right candidate is known.
CANDIDATE_FIELDS = {"id", "name", "category_code", "best_price", "offer_count", "available", "shop",
                    "url", "alltime_price_min", "alltime_price_max", "alltime_last_date"}


def title_tokens(text: str) -> list[str]:
    """Comparable tokens of a product name or ad title: folded, de-noised, with
    fused series+number tokens split apart."""
    out = []
    for token in _TOKEN_RE.findall(fold(text or "")):
        if len(token) < 2 or token in _AD_NOISE:
            continue
        fused = _FUSED_RE.match(token)
        out.extend(fused.groups() if fused else [token])
    return out


def match_score(query: set, name: str) -> float:
    """Heuristic 0-1 confidence that `name` is the same product as the query
    tokens: how much of the query the name covers, discounted when the name
    carries extra words, and heavily discounted on a model-number or
    variant-marker mismatch."""
    candidate = set(title_tokens(name))
    if not query or not candidate:
        return 0.0
    covered = query & candidate
    if not covered:
        return 0.0
    # Geizhals appends the specs after the first comma ("..., 12GB GDDR7, HDMI");
    # score how specific the match is against the name proper, not that tail.
    head = set(title_tokens((name or "").split(",")[0])) or candidate
    matched_head = len(query & head)
    # A word the query does not account for is weak evidence against a match --
    # product names are simply longer than ad titles. Half-weight it, so a short
    # name does not out-rank a better match that merely spells more out.
    unexplained = (len(head) - matched_head) * 0.5
    specificity = matched_head / (matched_head + unexplained) if matched_head else 0.0
    score = len(covered) / len(query) * (0.75 + 0.25 * specificity)
    numbers = {t for t in query if t.isdigit()}
    if numbers and not numbers <= candidate:
        score *= 0.4
    if (_VARIANT_TOKENS & candidate) ^ (_VARIANT_TOKENS & query):
        score *= 0.5
    return round(min(score, 1.0), 3)


def median(values: list[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else round((ordered[mid - 1] + ordered[mid]) / 2, 2)


def model_variants(hits: list[dict], wanted: set) -> list[dict]:
    """Hits that really are the wanted model: every model word present, and no
    variant marker the model itself does not carry -- "RTX 4070" must not be
    priced off a 4070 Ti or a 4070 Super."""
    out = []
    for hit in hits:
        tokens = set(title_tokens(hit.get("name") or ""))
        if wanted <= tokens and not (_VARIANT_TOKENS & tokens) - wanted:
            out.append(hit)
    return out


async def detect_category(model: str, wanted: set, *, loc: str, hloc) -> Optional[str]:
    """Guess which category a model name belongs to.

    An unscoped search for an expensive product is dominated by things that are
    not it: cases and water blocks below it, prebuilt systems and notebooks
    above. Both are excluded here -- containing products carry many words the
    model name does not explain and lose on match score, and of the categories
    that survive that cut the product's own is the dearest, because anything
    borrowing a model's name to sell an accessory is cheaper than the model.
    """
    data = await api.search_products(model, loc=loc, hloc=hloc, lang="en", sort="", rows=30)
    hits = [summaries.search_hit(p, summaries.site_for(loc)) for p in (data.get("products") or [])]
    scored = [(match_score(wanted, h["name"] or ""), h)
              for h in model_variants(hits, wanted) if h["category_code"]]
    if not scored:
        return None
    cutoff = max(score for score, _ in scored) - 0.03
    by_category: dict = {}
    for score, hit in scored:
        if score >= cutoff:
            by_category.setdefault(hit["category_code"], []).append(hit)

    def rank(entry):
        prices = [h["best_price"] for h in entry[1] if h["best_price"]]
        return (median(prices) or 0, len(entry[1]))

    return max(by_category.items(), key=rank)[0]

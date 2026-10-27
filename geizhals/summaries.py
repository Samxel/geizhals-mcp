"""Raw API records boiled down to the fields an answer needs, in one shape
whichever endpoint they came from."""

import html
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

from geizhals.categories import CATEGORY_PATH

IMAGE_HOST = "https://gzhls.at"


def _image_urls(images) -> list[str]:
    out = []
    for img in images or []:
        if isinstance(img, str):
            out.append(img if img.startswith("http") else f"{IMAGE_HOST}{img}")
    return out


def to_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def iso_date(ts) -> Optional[str]:
    """Geizhals timestamp (seconds, or milliseconds in history series) -> ISO date."""
    if not isinstance(ts, (int, float)):
        return None
    seconds = ts / 1000 if ts > 10 ** 11 else ts
    try:
        return datetime.fromtimestamp(seconds, timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _iso_minute(ts) -> Optional[str]:
    """Unix seconds -> "2026-10-27T13:05Z". Sorts the same as the timestamp."""
    if not isinstance(ts, (int, float)):
        return None
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


_DE_DATE_RE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})$")


def clean_html(value):
    """Strip the raw HTML Geizhals embeds in comparison spec values
    (``<a href=...>``, ``<br>``, entities) down to plain text."""
    if not isinstance(value, str):
        return value
    text = re.sub(r"<br\s*/?>", " / ", value, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    # spec values carry dates as dd.mm.yyyy on one code path and ISO on another
    match = _DE_DATE_RE.match(text)
    return f"{match[3]}-{match[2]}-{match[1]}" if match else text


def site_for(loc: str) -> str:
    """The country site the ids/links of a `loc` belong to. Both serve the same
    catalogue, so an id from one is valid on the other."""
    return {"at": "geizhals.at", "de": "geizhals.de"}.get(loc, "geizhals.at")


def _leaf_cat(categories: Optional[list]) -> Optional[str]:
    """The browseable `cat` code of the deepest category in a hit's category
    path (the code `browse_category` / the `category` search filter take)."""
    for c in reversed(categories or []):
        idd = (c or {}).get("id") or {}
        if isinstance(idd, dict) and idd.get("cat"):
            return idd["cat"]
    return None


def _best_shop(p: dict) -> Optional[str]:
    for offer in p.get("offers") or []:
        shop = (offer or {}).get("shop") or {}
        # merchant_name is the shop's site name ("alza.at"), which is what
        # search hits call it too; name is the company ("Alza.at GmbH")
        name = shop.get("merchant_name") or shop.get("name")
        if name:
            return name
    return None


def _currency(p: dict) -> Optional[str]:
    for offer in p.get("offers") or []:
        currency = ((offer or {}).get("pricing") or {}).get("loc_currency")
        if currency:
            return currency
    return None


def search_hit(p: dict, site: str = "geizhals.at", lang: str = "en") -> dict:
    urls = p.get("urls") or {}
    prices = p.get("prices") or {}
    best_price = to_float(prices.get("best"))
    offer_count = p.get("offer_count")
    available = bool(best_price is not None and (offer_count or 0) > 0)
    hit = {
        "id": p.get("gzhid"),
        "variant_id": p.get("variant_id"),
        "name": clean_html(p.get("product") or p.get("product_for_sort")),
        "manufacturer": p.get("manufacturer_name"),
        # uncategorised hits (Amazon passthrough listings) carry category: null
        "category": (CATEGORY_PATH[lang].get(_leaf_cat(p.get("category")) or "")
                     or [c.get("label") for c in (p.get("category") or []) if isinstance(c, dict)]),
        "category_code": _leaf_cat(p.get("category")),
        "best_price": best_price,
        "avg_price": to_float(prices.get("avg")),
        "currency": _currency(p),
        "offer_count": offer_count,
        "available": available,
        "shop": _best_shop(p),
        "rating_stars": p.get("rating_stars"),
        "rating_count": p.get("rating_count"),
        "url": f"https://{site}{urls.get('overview')}" if urls.get("overview") else None,
        "mpn": p.get("mpn"),
        "listed_since": (p.get("listed_since") or "")[:10] or None,
    }
    # A product with no live offers would otherwise be nothing but nulls. The
    # all-time extrema come with the search response, so give the EOL anchor
    # here rather than making the caller fetch each hit individually.
    bp = p.get("bestprices") or {}
    if not available and bp:
        hit.update({
            "alltime_price_min": to_float(bp.get("min")),
            "alltime_price_max": to_float(bp.get("max")),
            "alltime_last_date": iso_date(bp.get("last")),
        })
    return hit


def product(p: dict, site: str = "geizhals.at") -> dict:
    urls = p.get("urls") or {}
    bp = p.get("bestprices") or {}
    prices = p.get("prices") or {}
    best_price = to_float(prices.get("best"))
    offer_count = p.get("offer_count")
    return {
        "id": p.get("gzhid"),
        "variant_id": p.get("variant_id"),
        "name": clean_html(p.get("product_for_sort") or p.get("product")),
        "manufacturer": p.get("manufacturer_name"),
        "category": [c.get("label") for c in (p.get("category") or []) if isinstance(c, dict)],
        "category_code": _leaf_cat(p.get("category")),
        "best_price": best_price,
        "avg_price": to_float(prices.get("avg")),
        "offer_count": offer_count,
        "available": bool(best_price is not None and (offer_count or 0) > 0),
        "shop": _best_shop(p),
        "listed_since": (p.get("listed_since") or "")[:10] or None,
        "variant_count": p.get("variant_count"),
        "rating_stars": p.get("rating_stars"),
        "rating_count": p.get("rating_count"),
        # bestprices is the observed range over the product's whole listed
        # history, not the price on offer today.
        "alltime_price_min": to_float(bp.get("min")),
        "alltime_price_max": to_float(bp.get("max")),
        "alltime_first_date": iso_date(bp.get("first")),
        "alltime_last_date": iso_date(bp.get("last")),
        "images": _image_urls(p.get("images")),
        "offers_url": f"https://{site}{urls.get('offers')}" if urls.get("offers") else None,
        "test_reviews": len(p.get("test_reviews") or []),
        "gtin": p.get("gtin") or None,
    }


def offer(o: dict, loc: str) -> dict:
    """One shop's offer: price, cheapest shipping to `loc` and what the shop says
    about stock. Shipping is listed per payment method, and a negative value
    there is a prepayment discount rather than a shipping cost, so those are
    skipped; a shop with no shipping entry only sells for pickup."""
    shop = o.get("shop") or {}
    price = to_float((o.get("price") or {}).get("value"))
    methods = ((shop.get("shipping") or {}).get(loc) or {}).values()
    costs = [to_float(m.get("shipping_price")) for m in methods if isinstance(m, dict)]
    costs = [c for c in costs if c is not None and c >= 0]
    shipping = min(costs) if costs else None
    stock = (((o.get("avl") or {}).get("descr") or [{}])[0] or {}).get("text") or ""
    rating = shop.get("rating") or {}
    return {
        "shop": shop.get("merchant_name") or shop.get("name"),
        "price": price,
        "shipping": shipping,
        "total": round(price + shipping, 2) if price is not None and shipping is not None else None,
        # the first line is the mail-order stock; the rest lists pickup branches
        "availability": stock.splitlines()[0] if stock else None,
        "shop_rating": round(rating["rating"], 1) if isinstance(rating.get("rating"), (int, float)) else None,
        "shop_rating_count": rating.get("count"),
    }


def deal(d: dict, site: str = "geizhals.at") -> dict:
    return {
        "id": d.get("id"),
        "name": clean_html(d.get("product")),
        "manufacturer": d.get("manufacturer_name"),
        "category": d.get("category_path") or d.get("cat_name"),
        "category_code": d.get("cat"),
        "change_percent": d.get("change_in_percent"),
        "change_amount": d.get("change_in_local"),
        "old_price": d.get("old_price"),
        "best_price": d.get("best_price"),
        "alltime_best": bool(d.get("alltime_best")),
        "top_deal": bool(d.get("top_deal")),
        "rank": d.get("rank"),
        "offer_count": d.get("offer_count"),
        "rating_stars": d.get("rating_stars"),
        "rating_count": d.get("rating_count"),
        "shop": d.get("hname"),
        "changed_at": _iso_minute(d.get("timestamp")),
        # best_deep_link is a 300-character tracking redirect to the shop; the
        # product page is what an answer links to, and its short form is enough
        "url": f"https://{site}/a{d['id']}.html" if d.get("id") else None,
    }


def category_hit(p: dict, category: Optional[str] = None, lang: str = "en") -> dict:
    """Normalize a categorylist product into the same shape ``search_geizhals``
    returns (categorylist ships raw, inconsistent fields otherwise), so code
    that reads either source sees the same keys."""
    pricing = p.get("pricing") or {}
    best_price = to_float(p.get("best_price"))
    offer_count = p.get("offer_count")
    available = bool(best_price is not None and (offer_count or 0) > 0)
    return {
        "id": p.get("id"),
        "variant_id": p.get("variant_id"),
        "name": clean_html(p.get("product_for_sort") or p.get("product")),
        # every hit of a category listing is in that category by definition
        "category": CATEGORY_PATH[lang].get(category or ""),
        "category_code": category,
        "best_price": best_price,
        "currency": pricing.get("loc_currency"),
        "offer_count": offer_count,
        "available": available,
        "shop": p.get("best_merch_name"),
        "rating_stars": p.get("rating_stars"),
        "rating_count": p.get("rating_count"),
        # product_link carries the listing's own ?vl=..&hloc=.. query
        "url": (p.get("product_link") or "").split("?")[0] or None,
        "mpn": p.get("mpn"),
    }


def compared(p: dict, price_map: dict) -> dict:
    """Normalize one product of a comparison: pair properties with cleaned
    spec values, and fill in pricing from ``products_details`` when the
    compare endpoint left it empty (it is not reliable for every id)."""
    labels = p.get("properties") or []
    values = p.get("propvalues") or []
    # The endpoint unions the property list across all compared products, so a
    # printhead ends up with an empty "Förderhöhe" from the pump next to it.
    # An empty string reads as "unknown", not "does not apply" -- drop those.
    specs = {label: cleaned for label, value in zip(labels, values)
             if (cleaned := clean_html(value)) not in (None, "", [], {})}

    pricing = p.get("pricing") or {}
    fallback = price_map.get(str(p.get("id")), {})
    best_price = to_float(p.get("price_raw"))
    if best_price is None:
        best_price = fallback.get("best_price")
    offers = p.get("offers") or fallback.get("offers")

    rating = p.get("rating") or {}
    share = p.get("share_url")
    # No price and no offers is a real state (discontinued or temporarily
    # unlisted), not missing data -- say so rather than leaving a bare null.
    available = bool(best_price is not None and (offers or 0) > 0)
    return {
        "id": p.get("id"),
        "name": p.get("name"),
        "manufacturer": p.get("mfc"),
        "category": p.get("catname"),
        "best_price": best_price,
        "currency": pricing.get("loc_currency"),
        "offers": offers,
        "available": available,
        "rating_stars": to_float(rating.get("rate_val")),
        "rating_count": rating.get("count"),
        "url": urllib.parse.unquote(share) if share else None,
        "specs": specs,
    }


# A broad query brings 20+ manufacturers and a dozen categories; the largest
# ones are what a narrower follow-up call picks from.
FACET_LIMIT = 10


def largest(facet: Optional[list]) -> list[dict]:
    """The FACET_LIMIT biggest buckets of a facet list, largest first."""
    buckets = [b for b in facet or [] if isinstance(b, dict)]
    return sorted(buckets, key=lambda b: -(b.get("count") or 0))[:FACET_LIMIT]

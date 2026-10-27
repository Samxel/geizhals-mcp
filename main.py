# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=2.3.0,<3", "httpx[http2]>=0.28.1"]
# ///
import argparse
import asyncio
import functools
import inspect
import json
import logging
import re
from datetime import datetime, timezone
from typing import Literal, Optional

from mcp.server import MCPServer
from mcp.server.caching import CacheHint
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from geizhals import api, categories, matching, summaries
from geizhals.api import CategorySort, Country, Sort
from geizhals.categories import CATEGORY_PATH

HOST = "127.0.0.1"
PORT = 8000
MCP_PATH = "/mcp"

# Sent once when a client connects, so what every tool shares is said here
# instead of in each tool's description, which the model reads on every turn.
INSTRUCTIONS = """\
Geizhals price comparison for Austria and Germany. All prices are in EUR.

Which tool to use:
- a product or model by name: search_geizhals. Its hits already carry the live \
price, cheapest shop, rating and availability.
- a product type such as "washing machines": list_categories, then browse_category.
- what a model costs across all its variants: get_model_price_range.
- a second-hand ad: match_geizhals, then get_model_price_range for the new price.
- more on a known id: get_product, get_price_history, get_product_ratings or \
compare_products.
- current price drops: get_deals.

Shared parameters: loc is the country site, "at" (default) or "de". hloc lists \
the shop countries to include and defaults to [loc]. lang ("en" or "de") sets \
the language of category names.

id is one product. variant_id is shared by all sibling variants of a product \
(the OC and non-OC version of a card), so group by it but never deduplicate by \
it. Category codes come from list_categories, a hit's category_code or the \
search facets; don't guess them.

available: false means a product has no live offers right now (discontinued or \
temporarily unlisted). Such hits carry their all-time price range, and \
get_product adds the last known price.

Fields without a value are left out of results.
"""

# The tool list only changes with a new release, so clients on the 2026-07-28
# protocol may keep it for a day instead of asking again on every connect.
mcp = MCPServer("geizhals-mcp", instructions=INSTRUCTIONS,
                cache_hints={"tools/list": CacheHint(ttl_ms=24 * 60 * 60 * 1000, scope="public")})

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')


def _prune(value):
    """Drop the null fields from every dict in `value`; lists keep their items."""
    if isinstance(value, dict):
        return {k: _prune(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_prune(v) for v in value]
    return value


# Every tool only reads, so clients can run them without asking each time. All
# but list_categories, which answers from the shipped tree, go out to Geizhals.
ONLINE = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
LOCAL = ToolAnnotations(readOnlyHint=True, openWorldHint=False)


def _tool(fn=None, *, annotations: ToolAnnotations = ONLINE):
    """Register `fn` as a tool whose dict result goes out as compact JSON with
    its null fields left out. Left to the SDK, a dict is pretty-printed with a
    two-space indent, which is about a third of a typical result's tokens.
    structured_output stays off: it would send every result a second time as
    structuredContent and add an output schema to the tool listing. The
    docstring is dedented here because only Python 3.13+ does that itself; on
    older ones every description line would carry four spaces of indent."""
    if fn is None:
        return functools.partial(_tool, annotations=annotations)

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        result = await fn(*args, **kwargs)
        return json.dumps(_prune(result), ensure_ascii=False, separators=(",", ":"))
    return mcp.tool(description=inspect.cleandoc(fn.__doc__ or ""), annotations=annotations,
                    structured_output=False)(wrapper)


# One call must not be able to flood the model's context -- a 500-row search is
# ~120k tokens. Larger asks are clamped; `offset` pages through the rest.
MAX_ROWS = 50
MAX_COMPARE = 10
MAX_OFFERS = 20


def _cap(value: int, name: str) -> int:
    """`value` clamped to 1..MAX_ROWS, for a tool's row count / limit."""
    if value < 1:
        raise ToolError(f"{name} must be at least 1 (got {value}).")
    return min(value, MAX_ROWS)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
@_tool
async def search_geizhals(
    query: str,
    *,
    loc: Country = "at",
    hloc: Optional[list[Country]] = None,
    lang: Literal["en", "de"] = "en",
    category: Optional[str] = None,
    manufacturer: Optional[int] = None,
    sort: Sort = "",
    rows: int = 10,
    offset: int = 0,
) -> dict:
    """Search products by keyword, e.g. "iphone 15" or "rtx 4070". Start here
    unless you already have a product id or a category code.

    Returns ``{total, results, facets}``. Each hit carries its live
    ``best_price``, ``avg_price``, ``offer_count``, cheapest ``shop``, rating and
    ``available``, so "what does X cost" needs no second call. A hit with
    ``available: false`` adds ``alltime_price_min`` / ``alltime_price_max`` /
    ``alltime_last_date``. Geizhals caps ``total`` at 1000.

    ``facets`` lists the largest categories and manufacturers of the whole
    result set with counts, to narrow a follow-up call with ``category`` or
    ``manufacturer``. ``facets.price_range`` has no ``min`` because Geizhals
    reports that floor as 0 whatever the hits cost.

    Args:
        query: Free-text search term.
        category: Category code to restrict to.
        manufacturer: Manufacturer id from ``facets.manufacturers``.
        sort: "" (relevance, default), "p" (cheapest first) or "-p" (dearest
            first). A price sort also drops products without a live price from
            ``results`` and ``total``.
        rows: Results per page, at most 50. Default 10.
        offset: Paging offset. Default 0.
    """
    rows = _cap(rows, "rows")
    data = await api.search_products(query, loc=loc, hloc=hloc, lang=lang, category=category,
                                  manufacturer=manufacturer, sort=sort, rows=rows, offset=offset)
    # every list below can come back as an explicit null (no hits, uncategorised
    # hits, no facets), so `or []` rather than a dict default
    facets = data.get("facet_aggregates") or {}
    site = summaries.site_for(loc)
    # Geizhals reports the facet's price floor as 0 whatever the hits cost, so
    # null it rather than pass off a meaningless number as the cheapest hit.
    price_range = facets.get("price_range") or {}
    price_range = {"min": price_range.get("min") or None, "max": price_range.get("max") or None}
    return {
        "total": data.get("total"),
        "results": [summaries.search_hit(p, site, lang) for p in (data.get("products") or [])[:rows]],
        "facets": {
            "categories": [{"id": c.get("id"),
                            "name": (CATEGORY_PATH[lang].get(c.get("id") or "") or [c.get("name")])[-1],
                            "count": c.get("count")}
                           for c in summaries.largest(facets.get("categories"))],
            "manufacturers": [{"id": m.get("id"), "name": m.get("name"), "count": m.get("count")}
                              for m in summaries.largest(facets.get("manufacturer"))],
            "price_range": price_range,
        },
    }


async def _last_known_price(product_id: int, loc: str) -> dict:
    """Last recorded price of a product that has no live offers, so a
    discontinued product still gives an agent something to compare against
    instead of a bare null."""
    try:
        data = await api.post("price_history", {"id": product_id,
                                             "params": {"days": 365, "loc": loc, "hloc": []}})
    except api.UpstreamError:
        return {}
    for point in reversed(data.get("response") or []):
        if isinstance(point, list) and len(point) >= 2 and point[1] is not None:
            date = summaries.iso_date(point[0])
            days = None
            if date:
                days = (datetime.now(timezone.utc).date() - datetime.fromisoformat(date).date()).days
            return {"last_known_price": summaries.to_float(point[1]), "last_known_date": date,
                    "days_since_last_price": days}
    return {}


@_tool
async def get_product(product_id: int, *, loc: Country = "at",
                      hloc: Optional[list[Country]] = None,
                      lang: Literal["en", "de"] = "en", n_offers: int = 5) -> dict:
    """Full detail of one product: live ``best_price``, ``offer_count``,
    cheapest ``shop``, rating, images, ``gtin``, ``variant_count``, the number of
    test reviews and the all-time price range (``alltime_*``, not today's price).
    Without live offers it adds ``last_known_price``, ``last_known_date`` and
    ``days_since_last_price``.

    ``offers`` lists the cheapest shops with ``price``, ``shipping`` (cheapest
    method, left out for pickup-only shops), ``total``, the shop's own
    ``availability`` text and its ``shop_rating`` out of 5. Sorting by
    ``total`` can change the winner.

    Args:
        product_id: The Geizhals product id, e.g. a search hit's ``id``.
        n_offers: Shop offers to list, cheapest first, at most 20. Default 5.
    """
    n_offers = min(_cap(n_offers, "n_offers"), MAX_OFFERS)
    payload = {
        "query": str(product_id),
        "type": "id",
        "params": api.params(loc, hloc, lang=lang, n_offers=n_offers, add_ratings=1, merchant_details=1,
                          bestprice_extrema=True, review_details=1, test_reviews=True,
                          image_size="n"),
    }
    response = (await api.post("query_product", payload)).get("response") or []
    if not response:
        raise ToolError(f"No product with id {product_id}.")
    product = summaries.product(response[0], summaries.site_for(loc))
    product["offers"] = [summaries.offer(o, loc) for o in (response[0].get("offers") or [])[:n_offers]
                         if isinstance(o, dict)]
    if not product["available"]:
        product.update(await _last_known_price(product_id, loc))
    return product


def _changes(points: list) -> list:
    """Keep only the points where the price moved, plus the last one. Prices sit
    still for days at a time, so a flat month is two points instead of 31 and
    the series still redraws exactly: each price holds until the next point."""
    out: list = []
    for i, (date, price) in enumerate(points):
        if not out or price != out[-1][1] or i == len(points) - 1:
            out.append([date, price])
    return out


def _weekly(points: list) -> list:
    """Downsample a daily series to one point per ISO week (the week's last)."""
    by_week: dict = {}
    for date, price in points:
        by_week[datetime.fromisoformat(date).isocalendar()[:2]] = [date, price]
    return list(by_week.values())


@_tool
async def get_price_history(product_id: int, *, days: int = 31,
                            loc: Country = "at", include_series: bool = True,
                            granularity: Literal["change", "day", "week"] = "change") -> dict:
    """Price history of one product, for "has it got cheaper, should I
    wait" and for pricing something that is no longer sold.

    ``window_*`` fields cover the requested window only, ``alltime_*`` the
    product's whole listed history. When the product is not ``available``,
    ``days_since_last_price`` says how old ``last_price`` is. The ``series`` of
    ``[date, price]`` pairs only lists the days the price changed, plus the
    last one.

    Args:
        product_id: The Geizhals product id.
        days: 31, 91, 183 or 365; other values snap to the nearest. Default 31.
        include_series: False for the summary alone. ``points`` counts the
            daily observations either way.
        granularity: "change" (default), "day" or "week" (each ISO week's last
            price).
    """
    window = min(api.HISTORY_WINDOWS, key=lambda w: abs(w - days))
    payload = {"id": product_id, "params": {"days": window, "loc": loc, "hloc": []}}
    try:
        data = await api.post("price_history", payload)
    except api.UpstreamError as exc:
        if exc.status != 400:
            raise
        raise api.UpstreamError(
            f"{exc} Product {product_id} most likely has no Geizhals price history -- "
            f"uncategorised marketplace listings (a single shop's feed, no category_code "
            f"on the search hit) are not price-tracked.", exc.status
        ) from exc
    meta = data.get("meta") or {}
    points = [[summaries.iso_date(p[0]), summaries.to_float(p[1])] for p in (data.get("response") or [])
              if isinstance(p, list) and len(p) >= 2 and p[1] is not None]
    prices = [p[1] for p in points]

    # meta.current_best is the live best offer and is null once a product stops
    # being offered; the series still holds what it last cost.
    current_best = summaries.to_float(meta.get("current_best"))
    last_date, last_price = points[-1] if points else (None, None)
    stale = ((datetime.now(timezone.utc).date() - datetime.fromisoformat(last_date).date()).days
             if last_date else None)

    result = {
        "window_days": window,
        "points": len(points),
        "available": current_best is not None,
        "current_best": current_best,
        "last_price": last_price,
        "last_price_date": last_date,
        "days_since_last_price": stale,
        "window_min": min(prices) if prices else None,
        "window_max": max(prices) if prices else None,
        "window_avg": round(sum(prices) / len(prices), 2) if prices else None,
        "window_change_percent": (round((prices[-1] - prices[0]) / prices[0] * 100, 1)
                                  if len(prices) > 1 and prices[0] else None),
        "alltime_min": summaries.to_float(meta.get("min")),
        "alltime_max": summaries.to_float(meta.get("max")),
        "alltime_first_date": summaries.iso_date(meta.get("first_ts")),
        "alltime_last_date": summaries.iso_date(meta.get("last_ts")),
    }
    if include_series:
        result["series"] = {"change": _changes, "day": list, "week": _weekly}[granularity](points)
    return result


@_tool
async def get_product_ratings(product_id: int, *, loc: Country = "at") -> dict:
    """User ratings of one product: ``average``, ``total`` and the count
    per star, plus a ``reviews_url``. The review texts are not included.

    Args:
        product_id: The Geizhals product id.
    """
    # pagesize/sort only page the review texts, which are not returned; the
    # aggregates always cover every rating
    payload = {
        "product_id": product_id, "filter_ghonly": 0, "offset": 0,
        "pagesize": 1, "sort": "latest", "params": {"comments": True},
    }
    data = await api.post("query_product_ratings", payload)
    per_star = data.get("per_star_rating_count") or {}
    # total_star_ratings is sometimes 0 even when per_star holds the real
    # counts, so fall back to summing them.
    total = data.get("total_star_ratings")
    if not total and per_star:
        total = sum(v for v in per_star.values() if isinstance(v, (int, float)))
    # the endpoint always answers with a geizhals.de url, whatever loc says
    url = data.get("ratings_url")
    if url:
        url = re.sub(r"^https://[^/]+", f"https://{summaries.site_for(loc)}", url)
    return {
        "product_name": summaries.clean_html(data.get("product_name")),
        "average": data.get("aggregate_star_rating"),
        "total": total,
        "per_star": {star: per_star[star] for star in sorted(per_star, reverse=True)},
        "reviews_url": url,
    }


@_tool
async def browse_category(category: str, *, loc: Country = "at",
                          hloc: Optional[list[Country]] = None,
                          lang: Literal["en", "de"] = "en", sort: CategorySort = "t",
                          price_min: Optional[float] = None, price_max: Optional[float] = None,
                          rows: int = 20, offset: int = 0) -> dict:
    """List the products of one category, for when the user names a
    product type ("washing machines") rather than a product. Take the code
    from ``list_categories`` or a hit's ``category_code`` instead of guessing.

    Hits have the fields of ``search_geizhals`` hits except ``avg_price``,
    ``manufacturer`` and ``listed_since``. ``price_range`` is the category's
    real one.

    Args:
        category: Category code, e.g. "gra16_512" for graphics cards.
        sort: "t" (relevance, default), "p" (cheapest first), "-p" (dearest
            first), "n" (newest listings) or "bew" (best rated).
        price_min / price_max: Optional bounds on the best price.
        rows: Results per page, at most 50. Default 20.
        offset: Paging offset. Default 0.
    """
    rows = _cap(rows, "rows")
    if price_min is not None and price_max is not None and price_min > price_max:
        raise ToolError(f"price_min ({price_min}) is above price_max ({price_max}); swap them.")
    params = api.params(loc, hloc, lang=lang, offset=offset, pagesize=api.page_size(rows), sort=sort,
                     deals_as_array=1, add_metadata=True, asd=False, price_range=1,
                     bpmin=price_min or 0.0, bpmax=price_max or 250000.0,
                     reverse_order=0, t="alle", v="e", vl=loc, xf="", asuch="",
                     hide_deals=0, omit_description=1, allow_other_hloc=1, new_filters=0)
    try:
        response = await api.post("categorylist", {"category": category, "params": params})
    except api.UpstreamError as exc:
        if exc.status != 400:
            raise
        raise api.UpstreamError(
            f"{exc} '{category}' is probably not a valid category code -- use "
            f"list_categories to look one up.", exc.status
        ) from exc
    data = response.get("response") or {}
    products = data.get("productlist") or data.get("products") or []
    return {
        "category": category,
        "total": data.get("total"),
        # unlike the search facet, this one is real
        "price_range": data.get("price_range"),
        "results": [summaries.category_hit(p, category, lang)
                    for p in products[:rows] if isinstance(p, dict)],
    }


@_tool
async def compare_products(product_ids: list[int], *, loc: Country = "at") -> dict:
    """Compare products side by side. Each one gets a ``specs`` map with
    German labels and values, HTML stripped and dates as ISO; specs that do
    not apply to a product are left out instead of showing up empty. A product
    without live offers gets ``last_known_price`` and ``last_known_date``.

    Args:
        product_ids: 1 to 10 Geizhals product ids.
    """
    if not 1 <= len(product_ids) <= MAX_COMPARE:
        raise ToolError(f"Pass 1 to {MAX_COMPARE} product ids (got {len(product_ids)}); "
                        f"each one adds its full spec sheet.")
    products = (await api.post("compare_products",
                            {"ids": product_ids, "params": api.params(loc, None)})).get("response") or []

    # The compare endpoint does not return pricing reliably for every id, so
    # backfill the best price / offer count from products_details.
    price_map: dict = {}
    try:
        details = (await api.post("products_details",
                               {"id": product_ids, "params": api.params(loc, None, images=1, availability=1)})
                   ).get("response") or {}
        # products_details keys its response by product id.
        entries = details.values() if isinstance(details, dict) else details
        for d in entries:
            if not isinstance(d, dict):
                continue
            # best_price is a {value, ...} object on some responses, a bare
            # price on others, and absent when the product has no live offers.
            bp = d.get("best_price")
            bp = bp.get("value") if isinstance(bp, dict) else bp
            if bp is None:
                bp = (d.get("pricing") or {}).get("loc_value")
            offer_count = d.get("offer_count")
            price_map[str(d.get("id"))] = {
                "best_price": summaries.to_float(bp),
                "offers": int(offer_count) if str(offer_count or "").isdigit() else None,
            }
    except Exception:
        logger.warning("products_details pricing backfill failed for compare_products", exc_info=True)

    compared = [summaries.compared(p, price_map) for p in products]
    # a product with no live offers is exactly the EOL case a used-market
    # comparison cares about -- give it its last known price instead of a null
    unavailable = [p for p in compared if not p["available"] and p.get("id")]
    for product, last in zip(unavailable, await asyncio.gather(
            *(_last_known_price(p["id"], loc) for p in unavailable))):
        product.update(last)
    return {"products": compared}


@_tool
async def get_deals(
    *,
    sort: Literal["percent", "price", "latest", "popularity", "top"] = "percent",
    loc: Country = "at",
    hloc: Optional[list[Country]] = None,
    lang: Literal["en", "de"] = "en",
    min_discount_percent: Optional[float] = None,
    max_price: Optional[float] = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """Current price drops, for "what's on sale right now". Each deal has
    ``change_percent`` (negative means cheaper), ``change_amount``,
    ``old_price``, ``best_price`` and the ``alltime_best`` / ``top_deal`` flags.

    Every current drop (about a thousand) is scanned, then filtered and
    sorted here. ``scanned`` is how many that were, ``matched`` how many passed
    the filters and ``top_deal_count`` how many of all drops are top deals.
    While more matches are left, ``next_offset`` says where the next page starts.

    Args:
        sort: "percent" (biggest drop, default), "price" (cheapest),
            "latest", "popularity" or "top" (top deals first).
        min_discount_percent: Keep drops of at least this many percent.
        max_price: Keep deals with a ``best_price`` of at most this.
        limit: Deals to return, at most 50. Default 20.
        offset: Skip this many matches, to page on. Default 0.
    """
    limit = _cap(limit, "limit")
    if offset < 0:
        raise ToolError(f"offset must not be negative (got {offset}).")
    raw, total = await api.all_deals(api.params(loc, hloc, lang=lang, limit=api.DEALS_PAGE_SIZE,
                                                price_range=1))
    deals = [summaries.deal(d, summaries.site_for(loc)) for d in raw]
    scanned = len(deals)
    top_deal_count = sum(1 for d in deals if d["top_deal"])

    if min_discount_percent is not None:
        floor = -abs(min_discount_percent)
        deals = [d for d in deals if (d.get("change_percent") or 0) <= floor]
    if max_price is not None:
        deals = [d for d in deals if d["best_price"] is not None and d["best_price"] <= max_price]

    if sort == "percent":
        deals.sort(key=lambda d: d["change_percent"] if d["change_percent"] is not None else 0)
    elif sort == "price":
        deals.sort(key=lambda d: d["best_price"] if d["best_price"] is not None else float("inf"))
    elif sort == "latest":
        deals.sort(key=lambda d: d["changed_at"] or "", reverse=True)
    elif sort == "popularity":
        deals.sort(key=lambda d: d["rank"] or 10 ** 9)
    elif sort == "top":
        deals.sort(key=lambda d: (0 if d["top_deal"] else 1,
                                  d["change_percent"] if d["change_percent"] is not None else 0))

    matched = len(deals)
    deals = deals[offset:offset + limit]
    return {"count": len(deals), "matched": matched, "scanned": scanned,
            "total_available": total, "top_deal_count": top_deal_count,
            "next_offset": offset + limit if offset + limit < matched else None,
            "deals": deals}


@_tool
async def get_model_price_range(
    model: str,
    *,
    category: Optional[str] = None,
    loc: Country = "at",
    hloc: Optional[list[Country]] = None,
    max_variants: int = 300,
) -> dict:
    """What a model costs right now across all its variants ("RTX 5070",
    not one board partner's card): ``min``, ``median``, ``max`` and the five
    ``cheapest`` with their ids. This is the new-price reference for a used
    item.

    The numbers come from one category, because accessories and prebuilt
    systems that borrow the model's name would skew them badly. Without a
    ``category`` it is detected and returned as ``category_code`` with a
    ``note``, so check it. ``considered`` is how many hits were looked at and
    ``total_hits`` how many exist.

    Args:
        model: The model as people write it, e.g. "RTX 5070" or "iPhone 15
            Pro". Every word must appear in a variant's name, so leave vendor
            and edition words out.
        category: Category code to scope to; saves a request and the guess.
        max_variants: Hits to consider, most relevant first. Default and
            maximum 300.
    """
    max_variants = max(1, min(int(max_variants), 300))
    site = summaries.site_for(loc)
    wanted = set(matching.title_tokens(model))
    if not wanted:
        raise ToolError(f"Nothing searchable in the model name {model!r}.")

    detected = None
    if category is None:
        category = detected = await matching.detect_category(model, wanted, loc=loc, hloc=hloc)

    # Relevance, not price: sorting by price would show the cheapest hits of a
    # fuzzy query, and for a pricey model those are all the *other* models --
    # an "iPhone 16 Pro" price sort is 60 cheaper iPhones and no 16 Pro at all.
    data = await api.search_products(model, loc=loc, hloc=hloc, lang="en", category=category,
                                  sort="", rows=max_variants)
    hits = [summaries.search_hit(p, site) for p in (data.get("products") or [])[:max_variants]]
    variants = matching.model_variants(hits, wanted)
    prices = [h["best_price"] for h in variants if h["available"] and h["best_price"] is not None]
    cheapest = sorted((h for h in variants if h["available"]), key=lambda h: h["best_price"])
    result = {
        "model": model,
        "category_code": category,
        "category": CATEGORY_PATH["en"].get(category or ""),
        "min": min(prices) if prices else None,
        "median": matching.median(prices),
        "max": max(prices) if prices else None,
        "variants": len(variants),
        "available": len(prices),
        "considered": len(hits),
        "total_hits": data.get("total"),
        "cheapest": [{"id": h["id"], "name": h["name"], "best_price": h["best_price"],
                      "offer_count": h["offer_count"], "shop": h["shop"]} for h in cheapest[:5]],
    }
    notes = []
    if detected:
        notes.append("category_code was detected, not given -- check it fits.")
    elif category is None:
        notes.append("No category could be detected, so these numbers may mix the model with "
                     "accessories and prebuilt systems that borrow its name. Pass 'category'.")
    if not variants and hits:
        notes.append(f"Nothing listed is exactly '{model}' -- every hit was a sibling model, so it "
                     f"is most likely discontinued. search_geizhals gives its all-time range.")
    elif variants and not prices:
        notes.append(f"All {len(variants)} variants are out of stock; get_product on one gives its "
                     f"last known price.")
    if notes:
        result["note"] = " ".join(notes)
    return result


@_tool
async def match_geizhals(
    title: str,
    *,
    category: Optional[str] = None,
    loc: Country = "at",
    hloc: Optional[list[Country]] = None,
    limit: int = 5,
) -> dict:
    """Resolve a classifieds ad title (willhaben, eBay and the like) to the
    Geizhals products it could be. Condition, packaging and sales words are
    dropped first.

    Candidates are sorted by ``confidence``, a 0-1 token-overlap heuristic:
    0.8 and up is a safe match, 0.5 to 0.8 needs a look at the name, anything
    lower is a guess. Model-number and variant mismatches ("4070" vs "4070
    Ti") and marketplace listings without a category score low. A ``note``
    says when the top candidates are too close to tell apart.

    Args:
        title: The ad title as written.
        category: Category code to scope to; removes most wrong candidates.
        limit: Candidates to return, at most 50. Default 5.
    """
    limit = _cap(limit, "limit")
    tokens = matching.title_tokens(title)
    if not tokens:
        raise ToolError(f"Nothing searchable left in the title {title!r} once the ad words are dropped.")
    # long ad titles are mostly prose; the leading words carry the product
    query = " ".join(tokens[:8])
    site = summaries.site_for(loc)
    data = await api.search_products(query, loc=loc, hloc=hloc, lang="en", category=category, rows=30)
    products = data.get("products") or []
    if not products and len(tokens) > 4:  # too specific -- retry on the head of the title
        query = " ".join(tokens[:4])
        data = await api.search_products(query, loc=loc, hloc=hloc, lang="en", category=category, rows=30)
        products = data.get("products") or []

    wanted = set(tokens)
    candidates = []
    for hit in (summaries.search_hit(p, site) for p in products):
        score = matching.match_score(wanted, hit["name"] or "")
        if not hit["category_code"]:
            score = round(score * matching.UNCATEGORISED_FACTOR, 3)
        if score:
            candidates.append({"confidence": score,
                               **{k: v for k, v in hit.items() if k in matching.CANDIDATE_FIELDS}})
    candidates.sort(key=lambda c: (-c["confidence"], c["best_price"] is None))
    result = {"query": query, "count": len(candidates), "candidates": candidates[:limit]}
    if not candidates:
        result["note"] = ("Nothing matched. Try a shorter title, or scope it with 'category'.")
    elif candidates[0]["confidence"] < 0.5:
        result["note"] = (f"No dependable match -- the best is only {candidates[0]['confidence']}. "
                          f"Treat these as guesses rather than as the product.")
    elif len(candidates) > 1 and candidates[0]["confidence"] - candidates[1]["confidence"] < 0.05:
        result["note"] = ("The top candidates score within 0.05 of each other, so the title does "
                          "not tell them apart and their prices can differ a lot. Confirm the exact "
                          "model from the ad's photos or specs before using one as the reference.")
    return result


@_tool(annotations=LOCAL)
async def list_categories(query: Optional[str] = None, limit: int = 40) -> dict:
    """Look up category codes by name, for ``browse_category`` and the
    ``category`` filter of ``search_geizhals``. Matches English and German
    names ("graphics cards", "grafikkarten") anywhere in the category path and
    returns ``{count, categories: [{code, name, name_de, path}]}``.

    Args:
        query: Case- and accent-insensitive substring. Omit to list all.
        limit: At most 50. Default 40.
    """
    limit = _cap(limit, "limit")
    rows = categories.search(query)
    return {"count": len(rows), "categories": rows[:limit]}


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
@mcp.prompt(title="Check a second-hand listing")
def check_listing(title: str, price: str) -> str:
    """Is a second-hand offer a good deal? Matches the ad to Geizhals and weighs
    its price against what the same model costs new."""
    return f"""\
A second-hand listing titled "{title}" asks {price} EUR. Tell me whether that is a good deal.

1. Call match_geizhals with the title. If the best candidate scores below 0.8, or the \
note says the top candidates are too close, say which models it could be and what in \
the ad would settle it.
2. Call get_model_price_range for the model, passing the candidate's category_code. \
If nothing is on sale any more, use get_product on the candidate for its last known \
price and get_price_history for how it got there.
3. Answer with the new price range, how far below the cheapest new offer the listing \
is in percent, and a short verdict. Mention what a used buyer gives up (warranty, \
condition) and anything in the title that looks off."""


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Geizhals MCP server")
    parser.add_argument("--stdio", action="store_true",
                        help="speak MCP over stdin/stdout instead of serving HTTP")
    if parser.parse_args().stdio:
        # stdout carries the protocol; the log already goes to stderr
        mcp.run("stdio")
    else:
        url = f"http://{HOST}:{PORT}{MCP_PATH}"
        logger.info("Starting geizhals-mcp server on %s", url)
        mcp.run("streamable-http", host=HOST, port=PORT, streamable_http_path=MCP_PATH)

from mcp.server import MCPServer
from mcp.server.mcpserver import Image
import httpx
import asyncio
import json
import re
import time
import hmac
import hashlib
import base64
import html
import unicodedata
import urllib.parse
import functools
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union, Literal
import logging

BASE_URL = "https://api.geizhals.net/gh/v9"
IMAGE_HOST = "https://gzhls.at"

# Host used in the request_fingerprint signing string. Constant across
# /gh/v9, /usercontent/v0, etc. (only the oauth client uses a different host).
API_HOST = "api.geizhals.net"

GH_CLIENT = "Geizhals/3.13.1 (Android 14; sdk_gphone64_x86_64; emu64xa; x86_64; at)"

# --- Request authentication ------------------------------------------------
GH_TOKEN_ID = "mobileapp-2026-android-3.12.7"
GH_AUTH_ROLE = "mobileapp-2026-android-3.12.7"
GH_HMAC_SECRET = "2Uq.p2gD1z5Im,m73u5eSVzeuFZJpcQVtzx.M3OtyW.4LvzO"

HOST = "127.0.0.1"
PORT = 8000
MCP_PATH = "/mcp"

MAX_RETRIES = 2
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

mcp = MCPServer("geizhals-mcp")
client = httpx.AsyncClient(http2=True)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

# Country / market: Geizhals runs one API for several country sites. `loc` is the
# pricing/site, `hloc` the shops to include.
Country = Literal["at", "de", "eu", "uk", "pl", "sk"]

# Sort keys seen in the app (t = default relevance, p = price, n = newest).
Sort = Literal["", "t", "p", "n", "r"]


# ---------------------------------------------------------------------------
# Auth token
# ---------------------------------------------------------------------------
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def request_fingerprint(method: str, body_json_str: str = "", query_string: str = "") -> str:
    """Canonical per-request fingerprint the JWT payload carries: a sha256 hex
    digest over a signing string built from the method, host, query and body,
    so the token only validates for this exact request."""
    if method == "POST":
        s = f"POST|{API_HOST}||{body_json_str}"
    else:  # GET
        s = f"{method}|{API_HOST}|{query_string}|"
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _auth_header(body_bytes: bytes, method: str = "POST", query_string: str = "") -> str:
    """Build the ``Bearer`` JWT the app sends: an HS256 token whose payload
    carries a ``request_fingerprint`` that binds it to this exact request,
    signed with ``GH_HMAC_SECRET``."""
    now = int(time.time())

    body_str = body_bytes.decode("utf-8")
    fp = request_fingerprint(method, body_str, query_string)

    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "token_id": GH_TOKEN_ID,
        "timestamp": now,
        "request_fingerprint": fp,
        "iat": now,
    }

    header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url(json.dumps(payload, separators=(",", ":")).encode())

    signing_input = f"{header_b64}.{payload_b64}"

    signature = hmac.new(
        GH_HMAC_SECRET.encode("utf-8"),
        signing_input.encode("utf-8"),
        hashlib.sha256
    ).digest()

    signature_b64 = _b64url(signature)

    return f"Bearer {signing_input}.{signature_b64}"


class UpstreamError(RuntimeError):
    """An upstream Geizhals failure, already phrased for the caller. Tools turn
    it into ``{"error": ...}`` instead of leaking the internal url."""


def _tool_errors(fn):
    """Return upstream failures as ``{"error": ...}`` -- the shape ``get_product``
    already used -- rather than raising a raw httpx error at the client."""
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except UpstreamError as exc:
            return {"error": str(exc)}
    return wrapper


async def _post(endpoint: str, payload: dict) -> dict:
    """POST a signed request to a gh/v9 endpoint, retrying transient failures."""
    body = json.dumps(payload, separators=(",", ":")).encode()
    headers = {
        "authorization": _auth_header(body),
        "auth-role": GH_AUTH_ROLE,
        "user-agent": GH_CLIENT,
        "content-type": "application/json",
        "accept-encoding": "gzip",
    }
    url = f"{BASE_URL}/{endpoint}"
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = await client.post(url, content=body, headers=headers)
        except httpx.TransportError as exc:
            if attempt == MAX_RETRIES:
                raise UpstreamError(f"Could not reach Geizhals ({type(exc).__name__}).") from exc
        else:
            if response.status_code == 403:
                raise UpstreamError(
                    "Geizhals rejected the request signature (403) -- the app's "
                    "signing credentials in main.py are most likely outdated."
                )
            if response.status_code not in RETRYABLE_STATUS or attempt == MAX_RETRIES:
                if response.status_code >= 400:
                    raise UpstreamError(
                        f"Geizhals rejected the '{endpoint}' request (HTTP "
                        f"{response.status_code}); check the arguments you passed."
                    )
                return response.json()
        delay = 0.5 * (2 ** attempt)
        logger.warning("Request to '%s' failed (attempt %d/%d), retrying in %.1fs",
                        url, attempt + 1, MAX_RETRIES + 1, delay)
        await asyncio.sleep(delay)


def _params(loc: str, hloc: Optional[list[str]], *, lang: str = "en", **extra) -> dict:
    """Common param block (loc = pricing site, hloc = shop countries, lang =
    display language for names/labels)."""
    p = {"loc": loc, "hloc": hloc or [loc], "lang": lang}
    p.update({k: v for k, v in extra.items() if v is not None})
    return p


# Price history is only served for these fixed windows (1/3/6/12 months); any
# other `days` value gives a 400, so requests are snapped to the nearest one.
HISTORY_WINDOWS = (31, 91, 183, 365)

# `pagesize` is validated server-side against this fixed set, so an arbitrary
# row count gives a 400. Requests ask for the next size up and the extra rows
# are trimmed off the response.
PAGE_SIZES = (1, 5, 10, 30, 100, 300, 1000)


def _page_size(rows: int) -> int:
    """Smallest allowed `pagesize` that covers `rows`."""
    return next((s for s in PAGE_SIZES if s >= rows), PAGE_SIZES[-1])


def _leaf_cat(categories: Optional[list]) -> Optional[str]:
    """The browseable `cat` code of the deepest category in a hit's category
    path (the code `browse_category` / the `category` search filter take)."""
    for c in reversed(categories or []):
        idd = (c or {}).get("id") or {}
        if isinstance(idd, dict) and idd.get("cat"):
            return idd["cat"]
    return None


# ---------------------------------------------------------------------------
# Categories (shipped tree, like the marketplace category tree)
# ---------------------------------------------------------------------------
def _fold(s: str) -> str:
    """Lowercase and strip diacritics, so "Grafikkarte" and "GRAFIKKARTE" match."""
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()


def _norm(s: str) -> str:
    return "".join(_fold(s).split())


def _load_categories() -> list[dict]:
    path = Path(__file__).parent / "data" / "categories.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logging.getLogger(__name__).warning("categories.json not found -- list_categories disabled")
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


def _category_paths() -> dict[str, list[str]]:
    """code -> label path, so a category listing can name its category the same
    way a search hit does instead of only echoing the code back."""
    flat: list = []
    _walk_categories(_CATEGORIES, [], [], flat)
    paths: dict[str, list[str]] = {}
    for node, path, _ in flat:
        code = _cat_code(node)
        if code:
            paths.setdefault(code, path.split(" / "))
    return paths


_CATEGORY_PATH = _category_paths()


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------
def _image_urls(images) -> list[str]:
    out = []
    for img in images or []:
        if isinstance(img, str):
            out.append(img if img.startswith("http") else f"{IMAGE_HOST}{img}")
    return out


def _to_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso_date(ts) -> Optional[str]:
    """Geizhals timestamp (seconds, or milliseconds in history series) -> ISO date."""
    if not isinstance(ts, (int, float)):
        return None
    seconds = ts / 1000 if ts > 10 ** 11 else ts
    try:
        return datetime.fromtimestamp(seconds, timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


_DE_DATE_RE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})$")


def _clean_html(value):
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


def _site(loc: str) -> str:
    """The country site the ids/links of a `loc` belong to. Geizhals serves .at,
    .de, .eu, .co.uk, .pl and .sk from the same catalogue."""
    return {"at": "geizhals.at", "de": "geizhals.de", "eu": "geizhals.eu",
            "uk": "skinflint.co.uk", "pl": "geizhals.pl", "sk": "geizhals.sk"}.get(loc, "geizhals.at")


def _best_shop(p: dict) -> Optional[str]:
    for offer in p.get("offers") or []:
        name = ((offer or {}).get("shop") or {}).get("name")
        if name:
            return name
    return None


def _currency(p: dict) -> Optional[str]:
    for offer in p.get("offers") or []:
        currency = ((offer or {}).get("pricing") or {}).get("loc_currency")
        if currency:
            return currency
    return None


def _summarize_search_hit(p: dict, site: str = "geizhals.at") -> dict:
    urls = p.get("urls") or {}
    prices = p.get("prices") or {}
    best_price = _to_float(prices.get("best"))
    offer_count = p.get("offer_count")
    available = bool(best_price is not None and (offer_count or 0) > 0)
    hit = {
        "id": p.get("gzhid"),
        "variant_id": p.get("variant_id"),
        "name": _clean_html(p.get("product") or p.get("product_for_sort")),
        "manufacturer": p.get("manufacturer_name"),
        # uncategorised hits (Amazon passthrough listings) carry category: null
        "category": [c.get("label") for c in (p.get("category") or []) if isinstance(c, dict)],
        "category_code": _leaf_cat(p.get("category")),
        "best_price": best_price,
        "avg_price": _to_float(prices.get("avg")),
        "currency": _currency(p),
        "offer_count": offer_count,
        "available": available,
        "status": "available" if available else "unavailable",
        "shop": _best_shop(p),
        "rating_stars": p.get("rating_stars"),
        "rating_percent": p.get("rating_percent"),
        "rating_count": p.get("rating_count"),
        "image": (_image_urls(p.get("images")) or [None])[0],
        "url": f"https://{site}{urls.get('overview')}" if urls.get("overview") else None,
        "mpn": p.get("mpn"),
        "listed_since": p.get("listed_since"),
    }
    # A product with no live offers would otherwise be nothing but nulls. The
    # all-time extrema come with the search response, so give the EOL anchor
    # here rather than making the caller fetch each hit individually.
    bp = p.get("bestprices") or {}
    if not available and bp:
        hit.update({
            "alltime_price_min": _to_float(bp.get("min")),
            "alltime_price_max": _to_float(bp.get("max")),
            "alltime_last_date": _iso_date(bp.get("last")),
        })
    return hit


def _summarize_product(p: dict, site: str = "geizhals.at") -> dict:
    urls = p.get("urls") or {}
    bp = p.get("bestprices") or {}
    prices = p.get("prices") or {}
    best_price = _to_float(prices.get("best"))
    offer_count = p.get("offer_count")
    return {
        "id": p.get("gzhid"),
        "variant_id": p.get("variant_id"),
        "name": _clean_html(p.get("product_for_sort") or p.get("product")),
        "manufacturer": p.get("manufacturer_name"),
        "category": [c.get("label") for c in (p.get("category") or []) if isinstance(c, dict)],
        "category_code": _leaf_cat(p.get("category")),
        "best_price": best_price,
        "avg_price": _to_float(prices.get("avg")),
        "offer_count": offer_count,
        "available": bool(best_price is not None and (offer_count or 0) > 0),
        "shop": _best_shop(p),
        "listed_since": p.get("listed_since"),
        "variant_count": p.get("variant_count"),
        "rating_stars": p.get("rating_stars"),
        "rating_percent": p.get("rating_percent"),
        "rating_comments": p.get("rating_comments"),
        "rating_count": p.get("rating_count"),
        # bestprices is the observed range over the product's whole listed
        # history, not the price on offer today.
        "alltime_price_min": bp.get("min"),
        "alltime_price_max": bp.get("max"),
        "alltime_first_date": _iso_date(bp.get("first")),
        "alltime_last_date": _iso_date(bp.get("last")),
        "images": _image_urls(p.get("images")),
        "offers_url": f"https://{site}{urls.get('offers')}" if urls.get("offers") else None,
        "test_reviews": len(p.get("test_reviews") or []),
    }


def _summarize_deal(d: dict) -> dict:
    img = d.get("image_thumb")
    return {
        "id": d.get("id"),
        "name": _clean_html(d.get("product")),
        "manufacturer": d.get("manufacturer_name"),
        "category": d.get("category_path") or d.get("cat_name"),
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
        "timestamp": d.get("timestamp"),
        "image": (_image_urls([img]) or [None])[0],
        "url": d.get("best_deep_link"),
    }


def _summarize_category_hit(p: dict, category: Optional[str] = None) -> dict:
    """Normalize a categorylist product into the same shape ``search_geizhals``
    returns (categorylist ships raw, inconsistent fields otherwise), so code
    that reads either source sees the same keys."""
    pricing = p.get("pricing") or {}
    best_price = _to_float(p.get("best_price"))
    offer_count = p.get("offer_count")
    available = bool(best_price is not None and (offer_count or 0) > 0)
    return {
        "id": p.get("id"),
        "variant_id": p.get("variant_id"),
        "name": _clean_html(p.get("product_for_sort") or p.get("product")),
        # every hit of a category listing is in that category by definition
        "category": _CATEGORY_PATH.get(category or ""),
        "category_code": category,
        "best_price": best_price,
        "currency": pricing.get("loc_currency"),
        "offer_count": offer_count,
        "available": available,
        "status": "available" if available else "unavailable",
        "shop": p.get("best_merch_name"),
        "rating_stars": p.get("rating_stars"),
        "rating_percent": p.get("rating_percent"),
        "rating_count": p.get("rating_count"),
        "image": p.get("image_n") or p.get("image_m") or p.get("image_thumb"),
        "url": p.get("product_link"),
        "mpn": p.get("mpn"),
    }


def _summarize_compare(p: dict, price_map: dict) -> dict:
    """Normalize one product of a comparison: pair properties with cleaned
    spec values, and fill in pricing from ``products_details`` when the
    compare endpoint left it empty (it is not reliable for every id)."""
    labels = p.get("properties") or []
    values = p.get("propvalues") or []
    # The endpoint unions the property list across all compared products, so a
    # printhead ends up with an empty "Förderhöhe" from the pump next to it.
    # An empty string reads as "unknown", not "does not apply" -- drop those.
    specs = {label: cleaned for label, value in zip(labels, values)
             if (cleaned := _clean_html(value)) not in (None, "", [], {})}

    pricing = p.get("pricing") or {}
    fallback = price_map.get(str(p.get("id")), {})
    best_price = _to_float(p.get("price_raw"))
    if best_price is None:
        best_price = fallback.get("best_price")
    offers = p.get("offers") or fallback.get("offers")

    rating = p.get("rating") or {}
    share = p.get("share_url")
    return {
        "id": p.get("id"),
        "name": p.get("name"),
        "manufacturer": p.get("mfc"),
        "category": p.get("catname"),
        "best_price": best_price,
        "currency": pricing.get("loc_currency"),
        "offers": offers,
        # No price and no offers is a real state (discontinued or temporarily
        # unlisted), not missing data -- say so rather than leaving a bare null.
        "available": bool(best_price is not None and (offers or 0) > 0),
        "rating_percent": rating.get("rate_perc"),
        "rating_stars": _to_float(rating.get("rate_val")),
        "rating_count": rating.get("count"),
        "image": p.get("image"),
        "url": urllib.parse.unquote(share) if share else None,
        "specs": specs,
    }


async def _search_products(query: str, *, loc: str, hloc, lang: str, category=None,
                           manufacturer=None, sort: str = "", rows: int = 10,
                           offset: int = 0) -> dict:
    """Raw product search (shared by the search tool and the model/match tools)."""
    payload = {
        "query": query,
        # bestprice_extrema=1 costs nothing extra and is what lets a hit with no
        # live offers still report its all-time range (see _summarize_search_hit)
        "params": _params(loc, hloc, lang=lang, offset=offset, pagesize=_page_size(rows), n_offers=1,
                          bestprice_extrema=1, add_popularity=False,
                          filter_category=category or "", filter_manufacturer=manufacturer or 0,
                          add_ratings=1, show_parent_category=1, category_suggestions=1,
                          sort=sort, category_suggestions_details=1, add_asin=1,
                          allow_other_hloc=1, has_variants=0),
    }
    return (await _post("search_product", payload)).get("response") or {}


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
@mcp.tool()
@_tool_errors
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
    """Search Geizhals products by free-text keyword, e.g. "iphone 15" or
    "rtx 4070". This is the main entry point for finding products -- start
    here unless you already have a product id or category code.

    Returns ``{total, results: [...], facets}``. Each hit already carries its
    current ``best_price``, ``avg_price``, ``offer_count``, cheapest ``shop``,
    ``currency``, ``rating_stars`` / ``rating_count`` and an ``available`` flag,
    so a plain "what does X cost / how is it rated" needs no follow-up call. Go
    to ``get_product`` only for images and the all-time range of a *listed*
    product, to ``get_price_history`` for the trend, and to
    ``compare_products`` for specs.

    A hit with ``status: "unavailable"`` has no live offers (discontinued or
    temporarily unlisted); those additionally carry ``alltime_price_min`` /
    ``alltime_price_max`` / ``alltime_last_date``, so a list of old hardware is
    still priceable without a call per hit. ``get_product`` adds the exact
    ``last_known_price`` when you need it for one of them.

    ``facets`` lists the categories and manufacturers present in the full
    result set with counts -- use these to decide values for ``category`` /
    ``manufacturer`` on a follow-up, narrower call rather than guessing ids.
    ``facets.price_range.min`` is null because Geizhals reports the facet floor
    as 0 whatever the hits cost; for a real range use the hits' ``best_price``
    or ``browse_category``, whose ``price_range`` is genuine.

    Args:
        query: Free-text search term.
        loc: Country site the prices are shown for: "at", "de", "eu", "uk",
            "pl" or "sk". Default "at" (Austria).
        hloc: Which shop countries' offers to include; defaults to ``[loc]``.
        lang: Display language for names/labels in the results, "en" (default)
            or "de".
        category: Restrict to a category code, e.g. from a prior call's
            ``facets.categories`` (each hit also carries its own
            ``category_code``) or from ``list_categories``.
        manufacturer: Restrict to a manufacturer id from a prior call's
            ``facets.manufacturers``.
        sort: "" (relevance, default), "p" (price), "n" (newest) or "r"
            (rating).
        rows: Max results to return (page size). Default 10.
        offset: Paging offset into the result set. Default 0.
    """
    if rows < 1:
        raise ValueError(f"rows must be at least 1 (got {rows}).")
    data = await _search_products(query, loc=loc, hloc=hloc, lang=lang, category=category,
                                  manufacturer=manufacturer, sort=sort, rows=rows, offset=offset)
    # every list below can come back as an explicit null (no hits, uncategorised
    # hits, no facets), so `or []` rather than a dict default
    facets = data.get("facet_aggregates") or {}
    site = _site(loc)
    # Geizhals reports the facet's price floor as 0 whatever the hits cost, so
    # null it rather than pass off a meaningless number as the cheapest hit.
    price_range = facets.get("price_range") or {}
    price_range = {"min": price_range.get("min") or None, "max": price_range.get("max") or None}
    return {
        "total": data.get("total"),
        "results": [_summarize_search_hit(p, site) for p in (data.get("products") or [])[:rows]],
        "facets": {
            "categories": [{"id": c.get("id"), "name": c.get("name"), "count": c.get("count")}
                           for c in (facets.get("categories") or [])],
            "manufacturers": [{"id": m.get("id"), "name": m.get("name"), "count": m.get("count")}
                              for m in (facets.get("manufacturer") or [])],
            "price_range": price_range,
        },
    }


async def _last_known_price(product_id: Union[int, str], loc: str) -> dict:
    """Last recorded price of a product that has no live offers, so a
    discontinued product still gives an agent something to compare against
    instead of a bare null."""
    try:
        data = await _post("price_history", {"id": int(product_id),
                                             "params": {"days": 365, "loc": loc, "hloc": []}})
    except (UpstreamError, ValueError, TypeError):
        return {}
    for point in reversed(data.get("response") or []):
        if isinstance(point, list) and len(point) >= 2 and point[1] is not None:
            date = _iso_date(point[0])
            days = None
            if date:
                days = (datetime.now(timezone.utc).date() - datetime.fromisoformat(date).date()).days
            return {"last_known_price": _to_float(point[1]), "last_known_date": date,
                    "days_since_last_price": days}
    return {}


@mcp.tool()
@_tool_errors
async def get_product(product_id: Union[int, str], *, loc: Country = "at",
                      hloc: Optional[list[Country]] = None,
                      lang: Literal["en", "de"] = "en", n_offers: int = 20) -> dict:
    """Look up full detail for a single product you already have the Geizhals
    id for (from ``search_geizhals`` or ``browse_category`` results). Returns
    the current ``best_price`` / ``offer_count`` / cheapest ``shop``, name,
    manufacturer, category, rating, image urls, a link to the shop offers, and
    how many test reviews exist.

    ``status`` is "available" or "unavailable"; the ``alltime_*`` fields are the
    range observed over the product's whole listed history, not today's price.
    When a product has no live offers (discontinued or temporarily unlisted)
    this adds ``last_known_price`` / ``last_known_date`` /
    ``days_since_last_price`` from the price history, so an EOL product is still
    comparable instead of a bare null. For the trend use ``get_price_history``,
    for specs ``compare_products``, for review text ``get_product_ratings``.

    Args:
        product_id: The Geizhals product id (``gzhid``), e.g. from a search
            hit's ``id`` field.
        loc: Country site for pricing: "at", "de", "eu", "uk", "pl" or "sk".
        hloc: Which shop countries' offers to include; defaults to ``[loc]``.
        lang: Display language for names/labels, "en" (default) or "de".
        n_offers: Max number of individual shop offers to consider for the
            best-price calculation. Default 20.
    """
    payload = {
        "query": str(product_id),
        "type": "id",
        "params": _params(loc, hloc, lang=lang, n_offers=n_offers, add_ratings=1, merchant_details=1,
                          bestprice_extrema=True, review_details=1, test_reviews=True,
                          image_size="n"),
    }
    response = (await _post("query_product", payload)).get("response") or []
    if not response:
        return {"error": f"no product for id {product_id}"}
    product = _summarize_product(response[0], _site(loc))
    product["status"] = "available" if product["available"] else "unavailable"
    if not product["available"]:
        product.update(await _last_known_price(product_id, loc))
    return product


def _weekly(points: list) -> list:
    """Downsample a daily series to one point per ISO week (the week's last)."""
    by_week: dict = {}
    for date, price in points:
        by_week[datetime.fromisoformat(date).isocalendar()[:2]] = [date, price]
    return list(by_week.values())


@mcp.tool()
@_tool_errors
async def get_price_history(product_id: Union[int, str], *, days: int = 31,
                            loc: Country = "at", include_series: bool = True,
                            granularity: Literal["day", "week"] = "day") -> dict:
    """Price history for a product, to answer "has this gotten cheaper / should
    I wait" type questions, and to price a product that is no longer on sale.

    The summary fields keep window and all-time values strictly apart:
    ``window_min`` / ``window_max`` / ``window_avg`` / ``window_change_percent``
    describe the requested window only, while ``alltime_min`` / ``alltime_max``
    / ``alltime_first_date`` / ``alltime_last_date`` cover the product's whole
    listed history. ``status`` is "available" or "unavailable"; for an
    unavailable (discontinued or unlisted) product ``last_price`` plus
    ``days_since_last_price`` tell you how stale the last data point is -- a
    large number there means the price is historical, not current.

    A full daily ``series`` is a few thousand tokens; if you only need the
    summary, pass ``include_series=False``, and prefer
    ``granularity="week"`` for long windows.

    Args:
        product_id: The Geizhals product id (``gzhid``).
        days: History window. Geizhals only serves four fixed windows --
            31, 91, 183 or 365 days (1/3/6/12 months) -- so any other value is
            snapped to the nearest one. Default 31.
        loc: Country site the prices are shown for: "at", "de", "eu", "uk",
            "pl" or "sk".
        include_series: Include the per-point ``series`` of
            ``[iso_date, price]`` pairs. Default True; set False for just the
            summary. ``points`` counts the daily observations in the window
            regardless, so it stays comparable across both settings.
        granularity: "day" (default, one point per day) or "week" (one point
            per ISO week, the week's last price).
    """
    window = min(HISTORY_WINDOWS, key=lambda w: abs(w - days))
    payload = {"id": int(product_id), "params": {"days": window, "loc": loc, "hloc": []}}
    try:
        data = await _post("price_history", payload)
    except UpstreamError as exc:
        raise UpstreamError(
            f"{exc} Product {product_id} most likely has no Geizhals price history -- "
            f"uncategorised marketplace listings (a single shop's feed, no category_code "
            f"on the search hit) are not price-tracked."
        ) from exc
    meta = data.get("meta") or {}
    points = [[_iso_date(p[0]), _to_float(p[1])] for p in (data.get("response") or [])
              if isinstance(p, list) and len(p) >= 2 and p[1] is not None]
    prices = [p[1] for p in points]

    # meta.current_best is the live best offer and is null once a product stops
    # being offered; the series still holds what it last cost.
    current_best = _to_float(meta.get("current_best"))
    last_date, last_price = points[-1] if points else (None, None)
    stale = ((datetime.now(timezone.utc).date() - datetime.fromisoformat(last_date).date()).days
             if last_date else None)

    result = {
        "window_days": window,
        "points": len(points),
        "status": "available" if current_best is not None else "unavailable",
        "current_best": current_best,
        "last_price": last_price,
        "last_price_date": last_date,
        "days_since_last_price": stale,
        "window_min": min(prices) if prices else None,
        "window_max": max(prices) if prices else None,
        "window_avg": round(sum(prices) / len(prices), 2) if prices else None,
        "window_change_percent": (round((prices[-1] - prices[0]) / prices[0] * 100, 1)
                                  if len(prices) > 1 and prices[0] else None),
        "alltime_min": _to_float(meta.get("min")),
        "alltime_max": _to_float(meta.get("max")),
        "alltime_first_date": _iso_date(meta.get("first_ts")),
        "alltime_last_date": _iso_date(meta.get("last_ts")),
    }
    if include_series:
        result["series"] = _weekly(points) if granularity == "week" else points
    return result


@mcp.tool()
@_tool_errors
async def get_product_ratings(product_id: Union[int, str], *, rows: int = 10,
                              sort: Literal["latest", "helpful"] = "latest",
                              loc: Country = "at") -> dict:
    """Aggregate user ratings for a product: average rating, total count,
    and the count per star (1-5). Returns a ``reviews_url`` link rather than
    the individual review texts.

    Args:
        product_id: The Geizhals product id (``gzhid``).
        rows: Max number of underlying reviews Geizhals aggregates over.
            Default 10.
        sort: "latest" (default) or "helpful".
        loc: Country site the ``reviews_url`` should point at: "at", "de",
            "eu", "uk", "pl" or "sk". Default "at".
    """
    payload = {
        "product_id": int(product_id), "filter_ghonly": 0, "offset": 0,
        "pagesize": _page_size(rows), "sort": sort, "params": {"comments": True},
    }
    data = await _post("query_product_ratings", payload)
    per_star = data.get("per_star_rating_count") or {}
    # total_star_ratings is sometimes 0 even when per_star holds the real
    # counts, so fall back to summing them.
    total = data.get("total_star_ratings")
    if not total and per_star:
        total = sum(v for v in per_star.values() if isinstance(v, (int, float)))
    # the endpoint always answers with a geizhals.de url, whatever loc says
    url = data.get("ratings_url")
    if url:
        url = re.sub(r"^https://[^/]+", f"https://{_site(loc)}", url)
    return {
        "product_name": _clean_html(data.get("product_name")),
        "average": data.get("aggregate_star_rating"),
        "total": total,
        "per_star": per_star,
        "reviews_url": url,
    }


@mcp.tool()
@_tool_errors
async def browse_category(category: str, *, loc: Country = "at",
                          hloc: Optional[list[Country]] = None,
                          lang: Literal["en", "de"] = "en", sort: Sort = "t",
                          price_min: Optional[float] = None, price_max: Optional[float] = None,
                          rows: int = 20, offset: int = 0) -> dict:
    """List products belonging to one category, browsed by category code
    rather than free-text search -- use this when the user names a category
    ("graphics cards", "washing machines") instead of a specific product.
    Use ``list_categories`` first to resolve the name to a code (e.g. "gra16"
    for graphics cards); don't guess codes.

    Hits have the same shape as ``search_geizhals`` results (``best_price``,
    ``offer_count``, ``currency``, ``available`` / ``status``, ``shop``,
    ``rating_*``, ``mpn``, ``category``), so code can read either source; only
    ``avg_price``, ``manufacturer`` and ``listed_since`` are missing, because
    the category feed does not carry them. Unlike the search facet, the
    ``price_range`` returned here is the category's real one.

    Args:
        category: The category code from ``list_categories`` or a search hit's
            ``category_code`` / ``facets.categories``.
        loc: Country site for pricing: "at", "de", "eu", "uk", "pl" or "sk".
        hloc: Which shop countries' offers to include; defaults to ``[loc]``.
        lang: Display language for names/labels, "en" (default) or "de".
        sort: "t" (default relevance), "p" (price), "n" (newest) or "r"
            (rating).
        price_min / price_max: Optional best-price bounds to filter to.
        rows: Max results to return (page size). Default 20.
        offset: Paging offset into the result set. Default 0.
    """
    if rows < 1:
        raise ValueError(f"rows must be at least 1 (got {rows}).")
    if price_min is not None and price_max is not None and price_min > price_max:
        raise ValueError(f"price_min ({price_min}) is above price_max ({price_max}); swap them.")
    params = _params(loc, hloc, lang=lang, offset=offset, pagesize=_page_size(rows), sort=sort,
                     deals_as_array=1, add_metadata=True, asd=False, price_range=1,
                     bpmin=price_min or 0.0, bpmax=price_max or 250000.0,
                     reverse_order=0, t="alle", v="e", vl=loc, xf="", asuch="",
                     hide_deals=0, omit_description=1, allow_other_hloc=1, new_filters=0)
    try:
        response = await _post("categorylist", {"category": category, "params": params})
    except UpstreamError as exc:
        raise UpstreamError(
            f"{exc} '{category}' is probably not a valid category code -- use "
            f"list_categories to look one up."
        ) from exc
    data = response.get("response") or {}
    products = data.get("productlist") or data.get("products") or []
    return {
        "category": category,
        "total": data.get("total"),
        # unlike the search facet, this one is real
        "price_range": data.get("price_range"),
        "results": [_summarize_category_hit(p, category) for p in products[:rows] if isinstance(p, dict)],
    }


@mcp.tool()
@_tool_errors
async def compare_products(product_ids: list[Union[int, str]], *, loc: Country = "at",
                           lang: Literal["en", "de"] = "en") -> dict:
    """Compare several products side by side, e.g. to help the user pick
    between a shortlist of alternatives. Returns ``{products: [...]}`` where
    each product has its name, manufacturer, best price, rating and a
    ``specs`` map (property -> value) with the HTML Geizhals embeds stripped
    out and dates normalized to ISO. Geizhals unions the property list across
    everything being compared, so properties that do not apply to a product
    (a pump's "Förderhöhe" on a printhead) are dropped from its ``specs``
    rather than left as an empty string that reads like missing data.

    Pricing missing from the comparison response is backfilled from
    ``products_details``. ``available`` is false when a product genuinely has
    no current offers (discontinued or temporarily unlisted), so a null price
    is distinguishable from a lookup failure -- for those, ``last_known_price``
    and ``last_known_date`` are filled in from the price history so an EOL
    product can still be compared against a used-market price.

    Args:
        product_ids: The Geizhals product ids (``gzhid``) to compare; pass two
            or more for a meaningful side-by-side.
        loc: Country site for pricing: "at", "de", "eu", "uk", "pl" or "sk".
        lang: Display language for names/labels, "en" (default) or "de".
    """
    ids = [int(i) for i in product_ids]
    products = (await _post("compare_products",
                            {"ids": ids, "params": _params(loc, None, lang=lang)})).get("response") or []

    # The compare endpoint does not return pricing reliably for every id, so
    # backfill the best price / offer count from products_details.
    price_map: dict = {}
    try:
        details = (await _post("products_details",
                               {"id": ids, "params": _params(loc, None, lang=lang,
                                                             images=1, availability=1)})).get("response") or {}
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
                "best_price": _to_float(bp),
                "offers": int(offer_count) if str(offer_count or "").isdigit() else None,
            }
    except Exception:
        logger.warning("products_details pricing backfill failed for compare_products", exc_info=True)

    compared = [_summarize_compare(p, price_map) for p in products]
    # a product with no live offers is exactly the EOL case a used-market
    # comparison cares about -- give it its last known price instead of a null
    unavailable = [p for p in compared if not p["available"] and p.get("id")]
    for product, last in zip(unavailable, await asyncio.gather(
            *(_last_known_price(p["id"], loc) for p in unavailable))):
        product["status"] = "unavailable"
        product.update(last)
    for product in compared:
        product.setdefault("status", "available" if product["available"] else "unavailable")
    return {"products": compared}


# bestprice_development has no offset, so filtering and sorting can only ever
# work over one fetched page -- take a generous one and trim it down locally.
DEALS_POOL = 300


@mcp.tool()
@_tool_errors
async def get_deals(
    *,
    sort: Literal["percent", "price", "latest", "popularity", "top"] = "percent",
    loc: Country = "at",
    hloc: Optional[list[Country]] = None,
    lang: Literal["en", "de"] = "en",
    min_discount_percent: Optional[float] = None,
    max_price: Optional[float] = None,
    limit: int = 20,
) -> dict:
    """Current Geizhals price drops ("Schnaeppchen" / Bestpreis-Entwicklung):
    products whose best price just fell, and by how much. Use this for "what's
    on sale / biggest discounts right now" questions rather than searching for
    a specific product.

    Returns ``{count, deals: [...]}``. Each deal carries ``change_percent``
    (negative = cheaper, e.g. -10.0) and ``change_amount`` next to the
    ``old_price`` / ``best_price``, plus ``alltime_best`` and ``top_deal``
    flags.

    ``limit`` is a target number of *matching* deals, not a fetch size: a large
    pool is always fetched and filtered/sorted locally, so a filter no longer
    shrinks the result below ``limit`` while matches remain. ``scanned`` says
    how many deals that pool held and ``top_deal_count`` how many of them
    Geizhals flagged as a top deal -- with ``sort="top"`` and
    ``top_deal_count: 0`` there simply were none, which is not the same as the
    sort having no effect.

    Args:
        sort: How to order the deals -- "percent" (biggest % drop, default),
            "price" (cheapest best_price), "latest" (most recently changed),
            "popularity" (most popular products first) or "top" (Geizhals'
            top_deal flag first, biggest drop within that).
        loc: Country site for pricing: "at", "de", "eu", "uk", "pl" or "sk".
        hloc: Which shop countries' offers to include; defaults to ``[loc]``.
        lang: Display language for names/labels, "en" (default) or "de".
        min_discount_percent: Only keep deals that dropped at least this many
            percent, e.g. 15 for "-15% or better". Omit for no floor.
        max_price: Only keep deals whose current ``best_price`` is at or below
            this. Omit for no cap.
        limit: Target number of matching deals to return. Default 20.
    """
    params = _params(loc, hloc, lang=lang, limit=max(limit, DEALS_POOL), price_range=1)
    data = (await _post("bestprice_development", {"params": params})).get("response") or {}
    deals = [_summarize_deal(d) for d in (data.get("deals") or [])]
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
        deals.sort(key=lambda d: d["timestamp"] or 0, reverse=True)
    elif sort == "popularity":
        deals.sort(key=lambda d: d["rank"] or 10 ** 9)
    elif sort == "top":
        deals.sort(key=lambda d: (0 if d["top_deal"] else 1,
                                  d["change_percent"] if d["change_percent"] is not None else 0))

    matched = len(deals)
    deals = deals[:limit]
    return {"count": len(deals), "matched": matched, "scanned": scanned,
            "total_available": data.get("total"), "top_deal_count": top_deal_count,
            "deals": deals}


# ---------------------------------------------------------------------------
# Model pricing & listing matching
# ---------------------------------------------------------------------------
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
}

# Tokens that separate one model from its sibling. A candidate that carries one
# the query does not (or the other way round) is a different product, not a
# near miss -- "4070" vs "4070 Ti" vs "4070 Super".
_VARIANT_TOKENS = {"ti", "super", "xt", "xtx", "pro", "max", "plus", "ultra", "mini", "le"}


def _title_tokens(text: str) -> list[str]:
    """Comparable tokens of a product name or ad title: folded, de-noised, with
    fused series+number tokens split apart."""
    out = []
    for token in _TOKEN_RE.findall(_fold(text or "")):
        if len(token) < 2 or token in _AD_NOISE:
            continue
        fused = _FUSED_RE.match(token)
        out.extend(fused.groups() if fused else [token])
    return out


def _match_score(query: set, name: str) -> float:
    """Heuristic 0-1 confidence that `name` is the same product as the query
    tokens: how much of the query the name covers, discounted when the name
    carries extra words, and heavily discounted on a model-number or
    variant-marker mismatch."""
    candidate = set(_title_tokens(name))
    if not query or not candidate:
        return 0.0
    covered = query & candidate
    if not covered:
        return 0.0
    # Geizhals appends the specs after the first comma ("..., 12GB GDDR7, HDMI");
    # score how specific the match is against the name proper, not that tail.
    head = set(_title_tokens((name or "").split(",")[0])) or candidate
    score = len(covered) / len(query) * (0.75 + 0.25 * len(query & head) / len(head))
    numbers = {t for t in query if t.isdigit()}
    if numbers and not numbers <= candidate:
        score *= 0.4
    if (_VARIANT_TOKENS & candidate) ^ (_VARIANT_TOKENS & query):
        score *= 0.5
    return round(min(score, 1.0), 3)


def _median(values: list[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else round((ordered[mid - 1] + ordered[mid]) / 2, 2)


@mcp.tool()
@_tool_errors
async def get_model_price_range(
    model: str,
    *,
    category: Optional[str] = None,
    loc: Country = "at",
    hloc: Optional[list[Country]] = None,
    max_variants: int = 60,
) -> dict:
    """What a *model* costs right now across all its board partner / vendor
    variants -- "what does an RTX 5070 go for", not "what does the Zotac Twin
    Edge OC go for". This is the number you want when pricing a used item
    against the new market; doing it by hand would mean a search, picking the
    variants out yourself and a ``compare_products`` call.

    Returns ``{min, median, max, variants, available, cheapest: [...]}`` over
    every listed variant whose name contains all of the ``model`` words. ``min``
    is the cheapest live offer for the model, ``variants`` how many variants
    matched and ``available`` how many of those are actually on sale.
    ``cheapest`` lists the five cheapest with their ids, so you can go straight
    into ``get_product`` / ``get_price_history`` from here.

    Args:
        model: The model as people write it, e.g. "RTX 5070", "iPhone 15 Pro"
            or "Ryzen 7 7800X3D". All words must appear in a variant's name, so
            keep it to the model itself and leave vendor/edition words out.
        category: Optional category code to scope to (from ``list_categories``
            or a search hit's ``category_code``) -- worth passing when the model
            name also appears in other categories, e.g. graphics cards showing
            up inside prebuilt systems.
        loc: Country site for pricing: "at", "de", "eu", "uk", "pl" or "sk".
        hloc: Which shop countries' offers to include; defaults to ``[loc]``.
        max_variants: How many hits to consider, cheapest first. Default 60,
            max 100 -- with more listed variants than that the ``max`` and
            ``median`` describe the cheapest ``max_variants`` only.
    """
    max_variants = max(1, min(int(max_variants), 100))
    data = await _search_products(model, loc=loc, hloc=hloc, lang="en", category=category,
                                  sort="p", rows=max_variants)
    site = _site(loc)
    wanted = set(_title_tokens(model))
    hits = [_summarize_search_hit(p, site) for p in (data.get("products") or [])[:max_variants]]
    # The free-text search is fuzzy, so keep only variants that really carry the
    # model -- and drop the siblings a model name subsumes: "RTX 4070" must not
    # be priced off a 4070 Ti or a 4070 Super.
    variants = []
    for hit in hits:
        tokens = set(_title_tokens(hit["name"] or ""))
        if wanted <= tokens and not (_VARIANT_TOKENS & tokens) - wanted:
            variants.append(hit)
    prices = [h["best_price"] for h in variants if h["available"] and h["best_price"] is not None]
    cheapest = sorted((h for h in variants if h["available"]), key=lambda h: h["best_price"])
    result = {
        "model": model,
        "min": min(prices) if prices else None,
        "median": _median(prices),
        "max": max(prices) if prices else None,
        "variants": len(variants),
        "available": len(prices),
        "considered": len(hits),
        "total_hits": data.get("total"),
        "cheapest": [{"id": h["id"], "name": h["name"], "best_price": h["best_price"],
                      "offer_count": h["offer_count"], "shop": h["shop"]} for h in cheapest[:5]],
    }
    if not variants and hits:
        result["note"] = (f"No variant of exactly '{model}' is listed -- the hits were all "
                          f"sibling models (e.g. {hits[0]['name']}). The model is most likely "
                          f"discontinued; get_price_history on one of them gives its last price.")
    elif variants and not prices:
        result["note"] = (f"All {len(variants)} listed variants are out of stock; use get_product "
                          f"or get_price_history on one for its last known price.")
    return result


@mcp.tool()
@_tool_errors
async def match_geizhals(
    title: str,
    *,
    category: Optional[str] = None,
    loc: Country = "at",
    hloc: Optional[list[Country]] = None,
    limit: int = 5,
) -> dict:
    """Resolve a free-form listing title -- a willhaben/eBay/classifieds ad
    headline, with all its noise -- to the Geizhals products it could be, each
    with a confidence score. Use it as the bridge between a used listing and
    its new price instead of hand-crafting a search query and eyeballing which
    variant is the right one.

    Returns ``{query, candidates: [...]}`` sorted by ``confidence`` (0-1, a
    token-overlap heuristic, not a promise): roughly, >=0.8 is a safe match,
    0.5-0.8 needs a look at the name, below that treat it as a guess. Number
    and variant-marker mismatches ("4070" vs "4070 Ti") are scored down hard,
    because those are different products rather than near misses. Each
    candidate carries the live ``best_price`` / ``offer_count`` / ``available``,
    so a match is usually the last call you need.

    Args:
        title: The listing title as written, e.g. "Gigabyte RTX 5070 Windforce
            OC 12GB NEU OVP mit Rechnung". Condition, packaging and price words
            are stripped out for you.
        category: Optional Geizhals category code to scope to (from
            ``list_categories``) -- worth passing when you know the product
            type, it removes most of the wrong-category candidates.
        loc: Country site for pricing: "at", "de", "eu", "uk", "pl" or "sk".
        hloc: Which shop countries' offers to include; defaults to ``[loc]``.
        limit: Max candidates to return. Default 5.
    """
    tokens = _title_tokens(title)
    if not tokens:
        return {"error": f"nothing searchable left in the title {title!r}"}
    # long ad titles are mostly prose; the leading words carry the product
    query = " ".join(tokens[:8])
    site = _site(loc)
    data = await _search_products(query, loc=loc, hloc=hloc, lang="en", category=category, rows=30)
    products = data.get("products") or []
    if not products and len(tokens) > 4:  # too specific -- retry on the head of the title
        query = " ".join(tokens[:4])
        data = await _search_products(query, loc=loc, hloc=hloc, lang="en", category=category, rows=30)
        products = data.get("products") or []

    wanted = set(tokens)
    candidates = []
    for hit in (_summarize_search_hit(p, site) for p in products):
        score = _match_score(wanted, hit["name"] or "")
        if score:
            candidates.append({"confidence": score, **hit})
    candidates.sort(key=lambda c: (-c["confidence"], c["best_price"] is None))
    return {"query": query, "count": len(candidates), "candidates": candidates[:limit]}


@mcp.tool()
async def list_categories(query: Optional[str] = None, limit: int = 40) -> dict:
    """Look up category codes by name, for use with ``browse_category`` (and
    the ``category`` filter of ``search_geizhals``). Call this first whenever
    you need a category code and don't already have one from a search's
    facets -- don't guess codes.

    Returns ``{count, categories: [{code, name, name_de, path}]}``. ``path``
    shows where the category sits in the tree (e.g. "Hardware / Graphics Cards
    / PCIe"). The query matches either English or German names, so both
    "graphics cards" and "grafikkarten" work; ``name`` is English and
    ``name_de`` German. Each browseable ``code`` appears once: Geizhals models
    sub-filters (e.g. "Apple macOS" under Notebooks) as the same ``code`` plus
    an internal filter, so those refinements are collapsed into their parent
    category here.

    Args:
        query: Optional case/diacritic-insensitive substring matched against
            the whole category path in English and German, e.g. "graphics",
            "grafikkarten" or "waschmaschine". Omit to list all categories, up
            to ``limit``.
        limit: Max number of categories to return. Default 40.
    """
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
    rows = [{"code": code, "name": name, "name_de": name_de, "path": path}
            for code, name, name_de, path, path_de in canonical
            if not q or q in _norm(path) or q in _norm(path_de)]
    return {"count": len(rows), "categories": rows[:limit]}


if __name__ == "__main__":
    url = f"http://{HOST}:{PORT}{MCP_PATH}"
    logger.info("Starting geizhals-mcp server on %s", url)
    mcp.run("streamable-http", host=HOST, port=PORT, streamable_http_path=MCP_PATH)

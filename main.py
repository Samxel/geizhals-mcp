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
import unicodedata
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
        except httpx.TransportError:
            if attempt == MAX_RETRIES:
                raise
        else:
            if response.status_code == 403:
                raise RuntimeError(
                    "Error"
                )
            if response.status_code not in RETRYABLE_STATUS or attempt == MAX_RETRIES:
                response.raise_for_status()
                return response.json()
        delay = 0.5 * (2 ** attempt)
        logger.warning("Request to '%s' failed (attempt %d/%d), retrying in %.1fs",
                        url, attempt + 1, MAX_RETRIES + 1, delay)
        await asyncio.sleep(delay)


def _params(loc: str, hloc: Optional[list[str]], **extra) -> dict:
    """Common param block (loc = pricing site, hloc = shop countries)."""
    p = {"loc": loc, "hloc": hloc or [loc], "lang": "en"}
    p.update({k: v for k, v in extra.items() if v is not None})
    return p


# ---------------------------------------------------------------------------
# Categories (shipped tree, like the marketplace category tree)
# ---------------------------------------------------------------------------
def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return "".join(s.lower().split())


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


def _walk_categories(nodes, trail, out):
    for nd in nodes:
        label = nd.get("title") or ""
        path = trail + [label]
        out.append((nd, " / ".join(path)))
        _walk_categories(nd.get("childs", []), path, out)


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------
def _image_urls(images) -> list[str]:
    out = []
    for img in images or []:
        if isinstance(img, str):
            out.append(img if img.startswith("http") else f"{IMAGE_HOST}{img}")
    return out


def _summarize_search_hit(p: dict) -> dict:
    urls = p.get("urls") or {}
    return {
        "id": p.get("gzhid"),
        "name": p.get("product") or p.get("product_for_sort"),
        "manufacturer": p.get("manufacturer_name"),
        "category": [c.get("name") for c in p.get("category", []) if isinstance(c, dict)],
        "image": (_image_urls(p.get("images")) or [None])[0],
        "url": f"https://geizhals.at{urls.get('overview')}" if urls.get("overview") else None,
        "listed_since": p.get("listed_since"),
    }


def _summarize_product(p: dict) -> dict:
    urls = p.get("urls") or {}
    bp = p.get("bestprices") or {}
    return {
        "id": p.get("gzhid"),
        "variant_id": p.get("variant_id"),
        "name": p.get("product_for_sort"),
        "manufacturer": p.get("manufacturer_name"),
        "rating_stars": p.get("rating_stars"),
        "rating_percent": p.get("rating_percent"),
        "rating_comments": p.get("rating_comments"),
        "best_price_min": bp.get("min"),
        "best_price_max": bp.get("max"),
        "images": _image_urls(p.get("images")),
        "offers_url": f"https://geizhals.at{urls.get('offers')}" if urls.get("offers") else None,
        "test_reviews": len(p.get("test_reviews") or []),
    }


def _summarize_deal(d: dict) -> dict:
    img = d.get("image_thumb")
    return {
        "id": d.get("id"),
        "name": d.get("product"),
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


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
@mcp.tool()
async def search_geizhals(
    query: str,
    *,
    loc: Country = "at",
    hloc: Optional[list[Country]] = None,
    category: Optional[str] = None,
    manufacturer: Optional[int] = None,
    sort: Sort = "",
    rows: int = 10,
    offset: int = 0,
) -> dict:
    """Search Geizhals products by free-text keyword, e.g. "iphone 15" or
    "rtx 4070". This is the main entry point for finding products -- start
    here unless you already have a product id or category code.

    Returns ``{total, results: [...], facets}``. ``results`` are summarized
    hits (id, name, manufacturer, category, image, url) -- call
    ``get_product`` with a hit's ``id`` for full details (price, rating,
    offers). ``facets`` lists the categories and manufacturers present in the
    full result set with counts, plus the overall ``price_range`` -- use
    these to decide values for ``category`` / ``manufacturer`` on a follow-up,
    narrower call rather than guessing ids.

    Args:
        query: Free-text search term.
        loc: Country site the prices are shown for: "at", "de", "eu", "uk",
            "pl" or "sk". Default "at" (Austria).
        hloc: Which shop countries' offers to include; defaults to ``[loc]``.
        category: Restrict to a category code, e.g. from a prior call's
            ``facets.categories`` or from ``list_categories``.
        manufacturer: Restrict to a manufacturer id from a prior call's
            ``facets.manufacturers``.
        sort: "" (relevance, default), "p" (price), "n" (newest) or "r"
            (rating).
        rows: Max results to return (page size). Default 10.
        offset: Paging offset into the result set. Default 0.
    """
    payload = {
        "query": query,
        "params": _params(loc, hloc, offset=offset, pagesize=rows, n_offers=1,
                          add_ratings=1, bestprice_extrema=0, show_parent_category=1,
                          category_suggestions=1, sort=sort,
                          filter_category=category or "", filter_manufacturer=manufacturer or 0),
    }
    data = (await _post("search_product", payload)).get("response", {})
    facets = data.get("facet_aggregates", {})
    return {
        "total": data.get("total"),
        "results": [_summarize_search_hit(p) for p in data.get("products", [])],
        "facets": {
            "categories": [{"id": c.get("id"), "name": c.get("name"), "count": c.get("count")}
                           for c in facets.get("categories", [])],
            "manufacturers": [{"id": m.get("id"), "name": m.get("name"), "count": m.get("count")}
                              for m in facets.get("manufacturer", [])],
            "price_range": facets.get("price_range"),
        },
    }


@mcp.tool()
async def get_product(product_id: Union[int, str], *, loc: Country = "at",
                      hloc: Optional[list[Country]] = None, n_offers: int = 20) -> dict:
    """Look up full detail for a single product you already have the Geizhals
    id for (from ``search_geizhals`` or ``browse_category`` results). Returns
    name, manufacturer, rating (stars/percent/comment count), best-price
    range, image urls, a link to the shop offers, and how many test reviews
    exist. For the raw price history use ``get_price_history``; for review
    text use ``get_product_ratings``.

    Args:
        product_id: The Geizhals product id (``gzhid``), e.g. from a search
            hit's ``id`` field.
        loc: Country site for pricing: "at", "de", "eu", "uk", "pl" or "sk".
        hloc: Which shop countries' offers to include; defaults to ``[loc]``.
        n_offers: Max number of individual shop offers to consider for the
            best-price calculation. Default 20.
    """
    payload = {
        "query": str(product_id),
        "type": "id",
        "params": _params(loc, hloc, n_offers=n_offers, add_ratings=1, merchant_details=1,
                          bestprice_extrema=True, review_details=1, test_reviews=True,
                          image_size="n"),
    }
    response = (await _post("query_product", payload)).get("response", [])
    if not response:
        return {"error": f"no product for id {product_id}"}
    return _summarize_product(response[0])


@mcp.tool()
async def get_price_history(product_id: Union[int, str], *, days: int = 31,
                            loc: Country = "at") -> dict:
    """Price history for a product, to answer "has this gotten cheaper /
    should I wait" type questions. Returns ``{meta, series}``: ``meta`` has
    the min/max/current-best summary; ``series`` is the raw list of
    ``[timestamp_ms, price, flag]`` points over the requested window.

    Args:
        product_id: The Geizhals product id (``gzhid``).
        days: How many days of history to fetch, counting back from today.
            Default 31.
        loc: Country site the prices are shown for: "at", "de", "eu", "uk",
            "pl" or "sk".
    """
    payload = {"id": int(product_id), "params": {"days": days, "loc": loc, "hloc": []}}
    data = await _post("price_history", payload)
    return {"meta": data.get("meta"), "series": data.get("response")}


@mcp.tool()
async def get_product_ratings(product_id: Union[int, str], *, rows: int = 10,
                              sort: Literal["latest", "helpful"] = "latest") -> dict:
    """Aggregate user ratings for a product: average rating, total count,
    and the count per star (1-5). Returns a ``reviews_url`` link rather than
    the individual review texts.

    Args:
        product_id: The Geizhals product id (``gzhid``).
        rows: Max number of underlying reviews Geizhals aggregates over.
            Default 10.
        sort: "latest" (default) or "helpful".
    """
    payload = {
        "product_id": int(product_id), "filter_ghonly": 0, "offset": 0,
        "pagesize": rows, "sort": sort, "params": {"comments": True},
    }
    data = await _post("query_product_ratings", payload)
    return {
        "product_name": data.get("product_name"),
        "average": data.get("aggregate_star_rating"),
        "total": data.get("total_star_ratings"),
        "per_star": data.get("per_star_rating_count"),
        "reviews_url": data.get("ratings_url"),
    }


@mcp.tool()
async def browse_category(category: str, *, loc: Country = "at",
                          hloc: Optional[list[Country]] = None, sort: Sort = "t",
                          price_min: Optional[float] = None, price_max: Optional[float] = None,
                          rows: int = 20, offset: int = 0) -> dict:
    """List products belonging to one category, browsed by category code
    rather than free-text search -- use this when the user names a category
    ("graphics cards", "washing machines") instead of a specific product.
    Use ``list_categories`` first to resolve the name to a code (e.g. "gra16"
    for graphics cards); don't guess codes.

    Args:
        category: The category code from ``list_categories``.
        loc: Country site for pricing: "at", "de", "eu", "uk", "pl" or "sk".
        hloc: Which shop countries' offers to include; defaults to ``[loc]``.
        sort: "t" (default relevance), "p" (price), "n" (newest) or "r"
            (rating).
        price_min / price_max: Optional best-price bounds to filter to.
        rows: Max results to return (page size). Default 20.
        offset: Paging offset into the result set. Default 0.
    """
    params = _params(loc, hloc, offset=offset, pagesize=rows, sort=sort,
                     deals_as_array=1, add_metadata=True, price_range=1,
                     bpmin=price_min or 0.0, bpmax=price_max or 250000.0,
                     omit_description=1)
    data = (await _post("categorylist", {"category": category, "params": params})).get("response", {})
    products = data.get("productlist") or data.get("products") or []
    if isinstance(data, list):
        products = data
    return {"category": category, "results": products if isinstance(products, list) else products}


@mcp.tool()
async def compare_products(product_ids: list[Union[int, str]], *, loc: Country = "at") -> dict:
    """Compare several products side by side, e.g. to help the user pick
    between a shortlist of alternatives. Returns the raw Geizhals
    comparison response (unsummarized) for the given ids.

    Args:
        product_ids: 2+ Geizhals product ids (``gzhid``) to compare.
        loc: Country site for pricing: "at", "de", "eu", "uk", "pl" or "sk".
    """
    payload = {"id": [int(i) for i in product_ids], "params": _params(loc, None)}
    return await _post("compare_products", payload)


@mcp.tool()
async def get_deals(
    *,
    sort: Literal["percent", "price", "latest", "popularity", "top"] = "percent",
    loc: Country = "at",
    hloc: Optional[list[Country]] = None,
    min_discount_percent: Optional[float] = None,
    limit: int = 20,
) -> dict:
    """Current Geizhals price drops ("Schnaeppchen" / Bestpreis-Entwicklung):
    products whose best price just fell, and by how much. Use this for "what's
    on sale / biggest discounts right now" questions rather than searching for
    a specific product.

    Returns ``{count, deals: [...]}``. Each deal carries ``change_percent``
    (negative = cheaper, e.g. -10.0) and ``change_amount`` next to the
    ``old_price`` / ``best_price``, plus ``alltime_best`` and ``top_deal``
    flags. Filtering and ordering are applied here over the fetched set.

    Args:
        sort: How to order the deals -- "percent" (biggest % drop, default),
            "price" (cheapest best_price), "latest" (most recently changed),
            "popularity" (most popular products first) or "top" (Geizhals'
            top_deal flag first).
        loc: Country site for pricing: "at", "de", "eu", "uk", "pl" or "sk".
        hloc: Which shop countries' offers to include; defaults to ``[loc]``.
        min_discount_percent: Only keep deals that dropped at least this many
            percent, e.g. 15 for "-15% or better". Omit for no floor.
        limit: Max number of deals to fetch and return. Default 20.
    """
    params = _params(loc, hloc, limit=limit, price_range=1)
    data = (await _post("bestprice_development", {"params": params})).get("response", {})
    deals = [_summarize_deal(d) for d in data.get("deals", [])]

    if min_discount_percent is not None:
        floor = -abs(min_discount_percent)
        deals = [d for d in deals if (d.get("change_percent") or 0) <= floor]

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

    return {"count": len(deals), "deals": deals[:limit]}


@mcp.tool()
async def list_categories(query: Optional[str] = None, limit: int = 40) -> dict:
    """Look up category codes by name, for use with ``browse_category`` (and
    the ``category`` filter of ``search_geizhals``). Call this first whenever
    you need a category code and don't already have one from a search's
    facets -- don't guess codes.

    Returns ``{count, categories: [{code, name, path}]}``. ``path`` shows
    where the category sits in the tree (e.g. "Hardware / Grafikkarten");
    ``code`` is only present on leaf-ish categories that actually support
    browsing -- entries without a usable code are omitted from the results.

    Args:
        query: Optional case/diacritic-insensitive substring to filter
            category names by, e.g. "grafikkarten". Omit to list all
            (leaf-ish) categories, up to ``limit``.
        limit: Max number of categories to return. Default 40.
    """
    flat: list = []
    _walk_categories(_CATEGORIES, [], flat)
    rows = []
    q = _norm(query) if query else None
    for node, path in flat:
        code = _cat_code(node)
        if not code:
            continue
        if q and q not in _norm(node.get("title", "")):
            continue
        rows.append({"code": code, "name": node.get("title"), "path": path})
    return {"count": len(rows), "categories": rows[:limit]}


if __name__ == "__main__":
    url = f"http://{HOST}:{PORT}{MCP_PATH}"
    logger.info("Starting geizhals-mcp server on %s", url)
    mcp.run("streamable-http", host=HOST, port=PORT, streamable_http_path=MCP_PATH)

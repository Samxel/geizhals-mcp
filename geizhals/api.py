"""Signed requests to the Geizhals app API, and the param sets it accepts."""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Literal, Optional

import httpx
from mcp.server.mcpserver.exceptions import ToolError

BASE_URL = "https://api.geizhals.net/gh/v9"

# Host used in the request_fingerprint signing string. Constant across
# /gh/v9, /usercontent/v0, etc. (only the oauth client uses a different host).
API_HOST = "api.geizhals.net"

GH_CLIENT = "Geizhals/3.13.1 (Android 14; sdk_gphone64_x86_64; emu64xa; x86_64; at)"

# --- Request authentication ------------------------------------------------
GH_TOKEN_ID = "mobileapp-2026-android-3.12.7"
GH_AUTH_ROLE = "mobileapp-2026-android-3.12.7"
GH_HMAC_SECRET = "2Uq.p2gD1z5Im,m73u5eSVzeuFZJpcQVtzx.M3OtyW.4LvzO"

MAX_RETRIES = 2
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

client = httpx.AsyncClient(http2=True)

logger = logging.getLogger(__name__)

# Country / market: Geizhals runs one API for several country sites. `loc` is the
# pricing/site, `hloc` the shops to include. Only the Austrian and German sites
# are offered: on the others the endpoints disagree on currency (search answers
# in EUR labelled as PLN/GBP, the price history in PLN/GBP), sk answers every
# call with a 400, and the at/de sites ignore any other shop country in `hloc`.
Country = Literal["at", "de"]

# Sort keys each endpoint actually honours (checked against the live API).
# search_product silently ignores anything but relevance and price, so "n" and
# "r" there would only look like they worked; categorylist rejects unknown keys
# with a 400 and reads "r" as a price sort, its rating sort is "bew".
Sort = Literal["", "p", "-p"]
CategorySort = Literal["t", "p", "-p", "n", "bew"]


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


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------
class UpstreamError(ToolError):
    """An upstream Geizhals failure, already phrased for the caller. As a
    ``ToolError`` it reaches the model as an ``is_error`` result carrying this
    text; any other exception would only say "Error executing tool"."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


async def post(endpoint: str, payload: dict) -> dict:
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
                    "signing credentials in geizhals/api.py are most likely outdated.", 403
                )
            if response.status_code not in RETRYABLE_STATUS or attempt == MAX_RETRIES:
                if response.status_code >= 500:
                    # still failing after the retries: their side, not the arguments
                    raise UpstreamError(
                        f"Geizhals could not answer the '{endpoint}' request (HTTP "
                        f"{response.status_code}); this is on their side, not the arguments.",
                        response.status_code
                    )
                if response.status_code >= 400:
                    raise UpstreamError(
                        f"Geizhals rejected the '{endpoint}' request (HTTP "
                        f"{response.status_code}); check the arguments you passed.",
                        response.status_code
                    )
                return response.json()
        delay = 0.5 * (2 ** attempt)
        logger.warning("Request to '%s' failed (attempt %d/%d), retrying in %.1fs",
                        url, attempt + 1, MAX_RETRIES + 1, delay)
        await asyncio.sleep(delay)


def params(loc: str, hloc: Optional[list[str]], *, lang: str = "en", **extra) -> dict:
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


def page_size(rows: int) -> int:
    """Smallest allowed `pagesize` that covers `rows`."""
    return next((s for s in PAGE_SIZES if s >= rows), PAGE_SIZES[-1])


async def search_products(query: str, *, loc: str, hloc, lang: str, category=None,
                          manufacturer=None, sort: str = "", rows: int = 10,
                          offset: int = 0) -> dict:
    """Raw product search (shared by the search tool and the model/match tools)."""
    payload = {
        "query": query,
        # bestprice_extrema=1 costs nothing extra and is what lets a hit with no
        # live offers still report its all-time range (see summaries.search_hit)
        "params": params(loc, hloc, lang=lang, offset=offset, pagesize=page_size(rows), n_offers=1,
                         bestprice_extrema=1, add_popularity=False,
                         filter_category=category or "", filter_manufacturer=manufacturer or 0,
                         add_ratings=1, show_parent_category=1, category_suggestions=1,
                         sort=sort, category_suggestions_details=1, add_asin=1,
                         allow_other_hloc=1, has_variants=0),
    }
    return (await post("search_product", payload)).get("response") or {}


# ---------------------------------------------------------------------------
# Deal feed
# ---------------------------------------------------------------------------
# bestprice_development pages with `pg` (offset and page are ignored) and serves
# at most 300 drops a page. Filtering and sorting happen in get_deals, so every
# page of the current drops is fetched: the biggest drops are as likely to sit
# on the last page as on the first.
DEALS_PAGE_SIZE = 300
# The feed usually holds about a thousand drops, i.e. four pages. A page takes
# ~3s to answer, so those four are asked for at once instead of reading the
# page count off page 1 first; a page past the end just repeats the last one.
DEALS_USUAL_PAGES = 4
DEALS_MAX_PAGES = 10

# Reading the whole feed takes a few seconds, so it is kept briefly: paging on
# with `offset` should not wait for the same thousand drops again.
DEALS_CACHE_SECONDS = 120
_deals_cache: dict[str, tuple[float, list[dict], Optional[int]]] = {}


async def _deal_pages(feed_params: dict, pages) -> list[dict]:
    return [(r.get("response") or {}) for r in await asyncio.gather(
        *(post("bestprice_development", {"params": {**feed_params, "pg": pg}}) for pg in pages))]


async def all_deals(feed_params: dict) -> tuple[list[dict], Optional[int]]:
    """Every current price drop and Geizhals' total, from a fresh cache if any."""
    key = json.dumps(feed_params, sort_keys=True)
    cached = _deals_cache.get(key)
    if cached and time.monotonic() - cached[0] < DEALS_CACHE_SECONDS:
        return cached[1], cached[2]
    pages = await _deal_pages(feed_params, range(1, DEALS_USUAL_PAGES + 1))
    last = min(int((pages[0].get("pager") or {}).get("last_page") or 1), DEALS_MAX_PAGES)
    if last > DEALS_USUAL_PAGES:
        pages += await _deal_pages(feed_params, range(DEALS_USUAL_PAGES + 1, last + 1))
    deals, seen = [], set()
    for page in pages[:last]:
        for d in page.get("deals") or []:
            if isinstance(d, dict) and d.get("id") not in seen:
                seen.add(d.get("id"))
                deals.append(d)
    _deals_cache[key] = (time.monotonic(), deals, pages[0].get("total"))
    return deals, pages[0].get("total")

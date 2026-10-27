"""Smoke tests against the real API. The signing secret and the param sets are
reverse-engineered, so these are what notices Geizhals changing them; they only
run with GEIZHALS_LIVE=1 (the scheduled CI job sets it)."""

import os

import httpx
import pytest

import main

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(not os.environ.get("GEIZHALS_LIVE"), reason="set GEIZHALS_LIVE=1 to hit the real API"),
]

# A long-listed, widely stocked product, so the id stays valid for years.
PRODUCT_ID = 2872867  # AMD Ryzen 7 7800X3D, tray


@pytest.fixture(autouse=True)
async def fresh_client(monkeypatch):
    """main.client binds to the first event loop it runs on, and every test
    gets its own loop."""
    client = httpx.AsyncClient(http2=True)
    monkeypatch.setattr(main, "client", client)
    yield
    await client.aclose()


async def test_search_is_signed_and_priced(call):
    result = await call("search_geizhals", query="ryzen 7 7800x3d", rows=5)
    assert result["total"] > 0
    assert any(hit["best_price"] for hit in result["results"])


async def test_product_history_and_ratings(call):
    product = await call("get_product", product_id=PRODUCT_ID)
    assert product["name"].startswith("AMD Ryzen 7 7800X3D")
    history = await call("get_price_history", product_id=PRODUCT_ID, include_series=False)
    assert history["points"] > 0
    ratings = await call("get_product_ratings", product_id=PRODUCT_ID)
    assert ratings["total"] > 0


async def test_browse_compare_and_deals(call):
    browse = await call("browse_category", category="cpuamdam4", rows=5)
    assert browse["results"]
    compared = await call("compare_products", product_ids=[PRODUCT_ID, browse["results"][0]["id"]])
    assert len(compared["products"]) == 2
    deals = await call("get_deals", limit=5)
    assert deals["deals"]


async def test_german_site_answers_in_euro(call):
    result = await call("search_geizhals", query="ryzen 7 7800x3d", loc="de", rows=5)
    priced = [hit for hit in result["results"] if hit["best_price"]]
    assert priced and all(hit["currency"] == "EUR" for hit in priced)
    assert priced[0]["url"].startswith("https://geizhals.de/")
    deals = await call("get_deals", loc="de", limit=3)
    assert deals["deals"]


async def test_sort_keys_take_effect(call):
    dearest = await call("search_geizhals", query="rtx 5070", sort="-p", rows=10)
    prices = [hit["best_price"] for hit in dearest["results"]]
    assert prices == sorted(prices, reverse=True)
    rated = await call("browse_category", category="gra16_512", sort="bew", rows=5)
    assert all(hit.get("rating_stars") for hit in rated["results"])
    newest = await call("browse_category", category="gra16_512", sort="n", rows=5)
    ids = [hit["id"] for hit in newest["results"]]
    assert ids == sorted(ids, reverse=True)


async def test_model_price_range_and_matching(call):
    model = await call("get_model_price_range", model="Ryzen 7 7800X3D")
    assert model["category_code"] == "cpuamdam4"
    assert model["min"]
    match = await call("match_geizhals", title="AMD Ryzen 7 7800X3D tray NEU OVP")
    assert match["candidates"][0]["confidence"] > 0.8

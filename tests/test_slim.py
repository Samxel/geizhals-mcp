"""Hits carry what an answer needs, not every field Geizhals sends."""

import pytest

from samples import category_hit, deal, search_hit, search_response

pytestmark = pytest.mark.anyio


async def test_search_hits_drop_duplicated_and_bulky_fields(api, call):
    api.on("search_product", search_response(
        [search_hit(1, "ASUS RTX 5070 Prime, 12GB", best=917.55, offers=21,
                    rating_stars=4.9, rating_count=34)],
        manufacturers=[{"id": i, "name": f"Brand {i}", "count": i} for i in range(1, 23)]))
    result = await call("search_geizhals", query="rtx 5070")
    hit = result["results"][0]
    for field in ("status", "image", "rating_percent", "mpn"):
        assert field not in hit
    assert hit["listed_since"] == "2025-01-07"
    counts = [m["count"] for m in result["facets"]["manufacturers"]]
    assert counts == list(range(22, 12, -1))


async def test_deals_link_the_product_page_not_the_shop_redirect(api, call):
    api.on("bestprice_development", {"response": {"deals": [
        deal(1, percent=-20.0, best=80.0, old=100.0, ts=1793100000),
        deal(2, percent=-30.0, best=70.0, old=100.0, ts=1793105000),
    ]}})
    result = await call("get_deals", sort="latest", loc="de")
    first = result["deals"][0]
    assert first["id"] == 2
    assert first["url"] == "https://geizhals.de/a2.html"
    assert first["changed_at"] == "2026-10-27T12:43Z"
    assert first["category_code"] == "gra16_512"
    assert "image" not in first and "timestamp" not in first


async def test_category_hits_lose_the_listing_query(api, call):
    api.on("categorylist", {"response": {
        "total": 1, "products": [category_hit(5, "Bosch WAN28127", best=467.0)]}})
    hit = (await call("browse_category", category="hwaschf"))["results"][0]
    assert hit["url"] == "https://geizhals.at/bosch-wan28127-a5.html"


async def test_ratings_are_aggregates_ordered_by_star(api, call):
    api.on("query_product_ratings", {
        "product_name": "Apple iPhone 13", "aggregate_star_rating": 4.6, "total_star_ratings": 147,
        "per_star_rating_count": {"3": 2, "4": 17, "5": 118, "1": 8, "2": 2},
        "ratings_url": "https://geizhals.de/apple-iphone-13-a2601020.html#ratings"})
    result = await call("get_product_ratings", product_id=2601020)
    assert list(result["per_star"]) == ["5", "4", "3", "2", "1"]
    assert result["reviews_url"].startswith("https://geizhals.at/")
    assert api.sent("query_product_ratings")[0]["pagesize"] == 1


async def test_match_candidates_carry_only_what_a_match_needs(api, call):
    api.on("search_product", search_response(
        [search_hit(11, "GIGABYTE GeForce RTX 5070 Windforce OC SFF 12G, 12GB GDDR7",
                    best=864.9, offers=18)]))
    [candidate] = (await call("match_geizhals", title="Gigabyte RTX 5070 Windforce OC"))["candidates"]
    assert set(candidate) == {"confidence", "id", "name", "category_code", "best_price", "offer_count",
                              "available", "shop", "url"}


async def test_product_names_the_shop_like_search_does(api, call):
    product = search_hit(3381918, "GIGABYTE RTX 5070 Windforce OC SFF", best=864.9, offers=18)
    product["offers"] = [{"shop": {"name": "Alza.at GmbH", "merchant_name": "alza.at"}}]
    api.on("query_product", {"response": [product]})
    assert (await call("get_product", product_id=3381918))["shop"] == "alza.at"

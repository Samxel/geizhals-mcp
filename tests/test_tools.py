"""The tools end to end through an MCP client, against the fake API."""

import pytest

from samples import category_hit, deal, search_hit, search_response

pytestmark = pytest.mark.anyio


async def test_search_summarizes_hits_and_facets(api, call):
    api.on("search_product", search_response(
        [search_hit(1, "ASUS RTX 5070 Prime, 12GB", best=917.55, avg=1000.4, offers=21,
                    rating_stars=4.9, rating_count=34)],
        categories=[{"id": "gra16_512", "name": "PCIe", "count": 82}],
        manufacturers=[{"id": 272, "name": "ASUS", "count": 69}]))
    result = await call("search_geizhals", query="rtx 5070", rows=3)
    hit = result["results"][0]
    assert hit["id"] == 1
    assert hit["best_price"] == 917.55
    assert hit["category_code"] == "gra16_512"
    assert hit["shop"] == "alza.at"
    assert hit["available"] is True
    assert result["facets"]["categories"] == [{"id": "gra16_512", "name": "PCIe", "count": 82}]
    assert result["facets"]["price_range"]["min"] is None
    assert api.sent("search_product")[0]["params"]["pagesize"] == 5


async def test_search_gives_unavailable_hits_their_alltime_range(api, call):
    api.on("search_product", search_response([search_hit(
        2, "Apple iPhone 13 Mini 128GB", cat="umtsover",
        bestprices={"min": 324.3, "max": 1078.0, "last": 1768953600})]))
    hit = (await call("search_geizhals", query="iphone 13 mini"))["results"][0]
    assert hit["available"] is False
    assert hit["alltime_price_min"] == 324.3
    assert hit["alltime_last_date"] == "2026-01-21"


async def test_search_survives_a_zero_hit_response(api, call):
    api.on("search_product", search_response([]))
    result = await call("search_geizhals", query="xqzvwjkplmn")
    assert result["total"] == 0
    assert result["results"] == []


async def test_get_deals_filters_and_sorts_locally(api, call):
    api.on("bestprice_development", {"response": {"total": 1129, "deals": [
        deal(1, percent=-10.0, best=90.0, old=100.0),
        deal(2, percent=-50.0, best=15.0, old=30.0, top=True),
        deal(3, percent=-35.0, best=650.0, old=1000.0),
        deal(4, percent=-40.0, best=60.0, old=100.0),
    ]}})
    result = await call("get_deals", min_discount_percent=30, max_price=100, sort="price")
    assert [d["id"] for d in result["deals"]] == [2, 4]
    assert result["scanned"] == 4
    assert result["top_deal_count"] == 1


async def test_browse_category_normalizes_hits(api, call):
    api.on("categorylist", {"response": {"total": 1322, "price_range": {"min": 20.0, "max": 599.99},
                                          "products": [category_hit(5, "Bosch WAN28127", best=467.0,
                                                                    rating_stars=4.7, rating_count=65)]}})
    result = await call("browse_category", category="hwaschf", price_max=600)
    hit = result["results"][0]
    assert hit["best_price"] == 467.0
    assert hit["category"] == ["Home & Living", "Washing & Drying", "Washing Machines"]
    assert result["price_range"] == {"min": 20.0, "max": 599.99}


async def test_list_categories_matches_english_and_german():
    from conftest import call_tool
    english = await call_tool("list_categories", query="washing machines")
    german = await call_tool("list_categories", query="waschmaschine")
    assert "hwaschf" in [c["code"] for c in english["categories"]]
    assert "hwaschf" in [c["code"] for c in german["categories"]]


async def test_match_geizhals_ranks_the_exact_card_first(api, call):
    api.on("search_product", search_response([
        search_hit(10, "GIGABYTE GeForce RTX 5070 Ti Windforce OC 16G, 16GB GDDR7", best=1100.0, offers=9),
        search_hit(11, "GIGABYTE GeForce RTX 5070 Windforce OC SFF 12G, 12GB GDDR7", best=864.9, offers=18),
    ]))
    result = await call("match_geizhals", title="Gigabyte RTX 5070 Windforce OC 12GB NEU OVP mit Rechnung")
    assert result["query"] == "gigabyte rtx 5070 windforce oc 12gb"
    assert result["candidates"][0]["id"] == 11
    assert result["candidates"][0]["confidence"] > 0.9


async def test_get_model_price_range_detects_the_category(api, call):
    hits = [search_hit(20, "MSI GeForce RTX 5070 Ventus 2X OC, 12GB", best=846.05, offers=20),
            search_hit(21, "ASUS GeForce RTX 5070 Dual OC, 12GB", best=861.08, offers=19),
            search_hit(22, "MSI GeForce RTX 5070 Ti Gaming Trio, 16GB", best=1471.26, offers=16),
            search_hit(23, "Captiva Advanced Gaming R81-412, Ryzen 7 9800X3D, 32GB RAM, GeForce RTX 5070",
                       best=2449.0, offers=1, cat="sysdiv")]
    api.on("search_product", lambda payload: search_response(
        [h for h in hits if payload["params"]["filter_category"] in ("", h["category"][-1]["id"]["cat"])]))
    result = await call("get_model_price_range", model="RTX 5070")
    assert result["category_code"] == "gra16_512"
    assert (result["min"], result["max"], result["variants"]) == (846.05, 861.08, 2)

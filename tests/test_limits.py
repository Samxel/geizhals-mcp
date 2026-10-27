"""No single call can flood the context, whatever row count it asks for."""

import pytest

import main
from conftest import ToolFailed
from samples import category_hit, deal, search_hit, search_response

pytestmark = pytest.mark.anyio


async def test_search_and_browse_clamp_rows(api, call):
    api.on("search_product", search_response(
        [search_hit(i, f"Card {i}", best=100.0 + i, offers=1) for i in range(100)], total=1000))
    api.on("categorylist", {"response": {"total": 1322, "products": [
        category_hit(i, f"Washer {i}", best=300.0 + i) for i in range(100)]}})
    search = await call("search_geizhals", query="rtx", rows=500)
    browse = await call("browse_category", category="hwaschf", rows=500)
    assert len(search["results"]) == len(browse["results"]) == main.MAX_ROWS
    assert api.sent("search_product")[0]["params"]["pagesize"] == 100
    assert api.sent("categorylist")[0]["params"]["pagesize"] == 100


async def test_deals_categories_and_matches_clamp_limit(api, call):
    api.on("bestprice_development", {"response": {"deals": [
        deal(i, percent=-10.0, best=50.0, old=55.0) for i in range(300)]}})
    api.on("search_product", search_response(
        [search_hit(i, f"Card RTX {i}", best=100.0, offers=1) for i in range(30)]))
    assert len((await call("get_deals", limit=500))["deals"]) == main.MAX_ROWS
    assert len((await call("list_categories", limit=5000))["categories"]) == main.MAX_ROWS
    assert len((await call("match_geizhals", title="Card RTX", limit=500))["candidates"]) <= main.MAX_ROWS
    with pytest.raises(ToolFailed, match="limit must be at least 1"):
        await call("get_deals", limit=0)


async def test_compare_takes_one_to_ten_ids(api, call):
    with pytest.raises(ToolFailed, match="Pass 1 to 10 product ids"):
        await call("compare_products", product_ids=list(range(1, 12)))
    with pytest.raises(ToolFailed, match="got 0"):
        await call("compare_products", product_ids=[])
    assert not api.calls

"""Only the sort keys Geizhals honours are offered, per endpoint."""

import pytest

from conftest import ToolFailed
from samples import category_hit, search_response

pytestmark = pytest.mark.anyio


async def test_search_offers_relevance_and_both_price_orders(api, call):
    api.on("search_product", search_response([]))
    for key in ("", "p", "-p"):
        await call("search_geizhals", query="rtx", sort=key)
    assert [payload["params"]["sort"] for payload in api.sent("search_product")] == ["", "p", "-p"]
    # search_product ignores these without an error, so they must not be offered
    for key in ("n", "r", "t"):
        with pytest.raises(ToolFailed, match="sort"):
            await call("search_geizhals", query="rtx", sort=key)


async def test_browse_offers_newest_and_rating_but_not_r(api, call):
    api.on("categorylist", {"response": {"total": 1, "products": [category_hit(1, "Washer", best=400.0)]}})
    for key in ("t", "p", "-p", "n", "bew"):
        await call("browse_category", category="hwaschf", sort=key)
    assert [payload["params"]["sort"] for payload in api.sent("categorylist")] == ["t", "p", "-p", "n", "bew"]
    # categorylist reads "r" as a price sort
    with pytest.raises(ToolFailed, match="sort"):
        await call("browse_category", category="hwaschf", sort="r")

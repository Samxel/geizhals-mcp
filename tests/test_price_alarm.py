"""create_price_alarm: the product is checked first, then the alarm is set."""

import pytest

from conftest import ToolFailed
from geizhals.api import UpstreamError
from samples import search_hit

pytestmark = pytest.mark.anyio

ALARM = "pricealarm/product/3767985"


@pytest.fixture
def leggings(api):
    raw = search_hit(3767985, "Icebreaker 200 Oasis Leggings", best=64.99, offers=9, cat="hosen")
    raw["sizechart"] = {"sizes": [{"name": size, "args": [size]} for size in ("S", "M", "L")]}
    api.on("query_product", {"response": [raw]})
    api.on(ALARM, {"response": {"message": "Pricealarm created !", "success": 1}})
    return api


async def test_sets_the_alarm_with_what_the_website_sends(leggings, call):
    result = await call("create_price_alarm", product_id=3767985, email=" me@example.com ",
                        price_limit=49.5, sizes=["L"], expiry_days=14)
    sent = leggings.sent(ALARM)[0]
    assert (sent["email_address"], sent["price_limit"], sent["expiry_days"]) == ("me@example.com", 49.5, 14)
    assert (sent["sizes"], sent["hloc"], sent["availability"]) == (["L"], ["at"], "l")
    assert result["status"] == "created"
    assert result["best_price"] == 64.99
    assert "confirmation mail" in result["note"]


async def test_a_second_call_reports_an_update_and_a_met_limit(leggings, call):
    leggings.on(ALARM, {"response": {"message": "Pricealarm updated !", "success": 1}})
    result = await call("create_price_alarm", product_id=3767985, email="me@example.com", price_limit=70)
    assert result["status"] == "updated"
    assert leggings.sent(ALARM)[0]["expiry_days"] == 61
    assert "fires right away" in result["note"]
    assert "sizes" not in leggings.sent(ALARM)[0]


async def test_get_product_lists_the_sizes(leggings, call):
    assert (await call("get_product", product_id=3767985))["sizes"] == ["S", "M", "L"]


@pytest.mark.parametrize("args, error", [
    ({"email": "not-an-email"}, "not an e-mail address"),
    ({"price_limit": 0}, "must be above 0"),
    ({"sizes": ["XXL"]}, "no size XXL; it comes in S, M, L"),
])
async def test_bad_arguments_never_reach_the_alarm(leggings, call, args, error):
    with pytest.raises(ToolFailed, match=error):
        await call("create_price_alarm", **{"product_id": 3767985, "email": "me@example.com",
                                             "price_limit": 40, **args})
    assert not leggings.sent(ALARM)


async def test_unknown_product_is_refused(api, call):
    # Geizhals itself would accept an alarm on any id
    api.on("query_product", {"response": []})
    with pytest.raises(ToolFailed, match="No product with id 1"):
        await call("create_price_alarm", product_id=1, email="me@example.com", price_limit=5)


async def test_an_unconfirmed_address_is_explained(leggings, call):
    leggings.on(ALARM, UpstreamError("Geizhals rejected the request (HTTP 400). Geizhals says: error "
                                     "creating confirmation request for mail, already requested.", 400))
    with pytest.raises(ToolFailed, match="still waiting for me@example.com to confirm"):
        await call("create_price_alarm", product_id=3767985, email="me@example.com", price_limit=40)

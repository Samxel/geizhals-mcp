"""Failures reach the model as is_error results that say what went wrong."""

import httpx
import pytest

import geizhals.api
from conftest import ToolFailed
from samples import search_response

pytestmark = pytest.mark.anyio


async def test_bad_arguments_explain_themselves(api, call):
    with pytest.raises(ToolFailed, match="rows must be at least 1"):
        await call("search_geizhals", query="rtx", rows=0)
    with pytest.raises(ToolFailed, match="price_min .* is above price_max"):
        await call("browse_category", category="hwaschf", price_min=500, price_max=100)


async def test_product_ids_must_be_numbers(api, call):
    with pytest.raises(ToolFailed, match="valid integer"):
        await call("get_price_history", product_id="abc")
    api.on("query_product", {"response": []})
    with pytest.raises(ToolFailed, match="No product with id 123"):
        await call("get_product", product_id="123")
    assert api.sent("query_product")[0]["query"] == "123"


async def test_nothing_searchable_is_an_error(api, call):
    with pytest.raises(ToolFailed, match="Nothing searchable left"):
        await call("match_geizhals", title="neu ovp mit rechnung")


async def test_a_400_keeps_its_hint_and_a_503_does_not(api, call):
    api.on("categorylist", geizhals.api.UpstreamError("Geizhals rejected it (HTTP 400).", 400))
    with pytest.raises(ToolFailed, match="not a valid category code"):
        await call("browse_category", category="doesnotexist")
    api.on("categorylist", geizhals.api.UpstreamError("Geizhals could not answer it (HTTP 503).", 503))
    with pytest.raises(ToolFailed) as failure:
        await call("browse_category", category="hwaschf")
    assert "category code" not in str(failure.value)

    api.on("price_history", geizhals.api.UpstreamError("Geizhals rejected it (HTTP 400).", 400))
    with pytest.raises(ToolFailed, match="no Geizhals price history"):
        await call("get_price_history", product_id=6773734585)


@pytest.fixture
def http(monkeypatch):
    """Point geizhals.api.client at a canned HTTP status and skip the retry sleeps."""
    seen = []

    async def no_sleep(_):
        pass

    def install(status, body=None):
        def handler(request):
            seen.append(request)
            return httpx.Response(status, json=body if body is not None else {})
        monkeypatch.setattr(geizhals.api, "client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        return seen

    monkeypatch.setattr(geizhals.api.asyncio, "sleep", no_sleep)
    return install


async def test_post_signs_and_returns_json(http):
    seen = http(200, search_response([]))
    assert (await geizhals.api.post("search_product", {"query": "x"}))["response"]["total"] == 0
    assert seen[0].headers["authorization"].startswith("Bearer ")


@pytest.mark.parametrize("status, message, attempts", [
    (403, "signing credentials", 1),
    (400, "check the arguments", 1),
    (503, "on their side, not the arguments", geizhals.api.MAX_RETRIES + 1),
])
async def test_post_phrases_each_failure(http, status, message, attempts):
    seen = http(status)
    with pytest.raises(geizhals.api.UpstreamError, match=message) as failure:
        await geizhals.api.post("bestprice_development", {"params": {}})
    assert failure.value.status == status
    assert len(seen) == attempts

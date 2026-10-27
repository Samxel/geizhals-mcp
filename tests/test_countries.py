"""Only the at and de sites are offered; the others disagree on currency."""

import pytest

import main
from conftest import ToolFailed
from samples import search_hit, search_response

pytestmark = pytest.mark.anyio


async def test_every_tool_offers_only_at_and_de():
    from mcp import Client
    async with Client(main.mcp) as client:
        tools = (await client.list_tools()).tools
    for tool in tools:
        props = tool.input_schema["properties"]
        if "loc" in props:
            assert props["loc"]["enum"] == ["at", "de"], tool.name
        if "hloc" in props:
            assert props["hloc"]["anyOf"][0]["items"]["enum"] == ["at", "de"], tool.name


async def test_other_sites_are_rejected(api, call):
    for loc in ("uk", "pl", "eu", "sk"):
        with pytest.raises(ToolFailed, match="loc"):
            await call("search_geizhals", query="rtx", loc=loc)
    assert not api.calls


async def test_de_site_prices_and_links(api, call):
    api.on("search_product", search_response([search_hit(1, "AMD Ryzen 7 7800X3D, 8C/16T", best=279.0, offers=3)]))
    hit = (await call("search_geizhals", query="7800x3d", loc="de", hloc=["at", "de"]))["results"][0]
    assert hit["url"].startswith("https://geizhals.de/")
    params = api.sent("search_product")[0]["params"]
    assert (params["loc"], params["hloc"]) == ("de", ["at", "de"])

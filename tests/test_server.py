"""Server-level metadata and the stdio transport."""

import sys
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

import main

pytestmark = pytest.mark.anyio

MAIN = Path(main.__file__)


async def test_tools_are_read_only_and_only_list_categories_is_local():
    async with Client(main.mcp) as client:
        tools = (await client.list_tools()).tools
    for tool in tools:
        assert tool.annotations.read_only_hint is True, tool.name
        assert tool.annotations.open_world_hint is (tool.name != "list_categories"), tool.name


async def test_tool_list_may_be_cached_for_a_day():
    async with Client(main.mcp) as client:
        listing = await client.list_tools()
    assert listing.ttl_ms == 24 * 60 * 60 * 1000
    assert listing.cache_scope == "public"


async def test_stdio_transport_serves_the_same_tools():
    server = StdioServerParameters(command=sys.executable, args=[str(MAIN), "--stdio"], cwd=str(MAIN.parent))
    async with Client(server) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        result = await client.call_tool("list_categories", {"query": "waschmaschine"})
    assert {"search_geizhals", "get_product", "list_categories"} <= names
    assert '"code":"hwaschf"' in result.content[0].text

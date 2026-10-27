"""The tool listing stays small; what the tools share lives in the instructions."""

import inspect
import json

import pytest
from mcp import Client

import main

pytestmark = pytest.mark.anyio


async def test_instructions_reach_the_client_and_name_every_tool():
    async with Client(main.mcp) as client:
        instructions = client.instructions
        tools = (await client.list_tools()).tools
    assert instructions == main.INSTRUCTIONS
    for tool in tools:
        assert tool.name in instructions, tool.name


async def test_tool_listing_stays_small():
    async with Client(main.mcp) as client:
        tools = (await client.list_tools()).tools
    sizes = {t.name: len(json.dumps(t.model_dump(exclude_none=True, by_alias=True), ensure_ascii=False))
             for t in tools}
    # was ~21.8k characters before the shared notes moved into the instructions
    assert sum(sizes.values()) < 14_000, sizes
    assert max(sizes.values()) < 2_500, sizes


async def test_descriptions_are_dedented_on_every_python():
    # Python 3.13 dedents docstrings when compiling, older versions do not
    async with Client(main.mcp) as client:
        tools = (await client.list_tools()).tools
    for tool in tools:
        assert tool.description == inspect.cleandoc(tool.description), tool.name
        assert "\n    per star" not in tool.description

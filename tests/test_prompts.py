"""The check_listing prompt walks the model through pricing a used offer."""

import pytest
from mcp import Client

import main

pytestmark = pytest.mark.anyio


async def test_check_listing_is_listed_with_its_arguments():
    async with Client(main.mcp) as client:
        [prompt] = (await client.list_prompts()).prompts
    assert prompt.name == "check_listing"
    assert {a.name: a.required for a in prompt.arguments} == {"title": True, "price": True}


async def test_check_listing_fills_in_the_ad_and_names_the_tools():
    async with Client(main.mcp) as client:
        result = await client.get_prompt("check_listing", {"title": "RTX 5070 Windforce OVP", "price": "450"})
    [message] = result.messages
    text = message.content.text
    assert message.role == "user"
    assert '"RTX 5070 Windforce OVP" asks 450 EUR' in text
    for tool in ("match_geizhals", "get_model_price_range", "get_product", "get_price_history"):
        assert tool in text

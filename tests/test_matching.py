"""Listing matching and model pricing against marketplace noise."""

import pytest

import main
from samples import search_hit, search_response

pytestmark = pytest.mark.anyio

PREBUILT = ("MIFCOM-KS Helldivers 2 Edition Ryzen 7 7700 - RTX 5070 CPU: AMD Ryzen 7 7700, 8x 3,8 GHz "
            "GRA: NVIDIA GeForce RTX 5070, 12GB (Gigabyte Windforce OC) RAM: 32GB DDR5-6000, SSD: 1TB")


async def test_marketplace_prebuilts_do_not_pass_as_the_card(api, call):
    api.on("search_product", search_response([
        search_hit(6773734585, PREBUILT, best=2449.0, offers=1, cat=None),
        search_hit(3381918, "GIGABYTE GeForce RTX 5070 Windforce OC SFF 12G, 12GB GDDR7, HDMI, 3x DP",
                   best=864.9, offers=18),
    ]))
    result = await call("match_geizhals", title="Gigabyte RTX 5070 Windforce OC 12GB NEU OVP mit Rechnung")
    first, second = result["candidates"]
    assert first["id"] == 3381918 and first["confidence"] > 0.9
    # still listed, but well under the "safe match" line of 0.8
    assert second["id"] == 6773734585 and second["confidence"] < 0.6


def test_more_ad_prose_is_dropped():
    tokens = main._title_tokens(
        "Verkaufe meine PS5 Slim Digital Edition 1TB wie neu inkl 2 Controller, nur Abholung")
    assert tokens == ["ps5", "slim", "digital", "edition", "1tb", "controller"]


async def test_model_range_counts_variants_beyond_the_first_hundred(api, call):
    cards = [search_hit(i, f"Brand{i} GeForce RTX 5070 Model{i}, 12GB", best=800.0 + i, offers=3)
             for i in range(150)]
    api.on("search_product", search_response(cards, total=150))
    result = await call("get_model_price_range", model="RTX 5070", category="gra16_512")
    assert result["variants"] == result["considered"] == 150
    assert result["max"] == 949.0
    assert api.sent("search_product")[0]["params"]["pagesize"] == 300

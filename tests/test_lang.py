"""`lang` names categories in the asked language, even where the API ignores it."""

import pytest

from samples import category_hit, search_hit, search_response

pytestmark = pytest.mark.anyio


@pytest.fixture
def gpu_search(api):
    # search_product labels at/de hits in German whatever lang says
    api.on("search_product", search_response(
        [search_hit(1, "MSI GeForce RTX 5070 Ventus, 12GB", best=846.05, offers=20)],
        categories=[{"id": "gra16_512", "name": "PCIe", "count": 82},
                    {"id": "sysnn", "name": "Diverse Komplettsysteme", "count": 40},
                    {"id": "unknown_code", "name": "Unbekannt", "count": 1}]))
    return api


async def test_search_facets_follow_lang(gpu_search, call):
    english = await call("search_geizhals", query="rtx 5070")
    german = await call("search_geizhals", query="rtx 5070", lang="de")
    # hits carry only the code; the facets name it
    assert "category" not in english["results"][0]
    assert english["results"][0]["category_code"] == "gra16_512"
    english_facets = {c["id"]: c["name"] for c in english["facets"]["categories"]}
    german_facets = {c["id"]: c["name"] for c in german["facets"]["categories"]}
    assert english_facets["sysnn"] == "Miscellaneous Systems"
    assert german_facets["sysnn"] == "Diverse Komplettsysteme"
    # not in the shipped tree: keep the API's own label
    assert english_facets["unknown_code"] == "Unbekannt"


async def test_uncategorised_hits_carry_no_code(api, call):
    api.on("search_product", search_response(
        [search_hit(2, "MIFCOM Gaming PC", best=2449.0, offers=1, cat=None)]))
    hit = (await call("search_geizhals", query="mifcom"))["results"][0]
    assert "category_code" not in hit


async def test_browse_names_its_category_in_lang(api, call):
    api.on("categorylist", {"response": {
        "total": 1, "products": [category_hit(5, "Bosch WAN28127", best=467.0)]}})
    english = await call("browse_category", category="hwaschf")
    german = await call("browse_category", category="hwaschf", lang="de")
    assert english["category"][-1] == "Washing Machines"
    assert german["category"][-1] == "Waschmaschinen"
    assert "category" not in english["results"][0]


async def test_list_categories_gives_the_path_in_lang():
    from conftest import call_tool
    english = await call_tool("list_categories", query="waschmaschinen")
    german = await call_tool("list_categories", query="washing machines", lang="de")
    assert english["categories"][0] == {"code": "hwaschf", "path": "Home & Living / Washing & Drying / Washing Machines"}
    assert german["categories"][0]["path"].endswith("Waschmaschinen")

"""get_deals scans every page of the feed, not just the first."""

import pytest

import main
from conftest import ToolFailed
from samples import deal

pytestmark = pytest.mark.anyio


def paged(pages, *, last_page=None):
    """A bestprice_development stand-in serving `pages` by their `pg` param."""
    def respond(payload):
        pg = payload["params"]["pg"]
        return {"response": {"total": sum(len(p) for p in pages),
                             "pager": {"first_page": 1, "last_page": last_page or len(pages)},
                             "deals": pages[pg - 1] if pg <= len(pages) else []}}
    return respond


async def test_the_biggest_drop_on_the_last_page_is_found(api, call):
    api.on("bestprice_development", paged([
        [deal(1, percent=-20.0, best=80.0, old=100.0), deal(2, percent=-10.0, best=90.0, old=100.0)],
        [deal(3, percent=-30.0, best=70.0, old=100.0), deal(1, percent=-20.0, best=80.0, old=100.0)],
        [deal(4, percent=-83.0, best=10.07, old=59.9)],
    ]))
    result = await call("get_deals", limit=3)
    assert [d["id"] for d in result["deals"]] == [4, 3, 1]
    assert result["scanned"] == 4  # deal 1 sat on two pages
    # the usual four pages are asked for at once; the fourth is past the end
    assert sorted(p["params"]["pg"] for p in api.sent("bestprice_development")) == [1, 2, 3, 4]


async def test_pages_past_the_end_are_ignored(api, call):
    # Geizhals answers a page past the end with the last page again
    only = [deal(1, percent=-20.0, best=80.0, old=100.0)]
    api.on("bestprice_development", lambda payload: {"response": {
        "total": 1, "pager": {"last_page": 1}, "deals": only}})
    result = await call("get_deals")
    assert result["scanned"] == 1
    assert len(api.sent("bestprice_development")) == main.DEALS_USUAL_PAGES


async def test_a_long_feed_is_read_to_its_last_page(api, call):
    pages = [[deal(pg * 10 + i, percent=-10.0 - pg, best=50.0, old=60.0) for i in range(2)]
             for pg in range(6)]
    api.on("bestprice_development", paged(pages))
    result = await call("get_deals", limit=1)
    assert result["scanned"] == 12
    assert result["deals"][0]["change_percent"] == -15.0
    assert sorted(p["params"]["pg"] for p in api.sent("bestprice_development")) == [1, 2, 3, 4, 5, 6]


async def test_page_count_is_bounded(api, call):
    api.on("bestprice_development", paged([[deal(1, percent=-20.0, best=80.0, old=100.0)]], last_page=500))
    await call("get_deals")
    assert len(api.sent("bestprice_development")) == main.DEALS_MAX_PAGES


async def test_offset_pages_through_the_matches(api, call):
    api.on("bestprice_development", paged([[deal(i, percent=-float(i), best=50.0, old=60.0)
                                            for i in range(1, 46)]]))
    first = await call("get_deals", limit=20)
    second = await call("get_deals", limit=20, offset=first["next_offset"])
    last = await call("get_deals", limit=20, offset=second["next_offset"])
    assert [d["id"] for d in first["deals"]][:2] == [45, 44]
    assert (first["next_offset"], second["next_offset"]) == (20, 40)
    assert last["count"] == 5 and "next_offset" not in last
    with pytest.raises(ToolFailed, match="offset must not be negative"):
        await call("get_deals", offset=-1)


async def test_paging_on_reuses_the_feed_until_it_goes_stale(api, call, monkeypatch):
    api.on("bestprice_development", paged([[deal(1, percent=-20.0, best=80.0, old=100.0)]]))
    await call("get_deals")
    await call("get_deals", offset=1)
    assert len(api.sent("bestprice_development")) == main.DEALS_USUAL_PAGES
    # another country is another feed
    await call("get_deals", loc="de")
    assert len(api.sent("bestprice_development")) == 2 * main.DEALS_USUAL_PAGES
    monkeypatch.setattr(main, "DEALS_CACHE_SECONDS", 0)
    await call("get_deals")
    assert len(api.sent("bestprice_development")) == 3 * main.DEALS_USUAL_PAGES

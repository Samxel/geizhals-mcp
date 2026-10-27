"""Price history: window vs all-time summaries and a series that stays short."""

import pytest

import main

pytestmark = pytest.mark.anyio

DAY_MS = 86_400_000
START_MS = 1790380800000  # 2026-09-26


def history(prices, current_best=864.9):
    return {"meta": {"min": 519.0, "max": 889.0, "first_ts": 1742169600, "last_ts": 1792972800,
                     "current_best": current_best},
            "response": [[START_MS + i * DAY_MS, price, 1] for i, price in enumerate(prices)]}


def test_changes_keep_moves_and_the_last_point():
    points = [["d1", 10.0], ["d2", 10.0], ["d3", 12.0], ["d4", 12.0], ["d5", 12.0]]
    assert main._changes(points) == [["d1", 10.0], ["d3", 12.0], ["d5", 12.0]]
    assert main._changes([["d1", 10.0]]) == [["d1", 10.0]]
    assert main._changes([]) == []


async def test_a_flat_month_is_a_handful_of_points(api, call):
    prices = [859.9] * 29 + [864.9] * 3
    api.on("price_history", history(prices))
    result = await call("get_price_history", product_id=3381918)
    assert result["points"] == 32
    assert result["series"] == [["2026-09-26", 859.9], ["2026-10-25", 864.9], ["2026-10-27", 864.9]]
    assert result["window_change_percent"] == 0.6
    assert result["available"] is True
    assert (result["alltime_min"], result["alltime_max"]) == (519.0, 889.0)


async def test_day_and_week_granularity_still_work(api, call):
    api.on("price_history", history([100.0] * 14))
    daily = await call("get_price_history", product_id=1, granularity="day")
    weekly = await call("get_price_history", product_id=1, granularity="week")
    assert len(daily["series"]) == 14
    assert len(weekly["series"]) == 3


async def test_window_is_snapped_and_the_series_can_be_skipped(api, call):
    api.on("price_history", history([100.0, 90.0], current_best=None))
    result = await call("get_price_history", product_id=1, days=100, include_series=False)
    assert api.sent("price_history")[0]["params"]["days"] == 91
    assert "series" not in result
    assert result["available"] is False
    assert result["last_price"] == 90.0

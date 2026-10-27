"""get_product lists the cheapest shop offers with shipping and stock."""

import pytest

from conftest import ToolFailed
from samples import search_hit

pytestmark = pytest.mark.anyio


def offer(shop, price, *, shipping=None, stock="lagernd", rating=4.73, count=1618):
    return {
        "price": {"value": price, "currency": "EUR"},
        "avl": {"descr": [{"text": stock}]} if stock else {},
        "shop": {"name": f"{shop} GmbH", "merchant_name": shop,
                 "shipping": {"at": shipping} if shipping is not None else {},
                 "rating": {"rating": rating, "count": count}},
    }


@pytest.fixture
def product(api):
    raw = search_hit(3381918, "GIGABYTE RTX 5070 Windforce OC SFF", best=864.9, offers=3)
    raw["gtin"] = ["4719331355715"]
    raw["offers"] = [
        offer("alza.at", 864.9, shipping={"b": {"shipping_price": 4.49}, "pp": {"shipping_price": 4.49}},
              stock="Versandlager: lagernd, Lieferzeit 1-2 Werktage\nFiliale Wien: abholbereit"),
        # a negative entry is a prepayment discount, not a shipping cost
        offer("e-tec.at", 956.98, shipping={"cc": {"shipping_price": 0}, "pa": {"shipping_price": -4.78}}),
        offer("Cyberport Stores", 959.0, shipping=None, stock="nicht lagernd", rating=1.986),
    ]
    api.on("query_product", {"response": [raw]})
    return api


async def test_offers_carry_price_shipping_total_and_stock(product, call):
    result = await call("get_product", product_id=3381918)
    alza, etec, store = result["offers"]
    assert alza == {"shop": "alza.at", "price": 864.9, "shipping": 4.49, "total": 869.39,
                    "availability": "Versandlager: lagernd, Lieferzeit 1-2 Werktage",
                    "shop_rating": 4.7, "shop_rating_count": 1618}
    assert (etec["shipping"], etec["total"]) == (0.0, 956.98)
    assert "shipping" not in store and "total" not in store
    assert result["gtin"] == ["4719331355715"]
    assert result["shop"] == "alza.at"


async def test_n_offers_trims_and_is_bounded(product, call):
    assert len((await call("get_product", product_id=3381918, n_offers=1))["offers"]) == 1
    await call("get_product", product_id=3381918, n_offers=500)
    assert product.sent("query_product")[-1]["params"]["n_offers"] == 20
    with pytest.raises(ToolFailed, match="n_offers must be at least 1"):
        await call("get_product", product_id=3381918, n_offers=0)

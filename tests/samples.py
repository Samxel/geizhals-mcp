"""Canned Geizhals API responses, trimmed to the fields main.py reads but shaped
like the live ones (see search_api.md), so the suite runs offline."""

CATEGORY_LABELS = {
    "gra16_512": ["Hardware", "Grafikkarten", "PCIe"],
    "sysdiv": ["Hardware", "Komplettsysteme", "Komplettsysteme"],
    "umtsover": ["Telefon", "Mobiltelefone", "Handys ohne Vertrag"],
    "hwaschf": ["Haushalt", "Waschen & Trocknen", "Waschmaschinen"],
}


def category_path(code):
    """A search hit's ``category``: the label path, the leaf carrying the code."""
    if code is None:
        return None
    labels = CATEGORY_LABELS.get(code, ["Hardware", "Misc", "Misc"])
    path = [{"label": label, "id": {"m": i}} for i, label in enumerate(labels[:-1])]
    return path + [{"label": labels[-1], "id": {"cat": code}}]


def search_hit(gzhid, name, *, best=None, avg=None, offers=0, cat="gra16_512",
               shop="alza.at", variant_id=1, rating_stars=None, rating_count=None,
               bestprices=None, listed_since="2025-01-07T12:22:17+01:00"):
    return {
        "gzhid": gzhid,
        "variant_id": variant_id,
        "product": name,
        "manufacturer_name": name.split()[0],
        "category": category_path(cat),
        "prices": {"best": best, "avg": avg},
        "offer_count": offers or None,
        "offers": [{"shop": {"name": shop}, "pricing": {"loc_currency": "EUR"}}] if offers else [],
        "rating_stars": rating_stars,
        "rating_percent": rating_stars * 20 if rating_stars else None,
        "rating_count": rating_count,
        "images": [f"/pix/{gzhid}-n.webp"],
        "urls": {"overview": f"/{name.split(',')[0].lower().replace(' ', '-')}-a{gzhid}.html"},
        "mpn": None,
        "listed_since": listed_since,
        "bestprices": bestprices or {},
    }


def search_response(hits, *, total=None, categories=None, manufacturers=None):
    return {"response": {
        "total": len(hits) if total is None else total,
        "products": hits or None,
        "facet_aggregates": {
            "categories": categories,
            "manufacturer": manufacturers,
            "price_range": {"min": 0, "max": 5999},
        },
    }}


def deal(gzhid, *, percent, best, old=None, top=False, rank=100, ts=1793100000, alltime=False):
    return {
        "id": gzhid,
        "product": f"Product {gzhid}",
        "manufacturer_name": "Brand",
        "category_path": "Hardware > Graphics Cards > PCIe",
        "cat": "gra16_512",
        "change_in_percent": percent,
        "change_in_local": round(best - (old or best), 2),
        "old_price": old,
        "best_price": best,
        "alltime_best": int(alltime),
        "top_deal": int(top),
        "rank": rank,
        "offer_count": 5,
        "hname": "Amazon.at",
        "timestamp": ts,
        "image_thumb": f"https://gzhls.at/pix/{gzhid}-n.webp",
        "best_deep_link": "https://geizhals.at/redir/" + "A" * 300,
    }


def category_hit(gzhid, name, *, best, offers=5, rating_stars=None, rating_count=None):
    return {
        "id": gzhid,
        "variant_id": 1,
        "product": name,
        "product_for_sort": name,
        "best_price": best,
        "pricing": {"loc_currency": "EUR", "loc_value": best},
        "offer_count": offers,
        "best_merch_name": "Köck",
        "rating_stars": rating_stars,
        "rating_percent": rating_stars * 20 if rating_stars else None,
        "rating_count": rating_count,
        "image_n": f"https://gzhls.at/pix/{gzhid}-n.webp",
        "product_link": f"https://geizhals.at/{name.lower().replace(' ', '-')}-a{gzhid}.html?vl=at&hloc=at",
        "mpn": None,
    }

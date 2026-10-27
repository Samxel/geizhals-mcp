# Geizhals API

The Geizhals mobile app talks to a single JSON API. All calls are `POST` with a
JSON body.

## Endpoint

```
POST https://api.geizhals.net/gh/v9/<method>
```

`api.geizhals.net` is a direct Geizhals host (not behind Cloudflare, unlike the
`geizhals.at` website). Responses are JSON, gzip-encoded.

## Headers

| Header | Value |
|---|---|
| `authorization` | `Bearer <jwt>` (see [Auth](#auth)) |
| `auth-role` | `mobileapp-2026-android-3.12.7` |
| `user-agent` | `Geizhals/3.13.1 (Android 14; ...)` |
| `content-type` | `application/json` |

## Auth

Every request carries a per-request `HS256` JWT the app signs **locally**:

```
header  {"alg":"HS256","typ":"JWT"}
payload {"token_id":"mobileapp-2026-android-3.12.7",
         "timestamp":<unix>, "iat":<unix>,
         "request_fingerprint":"<sha256-style hex>"}
```

`request_fingerprint` binds the token to the request: it is a `sha256` hex
digest over a canonical string built from the method, host, query and body (see
`request_fingerprint` in `main.py`), not a plain `sha256(body)`. The `HS256`
secret is symmetric, so the app signs offline; it is reverse-engineered from the
app's Flutter binary (`libapp.so`) and hardcoded in `main.py` as
`GH_HMAC_SECRET`. A wrong or missing token gives `403`, and because both the
secret and the scheme are hardcoded they can drift whenever Geizhals rotates
them.

## Common params

Most methods take a `params` object with:

| Field | Meaning |
|---|---|
| `loc` | pricing site / country (`at`, `de`, `eu`, `uk`, `pl`; see [Sites](#sites)) |
| `hloc` | list of shop countries to include |
| `lang` | response language (`en`, `de`) |
| `pagesize` / `offset` | paging. `pagesize` is validated against a fixed set (1, 5, 10, 30, 100, 300, 1000); any other value returns 400 |
| `n_offers` | how many offers to include per product |

## Methods

| Method | Body | Returns |
|---|---|---|
| `search_product` | `{query, params}` | `response.products[]`, `facet_aggregates` (categories, manufacturer, price_range), `total` |
| `query_product` | `{query, type:"id", params}` | `response[]` full product (prices, bestprices, offer_count, rating, images, urls, test_reviews) |
| `products_details` | `{id:[...], params}` | `response[]` best_price, offer_count, pricing, images |
| `price_history` | `{id, params:{days, loc}}` | `response[] = [ts_ms, price, flag]`, `meta{min,max,first_ts,last_ts,current_best}`. `days` must be one of 31/91/183/365 (else 400) |
| `query_product_ratings` | `{product_id, offset, pagesize, sort, params}` | aggregate_star_rating, per_star_rating_count, ... |
| `query_variant` | `{variant, params}` | `response` variant offers |
| `categorylist` | `{category:<code>, params}` | `response` products of a category |
| `categories` | `{params:{lang}}` | `categories[]` full tree (title, id, childs) |
| `compare_products` | `{ids:[...], params}` | side-by-side comparison (note the key is `ids`, not `id`) |
| `bestprice_development` | `{params:{limit, price_range, loc, hloc}}` | `response.deals[]` price drops (`change_in_percent`, `change_in_local`, `old_price`, `best_price`, `alltime_best`, `top_deal`, `rank`) |
| `top_products` / `new_products` / `top_categories` / `hero` | `{params}` | home-screen widgets |

There is also a `/usercontent/v0/*` namespace (price alarms, push settings,
feedback) tied to a user account.

## Response quirks

- `search_product` hits carry the live price in `prices.best` / `prices.avg`
  next to `offer_count` and `offers[].shop.name`, so a search already answers
  "what does it cost" — `query_product` is only needed for offers, ratings and images.
- Uncategorised hits (Amazon passthrough listings) come back with
  `category: null`, not `[]`, and their `product` name has raw `<br>` in it.
  Zero-hit responses null out `products` and the facet lists the same way.
- `price_history`'s `meta` is **all-time**, not window-scoped: `min`, `max`,
  `first_ts` and `last_ts` describe the product's whole listed history even
  when `days=31`. Only `response[]` respects the window.
- `meta.current_best` is `null` once a product has no live offers; the series
  still holds its last recorded price, which is the only way to price a
  discontinued product.
- `bestprice_development` honours `limit` (tested up to 300) and pages with
  `pg`; `offset` and `page` are ignored. `pager.last_page` says how many pages
  there are (about four of 300), and a `pg` past the end repeats the last page.
  Each page takes ~3s, and the biggest drops are as likely to be on the last
  page as on the first. `boundary_filters` reports the drop range (up to 90%),
  but none of the `drop_percent` param spellings tried filtered anything.
- `query_product_ratings` always answers with a `geizhals.de` `ratings_url`,
  whatever `loc` says.
- `facet_aggregates.price_range.min` is the filter widget's floor and is
  almost always `0`; it is not the cheapest hit. `categorylist`'s top-level
  `price_range`, by contrast, is real.
- `bestprice_extrema=1` adds a per-hit `bestprices{min,max,first,last}` to
  `search_product` without disturbing `prices`/`offer_count`, which is the only
  way to price a hit that has no live offers without a second request.
- `compare_products` unions the property list across every id in the call, so a
  product gets empty values for properties that belong to the others.
- `price_history` answers `400` for products with no tracked history at all
  (uncategorised marketplace listings), which looks the same as a bad `days`.
- `sort: "p"` is a filter as well as an order: products with no live price
  cannot be price-ordered and drop out of `products` **and** `total` (289 hits
  become 146). The other sort keys leave the population alone.
- `variant_id` identifies a product *family*, not a product — every sibling
  variant shares one, and `variant_count` says how many there are.
- `category_suggestions` comes back empty in practice, even with
  `category_suggestions=1` and `category_suggestions_details=1`.
- `search_product` caps `total` at 1000; a broad query never reports more.
- `search_product` ignores `lang` for category labels: hits on the at/de sites
  are always labelled in German. `query_product` and `bestprice_development`
  do honour it. `compare_products` spec labels and values are German either
  way.
- `query_product_ratings` aggregates (`aggregate_star_rating`,
  `per_star_rating_count`) always cover every rating; `pagesize` and `sort`
  only page the review texts.
- `bestprice_development`'s `best_deep_link` is a ~300 character tracking
  redirect to the shop, not the product page. `https://geizhals.at/a<id>.html`
  is the short product link.

## Sort keys

Each endpoint takes its own set, and they fail differently:

| Endpoint | Honoured | Anything else |
|---|---|---|
| `search_product` | `""`/`t` relevance, `p` price up, `-p` price down | silently ignored (relevance) |
| `categorylist` | `t` relevance, `p` / `-p` price, `n` newest listings, `bew` best rated, `-bew` the reverse | 400, except `r`, which sorts by price like `p` |

## Offers

`query_product` returns up to `n_offers` offers, cheapest first:

- `price.value` is the offer price; `shop.merchant_name` is the shop's site
  name (`alza.at`), `shop.name` the company (`Alza.at GmbH`).
- `shop.shipping[<loc>]` maps a payment method (`b`, `cc`, `pp`, `pa`, `cod`)
  to `{shipping_price, shipping_option}`. A negative `shipping_price` is a
  discount for that payment method (usually prepayment), not a shipping cost.
  A shop without an entry only sells for pickup.
- `avl.descr[].text` is the shop's own stock note in German; the first line is
  mail order, further lines list pickup branches. `avl.best_code` does not map
  to a stable meaning.
- `shop.rating.rating` is the shop's rating out of 5 and `shop.rating.count`
  how many ratings it has. `shop.ratings` uses the inverse 1 (best) to 5 scale.
- `gtin` on the product is a list of EAN/GTIN codes.

## Sites

`loc` picks the country site, but only `at` and `de` are consistent:

- On `pl` and `uk`, `search_product`'s `prices.best` / `avg` are EUR
  (`eur_value`) while the offers' `pricing.loc_currency` says PLN/GBP;
  `categorylist` answers in the local currency, `query_product`'s
  `bestprices` and `price_history` in PLN/GBP on `pl`. `eu` mixes in values
  from other sites too.
- `sk` answers every call with a 400.
- `bestprice_development` answers 503 for anything but `at` and `de`.
- `categorylist` rejects `vl: "eu"` with a 400.
- On the `at` and `de` sites, `hloc` only distinguishes `at` and `de`: `pl` or
  `uk` alone are ignored (the result equals `[loc]`) and `eu` means both.

## Categories

`categories` returns a nested tree. Ids come in layers: `{"m":1}` main group,
`{"o":53}` overview, `{"cat":"nb"}` the **category code** used by `categorylist`
and the `filter_category` search param, and `{"xf":"..."}` a filter. Product and
image urls are relative to `https://geizhals.at` and `https://gzhls.at`.

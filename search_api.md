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
| `loc` | pricing site / country (`at`, `de`, `eu`, ...) |
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
  "what does it cost" — `query_product` is only needed for ratings and images.
- Uncategorised hits (Amazon passthrough listings) come back with
  `category: null`, not `[]`, and their `product` name has raw `<br>` in it.
  Zero-hit responses null out `products` and the facet lists the same way.
- `price_history`'s `meta` is **all-time**, not window-scoped: `min`, `max`,
  `first_ts` and `last_ts` describe the product's whole listed history even
  when `days=31`. Only `response[]` respects the window.
- `meta.current_best` is `null` once a product has no live offers; the series
  still holds its last recorded price, which is the only way to price a
  discontinued product.
- `bestprice_development` honours `limit` (tested up to 300) but ignores
  `offset`, so filtering and sorting can only work over one fetched page.
- `query_product_ratings` always answers with a `geizhals.de` `ratings_url`,
  whatever `loc` says.
- `facet_aggregates.price_range.min` is the filter widget's floor and is
  almost always `0`; it is not the cheapest hit.

## Categories

`categories` returns a nested tree. Ids come in layers: `{"m":1}` main group,
`{"o":53}` overview, `{"cat":"nb"}` the **category code** used by `categorylist`
and the `filter_category` search param, and `{"xf":"..."}` a filter. Product and
image urls are relative to `https://geizhals.at` and `https://gzhls.at`.

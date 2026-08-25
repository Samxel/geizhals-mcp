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
| `pagesize` / `offset` | paging |
| `n_offers` | how many offers to include per product |

## Methods

| Method | Body | Returns |
|---|---|---|
| `search_product` | `{query, params}` | `response.products[]`, `facet_aggregates` (categories, manufacturer, price_range), `total` |
| `query_product` | `{query, type:"id", params}` | `response[]` full product (bestprices, rating, images, urls, test_reviews) |
| `products_details` | `{id:[...], params}` | `response[]` best_price, offer_count, pricing, images |
| `price_history` | `{id, params:{days, loc}}` | `response[] = [ts_ms, price, flag]`, `meta{min,max,last_ts,current_best}`. `days` must be one of 31/91/183/365 (else 400) |
| `query_product_ratings` | `{product_id, offset, pagesize, sort, params}` | aggregate_star_rating, per_star_rating_count, ... |
| `query_variant` | `{variant, params}` | `response` variant offers |
| `categorylist` | `{category:<code>, params}` | `response` products of a category |
| `categories` | `{params:{lang}}` | `categories[]` full tree (title, id, childs) |
| `compare_products` | `{ids:[...], params}` | side-by-side comparison (note the key is `ids`, not `id`) |
| `bestprice_development` | `{params:{limit, price_range, loc, hloc}}` | `response.deals[]` price drops (`change_in_percent`, `change_in_local`, `old_price`, `best_price`, `alltime_best`, `top_deal`, `rank`) |
| `top_products` / `new_products` / `top_categories` / `hero` | `{params}` | home-screen widgets |

There is also a `/usercontent/v0/*` namespace (price alarms, push settings,
feedback) tied to a user account.

## Categories

`categories` returns a nested tree. Ids come in layers: `{"m":1}` main group,
`{"o":53}` overview, `{"cat":"nb"}` the **category code** used by `categorylist`
and the `filter_category` search param, and `{"xf":"..."}` a filter. Product and
image urls are relative to `https://geizhals.at` and `https://gzhls.at`.

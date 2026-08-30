<h1 align="center">geizhals-mcp</h1>

An MCP server that lets an AI search [Geizhals](https://geizhals.at) price
comparison data: products, best prices, price history, ratings and categories.
It wraps the Geizhals mobile app's API (`api.geizhals.net/gh/v9`) and returns the
important fields to the AI.

<p align="center">
  <a href="https://geizhals.at/"><img alt="Products tracked" src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2FSamxel%2Fgeizhals-mcp%2Fmain%2Fcoverage.json&query=%24.products&label=products&color=green&suffix=%20tracked&cacheSeconds=3600"></a>
  <a href="https://geizhals.at/"><img alt="Prices compared" src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2FSamxel%2Fgeizhals-mcp%2Fmain%2Fcoverage.json&query=%24.prices&label=prices&color=ff7300&suffix=%20compared&cacheSeconds=3600"></a>
  <a href="https://geizhals.at/"><img alt="Merchants" src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2FSamxel%2Fgeizhals-mcp%2Fmain%2Fcoverage.json&query=%24.merchants&label=merchants&color=1e6fff&suffix=%20shops&cacheSeconds=3600"></a>
</p>

## Highlights

- **Best price across every shop**  
  Find a product and get its **best price, full price range, star ratings and test-review count**, aggregated over all Geizhals merchants instead of a single listing.

- **Know when to buy**  
  Pull the **full price history** and the **current price drops** (Schnäppchen), sortable by biggest percent off, so a model can answer "is this cheap right now or should I wait".

- **From keyword to category**  
  Search by free text or browse the **complete Geizhals category tree** (2200+ categories shipped with the server) to drill into exactly the right segment, then compare a shortlist side by side.

- **Price a used listing**  
  `match_geizhals` turns a classifieds ad headline into the Geizhals products it could be (with a confidence score), and `get_model_price_range` gives the new-price range across every variant of a model — the two numbers a "is this second-hand offer a deal" answer needs.

## Tools

**`search_geizhals(query, ...)`**

Search products by keyword. Filters for country (`loc`/`hloc`), category and
manufacturer, plus sorting and paging. Every hit carries its current
`best_price`, `avg_price`, `offer_count`, `currency`, cheapest `shop`,
`rating_*` and an `available` flag, so a plain price-or-rating question needs no
follow-up call. Hits with no live offers add `alltime_price_min` /
`alltime_price_max` / `alltime_last_date`, so a list of discontinued hardware is
priceable without a call per hit. Also returns facet aggregates (categories,
manufacturers) to refine with.

Note that `sort="p"` narrows the result set as well as ordering it — Geizhals
cannot price-order a product that has no price, so unavailable products leave
both `results` and `total`.

**`get_product(product_id)`**

Full detail of one product: current best price and offer count, name, category,
rating, images, offer link, all-time price range and test-review count. A
product with no live offers gets its `last_known_price` / `last_known_date`
filled in instead of a bare `null`.

**`get_price_history(product_id, days=31)`**

Window (`window_min/max/avg/change_percent`) and all-time (`alltime_min/max`)
summaries kept strictly apart, plus a `[iso_date, price]` series.
`include_series=False` and `granularity="week"` keep long windows cheap.

**`get_product_ratings(product_id)`**

Average rating, totals, per-star counts and the reviews link.

**`browse_category(category, ...)`**

List the products in a category by its code, with price bounds and sorting.
Hits use the same field names as `search_geizhals`, and the `price_range`
returned alongside them is the category's real one (the search facet's is not).

**`compare_products(product_ids)`**

Compare several products side by side, specs included — properties that don't
apply to a product are dropped rather than shown as empty. Discontinued
products carry their last known price.

**`get_deals(sort="percent", ...)`**

Current price drops: products whose best price just fell, with the percent and
amount off. Sort by biggest `percent` drop, `price`, `latest`, `popularity` or
`top` deals, and filter with `min_discount_percent` / `max_price`. `limit` is a
target number of matches, not a fetch size.

**`get_model_price_range(model, ...)`**

What a whole model costs right now across all its variants — `min`, `median`,
`max` and the five cheapest — instead of one specific board partner card.
Sibling models (`4070 Ti`, `4070 Super`) are kept out, and the result is always
scoped to one category: an unscoped search for a pricey product is dominated by
cases and water blocks below it and prebuilt systems above it, so the category
is detected when you don't pass one and reported back as `category_code`.

**`match_geizhals(title, ...)`**

Resolve a free-form listing title ("Gigabyte RTX 5070 Windforce OC 12GB NEU OVP
mit Rechnung") to Geizhals products, each with a 0–1 `confidence` and its live
price. When the top candidates are too close to separate, or nothing scores
convincingly, a `note` says so rather than letting a coin-flip look like an
answer.

**`list_categories(query)`**

Browse Geizhals' category tree to find the category codes `browse_category`
takes. Matches English or German names ("graphics cards" and "grafikkarten"
both work). The full tree ships with the server in `data/categories.json`.

## Setup

Requires Python 3.9+.

```bash
pip install -r requirements.txt
```

## Run

```bash
python main.py
```

The server starts over streamable HTTP and prints where it's listening:

```
Starting geizhals-mcp server on http://127.0.0.1:8000/mcp
```

Point your MCP client at that URL. Host, port and path live at the top of
`main.py`.

## Use it from Claude Desktop

Claude Desktop launches MCP servers over stdio, so bridge to this HTTP server
with [`mcp-remote`](https://www.npmjs.com/package/mcp-remote) (needs
[Node.js](https://nodejs.org)):

1. Start the server (`python main.py`) and leave it running.
2. In Claude Desktop open **Settings > Developer > Edit Config**; that reveals
   `claude_desktop_config.json`. Open it and add the `geizhals` entry:

   ```json
   {
     "mcpServers": {
       "geizhals": {
         "command": "cmd",
         "args": ["/c", "npx", "-y", "mcp-remote", "http://127.0.0.1:8000/mcp"]
       }
     }
   }
   ```

   On macOS/Linux drop the Windows wrapper: use `"command": "npx"` with
   `"args": ["-y", "mcp-remote", "http://127.0.0.1:8000/mcp"]`.
3. Save the file and **restart Claude Desktop**.

## Notes

- `data/categories.json` is a snapshot of Geizhals' category tree (title,
  title_de, id, children). `main.py` loads it for `list_categories`, which
  matches queries against both the English and German names.
- `coverage.json` holds the catalogue counts shown in the badges above.
  `scripts/update_coverage.py` refreshes it from the Geizhals homepage and a
  daily GitHub Action commits any change.
- API details are documented in [`search_api.md`](search_api.md).
- This uses Geizhals' internal mobile API, not an official one. Be nice to it.

## Troubleshooting

**`403 invalid request_fingerprint in payload`** — the HMAC secret or
signing scheme in `main.py` (`GH_HMAC_SECRET`, `request_fingerprint`,
`API_HOST`) no longer matches what the live Geizhals app sends. This is
reverse-engineered from the app and hardcoded, so it can drift whenever
Geizhals rotates the secret or changes the fingerprint scheme.

**`400 Bad Request`** — Geizhals validates several params against fixed sets
and rejects anything else outright. The two that bite: `pagesize` must be one
of 1/5/10/30/100/300/1000, and `price_history`'s `days` must be 31/91/183/365.
The tools snap `rows` and `days` to allowed values, so a 400 usually means
another param drifted; the response body names the offending field. Tools
surface it as `{"error": "..."}` rather than raising the raw HTTP error, so the
model sees what went wrong instead of an internal URL.

## Disclaimer

This is an independent, unofficial project and is not affiliated with, endorsed
by, or connected to Geizhals. "Geizhals" and all related trademarks belong to
their respective owners.

It's published for educational and research purposes only. It talks to Geizhals'
internal API, which is not meant for public use and may break or change at any
time. You are responsible for how you use it: respect Geizhals' Terms of Service,
robots rules and applicable law, and don't hammer their servers.

## License

[`MIT LICENSE`](LICENSE). Provided "as is", without warranty.

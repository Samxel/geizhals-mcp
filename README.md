<h1 align="center">geizhals-mcp</h1>

An MCP server that lets an AI search [Geizhals](https://geizhals.at) price
comparison data: products, best prices, price history, ratings and categories.
It wraps the Geizhals mobile app's API (`api.geizhals.net/gh/v9`) and returns the
important fields to the AI.

## Tools

**`search_geizhals(query, ...)`**

Search products by keyword. Filters for country (`loc`/`hloc`), category and
manufacturer, plus sorting and paging. Returns the hits and facet aggregates
(categories, manufacturers, price range) to refine with.

**`get_product(product_id)`**

Full detail of one product: name, rating, best-price range, images, offer link
and how many test reviews it has.

**`get_price_history(product_id, days=31)`**

The min/max/current summary plus the raw `[timestamp, price, flag]` series.

**`get_product_ratings(product_id)`**

Average rating, totals, per-star counts and the reviews link.

**`browse_category(category, ...)`**

List the products in a category by its code, with price range and sorting.

**`compare_products(product_ids)`**

Compare several products side by side.

**`get_deals(sort="percent", ...)`**

Current price drops (Geizhals' Bestpreis-Entwicklung / Schnäppchen): products
whose best price just fell, with the percent and amount off. Sort by biggest
`percent` drop, `price`, `latest`, `popularity` or `top` deals, and filter with
`min_discount_percent`.

**`list_categories(query)`**

Browse Geizhals' category tree to find the category codes `browse_category`
takes. The full tree ships with the server in `data/categories.json`.

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

- `data/categories.json` is a snapshot of Geizhals' category tree (title, id,
  children). `main.py` loads it for `list_categories`.
- API details are documented in [`search_api.md`](search_api.md).
- This uses Geizhals' internal mobile API, not an official one. Be nice to it.

## Troubleshooting

**`403 invalid request_fingerprint in payload`** — the HMAC secret or
signing scheme in `main.py` (`GH_HMAC_SECRET`, `request_fingerprint`,
`API_HOST`) no longer matches what the live Geizhals app sends. This is
reverse-engineered from the app and hardcoded, so it can drift whenever
Geizhals rotates the secret or changes the fingerprint scheme — there's no
config to fix, the constants need updating to match the current app.

**`403` with no body / a different error** — check the response body, not
just the status: `_post` only raises a generic `RuntimeError("Error")` on
403, so add a temporary print of `response.text` in `_post` (or replicate
the request manually) to see the real reason before assuming it's the
fingerprint.

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

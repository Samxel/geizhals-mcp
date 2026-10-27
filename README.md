<h1 align="center">geizhals-mcp</h1>

An MCP server that lets an AI search [Geizhals](https://geizhals.at) price
comparison data: products, best prices, price history, ratings and categories.
It wraps the Geizhals mobile app's API (`api.geizhals.net/gh/v9`) and returns the
important fields to the AI.

<p align="center">
  <a href="https://geizhals.at/"><img alt="Products tracked" src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2FSamxel%2Fgeizhals-mcp%2Fcoverage%2Fcoverage.json&query=%24.products&label=products&color=green&suffix=%20tracked&cacheSeconds=3600"></a>
  <a href="https://geizhals.at/"><img alt="Prices compared" src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2FSamxel%2Fgeizhals-mcp%2Fcoverage%2Fcoverage.json&query=%24.prices&label=prices&color=ff7300&suffix=%20compared&cacheSeconds=3600"></a>
  <a href="https://geizhals.at/"><img alt="Merchants" src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2FSamxel%2Fgeizhals-mcp%2Fcoverage%2Fcoverage.json&query=%24.merchants&label=merchants&color=1e6fff&suffix=%20shops&cacheSeconds=3600"></a>
</p>

<p align="center">
  <a href="#highlights">Highlights</a> ·
  <a href="#setup">Setup</a> ·
  <a href="#run">Run</a> ·
  <a href="#add-it-to-claude-and-other-mcp-clients">Add to Claude</a> ·
  <a href="#tools">Tools</a> ·
  <a href="#notes">Notes</a> ·
  <a href="#tests">Tests</a> ·
  <a href="#troubleshooting">Troubleshooting</a> ·
  <a href="#disclaimer">Disclaimer</a> ·
  <a href="#license">License</a>
</p>

## Highlights

- **Best price across every shop**  
  Find a product and get its **best price, the cheapest shops with shipping and stock, full price range, star ratings and test-review count**, aggregated over all Geizhals merchants instead of a single listing.

- **Know when to buy**  
  Pull the **full price history** and the **current price drops** (Schnäppchen), sortable by biggest percent off, so a model can answer "is this cheap right now or should I wait".

- **From keyword to category**  
  Search by free text or browse the **complete Geizhals category tree** (2200+ categories shipped with the server) to drill into exactly the right segment, then compare a shortlist side by side.

- **Price a used listing**  
  `match_geizhals` turns a classifieds ad headline into the Geizhals products it could be (with a confidence score), and `get_model_price_range` gives the new-price range across every variant of a model — the two numbers a "is this second-hand offer a deal" answer needs.

## Setup

Requires Python 3.10+.

```bash
pip install -r requirements.txt
```

With [uv](https://docs.astral.sh/uv/) you can skip this step: `main.py`
declares its own dependencies, so `uv run main.py` installs them on the fly.

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

For clients that start the server themselves, `python main.py --stdio` speaks
MCP over stdin/stdout instead. Nothing has to run in the background then.

## Add it to Claude (and other MCP clients)

Clients that start their own servers use the stdio mode. Clients that connect
to a URL need `python main.py` running and take the URL it printed on startup.

### Claude Code

One command, no config file. Claude Code starts the server itself:

```bash
claude mcp add geizhals -- python /path/to/geizhals-mcp/main.py --stdio
```

Or connect to a server you already started with `python main.py`:

```bash
claude mcp add --transport http geizhals http://127.0.0.1:8000/mcp
```

Add `--scope user` to have it in every project instead of only the current one.
`claude mcp list` shows whether the connection came up, `claude mcp remove
geizhals` takes it out again.

### Cursor, Codex, VS Code and other JSON-config clients

Same URL, in the client's MCP config:

```json
{
  "mcpServers": {
    "geizhals": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

### Claude Desktop

Custom connectors (**Settings > Connectors**) are dialled from Anthropic's
cloud, so they cannot reach a server bound to your own machine. Two ways
around it:

**Let Claude Desktop start it over stdio.** Open **Settings > Developer > Edit
Config**, add the `geizhals` entry to `claude_desktop_config.json` and restart
Claude Desktop:

```json
{
  "mcpServers": {
    "geizhals": {
      "command": "python",
      "args": ["C:\\path\\to\\geizhals-mcp\\main.py", "--stdio"]
    }
  }
}
```

Use the full path to `main.py` (forward slashes on macOS/Linux). With uv
installed, `"command": "uv"` and `"args": ["run", "/path/to/geizhals-mcp/main.py",
"--stdio"]` also takes care of the dependencies.

**Or expose the server** (cloudflared, ngrok, or run it on a box with a public
hostname) and add that HTTPS URL under **Settings > Connectors > Add custom
connector**. That route also makes the tools available in claude.ai and the
mobile apps, not just the desktop client but the API it talks to is then
reachable by whoever finds the URL, so put auth in front of it.

Every tool is marked read-only, so clients that honour that hint won't ask
before each call. In Claude Desktop you can also open **Settings > Connectors >
geizhals** and set the tools' dropdown on the right to **Always allow**.

## Tools

The tools that take them share three parameters: `loc` is the country site,
`"at"` (default) or `"de"`; `hloc` lists the shop countries to include and
defaults to `[loc]`; `lang` (`"en"` or `"de"`) sets the language of category
names. Results come as compact JSON, and fields without a value are left out.

**`search_geizhals(query, ...)`**

Search products by keyword, with filters for category and manufacturer, sorting
and paging (`rows` up to 50). Every hit carries its current `best_price`,
`avg_price`, `offer_count`, `currency`, cheapest `shop`, `rating_*` and an
`available` flag, so a plain price-or-rating question needs no follow-up call.
Hits with no live offers add `alltime_price_min` / `alltime_price_max` /
`alltime_last_date`, so a list of discontinued hardware is priceable without a
call per hit. The facets list the ten largest categories and manufacturers to
refine with.

`sort` takes `""` (relevance), `"p"` (cheapest first) or `"-p"` (dearest first);
Geizhals has no newest or rating order for a search. A price sort narrows the
result set as well as ordering it: Geizhals cannot price-order a product that
has no price, so unavailable products leave both `results` and `total`.

**`get_product(product_id, n_offers=5)`**

Full detail of one product: current best price and offer count, name, category,
rating, images, GTIN, offer link, all-time price range and test-review count.
`offers` lists the cheapest shops with price, cheapest shipping, total, the
shop's own stock text and its rating. A product with no live offers gets its
`last_known_price` / `last_known_date` filled in.

**`get_price_history(product_id, days=31)`**

Window (`window_min/max/avg/change_percent`) and all-time (`alltime_min/max`)
summaries kept strictly apart, plus a `[iso_date, price]` series that only
lists the days the price changed. `granularity="day"` or `"week"` give a point
per day or per week instead, and `include_series=False` leaves the series out.

**`get_product_ratings(product_id)`**

Average rating, totals, per-star counts and the reviews link.

**`browse_category(category, ...)`**

List the products in a category by its code, with price bounds, paging (`rows`
up to 50) and sorting: `"t"` (relevance), `"p"` / `"-p"` (price up or down),
`"n"` (newest listings) or `"bew"` (best rated). Hits use the same field names
as `search_geizhals`, and the `price_range` returned alongside them is the
category's real one (the search facet's is not).

**`compare_products(product_ids)`**

Compare up to ten products side by side, specs included. Properties that don't
apply to a product are dropped rather than shown as empty, and the specs are in
German because that is all Geizhals has. Discontinued products carry their
last known price.

**`get_deals(sort="percent", ...)`**

Current price drops: products whose best price just fell, with the percent and
amount off and a link to the product page. Sort by biggest `percent` drop,
`price`, `latest`, `popularity` or `top` deals, and filter with
`min_discount_percent` / `max_price`. Filters and sorting work over every
current drop (about a thousand), and `limit` (up to 50) is how many matches come
back. `next_offset` pages on through the rest; the feed is kept for two minutes,
so the next page answers at once.

**`get_model_price_range(model, ...)`**

What a whole model costs right now across all its variants (`min`, `median`,
`max` and the five cheapest) instead of one specific board partner card.
Sibling models (`4070 Ti`, `4070 Super`) are kept out, and the result is always
scoped to one category: an unscoped search for a pricey product is dominated by
cases and water blocks below it and prebuilt systems above it, so the category
is detected when you don't pass one and reported back as `category_code`. Up to
300 search hits are considered.

**`match_geizhals(title, ...)`**

Resolve a free-form listing title ("Gigabyte RTX 5070 Windforce OC 12GB NEU OVP
mit Rechnung") to Geizhals products, each with a 0–1 `confidence` and its live
price. Marketplace listings without a category (mostly prebuilt PCs that name
the card they contain) score low, so they don't pass for the card itself. When
the top candidates are too close to separate, or nothing scores convincingly,
a `note` says so rather than letting a coin-flip look like an answer.

**`list_categories(query)`**

Browse Geizhals' category tree to find the category codes `browse_category`
takes. Matches English or German names ("graphics cards" and "grafikkarten"
both work). The full tree ships with the server in `data/categories.json`.

### Prompt

**`check_listing(title, price)`** turns a second-hand ad into a ready request:
match it with `match_geizhals`, price the model new with
`get_model_price_range`, and answer how far below the cheapest new offer the
ad is. Clients that support prompts show it as "Check a second-hand listing".

## Notes

- `data/categories.json` is a snapshot of Geizhals' category tree (title,
  title_de, id, children). `main.py` loads it for `list_categories`, which
  matches queries against both the English and German names.
- The badges above read `coverage.json` from the `coverage` branch.
  `scripts/update_coverage.py` refreshes it from the Geizhals homepage, and a
  daily GitHub Action commits any change to that branch, so the refresh stays
  out of `main`'s history.
- Only the Austrian and German sites are offered. On the others (`eu`, `uk`,
  `pl`) the endpoints disagree on currency, `sk` rejects every call, and the
  at/de sites ignore shops from other countries anyway.
- What all tools share (which tool to start with, what `loc`/`hloc`/`lang`
  mean, `id` vs `variant_id`) is sent once as the server's instructions
  instead of being repeated in every tool description.
- API details are documented in [`search_api.md`](search_api.md).
- This uses Geizhals' internal mobile API, not an official one. Be nice to it.

## Tests

```bash
pip install pytest
pytest
```

The suite runs offline against canned API responses and goes through a real
MCP client, stdio transport included. `GEIZHALS_LIVE=1 pytest` adds smoke tests
against the live API. CI runs the offline suite on every push and the live
tests once a day, which is what catches Geizhals rotating its signing secret.

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
report it as a tool error with a readable message rather than the raw HTTP
error, so the model sees what went wrong instead of an internal URL.

**`could not answer ... (HTTP 503)`** — the request was fine but Geizhals did
not answer, even after two retries. That is on their side; try again later.

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

# Scryfall API notes

A condensed summary of the parts of the API this project uses. Official docs: https://scryfall.com/docs/api

Each item is marked:
- **[verified YYYY-MM-DD]**: checked against a live response (see `tests/fixtures/`).
- **[docs]**: from Scryfall's documentation and not independently tested.

Update the mark when you re-check something.

## Request rules
- Every request must send a `User-Agent` and an `Accept` header, or Scryfall rejects it. We send `Accept: application/json;q=0.9,*/*;q=0.8`. **[docs]**
- Rate limits **[docs]**:
  - Most endpoints: 50-100 ms between requests (about 10/s). We use 100 ms.
  - `/cards/search`, `/cards/named`, `/cards/random`, `/cards/collection`: stricter (about 2/s). We use 500 ms (`DEFAULT_BUCKET_INTERVALS` in `client.py`).
  - Going over the limit returns HTTP 429. Repeated abuse can get an IP blocked temporarily.
  - `data.scryfall.io` (bulk files) and `cards.scryfall.io` (images) have **no** rate limit.
- Cache responses for at least 24 hours where possible; prices update about once a day. **[docs]**
- Use bulk data for anything touching thousands of cards, rather than paging through search results.

## Errors **[verified 2026-11-11]**
```json
{"object": "error", "code": "not_found", "status": 404, "details": "No cards found matching ..."}
```
- `type` and `warnings` are optional extra fields.
- A search with zero results returns a **404**, not an empty list. `ScryfallClient.search()` turns that into an empty result.
- Successful responses can also include a `warnings` list; the client logs these.

## Lists and pagination **[verified 2026-11-11]**
- Shape: `{"object": "list", "has_more": bool, "next_page": url?, "total_cards": int?, "data": [...]}`.
- Search pages hold up to 175 cards. Follow `next_page` exactly as given.

## Card objects **[verified 2026-11-11]** (fixtures: `card_*.json`)
- `set` is the set code; it becomes `Card.set_code` (since `set` is a Python built-in).
- `prices`: string values or `null`. Keys: `usd`, `usd_foil`, `usd_etched`, `eur`, `eur_foil`, `tix`.
- `legalities`: `{format: "legal" | "not_legal" | "restricted" | "banned"}`. The formats include standard, pioneer, modern, legacy, vintage, commander, pauper, brawl, alchemy and others (see fixture).
- `cmc` is a float, e.g. `1.0`.
- **Multi-face layouts differ:**

  | layout | top-level `image_uris` | top-level `mana_cost` / `oracle_text` | per-face `image_uris` |
  |---|---|---|---|
  | normal | yes | yes | no `card_faces` |
  | split (Fire // Ice) | yes | `mana_cost` joined with ` // `; **no** `oracle_text` | no |
  | transform (Delver) | **no** | **no** | yes |

  Other layouts (modal_dfc, adventure, flip, meld, ...) haven't been checked yet. Capture a fixture before relying on them.
- IDs: `id` is one specific printing; `oracle_id` is the card's rules identity, shared across all its printings. Group by `oracle_id` to count unique cards.

## Search query syntax **[docs]**
Full reference: https://scryfall.com/docs/syntax.

Examples: `t:dragon`, `c>=uw`, `id<=esper` (commander colour identity), `cmc<=3`, `o:"draw a card"`, `e:m21`, `r:mythic`, `f:modern`, `usd<1`, `is:commander`, `-t:land`, `(a or b)`.

Endpoint parameters:
- `unique`: `cards` (default), `art`, `prints`.
- `order`: `name`, `set`, `released`, `cmc`, `usd`, `edhrec`, and others.

## Bulk data **[verified 2026-11-11]** (fixture: `bulk_data_item.json`)
- `GET /bulk-data` lists the files. Each object has `type`, `updated_at`, `jsonl_download_uri` and `compressed_size`.
  - **The old `download_uri`, `size` and `content_type` fields are gone.**
- Files are **gzipped JSON Lines** (`.jsonl.gz`), served as `application/gzip`, so the HTTP client does *not* decompress them. Decompress with `gzip.open` (as `bulk.iter_records` does).
- Types and compressed sizes on 2026-11-11:

  | type | size | contents |
  |---|---|---|
  | `oracle_cards` | 25 MB | one card per Oracle identity |
  | `unique_artwork` | 39 MB | |
  | `default_cards` | 81 MB | every printing, in English or the printed language |
  | `all_cards` | 408 MB | every printing in every language |
  | `rulings` | 5 MB | about 79.7k rulings |
  | `art_tags`, `oracle_tags` | | tagger data; not card objects |
- Files are regenerated about every 12 hours.

## Other endpoints used
- `/cards/collection` (POST): at most 75 identifiers per request; returns `data` and `not_found`. The client splits larger requests into batches. **[docs]**
- `/symbology/parse-mana?cost=...` returns a `mana_cost` object (`cmc`, `colors`, `multicolored`, ...). **[verified 2026-11-11]**
- `/catalog/{name}` returns `{"data": [str, ...]}`, e.g. `card-names`, `creature-types`. **[docs]**

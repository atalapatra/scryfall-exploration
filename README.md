# scryfall-exploration

A small Python framework for the [Scryfall API](https://scryfall.com/docs/api).

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[dev]"
pytest
```

## Usage

```python
from scryfall import ScryfallClient, FileCache

with ScryfallClient(user_agent="my-app/0.1", cache=FileCache()) as sf:
    card = sf.named("Lightning Bolt")            # exact name, or fuzzy=True
    card.price("usd"); card.is_legal("modern"); card.image_url("large")

    for c in sf.search("t:dragon cmc<=4", order="cmc"):   # requests each page only as needed
        print(c.name, c.set_code)

    cards, missing = sf.collection([{"name": "Sol Ring"}, {"set": "lea", "collector_number": "232"}])
    sf.sets(); sf.rulings(card.id); sf.catalog("creature-types"); sf.parse_mana("{2}{W}{U}")
    sf.get("/cards/migrations")                  # for any endpoint without a helper
```

### Bulk data (for analysing many cards)

```python
from scryfall import bulk

path = bulk.download(sf, "oracle_cards")         # saves data/oracle_cards-<timestamp>.jsonl.gz; skipped if already saved
for card in bulk.iter_cards(path):               # reads one card at a time; low memory use
    ...
# also: bulk.iter_rulings(path), bulk.iter_records(path) for raw dicts (e.g. art_tags)
```

## Project docs
- [CLAUDE.md](CLAUDE.md): short orientation for AI-assisted sessions
- [docs/scryfall-api.md](docs/scryfall-api.md): API behaviour and data shapes (marked as verified or from docs)
- [docs/decisions.md](docs/decisions.md): why things are built the way they are
- `tests/fixtures/`: real API responses; refresh with `python scripts/capture_fixtures.py`

## What the framework handles

| Concern | Where |
|---|---|
| Required `User-Agent` and `Accept` headers | `client.py` |
| Rate limiting: 100ms between requests; 500ms for search/named/random/collection | `ratelimit.py` |
| Retries with exponential backoff on 429 and 5xx (follows `Retry-After`) | `ScryfallClient.request` |
| Typed errors (`NotFoundError`, `RateLimitError`, `ScryfallAPIError`) | `errors.py` |
| Following `next_page` links in paginated lists | `ScryfallClient.paginate` |
| Typed models that keep the full JSON in `.raw`; other fields readable as attributes | `models.py` |
| Optional 24h caching, in memory or on disk | `cache.py` |
| Bulk file download and streaming parser | `bulk.py` |

Pass `parse=False` to get plain dicts instead of model objects.

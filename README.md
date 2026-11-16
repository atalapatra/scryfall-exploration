# scryfall-exploration

A small Python framework for the [Scryfall API](https://scryfall.com/docs/api).

## Install in another project

The package is named `atalapatra_scryfall` (pip also accepts `atalapatra-scryfall`), and you import it as `atalapatra_scryfall`. Install it straight from GitHub:

```bash
pip install "atalapatra_scryfall @ git+https://github.com/atalapatra/scryfall-exploration.git@v0.1.0"   # pinned to a tag
pip install "atalapatra_scryfall @ git+https://github.com/atalapatra/scryfall-exploration.git@main"     # latest
```

Or list it as a dependency in the other project's `pyproject.toml`:

```toml
dependencies = ["atalapatra_scryfall @ git+https://github.com/atalapatra/scryfall-exploration.git@v0.1.0"]
```

(In `requirements.txt`, use the same `atalapatra_scryfall @ git+...` line.) Pin to a tag or commit so upgrades only happen when you choose them. To release a new version: bump `__version__` in `src/atalapatra_scryfall/__init__.py`, commit, then `git tag vX.Y.Z && git push --tags`.

Paths such as `FileCache()` (`.scryfall_cache/`), `bulk.download(...)` and `TagIndex.load(...)` (`data/`) are relative to the current working directory, so pass `directory=` / `dest_dir=` to put them somewhere else.

## Development setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[dev]"
pytest
```

## Usage

```python
from atalapatra_scryfall import ScryfallClient, FileCache

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
from atalapatra_scryfall import bulk

path = bulk.download(sf, "oracle_cards")         # saves data/oracle_cards-<timestamp>.jsonl.gz; skipped if already saved
for card in bulk.iter_cards(path):               # reads one card at a time; low memory use
    ...
# also: bulk.iter_rulings(path), bulk.iter_records(path) for raw dicts (e.g. art_tags)
```

### Card lists: EDHREC rank, roles and tags

Installing the package adds the `scryfall-card-info` command (also available as `python -m atalapatra_scryfall.cli`).

```bash
scryfall-card-info examples/decklist.txt               # table, plus a count of each role
scryfall-card-info deck.txt --csv deck.csv --sort edhrec
scryfall-card-info deck.txt --roles ramp,removal,draw,wipe
```

```python
from atalapatra_scryfall.decklist import lookup
from atalapatra_scryfall.tags import TagIndex

tags = TagIndex.load(sf)                         # downloads oracle_tags (~6 MB) when it changes
result = lookup(sf, open("deck.txt").read(), tag_index=tags)
for info in result.cards:
    print(info.card.name, info.card.edhrec_rank, info.roles)
result.rows()                                    # flat dicts, ready for pandas or CSV
tags.tags_for(card)                              # every tag, including inherited ones like "ramp"
```

The parser accepts plain names, `4x Name`, `1 Name (SET) 123 *F*`, `A // B` names, section headers, `SB:` lines and Archidekt `[Category]` labels.

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

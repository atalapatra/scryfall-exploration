# scryfall-exploration

A Python framework for the Scryfall (Magic: The Gathering card data) API, plus exploration and analysis built on top of it.

## Commands
- Setup: `python -m venv .venv` then `.venv\Scripts\python -m pip install -e ".[dev]"`
- Tests: `.venv\Scripts\python -m pytest -q` (offline, fast)
- Refresh fixtures from the live API: `.venv\Scripts\python scripts/capture_fixtures.py`

## Layout (`src/scryfall/`)
- `client.py`: `ScryfallClient`. All HTTP goes through `request()` (headers, rate limit, retry, cache, errors). Endpoint helpers sit on top.
- `models.py`: dataclass wrappers (`Card`, `Set`, ...). Fields without a typed attribute fall back to `.raw` via `__getattr__`.
- `bulk.py`: bulk file download (`.jsonl.gz`) and streaming readers.
- `ratelimit.py`, `cache.py`, `errors.py`: support code.
- `tests/fixtures/*.json`: **real** API responses; check data shapes here before assuming.

## Rules
- Tests never hit the live API: use `httpx.MockTransport` (see `make_client` / `client_returning` in tests).
- Every API call goes through `ScryfallClient.request` so rate limiting and the required headers apply. Never call `httpx` directly for api.scryfall.com.
- Don't add typed model fields just to read a value; `card.some_field` already works through `.raw`. Add typed fields for commonly used or converted values.
- Prices are strings or `null` in the API; use `Card.price()`.
- Multi-face cards: check `card_faces` before reading `oracle_text` / `image_uris` / `mana_cost`. Shapes differ by layout (see docs).

## More context (read when relevant)
- `docs/scryfall-api.md`: API behaviour, limits, object shapes, known quirks.
- `docs/decisions.md`: why things are built the way they are.

## Keeping context current
Update these files in the same change as the work that makes them out of date, not as a separate step afterwards. Before finishing a task, check this list and say which files you updated, or that none needed it.
- **`docs/decisions.md`**: add an entry (newest first, dated) when choosing between real alternatives, adding a dependency, or changing a default or behaviour. Skip routine work.
- **`docs/scryfall-api.md`**: when you learn how the API actually behaves (a new endpoint, a field shape, a quirk, a limit), record it, marked `[verified YYYY-MM-DD]` or `[docs]`. If the docs and a live response disagree, the live response wins: fix the note.
- **`tests/fixtures/`**: before writing code that depends on a data shape that has no fixture yet (e.g. a new card layout or endpoint), add it to `scripts/capture_fixtures.py` and re-run the script. Don't hand-write fixtures.
- **`CLAUDE.md`**: update the Layout, Commands or Rules sections when modules, commands or conventions change. Keep it short: put detail in `docs/` and add a pointer here.
- **`README.md`**: update the usage examples when the public API changes.

# Decisions

Newest first. Each entry: what was decided, why, and what would make us revisit it.

## 2026-11-11: Card tags come from the oracle_tags bulk file, including inherited parents
The API's card objects have no tags, and searching `otag:` once per tag per card would take thousands of requests. So `TagIndex` loads the `oracle_tags` bulk file (6 MB, refreshed at most twice a day) and, by default, adds each tag's ancestors. Without that, broad categories like `removal` never appear.
`DEFAULT_ROLES` is a hand-picked list of broad deck-role tags, for a readable summary; the full tag list is kept in the `tags` column.
Revisit if: you want your own categories. Pass `roles=`, or map tags to your own groups.

## 2026-11-11: Decklist lookups use /cards/collection, matched back to lines by position
`cards_for()` sends each distinct identifier once, in batches of 75, and matches results to requests by position, using `not_found` to place the misses. Matching by name instead would break on accents and multi-face names. If the counts don't add up, it raises an error rather than guessing.
The parser sends only the front-face name, because Scryfall doesn't match full `A // B` names.

## 2026-11-11: bulk.download deletes older files of the same type
Files are timestamped and regenerated about every 12 hours, so old copies would keep piling up in `data/`. Pass `keep_old=True` to keep them, e.g. for comparing prices over time.

## 2026-11-11: Bulk files are saved compressed and read as JSON Lines
Scryfall switched bulk data to gzipped `.jsonl` (`jsonl_download_uri`). We save the `.jsonl.gz` as-is, which is about 5x smaller on disk, and decompress line by line while reading. The JSON-array reader (`iter_json_array`) stays for older files.
Revisit if: we query the same bulk data repeatedly. Then load it into SQLite or Parquet once instead of re-parsing.

## 2026-11-11: Real responses saved as test fixtures
`tests/fixtures/` holds live responses captured by `scripts/capture_fixtures.py`. They are the reference for data shapes, and the tests run against them. Capturing them is how we found the bulk-data format change.
Revisit by: re-running the capture script now and then and checking `git diff tests/fixtures`. That shows what Scryfall changed.

## 2026-11-11: Models keep the full JSON and fall back to it
Dataclasses have typed attributes for common fields, and the full payload stays in `.raw`. `__getattr__` falls back to `.raw`, so new Scryfall fields work with no code change. This trades complete typing for resilience: Scryfall card objects have more than 70 fields and change often.

## 2026-11-11: httpx instead of requests
`httpx.MockTransport` lets the tests fake HTTP without extra mocking libraries, and `httpx.AsyncClient` leaves the door open for an async client.

## 2026-11-11: Client-side rate limiting with per-endpoint buckets
Every request waits on a global bucket (100 ms). Search, named, random and collection also wait on a `cards-heavy` bucket (500 ms), per Scryfall's stricter limits on those endpoints. Responses with status 429 or 5xx are retried with exponential backoff, following `Retry-After` when present.

## 2026-11-11: A search with no results returns an empty iterator
Scryfall returns a 404 for searches with no results. For analysis code, an empty result is more natural than an exception. Lookups by name or ID still raise `NotFoundError`.

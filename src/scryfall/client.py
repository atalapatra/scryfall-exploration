"""The Scryfall API client.

Example:
    >>> from scryfall import ScryfallClient
    >>> with ScryfallClient() as sf:
    ...     card = sf.named("Lightning Bolt")
    ...     for c in sf.search("t:dragon cmc<=4", order="cmc"):
    ...         print(c.name)
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Iterator
from typing import Any

import httpx

from . import __version__
from .cache import Cache
from .errors import NotFoundError, ScryfallAPIError, ScryfallError
from .models import BulkData, Card, CardSymbol, ManaCost, Ruling, Set, parse_object
from .ratelimit import RateLimiter

log = logging.getLogger(__name__)

BASE_URL = "https://api.scryfall.com"

# Scryfall requires every request to send a User-Agent and an Accept header.
DEFAULT_USER_AGENT = f"scryfall-exploration/{__version__}"
DEFAULT_ACCEPT = "application/json;q=0.9,*/*;q=0.8"

# Seconds between requests. Scryfall asks for 50-100ms between requests in general,
# and for longer gaps on the heavier card endpoints listed here.
DEFAULT_INTERVAL = 0.1
DEFAULT_BUCKET_INTERVALS = {"cards-heavy": 0.5}
_HEAVY_PREFIXES = ("/cards/search", "/cards/named", "/cards/random", "/cards/collection")

RETRY_STATUSES = {429, 500, 502, 503, 504}

COLLECTION_BATCH_SIZE = 75  # Scryfall's maximum number of identifiers per /cards/collection request


class ScryfallClient:
    """A synchronous Scryfall API client.

    Args:
        user_agent: Identifies your app to Scryfall. Required by Scryfall; set something descriptive.
        cache: Optional cache (``MemoryCache`` / ``FileCache``) for GET responses.
        rate_limiter: Override the default rate limiter (for example, to share one between clients).
        max_retries: How many times to retry 429 and 5xx responses, with exponential backoff.
        timeout: Request timeout in seconds.
        parse: If True (the default), wrap responses in model classes; if False, return raw dicts.
        transport: Optional httpx transport. Tests use this to fake HTTP responses.
    """

    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        base_url: str = BASE_URL,
        cache: Cache | None = None,
        rate_limiter: RateLimiter | None = None,
        max_retries: int = 3,
        backoff: float = 1.0,
        timeout: float = 30.0,
        parse: bool = True,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache = cache
        self.rate_limiter = rate_limiter or RateLimiter(DEFAULT_INTERVAL, DEFAULT_BUCKET_INTERVALS)
        self.max_retries = max_retries
        self.backoff = backoff
        self.parse = parse
        self._http = httpx.Client(
            base_url=self.base_url,
            headers={"User-Agent": user_agent, "Accept": DEFAULT_ACCEPT},
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
        )

    # ------------------------------------------------------------------ lifecycle

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "ScryfallClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ core HTTP

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        use_cache: bool = True,
    ) -> Any:
        """Send a request and return the decoded JSON. Raises ``ScryfallAPIError`` on errors.

        ``path`` can be relative ("/cards/search") or a full URL (e.g. a ``next_page`` link).
        """
        params = _clean_params(params)
        cacheable = use_cache and self.cache is not None and method.upper() == "GET"
        cache_key = str(self._http.build_request(method, path, params=params).url) if cacheable else ""
        if cacheable:
            hit = self.cache.get(cache_key)  # type: ignore[union-attr]
            if hit is not None:
                return hit

        bucket = "cards-heavy" if _path_of(path).startswith(_HEAVY_PREFIXES) else None
        attempt = 0
        while True:
            self.rate_limiter.wait(bucket)
            try:
                resp = self._http.request(method, path, params=params, json=json)
            except httpx.TransportError as exc:
                if attempt >= self.max_retries:
                    raise ScryfallError(f"Network error calling {path}: {exc}") from exc
                self._sleep_backoff(attempt, None)
                attempt += 1
                continue

            if resp.status_code in RETRY_STATUSES and attempt < self.max_retries:
                log.warning("Scryfall returned %s for %s; retrying", resp.status_code, path)
                self._sleep_backoff(attempt, resp.headers.get("Retry-After"))
                attempt += 1
                continue
            break

        data = _decode(resp)
        if resp.is_error or (isinstance(data, dict) and data.get("object") == "error"):
            payload = data if isinstance(data, dict) else {"details": resp.text}
            raise ScryfallAPIError.from_response(resp.status_code, payload)

        for warning in (data.get("warnings") or []) if isinstance(data, dict) else []:
            log.warning("Scryfall warning: %s", warning)

        if cacheable:
            self.cache.set(cache_key, data)  # type: ignore[union-attr]
        return data

    def get(self, path: str, **params: Any) -> Any:
        """GET any endpoint and return its decoded JSON. Useful for endpoints without a helper method."""
        return self.request("GET", path, params=params)

    def paginate(self, path: str, params: dict[str, Any] | None = None) -> Iterator[Any]:
        """Yield every item from a paginated ``list`` endpoint, requesting pages only as needed."""
        data = self.request("GET", path, params=params)
        while True:
            for item in data.get("data", []):
                yield self._wrap(item)
            if not data.get("has_more"):
                return
            data = self.request("GET", data["next_page"])

    def _wrap(self, item: Any) -> Any:
        return parse_object(item) if self.parse else item

    def _sleep_backoff(self, attempt: int, retry_after: str | None) -> None:
        try:
            delay = float(retry_after) if retry_after else self.backoff * (2**attempt)
        except ValueError:
            delay = self.backoff * (2**attempt)
        time.sleep(delay)

    # ------------------------------------------------------------------ cards

    def search(
        self,
        q: str,
        *,
        unique: str = "cards",
        order: str = "name",
        dir: str = "auto",
        include_extras: bool = False,
        include_multilingual: bool = False,
        include_variations: bool = False,
    ) -> Iterator[Card]:
        """Run a full-text search (https://scryfall.com/docs/syntax) and yield every matching card.

        Unlike the API, which returns a 404 error when nothing matches, this yields nothing.
        """
        params = {
            "q": q,
            "unique": unique,
            "order": order,
            "dir": dir,
            "include_extras": include_extras,
            "include_multilingual": include_multilingual,
            "include_variations": include_variations,
        }
        try:
            yield from self.paginate("/cards/search", params)
        except NotFoundError:
            return

    def named(self, name: str, *, fuzzy: bool = False, set: str | None = None) -> Card:
        """Get one card by name: an exact match by default, or a fuzzy one with ``fuzzy=True``."""
        key = "fuzzy" if fuzzy else "exact"
        return self._wrap(self.request("GET", "/cards/named", params={key: name, "set": set}))

    def autocomplete(self, q: str, *, include_extras: bool = False) -> list[str]:
        return self.request("GET", "/cards/autocomplete", params={"q": q, "include_extras": include_extras})["data"]

    def random(self, q: str | None = None) -> Card:
        """Get a random card, optionally limited to cards matching search query ``q``. Never cached."""
        return self._wrap(self.request("GET", "/cards/random", params={"q": q}, use_cache=False))

    def card(self, id: str) -> Card:
        """Get a card by its Scryfall ID."""
        return self._wrap(self.request("GET", f"/cards/{id}"))

    def card_by_set(self, set_code: str, collector_number: str | int, lang: str | None = None) -> Card:
        path = f"/cards/{set_code.lower()}/{collector_number}"
        if lang:
            path += f"/{lang}"
        return self._wrap(self.request("GET", path))

    def card_by_id(self, id_type: str, value: str | int) -> Card:
        """Get a card by an external ID.

        ``id_type`` is one of: multiverse, mtgo, arena, tcgplayer, cardmarket.
        """
        return self._wrap(self.request("GET", f"/cards/{id_type}/{value}"))

    def collection(self, identifiers: Iterable[dict[str, Any]]) -> tuple[list[Card], list[dict[str, Any]]]:
        """Fetch many cards at once. Returns ``(cards, not_found)``.

        Each identifier is a dict such as ``{"name": "Sol Ring"}``, ``{"id": "..."}`` or
        ``{"set": "lea", "collector_number": "1"}``. Requests are batched automatically
        (Scryfall accepts at most 75 identifiers per request).
        """
        ids = list(identifiers)
        cards: list[Card] = []
        not_found: list[dict[str, Any]] = []
        for start in range(0, len(ids), COLLECTION_BATCH_SIZE):
            batch = ids[start : start + COLLECTION_BATCH_SIZE]
            data = self.request("POST", "/cards/collection", json={"identifiers": batch})
            cards.extend(self._wrap(c) for c in data.get("data", []))
            not_found.extend(data.get("not_found", []))
        return cards, not_found

    def cards_for(self, identifiers: Iterable[dict[str, Any]]) -> list[Card | None]:
        """Like ``collection``, but returns one result per identifier, in order, with ``None`` for misses.

        Scryfall returns found cards in request order and leaves out the misses (listed in
        ``not_found``), so results are matched back to identifiers by position.
        """
        ids = list(identifiers)
        out: list[Card | None] = []
        for start in range(0, len(ids), COLLECTION_BATCH_SIZE):
            batch = ids[start : start + COLLECTION_BATCH_SIZE]
            data = self.request("POST", "/cards/collection", json={"identifiers": batch})
            cards = data.get("data", [])
            missing = [_norm_ident(i) for i in data.get("not_found", [])]
            if len(cards) + len(missing) != len(batch):
                raise ScryfallError(
                    f"/cards/collection returned {len(cards)} cards + {len(missing)} not found for {len(batch)} identifiers"
                )
            found = iter(cards)
            for ident in batch:
                norm = _norm_ident(ident)
                if norm in missing:
                    missing.remove(norm)
                    out.append(None)
                else:
                    out.append(self._wrap(next(found)))
        return out

    def rulings(self, card_id: str) -> list[Ruling]:
        return list(self.paginate(f"/cards/{card_id}/rulings"))

    # ------------------------------------------------------------------ sets

    def sets(self) -> list[Set]:
        return list(self.paginate("/sets"))

    def set(self, code_or_id: str) -> Set:
        return self._wrap(self.request("GET", f"/sets/{code_or_id}"))

    def set_cards(self, code: str, **search_kwargs: Any) -> Iterator[Card]:
        """Yield every card in a set, ordered by collector number by default."""
        search_kwargs.setdefault("order", "set")
        return self.search(f"e:{code}", **search_kwargs)

    # ------------------------------------------------------------------ misc

    def symbology(self) -> list[CardSymbol]:
        return list(self.paginate("/symbology"))

    def parse_mana(self, cost: str) -> ManaCost:
        return self._wrap(self.request("GET", "/symbology/parse-mana", params={"cost": cost}))

    def catalog(self, name: str) -> list[str]:
        """Get a catalog, e.g. ``"card-names"``, ``"creature-types"``, ``"keyword-abilities"``."""
        return self.request("GET", f"/catalog/{name}")["data"]

    def bulk_data(self) -> list[BulkData]:
        """List the available bulk data files. See ``scryfall.bulk`` to download them."""
        return list(self.paginate("/bulk-data"))

    def bulk_data_info(self, type: str) -> BulkData:
        """Get one bulk data file's details, e.g. ``"oracle_cards"`` or ``"default_cards"``."""
        return self._wrap(self.request("GET", f"/bulk-data/{type}"))


def _clean_params(params: dict[str, Any] | None) -> dict[str, Any] | None:
    """Drop parameters that are None, and turn booleans into the "true"/"false" strings Scryfall expects."""
    if not params:
        return None
    out: dict[str, Any] = {}
    for key, value in params.items():
        if value is None:
            continue
        out[key] = ("true" if value else "false") if isinstance(value, bool) else value
    return out or None


def _norm_ident(ident: dict[str, Any]) -> tuple:
    return tuple(sorted((k, str(v).lower()) for k, v in ident.items()))


def _path_of(path: str) -> str:
    return httpx.URL(path).path if path.startswith("http") else path


def _decode(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        if resp.is_error:
            return {"details": resp.text[:500]}
        raise ScryfallError(f"Expected JSON from {resp.request.url}, got {resp.headers.get('content-type')}")

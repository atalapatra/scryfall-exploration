import json

import httpx
import pytest

from scryfall import Card, MemoryCache, NotFoundError, RateLimiter, ScryfallAPIError, ScryfallClient
from scryfall.bulk import iter_json_array

BOLT = {
    "object": "card",
    "id": "abc",
    "name": "Lightning Bolt",
    "set": "lea",
    "cmc": 1.0,
    "type_line": "Instant",
    "legalities": {"modern": "legal", "standard": "not_legal"},
    "prices": {"usd": "1.50", "usd_foil": None},
    "image_uris": {"normal": "https://img/bolt.jpg"},
    "frame": "1993",
}


def make_client(handler, **kwargs):
    kwargs.setdefault("rate_limiter", RateLimiter(0, {}))
    kwargs.setdefault("backoff", 0)
    return ScryfallClient(transport=httpx.MockTransport(handler), **kwargs)


def error(status, code="not_found", details="nope"):
    return httpx.Response(status, json={"object": "error", "status": status, "code": code, "details": details})


def test_required_headers_and_named():
    seen = {}

    def handler(request):
        seen["headers"] = request.headers
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=BOLT)

    with make_client(handler, user_agent="test-agent/1.0") as sf:
        card = sf.named("Lightning Bolt")

    assert seen["headers"]["user-agent"] == "test-agent/1.0"
    assert "application/json" in seen["headers"]["accept"]
    assert seen["params"] == {"exact": "Lightning Bolt"}
    assert isinstance(card, Card)
    assert card.set_code == "lea"
    assert card.frame == "1993"  # not a typed field: read from the raw JSON
    assert card.is_legal("modern") and not card.is_legal("standard")
    assert card.price("usd") == 1.5 and card.price("usd_foil") is None
    assert card.image_url() == "https://img/bolt.jpg"


def test_search_paginates_and_formats_bools():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json={"object": "list", "has_more": False, "data": [dict(BOLT, name="B")]})
        assert request.url.params["include_extras"] == "false"
        return httpx.Response(
            200,
            json={
                "object": "list",
                "has_more": True,
                "next_page": "https://api.scryfall.com/cards/search?q=x&page=2",
                "data": [dict(BOLT, name="A")],
            },
        )

    with make_client(handler) as sf:
        names = [c.name for c in sf.search("x")]
    assert names == ["A", "B"]
    assert len(calls) == 2


def test_search_with_no_results_yields_nothing():
    with make_client(lambda r: error(404)) as sf:
        assert list(sf.search("nonsense")) == []


def test_not_found_raises():
    with make_client(lambda r: error(404, details="No card found")) as sf:
        with pytest.raises(NotFoundError) as exc:
            sf.card("missing")
    assert exc.value.status == 404 and "No card found" in str(exc.value)


def test_retries_on_429_then_succeeds():
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        return error(429, "too_many_requests") if attempts["n"] < 3 else httpx.Response(200, json=BOLT)

    with make_client(handler) as sf:
        assert sf.card("abc").name == "Lightning Bolt"
    assert attempts["n"] == 3


def test_gives_up_after_max_retries():
    with make_client(lambda r: error(503, "unavailable"), max_retries=1) as sf:
        with pytest.raises(ScryfallAPIError) as exc:
            sf.card("abc")
    assert exc.value.status == 503


def test_cache_avoids_second_request():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json=BOLT)

    with make_client(handler, cache=MemoryCache()) as sf:
        sf.card("abc")
        sf.card("abc")
    assert calls["n"] == 1


def test_collection_batches_75():
    batches = []

    def handler(request):
        ids = json.loads(request.content)["identifiers"]
        batches.append(len(ids))
        return httpx.Response(200, json={"object": "list", "data": [BOLT] * len(ids), "not_found": []})

    with make_client(handler) as sf:
        cards, missing = sf.collection([{"name": f"c{i}"} for i in range(160)])
    assert batches == [75, 75, 10]
    assert len(cards) == 160 and missing == []


def test_double_faced_image_url():
    card = Card.from_dict(
        {"object": "card", "name": "A // B", "card_faces": [{"name": "A", "image_uris": {"normal": "front"}}, {"name": "B", "image_uris": {"normal": "back"}}]}
    )
    assert card.image_url() == "front"
    assert card.image_url(face=1) == "back"


def test_rate_limiter_spacing():
    now = {"t": 0.0}
    slept = []

    def sleep(d):
        slept.append(round(d, 3))
        now["t"] += d

    rl = RateLimiter(0.1, {"heavy": 0.5}, clock=lambda: now["t"], sleep=sleep)
    rl.wait("heavy")
    rl.wait()
    rl.wait("heavy")
    assert slept == [0.1, 0.4]


def test_iter_json_array_small_chunks(tmp_path):
    items = [{"name": f"card {i}", "text": "x" * (i * 7)} for i in range(50)]
    path = tmp_path / "bulk.json"
    path.write_text("[\n" + ",\n".join(json.dumps(i) for i in items) + "\n]", encoding="utf-8")
    assert list(iter_json_array(path, chunk_size=64)) == items

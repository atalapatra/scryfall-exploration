"""Tests against real Scryfall responses saved in tests/fixtures/ (refresh: python scripts/capture_fixtures.py)."""

import gzip
import json
from pathlib import Path

import httpx
import pytest

from scryfall import BulkData, Card, ManaCost, NotFoundError, RateLimiter, Ruling, ScryfallClient, Set, bulk
from scryfall.models import parse_object

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def client_returning(payload_by_path, status=200):
    def handler(request):
        for key, payload in payload_by_path.items():
            if key in str(request.url):
                return httpx.Response(status, json=payload) if isinstance(payload, (dict, list)) else payload
        raise AssertionError(f"unexpected request {request.url}")

    return ScryfallClient(transport=httpx.MockTransport(handler), rate_limiter=RateLimiter(0, {}), backoff=0)


@pytest.mark.parametrize(
    "name,cls",
    [
        ("card_normal", Card),
        ("card_split", Card),
        ("card_transform_dfc", Card),
        ("card_creature", Card),
        ("set", Set),
        ("bulk_data_item", BulkData),
        ("mana_cost", ManaCost),
    ],
)
def test_fixture_parses_to_model(name, cls):
    obj = parse_object(load(name))
    assert isinstance(obj, cls)


def test_normal_card():
    card = Card.from_dict(load("card_normal"))
    assert card.name == "Lightning Bolt" and card.set_code == "m11"
    assert card.image_url() and card.card_faces is None
    assert card.price("usd") is not None


def test_split_card_has_shared_image_and_per_face_text():
    card = Card.from_dict(load("card_split"))
    assert card.layout == "split"
    assert card.image_url()  # split cards keep one image at the top level
    assert card.oracle_text is None  # ...but their rules text is only on the faces
    assert [f.name for f in card.card_faces] == ["Fire", "Ice"]
    assert all(f.oracle_text for f in card.card_faces)


def test_transform_card_has_per_face_images():
    card = Card.from_dict(load("card_transform_dfc"))
    assert card.layout == "transform"
    assert card.image_uris is None and card.mana_cost is None
    assert card.image_url(face=0) != card.image_url(face=1)
    assert card.card_faces[1].power is not None


def test_search_page_and_rulings_through_client():
    with client_returning({"/cards/search": load("search_page"), "/rulings": load("rulings")}) as sf:
        cards = list(sf.search("t:dragon e:m21"))
        rulings = sf.rulings("whatever")
    assert len(cards) == load("search_page")["total_cards"]
    assert all(isinstance(r, Ruling) for r in rulings)


def test_real_error_shape_raises_not_found():
    with client_returning({"/cards/named": load("error_not_found")}, status=404) as sf:
        with pytest.raises(NotFoundError):
            sf.named("Definitely Not A Real Card")


def test_bulk_download_and_iter_jsonl_gz(tmp_path):
    info = load("bulk_data_item")
    cards = [load("card_normal"), load("card_split")]
    body = gzip.compress(("\n".join(json.dumps(c) for c in cards) + "\n").encode())
    responses = {
        "/bulk-data/oracle_cards": info,
        "data.scryfall.io": httpx.Response(200, content=body, headers={"content-type": "application/gzip"}),
    }
    with client_returning(responses) as sf:
        path = bulk.download(sf, "oracle_cards", tmp_path)
        assert path.name.endswith(".jsonl.gz")
        assert bulk.download(sf, "oracle_cards", tmp_path) == path  # second call reuses the saved file
    assert [c.name for c in bulk.iter_cards(path)] == ["Lightning Bolt", "Fire // Ice"]

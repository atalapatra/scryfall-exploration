import json
from pathlib import Path

import httpx

from scryfall import Card, RateLimiter, ScryfallClient
from scryfall.decklist import lookup, parse_decklist
from scryfall.tags import TagIndex

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def collection_client(responder):
    def handler(request):
        return httpx.Response(200, json=responder(json.loads(request.content)["identifiers"]))

    return ScryfallClient(transport=httpx.MockTransport(handler), rate_limiter=RateLimiter(0, {}))


# ---------------------------------------------------------------- parsing


def test_parse_common_formats():
    text = """
    Commander
    1 Atraxa, Praetors' Voice

    Deck
    1x Sol Ring (CMM) 410 *F*
    4 Lightning Bolt
    Swords to Plowshares
    1 Delver of Secrets // Insectile Aberration
    1 Cultivate (m21) [Ramp, Land]
    # a comment
    // another comment
    Creatures (2)
    2 Llanowar Elves
    SB: 2 Pyroblast
    """
    e = parse_decklist(text)
    assert [(x.quantity, x.name) for x in e] == [
        (1, "Atraxa, Praetors' Voice"),
        (1, "Sol Ring"),
        (4, "Lightning Bolt"),
        (1, "Swords to Plowshares"),
        (1, "Delver of Secrets // Insectile Aberration"),
        (1, "Cultivate"),
        (2, "Llanowar Elves"),
        (2, "Pyroblast"),
    ]
    assert e[0].section == "commander" and e[1].section == "deck" and e[6].section == "creatures"
    assert e[7].section == "sideboard"
    assert e[1].identifier() == {"set": "cmm", "collector_number": "410"}
    assert e[4].identifier() == {"name": "Delver of Secrets"}  # front face only
    assert e[5].identifier() == {"name": "Cultivate", "set": "m21"}
    assert e[5].labels == ["Ramp", "Land"]


def test_card_name_that_looks_like_header_word_is_still_a_card():
    # "Lands" alone is a header, but a line with a quantity is always a card.
    e = parse_decklist("Lands\n1 Command Tower\n")
    assert [(x.name, x.section) for x in e] == [("Command Tower", "lands")]


# ---------------------------------------------------------------- cards_for alignment


def test_cards_for_aligns_with_real_collection_response():
    fx = load("collection")
    with collection_client(lambda ids: fx["response"]) as sf:
        result = sf.cards_for(fx["request"]["identifiers"])
    names = [c.name if c else None for c in result]
    # Real Scryfall behaviour: "Fire" (front face) matches, "Fire // Ice" (full name) does not.
    assert names == ["Sol Ring", None, "Fire // Ice", None, "Sol Ring", "Swords to Plowshares"]


def test_lookup_dedupes_requests_and_keeps_line_order():
    sent = []

    def responder(ids):
        sent.extend(ids)
        return {"object": "list", "not_found": [], "data": [{"object": "card", "name": i["name"]} for i in ids]}

    with collection_client(responder) as sf:
        result = lookup(sf, "1 Sol Ring\n1 Island\n1 sol ring\n")
    assert sent == [{"name": "Sol Ring"}, {"name": "Island"}]
    assert [c.card.name for c in result.cards] == ["Sol Ring", "Island", "Sol Ring"]
    assert result.not_found == []


# ---------------------------------------------------------------- tags


def tag_index():
    return TagIndex(load("oracle_tags_subset")["records"])


def oracle_id(name):
    return next(oid for oid, n in load("oracle_tags_subset")["sample_cards"].items() if n == name)


def test_tags_include_inherited_parents():
    idx = tag_index()
    sol = oracle_id("Sol Ring")
    direct = idx.tags_for(sol, inherited=False)
    full = idx.tags_for(sol)
    assert "mana-rock" in direct and "ramp" not in direct
    assert "ramp" in full  # inherited: mana-rock -> mana-producer -> ramp
    assert set(direct) < set(full)


def test_roles_and_alias_lookup():
    idx = tag_index()
    assert idx.get("wipe").slug == "sweeper"  # alias
    assert idx.get("Mana Rock").slug == "mana-rock"  # label
    rift = Card.from_dict({"object": "card", "name": "Cyclonic Rift", "oracle_id": oracle_id("Cyclonic Rift")})
    assert idx.roles_for(rift, ["sweeper", "ramp", "removal"]) == ["sweeper", "removal"]
    assert idx.roles_for(rift, ["wipe"]) == ["sweeper"]

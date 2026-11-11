"""Quick tour of the client. Run with: python examples/quickstart.py"""

from itertools import islice

from scryfall import FileCache, ScryfallClient

with ScryfallClient(user_agent="scryfall-exploration/0.1", cache=FileCache()) as sf:
    bolt = sf.named("lightnin bolt", fuzzy=True)
    print(bolt.name, bolt.mana_cost, bolt.type_line, bolt.price("usd"))

    print("\nCheapest-to-cast dragons:")
    for card in islice(sf.search("t:dragon", order="cmc"), 10):
        print(f"  {card.cmc:>4}  {card.name}")

    cards, missing = sf.collection([{"name": "Sol Ring"}, {"name": "Counterspell"}, {"name": "Not A Card"}])
    print("\nCollection:", [c.name for c in cards], "missing:", missing)

"""Save real Scryfall API responses as test fixtures.

Run from the repo root:  python scripts/capture_fixtures.py
Re-run this whenever you want fixtures that match Scryfall's current responses.
"""

import json
from pathlib import Path

from scryfall import ScryfallAPIError, ScryfallClient

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

# fixture filename -> (path, params)
REQUESTS = {
    "card_normal": ("/cards/named", {"exact": "Lightning Bolt", "set": "m11"}),
    "card_transform_dfc": ("/cards/named", {"exact": "Delver of Secrets", "set": "isd"}),
    "card_split": ("/cards/named", {"exact": "Fire // Ice", "set": "apc"}),
    "card_creature": ("/cards/named", {"exact": "Shivan Dragon", "set": "lea"}),
    "search_page": ("/cards/search", {"q": "t:dragon e:m21"}),
    "set": ("/sets/m21", None),
    "rulings": ("/cards/named", {"exact": "Delver of Secrets", "set": "isd"}),  # replaced below
    "bulk_data_item": ("/bulk-data/oracle_cards", None),
    "mana_cost": ("/symbology/parse-mana", {"cost": "{2}{W}{U}"}),
    "error_not_found": ("/cards/named", {"exact": "Definitely Not A Real Card"}),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with ScryfallClient(parse=False) as sf:
        for name, (path, params) in REQUESTS.items():
            if name == "rulings":
                delver = sf.request("GET", path, params=params)
                path, params = f"/cards/{delver['id']}/rulings", None
            try:
                data = sf.request("GET", path, params=params)
            except ScryfallAPIError as exc:
                data = exc.raw
            (OUT / f"{name}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"saved {name}.json")


if __name__ == "__main__":
    main()

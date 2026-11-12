"""Save real Scryfall API responses as test fixtures.

Run from the repo root:  python scripts/capture_fixtures.py
Re-run this whenever you want fixtures that match Scryfall's current responses.
"""

import json
from pathlib import Path

from scryfall import ScryfallAPIError, ScryfallClient, bulk

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "fixtures"

# fixture filename -> (path, params)
GETS = {
    "card_normal": ("/cards/named", {"exact": "Lightning Bolt", "set": "m11"}),
    "card_transform_dfc": ("/cards/named", {"exact": "Delver of Secrets", "set": "isd"}),
    "card_split": ("/cards/named", {"exact": "Fire // Ice", "set": "apc"}),
    "card_creature": ("/cards/named", {"exact": "Shivan Dragon", "set": "lea"}),
    "search_page": ("/cards/search", {"q": "t:dragon e:m21"}),
    "set": ("/sets/m21", None),
    "bulk_data_item": ("/bulk-data/oracle_cards", None),
    "mana_cost": ("/symbology/parse-mana", {"cost": "{2}{W}{U}"}),
    "error_not_found": ("/cards/named", {"exact": "Definitely Not A Real Card"}),
}

# A mix of matches, a miss, a front-face name, a full "A // B" name (which Scryfall does NOT match) and set+number.
COLLECTION_IDENTIFIERS = [
    {"name": "Sol Ring"},
    {"name": "Not A Real Card"},
    {"name": "Fire"},
    {"name": "Fire // Ice"},
    {"set": "cmm", "collector_number": "410"},
    {"name": "Swords to Plowshares"},
]

# Cards whose tags (and all ancestor tags) are kept in the oracle_tags_subset fixture.
TAG_SAMPLE_CARDS = ["Sol Ring", "Swords to Plowshares", "Cyclonic Rift"]


def save(name: str, data) -> None:
    (OUT / f"{name}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"saved {name}.json")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with ScryfallClient(parse=False) as sf:
        for name, (path, params) in GETS.items():
            try:
                data = sf.request("GET", path, params=params)
            except ScryfallAPIError as exc:
                data = exc.raw
            save(name, data)

        delver = sf.request("GET", "/cards/named", params={"exact": "Delver of Secrets", "set": "isd"})
        save("rulings", sf.request("GET", f"/cards/{delver['id']}/rulings"))

        save("collection", {
            "request": {"identifiers": COLLECTION_IDENTIFIERS},
            "response": sf.request("POST", "/cards/collection", json={"identifiers": COLLECTION_IDENTIFIERS}),
        })  # fmt: skip

        save_tag_subset(sf)


def save_tag_subset(sf: ScryfallClient) -> None:
    """Keep real tag records for a few cards, plus their ancestor tags, with taggings trimmed to those cards."""
    sample = {sf.request("GET", "/cards/named", params={"exact": n})["oracle_id"]: n for n in TAG_SAMPLE_CARDS}
    with ScryfallClient() as parsed_client:  # bulk.download needs model objects, so not the parse=False client
        path = bulk.download(parsed_client, "oracle_tags", ROOT / "data")
    records = {r["id"]: r for r in bulk.iter_records(path)}

    keep = {tid for tid, r in records.items() if any(t["oracle_id"] in sample for t in r["taggings"])}
    stack = list(keep)
    while stack:
        for pid in records[stack.pop()]["parent_ids"]:
            if pid in records and pid not in keep:
                keep.add(pid)
                stack.append(pid)

    subset = []
    for tid in sorted(keep):
        rec = dict(records[tid])
        rec["taggings"] = [t for t in rec["taggings"] if t["oracle_id"] in sample]
        rec["child_ids"] = [c for c in rec["child_ids"] if c in keep]
        subset.append(rec)
    save("oracle_tags_subset", {"sample_cards": sample, "records": subset})


if __name__ == "__main__":
    main()

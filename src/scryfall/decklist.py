"""Parse plain-text card lists and look up each card's details and tags.

Accepts the common export formats, e.g.::

    Commander
    1 Atraxa, Praetors' Voice
    Deck
    1x Sol Ring (CMM) 410 *F*
    1 Delver of Secrets // Insectile Aberration
    Swords to Plowshares
    1 Cultivate [Ramp]          # Archidekt-style [category]
    SB: 2 Pyroblast
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from .client import ScryfallClient
from .models import Card
from .tags import DEFAULT_ROLES, TagIndex

SECTION_HEADERS = {
    "commander", "commanders", "companion", "deck", "main", "mainboard", "maindeck", "sideboard",
    "maybeboard", "considering", "creature", "creatures", "land", "lands", "instant", "instants",
    "sorcery", "sorceries", "artifact", "artifacts", "enchantment", "enchantments", "planeswalker",
    "planeswalkers", "battle", "battles", "spells", "other", "tokens",
}  # fmt: skip

_HEADER_RE = re.compile(r"^(?P<name>[A-Za-z ]+?)\s*(?:\(\d+\))?\s*:?$")
_LINE_RE = re.compile(
    r"""^
    (?:(?P<qty>\d+)\s*x?\s+)?                      # "1 ", "1x ", "4x"
    (?P<name>.+?)
    (?:\s+\((?P<set>[A-Za-z0-9]{2,6})\)            # " (CMM)"
       (?:\s+(?P<num>[^\s*\[]+))?)?                # " 410"
    (?P<rest>(?:\s+(?:\*[A-Za-z]+\*|\[[^\]]*\]|\^[^^]*\^))*)  # "*F*", "[Ramp]", "^Tag^"
    \s*$""",
    re.VERBOSE,
)


@dataclass
class DeckEntry:
    name: str
    quantity: int = 1
    set_code: str | None = None
    collector_number: str | None = None
    section: str | None = None
    labels: list[str] = field(default_factory=list)  # e.g. Archidekt "[Ramp]" categories
    line: str = ""

    @property
    def lookup_name(self) -> str:
        """Front-face name. Scryfall's collection endpoint does not find "A // B" names."""
        return self.name.split(" // ")[0].strip()

    def identifier(self) -> dict[str, str]:
        if self.set_code and self.collector_number:
            return {"set": self.set_code.lower(), "collector_number": self.collector_number}
        if self.set_code:
            return {"name": self.lookup_name, "set": self.set_code.lower()}
        return {"name": self.lookup_name}


def parse_decklist(text: str) -> list[DeckEntry]:
    """Parse a text card list into entries. Blank lines, comments (#, //) and section headers are skipped."""
    entries: list[DeckEntry] = []
    section: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "//")):
            continue
        header = _HEADER_RE.match(line)
        if header and header["name"].strip().lower() in SECTION_HEADERS:
            section = header["name"].strip().lower()
            continue

        line_section = section
        if line.upper().startswith("SB:"):
            line, line_section = line[3:].strip(), "sideboard"

        m = _LINE_RE.match(line)
        if not m:
            continue
        labels = re.findall(r"\[([^\]]*)\]", m["rest"] or "")
        entries.append(
            DeckEntry(
                name=m["name"].strip(),
                quantity=int(m["qty"]) if m["qty"] else 1,
                set_code=m["set"],
                collector_number=m["num"],
                section=line_section,
                labels=[part.strip() for lab in labels for part in lab.split(",") if part.strip()],
                line=raw_line,
            )
        )
    return entries


@dataclass
class CardInfo:
    entry: DeckEntry
    card: Card
    tags: list[str] = field(default_factory=list)  # direct and inherited tag slugs
    roles: list[str] = field(default_factory=list)  # the subset of tags in the chosen roles list

    def as_row(self) -> dict[str, Any]:
        """A flat dict, handy for CSV export or ``pandas.DataFrame(...)``."""
        c = self.card
        return {
            "quantity": self.entry.quantity,
            "name": c.name,
            "section": self.entry.section,
            "type_line": c.type_line,
            "mana_cost": c.mana_cost or " // ".join(f.mana_cost or "" for f in c.card_faces or []),
            "cmc": c.cmc,
            "color_identity": "".join(c.color_identity),
            "edhrec_rank": c.edhrec_rank,
            "usd": c.price("usd"),
            "roles": ", ".join(self.roles),
            "tags": ", ".join(self.tags),
            "set": c.set_code,
            "scryfall_uri": c.scryfall_uri,
        }


@dataclass
class LookupResult:
    cards: list[CardInfo]
    not_found: list[DeckEntry]

    def rows(self) -> list[dict[str, Any]]:
        return [c.as_row() for c in self.cards]


def lookup(
    client: ScryfallClient,
    entries: str | Iterable[DeckEntry],
    *,
    tag_index: TagIndex | None = None,
    roles: Iterable[str] = DEFAULT_ROLES,
) -> LookupResult:
    """Fetch each entry's card, using as few requests as possible, and attach tags if ``tag_index`` is given.

    ``entries`` can be raw decklist text or parsed ``DeckEntry`` objects.
    """
    if isinstance(entries, str):
        entries = parse_decklist(entries)
    entries = list(entries)
    roles = list(roles)

    # Send each distinct identifier once, even if the same card appears on several lines.
    unique_ids: dict[tuple, dict[str, str]] = {}
    for entry in entries:
        ident = entry.identifier()
        unique_ids.setdefault(_key(ident), ident)
    found = dict(zip(unique_ids, client.cards_for(unique_ids.values())))

    result = LookupResult(cards=[], not_found=[])
    for entry in entries:
        card = found[_key(entry.identifier())]
        if card is None:
            result.not_found.append(entry)
            continue
        info = CardInfo(entry=entry, card=card)
        if tag_index is not None:
            info.tags = tag_index.tags_for(card)
            info.roles = tag_index.roles_for(card, roles)
        result.cards.append(info)
    return result


def _key(ident: dict[str, str]) -> tuple:
    return tuple(sorted((k, v.lower()) for k, v in ident.items()))

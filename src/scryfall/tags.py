"""Scryfall Tagger tags (https://tagger.scryfall.com), read from the ``oracle_tags`` bulk file.

Card objects from the API do not include tags. The ``oracle_tags`` bulk file
lists each tag with the cards (``oracle_id``) tagged with it, plus the tag's
parent tags. Tags form a hierarchy: e.g. ``removal`` has no cards tagged
directly, only child tags such as ``spot-removal`` and ``sweeper``. So
``tags_for(..., inherited=True)`` adds the ancestors of every direct tag.
This matches how ``otag:removal`` behaves in Scryfall search.

Tags are identified by ``slug`` (e.g. ``mana-rock``), which is the form
Scryfall's ``otag:`` search syntax uses.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import bulk
from .client import ScryfallClient
from .models import Card

# A starting set of broad "what does this card do in a deck" tags (all checked to exist on 2026-11-11).
# Pass your own list to TagIndex.roles_for() to change it.
DEFAULT_ROLES = (
    "ramp",
    "card-advantage",
    "draw",
    "tutor",
    "removal",
    "spot-removal",
    "sweeper",
    "counterspell",
    "protection",
    "recursion",
    "sacrifice-outlet",
    "flicker",
    "anthem",
    "cost-reducer",
    "lifegain",
    "burn",
    "mill",
    "discard",
    "combat-trick",
    "extra-turn",
    "alternate-win-condition",
)


@dataclass
class Tag:
    id: str
    slug: str
    label: str
    description: str = ""
    parent_ids: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)


class TagIndex:
    """Looks up a card's tags by ``oracle_id``, following the tag hierarchy."""

    def __init__(self, records: Iterable[dict[str, Any]]) -> None:
        self.tags: dict[str, Tag] = {}
        self._direct: dict[str, set[str]] = defaultdict(set)  # oracle_id -> tag ids
        self._by_name: dict[str, str] = {}  # slug / label / alias -> tag id
        self._ancestor_cache: dict[str, frozenset[str]] = {}

        for rec in records:
            tag = Tag(
                id=rec["id"],
                slug=rec["slug"],
                label=rec.get("label", rec["slug"]),
                description=rec.get("description") or "",
                parent_ids=list(rec.get("parent_ids") or []),
                aliases=list(rec.get("aliases") or []),
            )
            self.tags[tag.id] = tag
            for tagging in rec.get("taggings") or []:
                self._direct[tagging["oracle_id"]].add(tag.id)

        # Register aliases first, so that a real slug or label wins over another tag's alias.
        for tag in self.tags.values():
            for alias in tag.aliases:
                self._by_name.setdefault(_norm(alias), tag.id)
        for tag in self.tags.values():
            self._by_name[_norm(tag.label)] = tag.id
            self._by_name[_norm(tag.slug)] = tag.id

    @classmethod
    def from_file(cls, path: str | Path) -> "TagIndex":
        return cls(bulk.iter_records(path))

    @classmethod
    def load(cls, client: ScryfallClient, dest_dir: str | Path = "data") -> "TagIndex":
        """Download the ``oracle_tags`` bulk file if needed, then build an index from it."""
        return cls.from_file(bulk.download(client, "oracle_tags", dest_dir))

    def __len__(self) -> int:
        return len(self.tags)

    def get(self, name: str) -> Tag | None:
        """Find a tag by slug, label or alias (e.g. ``"wipe"`` finds ``sweeper``)."""
        tag_id = self._by_name.get(_norm(name))
        return self.tags.get(tag_id) if tag_id else None

    def tags_for(self, card_or_oracle_id: Card | str, *, inherited: bool = True) -> list[str]:
        """Sorted tag slugs for a card. With ``inherited=True``, also includes all ancestor tags."""
        ids = set()
        for oid in _oracle_ids(card_or_oracle_id):
            ids |= self._direct.get(oid, set())
        if inherited:
            for tag_id in list(ids):
                ids |= self._ancestors(tag_id)
        return sorted(self.tags[t].slug for t in ids if t in self.tags)

    def roles_for(self, card_or_oracle_id: Card | str, roles: Iterable[str] = DEFAULT_ROLES) -> list[str]:
        """The card's tags (including inherited ones) that appear in ``roles``, in ``roles`` order."""
        have = set(self.tags_for(card_or_oracle_id, inherited=True))
        wanted = [self.get(r).slug if self.get(r) else r for r in roles]  # type: ignore[union-attr]
        return [r for r in wanted if r in have]

    def _ancestors(self, tag_id: str) -> frozenset[str]:
        cached = self._ancestor_cache.get(tag_id)
        if cached is not None:
            return cached
        seen: set[str] = set()
        stack = list(self.tags[tag_id].parent_ids) if tag_id in self.tags else []
        while stack:
            pid = stack.pop()
            if pid in seen or pid not in self.tags:
                continue
            seen.add(pid)
            stack.extend(self.tags[pid].parent_ids)
        result = frozenset(seen)
        self._ancestor_cache[tag_id] = result
        return result


def _oracle_ids(card_or_oracle_id: Card | str) -> list[str]:
    if isinstance(card_or_oracle_id, str):
        return [card_or_oracle_id]
    card = card_or_oracle_id
    if card.oracle_id:
        return [card.oracle_id]
    # Some layouts (e.g. reversible_card) put oracle_id on each face instead of the card.
    return [f.raw["oracle_id"] for f in card.card_faces or [] if f.raw.get("oracle_id")]


def _norm(name: str) -> str:
    return name.strip().lower().replace(" ", "-")

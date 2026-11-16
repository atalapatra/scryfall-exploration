"""Light, typed wrappers around Scryfall JSON objects.

Each model has typed attributes for the commonly used fields and keeps the
full JSON payload in ``.raw``. Other fields can be read as attributes too
(``card.frame_effects``), or with ``card.raw.get(...)``. So when Scryfall
adds new fields, they are available right away, without changing this code.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import date
from typing import Any, ClassVar, TypeVar

T = TypeVar("T", bound="ScryfallObject")


@dataclass(repr=False)
class ScryfallObject:
    raw: dict[str, Any] = field(default_factory=dict, compare=False)

    # Maps a JSON key to a Python attribute name, where the two differ (e.g. "set" -> "set_code").
    _renames: ClassVar[dict[str, str]] = {}

    @classmethod
    def from_dict(cls: type[T], data: dict[str, Any]) -> T:
        names = {f.name for f in fields(cls)} - {"raw"}
        kwargs: dict[str, Any] = {}
        for key, value in data.items():
            attr = cls._renames.get(key, key)
            if attr in names:
                kwargs[attr] = value
        obj = cls(raw=data, **kwargs)
        obj.__post_init_from_dict__()
        return obj

    def __post_init_from_dict__(self) -> None:
        """Hook for subclasses to convert nested objects."""

    def __getattr__(self, name: str) -> Any:
        # Only called when normal attribute lookup fails: fall back to the raw JSON.
        raw = self.__dict__.get("raw", {})
        if name in raw:
            return raw[name]
        raise AttributeError(f"{type(self).__name__!s} has no attribute {name!r}")

    def __repr__(self) -> str:
        label = self.raw.get("name") or self.raw.get("code") or self.raw.get("id")
        return f"<{type(self).__name__} {label!r}>"


@dataclass(repr=False)
class CardFace(ScryfallObject):
    name: str = ""
    mana_cost: str | None = None
    type_line: str | None = None
    oracle_text: str | None = None
    colors: list[str] | None = None
    power: str | None = None
    toughness: str | None = None
    loyalty: str | None = None
    image_uris: dict[str, str] | None = None


@dataclass(repr=False)
class Card(ScryfallObject):
    _renames: ClassVar[dict[str, str]] = {"set": "set_code"}

    id: str = ""
    oracle_id: str | None = None
    name: str = ""
    lang: str = "en"
    layout: str = ""
    released_at: str | None = None
    mana_cost: str | None = None
    cmc: float = 0.0
    type_line: str = ""
    oracle_text: str | None = None
    power: str | None = None
    toughness: str | None = None
    loyalty: str | None = None
    colors: list[str] | None = None
    color_identity: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    legalities: dict[str, str] = field(default_factory=dict)
    games: list[str] = field(default_factory=list)
    reserved: bool = False
    set_code: str = ""
    set_name: str = ""
    collector_number: str = ""
    rarity: str = ""
    artist: str | None = None
    digital: bool = False
    image_uris: dict[str, str] | None = None
    card_faces: list[CardFace] | None = None
    prices: dict[str, str | None] = field(default_factory=dict)
    edhrec_rank: int | None = None
    scryfall_uri: str = ""
    uri: str = ""

    def __post_init_from_dict__(self) -> None:
        if self.card_faces:
            self.card_faces = [CardFace.from_dict(f) for f in self.card_faces]  # type: ignore[arg-type]

    @property
    def released(self) -> date | None:
        return date.fromisoformat(self.released_at) if self.released_at else None

    def is_legal(self, format: str) -> bool:
        return self.legalities.get(format) == "legal"

    def price(self, kind: str = "usd") -> float | None:
        """Price as a float, e.g. ``kind="usd"``, ``"usd_foil"``, ``"eur"``, ``"tix"``."""
        value = self.prices.get(kind)
        return float(value) if value else None

    def image_url(self, size: str = "normal", face: int = 0) -> str | None:
        """Image URL for the card. Double-faced cards store images per face.

        Sizes: small, normal, large, png, art_crop, border_crop.
        """
        if self.image_uris:
            return self.image_uris.get(size)
        if self.card_faces and len(self.card_faces) > face and self.card_faces[face].image_uris:
            return self.card_faces[face].image_uris.get(size)  # type: ignore[union-attr]
        return None


@dataclass(repr=False)
class Set(ScryfallObject):
    id: str = ""
    code: str = ""
    name: str = ""
    set_type: str = ""
    released_at: str | None = None
    card_count: int = 0
    digital: bool = False
    parent_set_code: str | None = None
    icon_svg_uri: str | None = None
    search_uri: str = ""


@dataclass(repr=False)
class Ruling(ScryfallObject):
    oracle_id: str = ""
    source: str = ""
    published_at: str = ""
    comment: str = ""


@dataclass(repr=False)
class BulkData(ScryfallObject):
    id: str = ""
    type: str = ""
    name: str = ""
    description: str = ""
    updated_at: str = ""
    # Current format: gzipped JSON Lines. download_uri/size are the older format's fields, kept for compatibility.
    jsonl_download_uri: str | None = None
    compressed_size: int | None = None
    download_uri: str | None = None
    size: int | None = None


@dataclass(repr=False)
class CardSymbol(ScryfallObject):
    symbol: str = ""
    english: str = ""
    cmc: float | None = None
    colors: list[str] = field(default_factory=list)
    svg_uri: str | None = None


@dataclass(repr=False)
class ManaCost(ScryfallObject):
    cost: str = ""
    cmc: float = 0.0
    colors: list[str] = field(default_factory=list)
    colorless: bool = False
    monocolored: bool = False
    multicolored: bool = False


# Maps Scryfall's "object" field to the model class that wraps it.
OBJECT_TYPES: dict[str, type[ScryfallObject]] = {
    "card": Card,
    "card_face": CardFace,
    "set": Set,
    "ruling": Ruling,
    "bulk_data": BulkData,
    "card_symbol": CardSymbol,
    "mana_cost": ManaCost,
}


def parse_object(data: Any) -> Any:
    """Wrap a JSON object in its model class, based on its ``object`` field.

    Unknown object types are returned unchanged.
    """
    if isinstance(data, dict):
        model = OBJECT_TYPES.get(data.get("object", ""))
        if model is not None:
            return model.from_dict(data)
    return data

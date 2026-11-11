"""Download and stream Scryfall bulk data files.

Bulk files (https://scryfall.com/docs/api/bulk-data) are the right tool for
analysing many cards. Scryfall now publishes them as gzipped JSON Lines
(``*.jsonl.gz``: one JSON object per line), linked by ``jsonl_download_uri``.
They are saved compressed and decompressed while reading, so even
``all_cards`` (~400 MB compressed) can be processed with little memory.

Older-style plain JSON-array files (``download_uri``) are still supported
when reading.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from .client import ScryfallClient
from .errors import ScryfallError
from .models import Card, Ruling


def download(
    client: ScryfallClient,
    type: str = "oracle_cards",
    dest_dir: str | Path = "data",
    *,
    force: bool = False,
) -> Path:
    """Download a bulk file and return its local path.

    Skips the download if the newest version is already saved locally (files
    are named after their ``updated_at`` timestamp), unless ``force=True``.
    """
    info = client.bulk_data_info(type)
    url = info.raw.get("jsonl_download_uri") or info.raw.get("download_uri")
    if not url:
        raise ScryfallError(f"Bulk data {type!r} has no download URI: {sorted(info.raw)}")

    stamp = datetime.fromisoformat(info.updated_at.replace("Z", "+00:00")).strftime("%Y%m%d%H%M%S")
    suffix = ".jsonl.gz" if url.endswith(".jsonl.gz") else Path(httpx.URL(url).path).suffix or ".json"
    dest = Path(dest_dir) / f"{type}-{stamp}{suffix}"
    if dest.exists() and not force:
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    # Bulk files are served from data.scryfall.io, which has no rate limit, so skip the
    # client's rate limiter but reuse its HTTP connection (same required headers; fake transport in tests).
    with client._http.stream("GET", url, timeout=None) as resp:
        resp.raise_for_status()
        with tmp.open("wb") as fh:
            for chunk in resp.iter_bytes(1 << 20):
                fh.write(chunk)
    tmp.replace(dest)
    return dest


def iter_records(path: str | Path) -> Iterator[dict[str, Any]]:
    """Yield each JSON object in a bulk file. Works for any bulk type, including tags."""
    path = Path(path)
    if path.name.endswith((".jsonl.gz", ".jsonl")):
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)
    else:
        yield from iter_json_array(path)


def iter_cards(path: str | Path) -> Iterator[Card]:
    """Yield each card in a bulk card file (oracle_cards, default_cards, ...) as a ``Card``."""
    for obj in iter_records(path):
        yield Card.from_dict(obj)


def iter_rulings(path: str | Path) -> Iterator[Ruling]:
    """Yield each ruling in a downloaded ``rulings`` bulk file as a ``Ruling``."""
    for obj in iter_records(path):
        yield Ruling.from_dict(obj)


def iter_json_array(path: str | Path, chunk_size: int = 1 << 20) -> Iterator[Any]:
    """Yield each element of a top-level JSON array, reading the file in chunks (older bulk format)."""
    decoder = json.JSONDecoder()
    with Path(path).open("r", encoding="utf-8") as fh:
        buf = fh.read(chunk_size)
        pos = _skip(buf, 0)
        if pos >= len(buf) or buf[pos] != "[":
            raise ValueError(f"{path} does not contain a JSON array")
        pos += 1
        eof = False
        while True:
            pos = _skip(buf, pos, ",")
            if pos < len(buf) and buf[pos] == "]":
                return
            try:
                obj, end = decoder.raw_decode(buf, pos)
            except json.JSONDecodeError:
                # The current element continues past the end of the buffer: read more and retry.
                if eof:
                    raise
                more = fh.read(chunk_size)
                eof = not more
                buf = buf[pos:] + more
                pos = 0
                continue
            yield obj
            pos = end
            if len(buf) - pos < chunk_size // 4 and not eof:
                more = fh.read(chunk_size)
                eof = not more
                buf = buf[pos:] + more
                pos = 0


def _skip(buf: str, pos: int, extra: str = "") -> int:
    while pos < len(buf) and (buf[pos].isspace() or buf[pos] in extra):
        pos += 1
    return pos

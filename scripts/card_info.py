"""Look up EDHREC rank, roles and tags for every card in a text list.

Usage (from the repo root):
    python scripts/card_info.py examples/decklist.txt
    python scripts/card_info.py deck.txt --csv deck.csv
    python scripts/card_info.py deck.txt --roles ramp,removal,draw,wipe
    python scripts/card_info.py deck.txt --no-tags          # skip the ~6 MB tag download
    type deck.txt | python scripts/card_info.py -          # read from stdin
"""

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

from scryfall import FileCache, ScryfallClient
from scryfall.decklist import lookup
from scryfall.tags import DEFAULT_ROLES, TagIndex


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", help="text file with one card per line, or - for stdin")
    parser.add_argument("--csv", type=Path, help="also write every field (including all tags) to this CSV file")
    parser.add_argument("--roles", help=f"comma-separated tags to show as roles (default: {','.join(DEFAULT_ROLES)})")
    parser.add_argument("--no-tags", action="store_true", help="skip tags (no bulk download needed)")
    parser.add_argument("--sort", choices=["list", "edhrec", "name", "cmc"], default="list")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")  # card names can contain characters the Windows console can't print by default
    text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
    roles = [r.strip() for r in args.roles.split(",")] if args.roles else list(DEFAULT_ROLES)

    with ScryfallClient(cache=FileCache()) as sf:
        tag_index = None if args.no_tags else TagIndex.load(sf)
        if tag_index is not None:
            unknown = [r for r in roles if tag_index.get(r) is None]
            if unknown:
                print(f"warning: unknown tags ignored: {', '.join(unknown)}", file=sys.stderr)
        result = lookup(sf, text, tag_index=tag_index, roles=roles)

    rows = result.rows()
    if args.sort == "edhrec":
        rows.sort(key=lambda r: r["edhrec_rank"] if r["edhrec_rank"] is not None else float("inf"))
    elif args.sort in ("name", "cmc"):
        rows.sort(key=lambda r: r[args.sort])

    print_table(rows, show_roles=tag_index is not None)

    if tag_index is not None:
        counts = Counter(role for r in rows for role in r["roles"].split(", ") if role for _ in range(r["quantity"]))
        if counts:
            print("\nRole counts (by quantity):", ", ".join(f"{k} {v}" for k, v in counts.most_common()))
    if result.not_found:
        sys.stdout.flush()  # so the warning appears after the table
        print("\nNot found:", "; ".join(e.line.strip() for e in result.not_found), file=sys.stderr)

    if args.csv:
        with args.csv.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["name"])
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nWrote {len(rows)} rows to {args.csv}")
    return 1 if result.not_found else 0


def print_table(rows: list[dict], show_roles: bool) -> None:
    cols = [("quantity", "Qty"), ("name", "Name"), ("cmc", "MV"), ("edhrec_rank", "EDHREC"), ("usd", "USD")]
    if show_roles:
        cols.append(("roles", "Roles"))
    cells = [[_fmt(r[k]) for k, _ in cols] for r in rows]
    widths = [max([len(h)] + [len(c[i]) for c in cells]) for i, (_, h) in enumerate(cols)]
    widths[1] = min(widths[1], 40)
    print("  ".join(h.ljust(w) for (_, h), w in zip(cols, widths)))
    print("  ".join("-" * w for w in widths))
    for c in cells:
        print("  ".join(v[:w].ljust(w) for v, w in zip(c, widths)))


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


if __name__ == "__main__":
    sys.exit(main())

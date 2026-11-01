"""`tsdb-dump <path> [--hex]`: print an SSTable, WAL segment, series.log or MANIFEST as text.
A directory dumps every file inside. Used for debugging and for the on-disk format demo."""

from __future__ import annotations


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())

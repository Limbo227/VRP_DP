#!/usr/bin/env python3
"""Rewrite repo README.md as UTF-8 if it was saved as UTF-16 (fixes 'binary' editor errors)."""
from __future__ import annotations

from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    p = root / "README.md"
    if not p.is_file():
        print("README.md not found:", p)
        raise SystemExit(1)
    raw = p.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        text = raw.decode("utf-16")
    elif len(raw) > 4 and raw[1] == 0 and raw[3] == 0 and raw[0] < 0x80:
        text = raw.decode("utf-16-le")
    else:
        text = raw.decode("utf-8")
    p.write_text(text, encoding="utf-8", newline="\n")
    print("OK:", p, "-> utf-8,", len(text), "chars")


if __name__ == "__main__":
    main()

"""Counting units for text offsets and conversion between them.

The same selection has a different start and end number depending on what is
counted:

- utf8: bytes of the UTF-8 encoding (Go and Rust strings, HTTP Range, W3C DataPositionSelector)
- utf16: UTF-16 code units (JavaScript strings, DOM Range, Java, .NET)
- codepoint: Unicode scalar values (Python str, Rust chars(), Go runes, RFC 5147, W3C TextPositionSelector)
- grapheme: extended grapheme clusters (what a reader perceives as one character; Unicode UAX #29)

A Ruler indexes one text once and converts offsets between units. Offsets that
fall inside a unit (a byte inside a multi-byte sequence, a code unit between
surrogates, a code point inside a grapheme cluster) raise BoundaryError rather
than being rounded.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass

import regex

UNITS = ("utf8", "utf16", "codepoint", "grapheme")
_GRAPHEME = regex.compile(r"\X")


class BoundaryError(ValueError):
    """An offset does not lie on a boundary of the requested unit."""


@dataclass(frozen=True)
class Measurement:
    unit: str
    start: int
    end: int
    on_boundary: bool = True

    def as_list(self) -> list[int]:
        return [self.start, self.end]


def _utf8_len(o: int) -> int:
    if o < 0x80:
        return 1
    if o < 0x800:
        return 2
    if o < 0x10000:
        return 3
    return 4


class Ruler:
    """Offset tables for one text. Build once, convert many times."""

    def __init__(self, text: str):
        self.text = text
        n = len(text)
        u8 = [0] * (n + 1)
        u16 = [0] * (n + 1)
        for i, ch in enumerate(text):
            o = ord(ch)
            u8[i + 1] = u8[i] + _utf8_len(o)
            u16[i + 1] = u16[i] + (2 if o > 0xFFFF else 1)
        self._u8 = u8
        self._u16 = u16
        self._graphemes = [m.start() for m in _GRAPHEME.finditer(text)] + [n]

    @property
    def codepoints(self) -> int:
        return len(self.text)

    def length(self, unit: str) -> int:
        if unit == "codepoint":
            return len(self.text)
        if unit == "utf8":
            return self._u8[-1]
        if unit == "utf16":
            return self._u16[-1]
        if unit == "grapheme":
            return len(self._graphemes) - 1
        raise ValueError(f"unknown unit {unit!r}")

    def to_codepoint(self, offset: int, unit: str) -> int:
        """Convert an offset counted in `unit` to a code-point offset."""
        if offset < 0:
            raise BoundaryError(f"negative offset {offset}")
        if unit == "codepoint":
            if offset > len(self.text):
                raise BoundaryError(f"code-point offset {offset} beyond text length {len(self.text)}")
            return offset
        if unit == "grapheme":
            if offset >= len(self._graphemes):
                raise BoundaryError(f"grapheme offset {offset} beyond {len(self._graphemes) - 1} clusters")
            return self._graphemes[offset]
        table = self._u8 if unit == "utf8" else self._u16 if unit == "utf16" else None
        if table is None:
            raise ValueError(f"unknown unit {unit!r}")
        i = bisect_left(table, offset)
        if i >= len(table) or table[i] != offset:
            if offset > table[-1]:
                raise BoundaryError(f"{unit} offset {offset} beyond text length {table[-1]}")
            raise BoundaryError(f"{unit} offset {offset} falls inside code point {i - 1} (U+{ord(self.text[i - 1]):04X})")
        return i

    def from_codepoint(self, cp: int, unit: str) -> int:
        """Convert a code-point offset to `unit`. Grapheme requires a cluster boundary."""
        if cp < 0 or cp > len(self.text):
            raise BoundaryError(f"code-point offset {cp} outside 0..{len(self.text)}")
        if unit == "codepoint":
            return cp
        if unit == "utf8":
            return self._u8[cp]
        if unit == "utf16":
            return self._u16[cp]
        if unit == "grapheme":
            i = bisect_left(self._graphemes, cp)
            if self._graphemes[i] != cp:
                cluster = self.text[self._graphemes[i - 1] : self._graphemes[i]]
                raise BoundaryError(
                    f"code point {cp} lies inside grapheme cluster {i - 1} ({cluster!r}, {len(cluster)} code points)"
                )
            return i
        raise ValueError(f"unknown unit {unit!r}")

    def grapheme_boundary(self, cp: int) -> bool:
        i = bisect_left(self._graphemes, cp)
        return i < len(self._graphemes) and self._graphemes[i] == cp

    def measure(self, start_cp: int, end_cp: int) -> dict[str, Measurement]:
        """The selection [start_cp, end_cp) expressed in every unit.

        For graphemes, a selection edge inside a cluster is reported with the
        enclosing cluster index and on_boundary=False instead of failing.
        """
        out: dict[str, Measurement] = {}
        for unit in ("utf8", "utf16", "codepoint"):
            out[unit] = Measurement(unit, self.from_codepoint(start_cp, unit), self.from_codepoint(end_cp, unit))
        gs = bisect_left(self._graphemes, start_cp)
        ge = bisect_left(self._graphemes, end_cp)
        on_boundary = self.grapheme_boundary(start_cp) and self.grapheme_boundary(end_cp)
        if not self.grapheme_boundary(start_cp):
            gs -= 1
        out["grapheme"] = Measurement("grapheme", gs, ge, on_boundary)
        return out

    def convert(self, offset: int, from_unit: str, to_unit: str) -> int:
        return self.from_codepoint(self.to_codepoint(offset, from_unit), to_unit)

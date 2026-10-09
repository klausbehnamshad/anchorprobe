"""Two demonstrations that fit on one screen.

unit_matrix: one selection, eight numbers. The same quotation measured in
utf8, utf16, codepoint and grapheme units on NFC and on NFD text.

hash_table: one paragraph, sixteen hashes. SHA-256 of the same visible text
under every combination of form (NFC/NFD), newline (LF/CRLF), BOM (no/yes) and
trailing newline (no/yes). STA-C14N collapses the encoding variance; the
trailing newline stays, because it is content.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from .canon import BOM, canonicalize, sha256_hex
from .units import Ruler


@dataclass(frozen=True)
class MatrixRow:
    form: str
    unit: str
    start: int
    end: int
    length: int
    on_boundary: bool


def unit_matrix(text: str, start_cp: int, end_cp: int) -> list[MatrixRow]:
    """Measure canonical [start_cp, end_cp) in every unit on NFC and NFD text."""
    canonical = canonicalize(text)
    exact = canonical.text[start_cp:end_cp]
    rows: list[MatrixRow] = []
    for form in ("NFC", "NFD"):
        vt = unicodedata.normalize(form, canonical.text)
        # locate the same quotation in the variant text by NFC-equivalence of the prefix
        prefix_len = len(unicodedata.normalize(form, canonical.text[:start_cp]))
        s, e = prefix_len, prefix_len + len(unicodedata.normalize(form, exact))
        ruler = Ruler(vt)
        for unit, m in ruler.measure(s, e).items():
            rows.append(MatrixRow(form, unit, m.start, m.end, m.end - m.start, m.on_boundary))
    return rows


def render_matrix(rows: list[MatrixRow], exact: str) -> str:
    lines = [f"Selection: {exact!r}", "", "| form | unit | start | end | length | on boundary |", "|---|---|---:|---:|---:|---|"]
    for r in rows:
        lines.append(f"| {r.form} | {r.unit} | {r.start} | {r.end} | {r.length} | {'yes' if r.on_boundary else 'no'} |")
    distinct = len({(r.start, r.end) for r in rows})
    lines += ["", f"{distinct} distinct (start, end) pairs for one selection."]
    return "\n".join(lines)


@dataclass(frozen=True)
class HashRow:
    form: str
    newline: str
    bom: bool
    trailing_newline: bool
    sha256: str
    canonical_sha256: str


def hash_table(text: str) -> list[HashRow]:
    base = canonicalize(text).text.rstrip("\n")
    rows: list[HashRow] = []
    for form in ("NFC", "NFD"):
        for newline in ("LF", "CRLF"):
            for bom in (False, True):
                for trailing in (False, True):
                    t = unicodedata.normalize(form, base)
                    if trailing:
                        t += "\n"
                    if newline == "CRLF":
                        t = t.replace("\n", "\r\n")
                    if bom:
                        t = BOM + t
                    rows.append(HashRow(form, newline, bom, trailing, sha256_hex(t), canonicalize(t).sha256))
    return rows


def render_hash_table(rows: list[HashRow]) -> str:
    lines = ["| form | newline | BOM | trailing LF | sha256 of bytes | sha256 after STA-C14N |", "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r.form} | {r.newline} | {'yes' if r.bom else 'no'} | {'yes' if r.trailing_newline else 'no'} | `{r.sha256[:12]}` | `{r.canonical_sha256[:12]}` |")
    raw = len({r.sha256 for r in rows})
    canon = len({r.canonical_sha256 for r in rows})
    lines += ["", f"{len(rows)} encodings of one paragraph: {raw} distinct hashes of the bytes, {canon} after canonicalization "
              f"({'the trailing newline is content and stays distinguishable' if canon == 2 else 'see rows'})."]
    return "\n".join(lines)

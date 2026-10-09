"""STA-C14N: the canonical text form on which Stable Text Anchors are measured.

Four decisions, each closing one source of offset drift:

1. UTF-8 is decoded strictly. Invalid bytes are an error, never replaced.
2. A single leading U+FEFF (byte order mark) is removed. RFC 5147 excludes it
   from character counting; a BOM counted as character 0 shifts every anchor.
3. Line endings CRLF and lone CR become LF. RFC 5147 counts every line ending
   as one character. After folding, code points and RFC 5147 characters agree.
4. The text is normalized to Unicode NFC. Canonically equivalent encodings
   (precomposed vs. base + combining mark) then yield the same code points,
   the same offsets and the same hash.

Nothing else is changed: no trimming, no whitespace collapse, no compatibility
(NFKC/NFKD) folding. Those would alter content, not encoding.
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass

BOM = "﻿"
FORMS = ("NFC", "NFD", "NFKC", "NFKD")


class CanonError(ValueError):
    """Raised when input cannot be brought into canonical form."""


@dataclass(frozen=True)
class Canonical:
    """A text in canonical form together with what canonicalization changed."""

    text: str
    sha256: str
    raw_codepoints: int
    bom_stripped: bool
    crlf_folded: int
    cr_folded: int
    form_changed: bool

    @property
    def codepoints(self) -> int:
        return len(self.text)

    @property
    def changed(self) -> bool:
        return self.bom_stripped or bool(self.crlf_folded or self.cr_folded) or self.form_changed

    def summary(self) -> dict:
        return {
            "codepoints": self.codepoints,
            "raw_codepoints": self.raw_codepoints,
            "text_sha256": self.sha256,
            "bom_stripped": self.bom_stripped,
            "crlf_folded": self.crlf_folded,
            "cr_folded": self.cr_folded,
            "form_changed": self.form_changed,
        }


def decode_utf8(data: bytes) -> str:
    try:
        return data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise CanonError(f"invalid UTF-8 at byte {exc.start}: {exc.reason}") from exc


def sha256_hex(text: str) -> str:
    """SHA-256 over the UTF-8 encoding of `text`, lowercase hex."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonicalize(raw: bytes | str) -> Canonical:
    """Apply STA-C14N to raw bytes or an already decoded string."""
    text = decode_utf8(raw) if isinstance(raw, bytes) else raw
    raw_cp = len(text)
    bom = text.startswith(BOM)
    if bom:
        text = text[1:]
    crlf = text.count("\r\n")
    text = text.replace("\r\n", "\n")
    cr = text.count("\r")
    text = text.replace("\r", "\n")
    nfc = unicodedata.normalize("NFC", text)
    return Canonical(
        text=nfc,
        sha256=sha256_hex(nfc),
        raw_codepoints=raw_cp,
        bom_stripped=bom,
        crlf_folded=crlf,
        cr_folded=cr,
        form_changed=nfc != text,
    )


def variant(raw: bytes | str, *, bom: str = "stripped", newline: str = "LF", form: str = "NFC") -> str:
    """Return the text under a chosen combination of canonicalization decisions.

    Used by forensics and the matrix to reproduce how another system may have
    counted. `bom` is "stripped" or "kept"; `newline` is "LF" (fold) or "raw";
    `form` is one of NFC, NFD, NFKC, NFKD or "raw" (no normalization).
    """
    text = decode_utf8(raw) if isinstance(raw, bytes) else raw
    if bom == "stripped" and text.startswith(BOM):
        text = text[1:]
    elif bom != "kept" and bom != "stripped":
        raise ValueError(f"bom must be 'stripped' or 'kept', not {bom!r}")
    if newline == "LF":
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    elif newline != "raw":
        raise ValueError(f"newline must be 'LF' or 'raw', not {newline!r}")
    if form in FORMS:
        text = unicodedata.normalize(form, text)
    elif form != "raw":
        raise ValueError(f"form must be one of {FORMS} or 'raw', not {form!r}")
    return text

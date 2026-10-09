#!/usr/bin/env python3
"""Write the drift corpus and its manifest.

This script deliberately does not import anchorprobe. It is a second, minimal
implementation of the same rules (standard library plus the `regex` module
for grapheme clusters), so that the manifest it writes can be used to test
the library rather than restate it. Run from anywhere:

    python tools/make_fixtures.py [fixtures-dir]
"""

from __future__ import annotations

import hashlib
import json
import sys
import unicodedata
from pathlib import Path

import regex

GERMAN = "Jena, den 1. August 1797\nSchiller schrieb an Göthe über die Universität und das Weiße Roß.\nGrüße aus Weimar, straßenweise.\n"

# id, description, traits, text, selections (each exact must occur once in the canonical text)
FIXTURES: list[tuple[str, str, list[str], str, list[str]]] = [
    (
        "ascii-plain",
        "ASCII only, LF. The control: every unit coincides here, so a unit bug stays invisible on ASCII test data.",
        ["ascii", "lf"],
        "The quick brown fox jumps over the lazy dog.\nSecond line, plain ASCII only.\n",
        ["brown fox", "ASCII"],
    ),
    (
        "german-nfc",
        "German with umlauts and sharp s, NFC, LF.",
        ["nfc", "lf", "latin-diacritics"],
        GERMAN,
        ["Göthe", "Weiße Roß"],
    ),
    (
        "german-nfd",
        "The same German text in NFD, as macOS file systems and some OCR engines produce it. Same hash as german-nfc after STA-C14N.",
        ["nfd", "lf", "latin-diacritics"],
        unicodedata.normalize("NFD", GERMAN),
        ["Göthe", "Weiße Roß"],
    ),
    (
        "crlf-windows",
        "German NFC text with CRLF line endings.",
        ["nfc", "crlf"],
        GERMAN.replace("\n", "\r\n"),
        ["Göthe", "Grüße"],
    ),
    (
        "bom-utf8",
        "German NFC text with a leading UTF-8 byte order mark.",
        ["nfc", "lf", "bom"],
        "﻿" + GERMAN,
        ["Jena", "Göthe"],
    ),
    (
        "greek-polytonic",
        "Polytonic Greek with precomposed letters, plus alpha with macron and acute, a combination without a precomposed form: even NFC keeps the combining mark.",
        ["nfc", "lf", "greek", "combining-in-nfc"],
        "Ἐν ἀρχῇ ἦν ὁ λόγος, καὶ ὁ λόγος ἦν πρὸς τὸν θεόν.\nᾱ́ (alpha with macron and acute)\n",
        ["ἀρχῇ", "θεόν", "ᾱ́"],
    ),
    (
        "emoji-zwj",
        "Astral characters: a ZWJ family sequence (7 code points, 11 UTF-16 units, 1 grapheme), a flag and a skin-tone modifier.",
        ["astral", "zwj", "lf"],
        "Family: \U0001F468‍\U0001F469‍\U0001F467‍\U0001F466 flag: \U0001F1F1\U0001F1FA wave: \U0001F44B\U0001F3FD done.\n",
        ["flag", "done"],
    ),
    (
        "cuneiform-gothic",
        "Supplementary-plane historic scripts (cuneiform, Gothic, Old Italic) and ATF-style transliteration with diacritics and subscript digits.",
        ["astral", "nfc", "lf", "latin-diacritics"],
        "\U0001202D\U00012097\U000121A4 (dEN.LÍL) · Gothic \U00010332\U0001033F\U00010344\U00010330 · Old Italic \U00010300\U00010301 · ATF: šu₂ ṭup-pu ḫa-za-nu\n",
        ["Gothic", "ṭup-pu", "ḫa-za-nu"],
    ),
    (
        "arabic-tashkeel",
        "Arabic with vowel marks (combining) and Arabic-Indic digits; logical order differs from visual order.",
        ["rtl", "combining", "lf"],
        "بِسْمِ ٱللّهِ ٱلرّحْمَٰنِ ٱلرّحِيمِ Zahlen ١٢٣\n",
        ["Zahlen", "١٢٣"],
    ),
    (
        "ligatures-nfkc",
        "Compatibility characters: fi and ff ligatures, micro sign, ohm sign, fullwidth letters. NFC already folds the ohm sign (a singleton decomposition); NFKC changes the length.",
        ["compatibility", "singleton", "lf"],
        "ﬁnance, µ-Zeichen vs. μ, Ω vs Ω, ﬀ, ＡＢＣ fullwidth.\n",
        ["Zeichen", "fullwidth"],
    ),
    (
        "zero-width",
        "Invisible characters that count: soft hyphen, zero width space, no-break space, word joiner, variation selector.",
        ["invisible", "lf"],
        "soft­hyphen zero​width non breaking word⁠joiner vari️ation\n",
        ["hyphen zero", "joiner"],
    ),
    (
        "luxembourgish-french",
        "Luxembourgish and French: diaeresis, cedilla, the oe ligature (not decomposed by any normalization form), guillemets.",
        ["nfc", "lf", "latin-diacritics", "ligature"],
        "Lëtzebuerg: « D'Stad » an d'Ëlwent. Œuvre, cœur, garçon, Noël, naïve. Dësch.\n",
        ["Ëlwent", "cœur, garçon", "Dësch"],
    ),
    (
        "mixed-newlines",
        "LF, CRLF, lone CR, NEL and LINE SEPARATOR in one file. STA folds CR and CRLF only; NEL and LS stay as content.",
        ["crlf", "cr", "nel", "ls"],
        "line one\r\nline two\rline three\nline four\u0085line five line six\n",
        ["line three", "line five"],
    ),
    (
        "empty-lines",
        "Blank and whitespace-only lines, trailing spaces, no final newline. The annophis line-node numbering skips lines 2, 3 and 5.",
        ["blank-lines", "no-trailing-newline"],
        "first\n\n   \nfourth has trailing spaces   \n\nlast without newline",
        ["fourth", "last"],
    ),
]


def c14n(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="strict")
    if text.startswith("﻿"):
        text = text[1:]
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", text)


def graphemes(text: str) -> list[str]:
    return regex.findall(r"\X", text)


def utf16_units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def measure(text: str, start: int, end: int) -> dict:
    prefix, piece = text[:start], text[start:end]
    out = {
        "codepoint": [start, end],
        "utf8": [len(prefix.encode("utf-8")), len((prefix + piece).encode("utf-8"))],
        "utf16": [utf16_units(prefix), utf16_units(prefix + piece)],
    }
    total = len(graphemes(text))
    g_prefix = len(graphemes(prefix))
    g_piece = len(graphemes(piece))
    g_rest = len(graphemes(text[end:]))
    if g_prefix + g_piece + g_rest == total:
        out["grapheme"] = [g_prefix, g_prefix + g_piece]
    else:
        out["grapheme"] = None
    nfd_prefix = unicodedata.normalize("NFD", prefix)
    out["nfd_codepoint"] = [len(nfd_prefix), len(nfd_prefix) + len(unicodedata.normalize("NFD", piece))]
    return out


def main(argv: list[str]) -> int:
    out_dir = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parents[1] / "fixtures"
    out_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for fid, description, traits, text, selections in FIXTURES:
        raw = text.encode("utf-8")
        path = out_dir / f"{fid}.txt"
        path.write_bytes(raw)
        canonical = c14n(raw)
        raw_text = raw.decode("utf-8")
        sels = []
        for exact in selections:
            count = canonical.count(exact)
            if count != 1:
                raise SystemExit(f"{fid}: selection {exact!r} occurs {count} times in the canonical text, must be exactly 1")
            start = canonical.index(exact)
            sels.append({"exact": exact, "canonical": [start, start + len(exact)], "measurements": measure(canonical, start, start + len(exact))})
        entries.append(
            {
                "id": fid,
                "file": path.name,
                "description": description,
                "traits": traits,
                "bytes_sha256": hashlib.sha256(raw).hexdigest(),
                "raw": {
                    "bytes": len(raw),
                    "codepoints": len(raw_text),
                    "utf16": utf16_units(raw_text),
                    "graphemes": len(graphemes(raw_text)),
                    "has_bom": raw_text.startswith("﻿"),
                    "crlf": raw_text.count("\r\n"),
                    "lone_cr": raw_text.replace("\r\n", "").count("\r"),
                    "is_nfc": unicodedata.is_normalized("NFC", raw_text),
                    "is_nfd": unicodedata.is_normalized("NFD", raw_text),
                },
                "canonical": {
                    "codepoints": len(canonical),
                    "utf8": len(canonical.encode("utf-8")),
                    "utf16": utf16_units(canonical),
                    "graphemes": len(graphemes(canonical)),
                    "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                    "nfd_codepoints": len(unicodedata.normalize("NFD", canonical)),
                    "nfkc_codepoints": len(unicodedata.normalize("NFKC", canonical)),
                },
                "selections": sels,
            }
        )
    manifest = {
        "name": "anchorprobe drift corpus",
        "version": "0.1.0",
        "unicode_version": unicodedata.unidata_version,
        "generator": "tools/make_fixtures.py (independent of the anchorprobe package)",
        "fixtures": entries,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(entries)} fixtures and manifest.json to {out_dir} (Unicode {unicodedata.unidata_version})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

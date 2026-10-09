# anchorprobe

**Stable Text Anchor profile, drift forensics and conformance probes for character-offset annotation.**

[![tests](https://github.com/klausbehnamshad/anchorprobe/actions/workflows/ci.yml/badge.svg)](https://github.com/klausbehnamshad/anchorprobe/actions/workflows/ci.yml)
[![live probes](https://github.com/klausbehnamshad/anchorprobe/actions/workflows/live-probes.yml/badge.svg)](https://github.com/klausbehnamshad/anchorprobe/actions/workflows/live-probes.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)

An offset into a text is not a number. It is a measurement, and a measurement has a unit. The quotation `ṭup-pu` in one of the fixtures has six correct pairs of coordinates:

| text form | UTF-8 bytes | UTF-16 units | code points | grapheme clusters |
|---|---:|---:|---:|---:|
| NFC | 89..97 | 64..70 | 55..61 | 55..61 |
| NFD | 91..99 | 66..73 | 57..64 | 55..61 |

A browser-based annotation editor records UTF-16 units. A Python verifier reads code points. A Go or Rust text server resolves bytes internally. An OCR pipeline hands over decomposed characters. Every one of them is right, they only disagree about the unit, and neither W3C Web Annotation nor RFC 5147 nor CTS URNs record which unit was used. The integrity side is no better: SHA-256 of "the text" is sixteen different values for one paragraph, depending on normalization form, line endings, byte order mark and trailing newline.

anchorprobe does four things about that:

1. **A profile.** The Stable Text Anchor (STA) fixes the unit (code points), the form (NFC), the newline (LF) and the BOM (stripped), binds an anchor to the SHA-256 of that canonical text, and stores the quotation as a second witness. [Specification](spec/STABLE-TEXT-ANCHOR.md) · [JSON Schema](schema/anchor.schema.json)
2. **Conversion.** To and from W3C `TextQuoteSelector` + `TextPositionSelector` (with a non-breaking `sta:` integrity extension), RFC 5147 `char=` fragments with `length` and `md5`, the textsurf query dialect, and CTS `@needle[k]` subreferences on annophis-style line nodes. Foreign measurements in bytes, UTF-16 units or grapheme clusters are converted, never guessed.
3. **Forensics.** When an anchor stops matching, `diagnose` re-reads the recorded numbers under every combination of unit, normalization form, newline and BOM handling and says which counting would have produced them. Only then does it look for edits. Results are candidates for a human decision, never corrections.
4. **Probes.** `anchorprobe probe` asks a running [textsurf](https://github.com/knaw-huc/textsurf) or [annophis-text-service](https://github.com/GhentCDH/annophis-text-service) how it counts, hashes and clamps, and renders a conformance report. Offline models of both services sit in the test suite; a CI workflow runs the probes against real builds.

Everything runs locally, needs Python 3.11 or newer and one dependency (`regex`, for grapheme clusters). The probes need `httpx`.

## Quick start

```bash
git clone https://github.com/klausbehnamshad/anchorprobe.git
cd anchorprobe
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

One selection, eight numbers:

```bash
anchorprobe matrix fixtures/cuneiform-gothic.txt --exact "ṭup-pu"
```

One paragraph, sixteen hashes, two after canonicalization:

```bash
anchorprobe hashes fixtures/german-nfc.txt
```

```text
16 encodings of one paragraph: 16 distinct hashes of the bytes, 2 after canonicalization
(the trailing newline is content and stays distinguishable).
```

Create an anchor, break it the way a browser would, and ask why:

```bash
anchorprobe anchor fixtures/emoji-zwj.txt --exact done > done.json
# a JavaScript editor would have stored start=42, end=46 (UTF-16 units) instead of 34..38
python3 -c "import json;a=json.load(open('done.json'));a['start'],a['end']=42,46;json.dump(a,open('browser.json','w'))"
anchorprobe diagnose browser.json fixtures/emoji-zwj.txt
```

```json
{
  "status": "measurement_drift",
  "hash_match": true,
  "discriminating": true,
  "review_required": true,
  "explanations": [
    {
      "kind": "measurement",
      "detail": "offsets 42..46 reproduce the quotation when counted in utf16 on NFC text with newline=LF, bom=stripped (19 other form/newline/bom choices give the same text here)",
      "params": {"unit": "utf16", "form": "NFC", "newline": "LF", "bom": "stripped", "equivalent_on_this_text": ["…"]},
      "candidate": [34, 38]
    }
  ],
  "candidate": {"sta": "0.1", "unit": "codepoint", "form": "NFC", "start": 34, "end": 38, "exact": "done", "…": "…"}
}
```

Convert a measurement instead of guessing it:

```bash
anchorprobe measure fixtures/emoji-zwj.txt --start 42 --end 46 --unit utf16
```

Express an anchor for other systems:

```bash
anchorprobe convert done.json --to w3c
anchorprobe convert done.json --to rfc5147 --file fixtures/emoji-zwj.txt
anchorprobe convert done.json --to textsurf --excerpt-checks
anchorprobe convert done.json --to cts --file fixtures/emoji-zwj.txt --namespace demo --work emoji
```

Probe a live service:

```bash
anchorprobe probe textsurf --url http://localhost:8080 --out reports
anchorprobe probe annophis --prepare-txt-data ./txt_data     # then start the service with txt_data pointing here
anchorprobe probe annophis --url http://localhost:8081 --out reports
```

## Findings

Statements about specifications are quotations of the specification text. Statements about services are read from the source code of the named version and encoded in the offline models under `tests/fake_services.py`; the live CI workflow is where they become measurements. Section 9 of the [specification](spec/STABLE-TEXT-ANCHOR.md#9-findings) keeps the full table with status per finding.

| system | finding |
|---|---|
| W3C Web Annotation | TextQuoteSelector counts code points, not code units, and says the text "MUST be normalized", but no normalization form is named. No selector and no State carries a hash or version. Two conformant implementations can count differently on the same text and cannot tell. |
| RFC 5147 | Its two integrity checks use different units: `length` counts code points with every line ending as one character, `md5` hashes the bytes of one charset. Unknown checks MUST be ignored, so a `sha256=` parameter cannot travel in a conformant fragment. Out-of-range positions clamp. |
| textsurf 0.7.0 | `length` and `md5` are evaluated against the returned excerpt, not the entity. `checksum` is SHA-256 of the stored bytes, so NFD, CRLF and BOM each change it. The indexer counts a leading BOM as character 0. |
| annophis-text-service 0.6.2 | Plain-text nodes are stored NFC; NFD offsets from a client are off by the number of combining marks. `@needle[k]` matches case-insensitively, so `k` counts differently from a literal CTS reading. The node hash follows `?normalize=`, so one node has as many hashes as normalization modes. |
| claimtrace | Strips the BOM and folds newlines but does not apply NFC. STA-C14N is claimtrace's canonicalization plus NFC. |
| everyone | On ASCII test data every unit coincides. A unit bug in an annotation tool is undetectable on ASCII, which is why the drift corpus exists. |

## The drift corpus

Fourteen small texts, each built to separate at least two counting choices. The manifest is computed by `tools/make_fixtures.py`, which does not import this package, so the tests compare two implementations. `anchorprobe fixtures` runs the cross-check.

| fixture | code points | UTF-8 | UTF-16 | graphemes | separates |
|---|---:|---:|---:|---:|---|
| ascii-plain | 76 | 76 | 76 | 76 | nothing: the control |
| german-nfc | 123 | 131 | 123 | 123 | bytes from code points |
| german-nfd | 123 | 131 | 123 | 123 | NFD input; same canonical hash as german-nfc |
| crlf-windows | 123 | 131 | 123 | 123 | CRLF folding; same canonical hash |
| bom-utf8 | 123 | 131 | 123 | 123 | BOM stripping; same canonical hash |
| greek-polytonic | 83 | 132 | 83 | 82 | a combining mark that survives NFC |
| emoji-zwj | 40 | 70 | 48 | 32 | all four units |
| cuneiform-gothic | 71 | 109 | 80 | 71 | astral characters, Latin diacritics |
| arabic-tashkeel | 47 | 82 | 47 | 34 | combining vowel marks, logical vs visual order |
| ligatures-nfkc | 51 | 65 | 51 | 51 | NFC singleton (ohm sign) vs NFKC folding |
| zero-width | 59 | 67 | 59 | 58 | invisible characters that count |
| luxembourgish-french | 77 | 87 | 77 | 77 | diacritics, the œ ligature no form decomposes |
| mixed-newlines | 58 | 61 | 58 | 58 | CR, CRLF, NEL and LS in one file |
| empty-lines | 62 | 62 | 62 | 62 | line-node numbering with blank lines |

The four German fixtures are the same paragraph in four encodings. Their byte hashes differ; their canonical hash is one value.

## How it relates to what exists

- **W3C Web Annotation** gives the vocabulary. STA adds the missing normalization form and an integrity term that older consumers ignore without harm.
- **RFC 5147** gives the counting rules. STA-C14N makes a code-point offset and an RFC 5147 character position the same number.
- **textsurf** and **annophis-text-service** are the two open text servers in the digital humanities that address by character offsets. The probes are written for them; their maintainers are welcome to disagree with a finding by pointing at a line of code.
- **claimtrace** is the author's own anchoring tool for oral history. Its export already carries both witnesses; STA generalizes that and adds NFC.

## Status and limits

Version 0.1.0 is a first public version. The profile is small on purpose. Not covered: anchors across several nodes or texts, selections in marked-up documents, authentication of who recorded an anchor (that belongs in a provenance journal, see [dh-provenance-journal](https://github.com/klausbehnamshad/dh-provenance-journal)), and homoglyph folding across scripts. Live confirmation of the source-read findings about textsurf and annophis-text-service depends on the CI workflow having run; until then they are statements about code, and the specification marks them as such.

## Development

```bash
pytest                                  # 83 tests, property tests included
python tools/make_fixtures.py           # regenerate fixtures and manifest (writes exact bytes)
anchorprobe fixtures                    # cross-check manifest against the library
ANCHORPROBE_TEXTSURF_URL=http://localhost:8080 pytest tests/test_live.py
ANCHORPROBE_ANNOPHIS_URL=http://localhost:8081 pytest tests/test_live.py
```

The fixture manifest records the Unicode version it was generated with (15.1.0). The CI regenerates the corpus and fails if a byte differs.

## Deutsche Kurzfassung

Ein Offset in einem Text ist keine Zahl, sondern eine Messung mit Einheit. Dieselbe Textstelle hat in UTF-8-Bytes, UTF-16-Einheiten, Code-Points und Graphem-Clustern verschiedene Koordinaten, und in NFC und NFD noch einmal andere. Weder W3C Web Annotation noch RFC 5147 noch CTS-URNs halten fest, in welcher Einheit gezählt wurde. Der Stable Text Anchor legt Einheit (Code-Points), Normalform (NFC), Zeilenende (LF) und BOM (entfernt) fest, bindet den Anker an den SHA-256 des so kanonisierten Textes und speichert das Zitat als zweiten Zeugen. `anchorprobe` wandelt zwischen W3C-Selektoren, RFC-5147-Fragmenten, textsurf-Abfragen und CTS-Subreferenzen um, erklärt bei einem gebrochenen Anker deterministisch, unter welcher Zählweise die Zahlen gestimmt hätten, und prüft laufende Textdienste darauf, wie sie zählen und hashen. Kandidaten für eine Korrektur werden vorgeschlagen, nie angewendet. Vierzehn Prüftexte trennen die Zählweisen; ein unabhängiges Skript berechnet ihre Sollwerte.

## Citation

Behnam Shad, Klaus (2026). *anchorprobe: Stable Text Anchor profile, drift forensics and conformance probes* (version 0.1.0). See `CITATION.cff`.

## Colophon

MIT license. Specification, design decisions and findings by the author; the code scaffold, tests and documentation were drafted with Claude Code and reviewed line by line before the first commit. Quotations from specifications are verbatim from the cited documents; statements about third-party services name the version and the source file they were read from.

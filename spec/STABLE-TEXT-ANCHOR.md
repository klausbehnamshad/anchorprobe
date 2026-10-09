# Stable Text Anchor (STA), version 0.1

Status: draft for public comment, 9 October 2026. Reference implementation: the `anchorprobe` package in this repository. Machine-readable schema: `schema/anchor.schema.json`. JSON-LD terms: `schema/sta-context.jsonld`.

The key words MUST, MUST NOT, SHOULD, SHOULD NOT and MAY are to be read as in RFC 2119.

## 1 The problem in one table

A text offset is not a number. It is a measurement, and a measurement has a unit and a reference object. The quotation `ṭup-pu` in the fixture `cuneiform-gothic.txt` has these coordinates, all correct:

| text form | unit | start | end |
|---|---|---:|---:|
| NFC | UTF-8 bytes | 89 | 97 |
| NFC | UTF-16 code units | 64 | 70 |
| NFC | code points | 55 | 61 |
| NFC | grapheme clusters | 55 | 61 |
| NFD | UTF-8 bytes | 91 | 99 |
| NFD | UTF-16 code units | 66 | 73 |
| NFD | code points | 57 | 64 |
| NFD | grapheme clusters | 55 | 61 |

Six distinct pairs for one selection. A JavaScript annotation editor records the second row, a Python verifier reads the third, a Go or Rust text server resolves the first, and an OCR pipeline that emits decomposed characters shifts everything into the lower half. None of these systems is wrong. They disagree about the unit, and no common annotation format records the unit.

The integrity side has the same shape. SHA-256 of "the text" is sixteen different values for one paragraph, depending on normalization form, line ending convention, byte order mark and trailing newline (`anchorprobe hashes`). A hash without a declared canonical form is a coincidence, not an integrity check.

STA fixes the unit, the form and the hash scope, and makes an anchor carry both a position and a quotation so that each can check the other.

## 2 Terms

- **Raw text**: the bytes of a text resource as stored or transmitted.
- **Canonical text**: the raw text after STA-C14N (section 3).
- **Code point**: a Unicode scalar value. Python `str` indices, Rust `char`, Go `rune`, RFC 5147 characters and W3C TextPositionSelector characters count code points.
- **Code unit**: a UTF-16 unit. JavaScript string indices, DOM `Range` offsets, Java and .NET string indices count code units.
- **Grapheme cluster**: an extended grapheme cluster as defined in Unicode Standard Annex 29.
- **Anchor**: an STA anchor object (section 4).
- **Witness**: one of the two independent ways an anchor identifies its target, the position and the quotation.

## 3 Canonical form: STA-C14N

A producer MUST derive the canonical text from the raw text by these steps, in this order:

1. **Decode** the raw bytes as UTF-8. Invalid sequences MUST be an error. Replacement characters MUST NOT be substituted.
2. **Strip the byte order mark**: remove a single U+FEFF at position 0 if present. U+FEFF anywhere else is content and MUST be kept.
3. **Fold line endings**: replace every CRLF with LF, then every remaining CR with LF. U+0085 (NEL), U+2028 and U+2029 are content and MUST be kept.
4. **Normalize** to Unicode Normalization Form C (NFC).

Nothing else changes. The canonical text MUST NOT be trimmed, whitespace MUST NOT be collapsed, and compatibility normalization (NFKC, NFKD) MUST NOT be applied: those alter content.

Consequences a verifier MAY rely on:

- Code-point positions in the canonical text equal RFC 5147 character positions of the same entity (BOM excluded, each line ending one character; RFC 5147 sections 2.1.2 and 4.1).
- Canonically equivalent raw texts (precomposed vs. decomposed) yield identical canonical texts, positions and hashes.
- Singleton decompositions are folded by NFC itself: U+2126 OHM SIGN becomes U+03A9, U+212B ANGSTROM SIGN becomes U+00C5, U+212A KELVIN SIGN becomes U+004B. A producer that compares code points before and after canonicalization MUST expect such changes.
- Unicode's normalization stability policy guarantees that the NFC form of a string of assigned characters does not change between Unicode versions. A producer SHOULD record the Unicode version of its implementation in any manifest of canonical values (the fixture manifest in this repository does).

**text_sha256** is the lowercase hexadecimal SHA-256 digest of the UTF-8 encoding of the whole canonical text.

## 4 The anchor object

```json
{
  "sta": "0.1",
  "unit": "codepoint",
  "form": "NFC",
  "newline": "LF",
  "bom": "stripped",
  "text_sha256": "150b385ba36e…",
  "start": 34,
  "end": 38,
  "exact": "done",
  "prefix": "👋🏽 ",
  "suffix": ".\n",
  "source": "fixtures/emoji-zwj.txt"
}
```

Constraints:

- `unit`, `form`, `newline` and `bom` MUST have exactly the values shown. They are fixed in version 0.1 and are present so that no reader has to assume them. A consumer MUST reject an anchor with other values rather than reinterpret it (`anchorprobe.units.Ruler` converts other measurements into STA anchors before they are stored).
- `start` is the code-point offset of the first selected character, inclusive; `end` the offset after the last, exclusive; both count from 0 in the canonical text. `end - start` MUST equal the code-point length of `exact`.
- `exact` MUST equal `canonical[start:end]` at the time of recording. It is the second witness.
- `prefix` and `suffix` SHOULD be present, each a few dozen code points, so that a quotation-only resolution can disambiguate repeated passages. They are context, not part of the selection.
- `source` MAY identify the text (IRI, URN, path).
- A selection SHOULD NOT start or end inside a grapheme cluster (as W3C Web Annotation also says). `Ruler.measure` reports such edges.

## 5 Verification: two witnesses

A verifier MUST canonicalize the text it has, compare `text_sha256`, and compare `canonical[start:end]` with `exact`. It MUST report one of:

| status | hash | exact at position | meaning |
|---|---|---|---|
| `verified` | equal | yes | the anchor holds against this text |
| `stale_hash` | differs | yes | the text changed somewhere else; the anchor still resolves but was recorded against another version |
| `drifted` | differs | no | the anchor does not resolve; run forensics (section 6) |
| `inconsistent` | equal | no | the anchor object contradicts itself; it was altered after recording |
| `out_of_range` | any | not applicable | `end` exceeds the text; STA does not clamp (RFC 5147 section 4.2 permits clamping; STA treats it as a finding) |

A verifier MUST NOT move an anchor on its own. Any repositioning is a candidate that requires a recorded human decision.

## 6 Drift forensics

When the status is `drifted`, a diagnostic SHOULD explain before it searches. The reference implementation tests, for every combination of unit (utf8, utf16, codepoint, grapheme), normalization form (NFC, NFD, NFKC, NFKD, raw), newline handling (folded, raw) and BOM handling (stripped, kept), whether the recorded `start` and `end`, read as a measurement under that combination, reproduce `exact`. Only then does it look for the quotation elsewhere (`shifted`, `ambiguous`), under whitespace equivalence (`whitespace_drift`), or for an edit in place (`edited`), and finally reports `missing`.

Two properties matter:

- **Underdetermination is reported.** On text where units coincide (ASCII, no BOM, LF), a wrong offset cannot be attributed to a unit; the diagnosis says `discriminating: false`. Test corpora made of ASCII cannot reveal a unit bug. This is why the drift corpus in `fixtures/` exists.
- **Candidates are not corrections.** A diagnosis MAY propose one candidate anchor when exactly one explanation fits. The candidate is marked `review_required` and MUST NOT replace the recorded anchor without a human decision.

## 7 Mappings

### 7.1 W3C Web Annotation Data Model

The Web Annotation Data Model (W3C Recommendation, 23 February 2017) says for TextQuoteSelector that "the selection of the text MUST be in terms of unicode code points (the 'character number'), not in terms of code units", that "selections SHOULD NOT start or end in the middle of a grapheme cluster", and that "the text MUST be normalized before recording in the Annotation". TextPositionSelector counts from 0, includes the start character and excludes the end character, and MUST be "selected and normalized in the same way as for the Text Quote Selector". DataPositionSelector counts bytes. No selector and no State carries a checksum, digest or version identifier; the only versioning hook is `TimeState.sourceDate`.

Two gaps follow. The model prescribes normalization but names no normalization form, so two conformant implementations can count differently on the same text. And it has no integrity field, so a consumer cannot tell whether the text it resolves against is the text the annotation was made on.

STA maps to a SpecificResource with both selectors as alternatives and two extension terms:

```json
{
  "@context": ["http://www.w3.org/ns/anno.jsonld", "…/schema/sta-context.jsonld"],
  "type": "SpecificResource",
  "source": "…",
  "selector": [
    {"type": "TextQuoteSelector", "exact": "done", "prefix": "👋🏽 ", "suffix": ".\n"},
    {"type": "TextPositionSelector", "start": 34, "end": 38}
  ],
  "sta:textSha256": "150b385ba36e…",
  "sta:canonicalization": "…/spec/STABLE-TEXT-ANCHOR.md#c14n",
  "sta:version": "0.1"
}
```

An STA-aware consumer MUST resolve both selectors independently and report `agree`, `position_only`, `quote_only` or `conflict`. A conflict MUST NOT be resolved by preferring one selector silently. Consumers without STA support ignore the `sta:` terms, as JSON-LD allows; they lose integrity, not addressability.

### 7.2 RFC 5147 (text/plain fragment identifiers)

RFC 5147 counts characters from 0, excludes an initial BOM, counts each line ending as one character, distinguishes positions (`char=100`) from ranges (`char=100,200`, `char=100,`, `char=,200`), carries two integrity checks, `length` in code points and `md5` over the binary representation of the entity, clamps out-of-range positions to the end, and requires clients to ignore unknown integrity checks.

Because STA-C14N applies the same counting rules, an STA anchor maps to `char=start,end;length=L;md5=M,UTF-8` where `L` is the code-point count of the canonical text and `M` the MD5 of its UTF-8 bytes. Three differences remain and MUST be respected by converters:

- RFC 5147's two checks live in different units: `length` is logical (code points, line endings folded), `md5` is physical (bytes of one charset). STA fixes the physical form to UTF-8 of the canonical text.
- A `sha256=` parameter cannot be added to an RFC 5147 fragment: conformant clients ignore it. Integrity beyond MD5 travels in the W3C extension or in the anchor object.
- STA does not clamp. A fragment whose range exceeds the canonical text is `out_of_range`.

### 7.3 textsurf (Text Referencing API)

textsurf (knaw-huc, version 0.7.0) moves the RFC 5147 fragment into the query string (`?char=a,b`), counts code points 0-indexed with exclusive end, supports negative offsets, and publishes `chars` (code points of the file), `bytes` and `checksum` (SHA-256) in `/stat/{id}` and `info.json`. Its API text requires UTF-8 with LF line endings. Read from `src/main.rs` and from `textframe`:

- `length` and `md5` are evaluated against the returned excerpt, not against the entity (`get_text`). To use them as entity checks, request the whole text. `anchorprobe.formats.to_textsurf_query(anchor, excerpt_checks=True)` produces the excerpt-scoped values.
- `checksum` is SHA-256 of the file bytes as stored (`PositionIndex::new` feeds the lines as read into the hash). A file in NFD, with CRLF or with a BOM therefore has a different checksum from its canonical form.
- `textframe` indexes every code point of the file, including a leading U+FEFF and CR characters. If the stored file carries a BOM, position 0 is the BOM and all RFC 5147 positions are shifted by one; CRLF counts as two. Both are outside textsurf's stated input contract (LF files) and are listed in section 9 as source-read findings awaiting live confirmation.

### 7.4 CTS URNs and annophis-text-service

The CTS URN specification allows a subreference `@string[k]` on a citable node, meaning the k-th occurrence of the literal string within the passage; an omitted index means `[1]`. The specification says nothing about case, normalization or overlapping matches.

annophis-text-service (GhentCDH, version 0.6.2) implements CTS URNs over CEX files and over plain-text directories (`txt_data`), where every non-empty line of a file becomes a node `urn:cts:<namespace>:<file>.txtparsed:<n>` with consecutive 1-based numbering. Read from `internal/server/`:

- Lines are split on LF, a trailing CR is trimmed, lines empty after `TrimSpace` are skipped, surviving lines are stored NFC and untrimmed (`txtindex.go`).
- Subreference needles are NFC-normalized and matched case-insensitively; `?ignoreAccents=true` also folds diacritics; offsets and `context` count runes, that is code points (`helpers.go`).
- `/texts/hash/{URN}` returns `hex(algorithm(UTF-8(normalize(text))))` per node with SHA-1 by default and SHA-256 on request; `?normalize=` changes the returned text and therefore the hash, but never the stored text or the anchor resolution (`hash.go`, `normalize.go`).
- No BOM handling appears in `txtindex.go`. A UTF-8 file with a BOM would keep U+FEFF as the first character of node 1 (Go's `TrimSpace` does not treat it as space). Listed in section 9 as source-read.

STA maps an anchor that lies within one line to `<n>@<exact>[k]`. Because case-insensitive and literal readings count occurrences differently, `LineNodes.to_subref` computes both and emits a note when they differ. An anchor that crosses a line boundary is not mapped in version 0.1.

### 7.5 Byte offsets

W3C DataPositionSelector and HTTP `Range` address bytes. STA anchors are converted with `Ruler.from_codepoint(cp, "utf8")` on the canonical text; a byte offset inside a multi-byte sequence is a `BoundaryError`, never rounded.

## 8 Conformance

**Anchor producer.** Applies STA-C14N; emits anchors with all fields of section 4; refuses to emit an anchor whose `exact` does not equal the canonical slice.

**Anchor verifier.** Reports exactly the statuses of section 5; never repositions; exposes forensics results as candidates with `review_required`.

**STA-compatible text service.** A service is STA-compatible when, for a text it serves:

1. positions are counted in code points, 0-based, end exclusive;
2. the served text is NFC, has LF line endings and no leading BOM, or the service documents that it serves the stored form unchanged (then the client MUST canonicalize and MAY need to re-measure);
3. a content hash is published together with the exact recipe (algorithm, normalization form, newline handling, scope: node or whole text), so that a client can reproduce it;
4. a position beyond the text is refused or at least flagged, not silently clamped;
5. where integrity parameters exist, the documentation says whether they cover the excerpt or the entity.

`anchorprobe probe` checks these points against a running instance and renders a report.

## 9 Findings

Source-read findings are statements about the code of the named version. Live-confirmed findings were observed against a running instance by the probe in the live CI workflow. Model-agreement means the offline model in `tests/fake_services.py` reproduces the behaviour.

| # | system | finding | status |
|---|---|---|---|
| F1 | W3C Web Annotation | normalization is required but no form is named; no selector carries a hash or version | specification text |
| F2 | RFC 5147 | `length` counts code points with line endings folded, `md5` hashes bytes of one charset: the two integrity checks use different units | specification text |
| F3 | RFC 5147 | unknown integrity checks MUST be ignored, so `sha256=` cannot be carried in a conformant fragment | specification text |
| F4 | textsurf 0.7.0 | `length` and `md5` are checked against the returned excerpt, not the entity | source-read (`src/main.rs`, `get_text`), model agrees |
| F5 | textsurf 0.7.0 | `checksum` is SHA-256 of the stored bytes; NFD, CRLF and BOM each change it | source-read (`textframe` `PositionIndex::new`) |
| F6 | textsurf 0.7.0 | a leading BOM is counted as character 0 and CRLF as two characters; both outside its LF-only contract | source-read, awaiting live confirmation |
| F7 | textsurf 0.7.0 | out-of-range positions are clamped (as RFC 5147 permits) | source-read via `textframe` negative/end handling, awaiting live confirmation |
| F8 | annophis-text-service 0.6.2 | plain-text nodes are stored NFC; a client holding NFD offsets is off by the number of combining marks | source-read (`txtindex.go`), model agrees |
| F9 | annophis-text-service 0.6.2 | `@needle[k]` matches case-insensitively, so `k` counts differently from a literal CTS reading | source-read (`helpers.go`), model agrees |
| F10 | annophis-text-service 0.6.2 | the node hash follows `?normalize=`; the same node has as many hashes as normalization modes | source-read (`hash.go`) |
| F11 | annophis-text-service 0.6.2 | a leading BOM survives into node 1 | source-read, awaiting live confirmation |
| F12 | claimtrace 0.x | canonicalization strips the BOM and folds newlines but does not apply NFC; its anchors on NFD sources differ from STA by the number of combining marks | source-read (`core.py`, `extract_source`) |
| F13 | all | on ASCII test data every unit coincides; a unit bug is undetectable there | by construction (`fixtures/ascii-plain.txt`) |

## 10 Rationale

**Why code points.** They are the unit RFC 5147 and W3C Web Annotation already name, the native index of Python, Rust and Go, and stable across Unicode versions for assigned characters. UTF-16 units are an implementation detail of one language family. Bytes depend on the encoding.

**Why not grapheme clusters.** They are what a reader sees, and W3C rightly asks selections not to cut through them. But cluster boundaries depend on the Unicode version: UAX 29 changed its rules repeatedly, most recently in Unicode 15.1 (rule GB9c for Indic conjuncts). An anchor counted in clusters by one library and resolved by another can drift without any change to the text. Clusters are a display and selection concern; STA checks cluster boundaries, it does not count in them.

**Why NFC.** W3C recommends NFC for interchange; CEX and annophis store NFC; most editors and fonts expect it. NFC removes the most common invisible drift source in humanities data: decomposed characters from macOS file systems, OCR output and some keyboard layouts.

**Why not NFKC.** Compatibility normalization is lossy. It turns `ﬁ` into `fi`, the micro sign into mu and fullwidth letters into ASCII, changing lengths and losing information an edition may need. It belongs to search, not to anchoring.

**Why the hash is over the canonical text, not the bytes.** The sixteen-hash table in section 1. A hash of the bytes changes when a file is re-saved with different line endings or a BOM, although no character changed. A hash of the canonical text changes only when content changes.

**Why two witnesses.** A position without a quotation fails silently when the text shifts; a quotation without a position is ambiguous when the text repeats. Together they detect each other's failure. claimtrace's exports and RFC 5147's `length` plus `md5` already follow this principle; STA names it.

**Why no clamping.** A reader asking for characters beyond the text has stale information. Returning the tail hides that.

## 11 Limits

- `text_sha256` is an integrity check, not authentication. Anyone can compute it for any text. Provenance of who recorded an anchor when belongs to a journal, not to the anchor.
- Homoglyphs across scripts (Latin A, Greek Α, Cyrillic А) are distinct code points and are not folded. Confusable detection (UTS 39) is out of scope.
- Anchors in STA 0.1 address one text. Anchors across nodes, ranges spanning several texts, and selections in marked-up documents (where the W3C model says tags SHOULD be removed) are not specified.
- Unicode version: new characters are unassigned in older implementations and pass through normalization unchanged; a producer and a consumer on different Unicode versions can disagree only about characters assigned between those versions.

## 12 References

- Web Annotation Data Model. W3C Recommendation, 23 February 2017. https://www.w3.org/TR/annotation-model/ (sections 4.2.1, 4.2.4, 4.2.5, 4.2.6, 4.3).
- RFC 5147, URI Fragment Identifiers for the text/plain Media Type. E. Wilde, M. Duerst, April 2008. https://www.rfc-editor.org/rfc/rfc5147.txt
- Canonical Text Services URN specification. https://cite-architecture.github.io/ctsurn_spec/
- Unicode Standard Annex 15, Unicode Normalization Forms; Unicode Standard Annex 29, Unicode Text Segmentation; Unicode Character Encoding Stability Policies.
- textsurf. https://github.com/knaw-huc/textsurf (0.7.0), textframe https://github.com/proycon/textframe
- annophis-text-service. https://github.com/GhentCDH/annophis-text-service (0.6.2)
- claimtrace. https://github.com/klausbehnamshad/claimtrace

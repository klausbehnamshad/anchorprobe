# Changelog

## 0.1.0 (2026-10-09)

First public version.

- Stable Text Anchor profile 0.1: code points on NFC text with LF newlines and no BOM, bound to the SHA-256 of the canonical text, with the quotation as second witness (`spec/STABLE-TEXT-ANCHOR.md`, `schema/anchor.schema.json`).
- `anchorprobe.canon`: STA-C14N with a report of what changed.
- `anchorprobe.units`: offset conversion between UTF-8 bytes, UTF-16 code units, code points and extended grapheme clusters; boundary violations are errors.
- `anchorprobe.anchor`: anchors, two-witness verification with five statuses.
- `anchorprobe.formats`: W3C Web Annotation selectors with the `sta:` integrity extension; RFC 5147 fragments with position/range distinction, `length`, `md5` and ignored checks; textsurf query dialect; annophis-text-service line nodes and `@needle[k]` subreferences in both the case-insensitive and the literal reading.
- `anchorprobe.forensics`: deterministic drift diagnosis over a 4 × 5 × 2 × 2 grid of counting choices, then shift, ambiguity, whitespace and edit detection; candidates never replace the anchor.
- `anchorprobe.matrix`: one selection as eight numbers; one paragraph as sixteen hashes.
- `anchorprobe.probe`: conformance probes for textsurf and annophis-text-service with Markdown and JSON reports; offline models of both services in the test suite; live CI workflow.
- Drift corpus: fourteen fixtures with a manifest computed by an independent script.

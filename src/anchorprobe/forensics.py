"""Drift forensics: explain why an anchor no longer matches, deterministically.

When exact is not at [start, end), the usual reaction is to search for the
quotation and move the anchor. That hides the cause. Forensics asks instead:
under which counting could these numbers have been correct? It re-measures the
same offsets under every combination of unit (utf8, utf16, codepoint,
grapheme), normalization form (NFC, NFD, NFKC, NFKD, raw), newline handling
(folded, raw) and BOM handling (stripped, kept), and reports every combination
that reproduces the quotation. Only then does it look for edits.

Results are candidates for a human decision, never corrections.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field

from .anchor import Anchor, make_anchor, verify
from .canon import Canonical, canonicalize, variant
from .units import UNITS, BoundaryError, Ruler

GRID_UNITS = UNITS
GRID_FORMS = ("NFC", "NFD", "NFKC", "NFKD", "raw")
GRID_NEWLINES = ("LF", "raw")
GRID_BOMS = ("stripped", "kept")


@dataclass(frozen=True)
class Explanation:
    kind: str  # measurement | shifted | ambiguous | whitespace | edited
    detail: str
    params: dict = field(default_factory=dict)
    candidate: tuple[int, int] | None = None  # canonical code-point range

    def to_dict(self) -> dict:
        return {"kind": self.kind, "detail": self.detail, "params": self.params, "candidate": list(self.candidate) if self.candidate else None}


@dataclass(frozen=True)
class Diagnosis:
    status: str
    hash_match: bool
    explanations: tuple[Explanation, ...]
    candidate: Anchor | None
    discriminating: bool
    verdict: dict

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "hash_match": self.hash_match,
            "discriminating": self.discriminating,
            "review_required": self.candidate is not None,
            "explanations": [e.to_dict() for e in self.explanations],
            "candidate": self.candidate.to_dict() if self.candidate else None,
            "verdict": self.verdict,
        }


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _canonical_offset_of_variant_slice(raw_text: str, bom: str, newline: str, form: str, start_cp: int, end_cp: int, canonical: Canonical) -> tuple[int, int] | None:
    """Map a slice in a variant text back to canonical code points when the slice is a unique match."""
    vt = variant(raw_text, bom=bom, newline=newline, form=form)
    piece = _nfc(vt[start_cp:end_cp].replace("\r\n", "\n").replace("\r", "\n"))
    hits = [m.start() for m in re.finditer(re.escape(piece), canonical.text)] if piece else []
    if len(hits) == 1:
        return hits[0], hits[0] + len(piece)
    return None


def discriminating(canonical: Canonical) -> bool:
    """Can counting choices be told apart on this text at all?

    True when at least one grid dimension changes the numbering somewhere in
    the text: a character outside ASCII (utf8 differs), outside the BMP (utf16
    differs), a multi-code-point grapheme, a normalization form of another
    length, a BOM or a CR. On pure ASCII with LF everything coincides, and a
    unit bug in an annotation tool stays invisible.
    """
    r = Ruler(canonical.text)
    n = canonical.codepoints
    if r.length("utf8") != n or r.length("utf16") != n or r.length("grapheme") != n:
        return True
    if any(len(unicodedata.normalize(form, canonical.text)) != n for form in ("NFD", "NFKC", "NFKD")):
        return True
    return canonical.bom_stripped or bool(canonical.crlf_folded or canonical.cr_folded) or canonical.form_changed


def measurement_grid(anchor: Anchor, raw: bytes | str, canonical: Canonical) -> tuple[list[Explanation], bool]:
    """Every (unit, form, newline, bom) under which [start, end) yields exact.

    Returns the explanations and whether the grid is discriminating on this
    text (see discriminating()).
    """
    text_raw = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    target = _nfc(anchor.exact)
    # Choices that cannot be told apart on this input are reported together:
    # form/newline/bom combinations that produce the identical text, and units
    # that produce the identical offsets on that text.
    seen_variants: dict[str, dict] = {}
    matches: dict[tuple[str, int, int], dict] = {}
    for bom in GRID_BOMS:
        for newline in GRID_NEWLINES:
            for form in GRID_FORMS:
                vt = variant(text_raw, bom=bom, newline=newline, form=form)
                if vt in seen_variants:
                    seen_variants[vt]["equivalent"].append({"form": form, "newline": newline, "bom": bom})
                    continue
                seen_variants[vt] = {"form": form, "newline": newline, "bom": bom, "equivalent": []}
                ruler = Ruler(vt)
                for unit in GRID_UNITS:
                    try:
                        s = ruler.to_codepoint(anchor.start, unit)
                        e = ruler.to_codepoint(anchor.end, unit)
                    except BoundaryError:
                        continue
                    if s > e:
                        continue
                    piece = _nfc(vt[s:e].replace("\r\n", "\n").replace("\r", "\n"))
                    if piece != target:
                        continue
                    if (unit, form, newline, bom) == ("codepoint", "NFC", "LF", "stripped"):
                        continue  # that is the profile itself; verify() already said no
                    key = (vt, s, e)
                    if key in matches:
                        matches[key]["units"].append(unit)
                    else:
                        matches[key] = {
                            "units": [unit],
                            "form": form,
                            "newline": newline,
                            "bom": bom,
                            "candidate": _canonical_offset_of_variant_slice(text_raw, bom, newline, form, s, e, canonical),
                        }
    found: list[Explanation] = []
    for (vt, _s, _e), m in matches.items():
        equivalent = seen_variants[vt]["equivalent"]
        units = " or ".join(m["units"])
        notes = []
        if len(m["units"]) > 1:
            notes.append("these units coincide on this text")
        if equivalent:
            notes.append(f"{len(equivalent)} other form/newline/bom choices give the same text here")
        tail = f" ({'; '.join(notes)})" if notes else ""
        params = {"unit": m["units"][0], "units": m["units"], "form": m["form"], "newline": m["newline"], "bom": m["bom"], "equivalent_on_this_text": equivalent}
        found.append(
            Explanation(
                "measurement",
                f"offsets {anchor.start}..{anchor.end} reproduce the quotation when counted in {units} "
                f"on {m['form']} text with newline={m['newline']}, bom={m['bom']}{tail}",
                params,
                m["candidate"],
            )
        )
    return found, discriminating(canonical)


def _collapse(s: str) -> str:
    return re.sub(r"\s+", " ", s)


def diagnose(anchor: Anchor, raw: bytes | str) -> Diagnosis:
    canonical = canonicalize(raw)
    verdict = verify(anchor, canonical)
    text = canonical.text
    if verdict.status in ("verified", "stale_hash"):
        return Diagnosis(verdict.status, verdict.hash_match, (), None, discriminating(canonical), verdict.to_dict())

    explanations: list[Explanation] = []
    candidate: Anchor | None = None

    # 1. Was the number right under another counting?
    grid, discriminating_text = measurement_grid(anchor, raw, canonical)
    explanations.extend(grid)
    if grid:
        candidates = {e.candidate for e in grid if e.candidate}
        status = "measurement_drift" if len(candidates) == 1 else "underdetermined"
        if len(candidates) == 1:
            s, e = next(iter(candidates))
            candidate = make_anchor(canonical, s, e, source=anchor.source)
        return Diagnosis(status, verdict.hash_match, tuple(explanations), candidate, discriminating_text, verdict.to_dict())

    # 2. Same quotation, other place: an edit before the anchor shifted it.
    hits = [m.start() for m in re.finditer(re.escape(anchor.exact), text)] if anchor.exact else []
    if anchor.prefix or anchor.suffix:
        narrowed = [h for h in hits if text.endswith(anchor.prefix, 0, h) and text.startswith(anchor.suffix, h + len(anchor.exact))]
        if narrowed:
            hits = narrowed
    if len(hits) == 1:
        s = hits[0]
        delta = s - anchor.start
        explanations.append(Explanation("shifted", f"quotation found once, {delta:+d} code points from the recorded position", {"delta": delta}, (s, s + len(anchor.exact))))
        candidate = make_anchor(canonical, s, s + len(anchor.exact), source=anchor.source)
        return Diagnosis("shifted", verdict.hash_match, tuple(explanations), candidate, discriminating_text, verdict.to_dict())
    if len(hits) > 1:
        for h in hits:
            explanations.append(Explanation("ambiguous", f"quotation occurs at {h}", {}, (h, h + len(anchor.exact))))
        return Diagnosis("ambiguous", verdict.hash_match, tuple(explanations), None, discriminating_text, verdict.to_dict())

    # 3. Whitespace drift: line wrapping, double spaces, tabs.
    if anchor.exact.strip():
        pattern = r"\s+".join(re.escape(part) for part in anchor.exact.split())
        ws_hits = list(re.finditer(pattern, text))
        if len(ws_hits) == 1:
            m = ws_hits[0]
            explanations.append(Explanation("whitespace", "quotation found once when whitespace runs are treated as equal", {}, (m.start(), m.end())))
            candidate = make_anchor(canonical, m.start(), m.end(), source=anchor.source)
            return Diagnosis("whitespace_drift", verdict.hash_match, tuple(explanations), candidate, discriminating_text, verdict.to_dict())

    # 4. Edited in place: compare the window at the old position.
    window = text[anchor.start : anchor.end]
    ratio = difflib.SequenceMatcher(None, anchor.exact, window, autojunk=False).ratio() if window else 0.0
    if ratio >= 0.6:
        ops = [f"{tag} {anchor.exact[i1:i2]!r}->{window[j1:j2]!r}" for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, anchor.exact, window, autojunk=False).get_opcodes() if tag != "equal"]
        explanations.append(Explanation("edited", f"text at the recorded position is {ratio:.0%} similar to the quotation", {"ratio": round(ratio, 3), "ops": ops[:8]}, (anchor.start, anchor.end)))
        return Diagnosis("edited", verdict.hash_match, tuple(explanations), None, discriminating_text, verdict.to_dict())

    explanations.append(Explanation("missing", "quotation not found under any counting, position or whitespace rule", {}))
    return Diagnosis("missing", verdict.hash_match, tuple(explanations), None, discriminating_text, verdict.to_dict())

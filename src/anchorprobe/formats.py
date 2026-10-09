"""Mappings between the Stable Text Anchor and the addressing schemes it meets.

- W3C Web Annotation: TextQuoteSelector + TextPositionSelector (code points,
  "normalized" without a named form, no integrity field)
- RFC 5147: text/plain fragments `char=a,b;length=n;md5=hex` (code points,
  BOM excluded, line ending = 1 character; md5 over the binary entity)
- textsurf: RFC 5147 syntax moved into the query part; length and md5 are
  evaluated against the returned excerpt (read from textsurf/src/main.rs 0.7.0)
- CTS URNs as served by annophis-text-service: line nodes `...txtparsed:<n>`
  and subreferences `@needle[k]`; stored NFC, matched case-insensitively,
  per-node hashes over the NFC text
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from .anchor import Anchor, ProfileError, make_anchor
from .canon import Canonical

WA_CONTEXT = "http://www.w3.org/ns/anno.jsonld"
STA_CONTEXT = "https://github.com/klausbehnamshad/anchorprobe/blob/main/schema/sta-context.jsonld"
STA_NS = "https://github.com/klausbehnamshad/anchorprobe/blob/main/spec/STABLE-TEXT-ANCHOR.md#"


# --------------------------------------------------------------------------- W3C

def to_w3c(anchor: Anchor, *, source: str | None = None) -> dict:
    """A SpecificResource with both selectors and the STA integrity extension.

    The two selectors are alternatives in the Web Annotation sense: a consumer
    may use either. STA-aware consumers read `sta:textSha256` and
    `sta:canonicalization`; others ignore the unknown terms, as JSON-LD allows.
    """
    quote = {"type": "TextQuoteSelector", "exact": anchor.exact}
    if anchor.prefix:
        quote["prefix"] = anchor.prefix
    if anchor.suffix:
        quote["suffix"] = anchor.suffix
    position = {"type": "TextPositionSelector", "start": anchor.start, "end": anchor.end}
    doc = {
        "@context": [WA_CONTEXT, STA_CONTEXT],
        "type": "SpecificResource",
        "selector": [quote, position],
        "sta:textSha256": anchor.text_sha256,
        "sta:canonicalization": STA_NS + "c14n",
        "sta:version": "0.1",
    }
    src = source or anchor.source
    if src:
        doc["source"] = src
    return doc


@dataclass(frozen=True)
class W3CResolution:
    """How the two W3C witnesses resolve against a canonical text."""

    agreement: str  # agree | position_only | quote_only | conflict | none
    position: tuple[int, int] | None
    quote_positions: tuple[tuple[int, int], ...]
    anchor: Anchor | None
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "agreement": self.agreement,
            "position": list(self.position) if self.position else None,
            "quote_positions": [list(p) for p in self.quote_positions],
            "anchor": self.anchor.to_dict() if self.anchor else None,
            "notes": list(self.notes),
        }


def _find_all(text: str, needle: str) -> list[int]:
    if not needle:
        return []
    out, pos = [], text.find(needle)
    while pos >= 0:
        out.append(pos)
        pos = text.find(needle, pos + 1)
    return out


def resolve_quote(text: str, exact: str, prefix: str = "", suffix: str = "") -> list[tuple[int, int]]:
    """All positions where exact occurs; narrowed by prefix and suffix when given."""
    hits = _find_all(text, exact)
    if prefix:
        hits = [h for h in hits if text.endswith(prefix, 0, h)]
    if suffix:
        hits = [h for h in hits if text.startswith(suffix, h + len(exact))]
    return [(h, h + len(exact)) for h in hits]


def from_w3c(doc: dict, canonical: Canonical, *, context: int = 32) -> W3CResolution:
    """Resolve a SpecificResource (or a bare selector list) against canonical text."""
    selectors = doc.get("selector", doc) if isinstance(doc, dict) else doc
    if isinstance(selectors, dict):
        selectors = [selectors]
    quote = next((s for s in selectors if s.get("type") == "TextQuoteSelector"), None)
    position = next((s for s in selectors if s.get("type") == "TextPositionSelector"), None)
    text = canonical.text
    notes: list[str] = []
    pos: tuple[int, int] | None = None
    if position is not None:
        start, end = position.get("start"), position.get("end")
        if isinstance(start, int) and isinstance(end, int) and 0 <= start <= end <= len(text):
            pos = (start, end)
        else:
            notes.append(f"TextPositionSelector {start}..{end} is out of range for {len(text)} code points")
    quote_hits: tuple[tuple[int, int], ...] = ()
    if quote is not None:
        quote_hits = tuple(resolve_quote(text, quote.get("exact", ""), quote.get("prefix", ""), quote.get("suffix", "")))
    declared = isinstance(doc, dict) and doc.get("sta:textSha256")
    if declared and declared != canonical.sha256:
        notes.append("sta:textSha256 differs from the canonical text: the annotation was recorded against another version")

    if pos and quote is not None:
        if pos in quote_hits:
            agreement = "agree"
        elif text[pos[0] : pos[1]] == quote.get("exact"):
            agreement = "agree"
            notes.append("prefix/suffix do not match at the position; the exact text does")
        elif quote_hits:
            agreement = "conflict"
            notes.append("position and quotation point to different places: do not choose silently")
        else:
            agreement = "position_only"
            notes.append("the quotation is not found anywhere; only the position remains")
    elif pos:
        agreement = "position_only"
    elif quote_hits:
        agreement = "quote_only" if len(quote_hits) == 1 else "conflict"
        if len(quote_hits) > 1:
            notes.append(f"quotation found {len(quote_hits)} times and no position given: ambiguous")
    else:
        agreement = "none"

    anchor = None
    if agreement == "agree" and pos:
        anchor = make_anchor(canonical, pos[0], pos[1], context=context, source=doc.get("source") if isinstance(doc, dict) else None)
    elif agreement == "quote_only":
        s, e = quote_hits[0]
        anchor = make_anchor(canonical, s, e, context=context)
    return W3CResolution(agreement, pos, quote_hits, anchor, tuple(notes))


# ---------------------------------------------------------------------- RFC 5147

_RFC5147 = re.compile(
    r"^(?P<scheme>char|line)=(?P<range>(?:\d+(?:,\d*)?)|(?:,\d+))(?P<checks>(?:;(?:length=\d+|md5=[0-9A-Fa-f]{32}|[A-Za-z0-9_-]+=[^;]*)(?:,[A-Za-z0-9!#$%&'+_.-]+)?)*)$"
)


@dataclass(frozen=True)
class Rfc5147Fragment:
    """`char=100` is a position (zero length); `char=100,`, `char=,100` and `char=100,200` are ranges.

    RFC 5147 section 2.2: a position is a point between characters, a range
    is a consecutive region. `kind` keeps the two apart; `start`/`end` are
    None where the fragment leaves them open (begin or end of the entity).
    """

    scheme: str
    start: int | None
    end: int | None
    kind: str = "range"  # position | range
    length: int | None = None
    md5: str | None = None
    charset: str | None = None
    ignored: tuple[str, ...] = field(default_factory=tuple)

    def __str__(self) -> str:
        if self.kind == "position":
            rng = str(self.start)
        else:
            rng = f"{self.start if self.start is not None else ''},{self.end if self.end is not None else ''}"
        parts = [f"{self.scheme}={rng}"]
        if self.length is not None:
            parts.append(f"length={self.length}")
        if self.md5 is not None:
            parts.append(f"md5={self.md5}")
        if self.charset and len(parts) > 1:
            parts[-1] += f",{self.charset}"
        return ";".join(parts)


def parse_rfc5147(fragment: str) -> Rfc5147Fragment:
    """Parse `char=a,b;length=n;md5=hex` following the RFC 5147 ABNF.

    Unknown integrity checks are recorded in `ignored`, as the RFC requires
    clients to ignore them. A fragment that does not match the grammar raises
    ValueError; RFC 5147 says such identifiers MUST be ignored.
    """
    frag = fragment[1:] if fragment.startswith("#") else fragment
    m = _RFC5147.match(frag)
    if not m:
        raise ValueError(f"not an RFC 5147 fragment: {fragment!r}")
    rng = m.group("range")
    if "," in rng:
        kind = "range"
        a, b = rng.split(",", 1)
        start = int(a) if a else None
        end = int(b) if b else None
        if start is not None and end is not None and end < start:
            raise ValueError("end before start: RFC 5147 says the fragment MUST be ignored")
    else:
        kind = "position"
        start, end = int(rng), int(rng)
    length = md5 = charset = None
    ignored: list[str] = []
    for check in filter(None, m.group("checks").split(";")):
        name, _, value = check.partition("=")
        value, _, cs = value.partition(",")
        if name == "length":
            if not value.isdigit():
                raise ValueError(f"length must be a number: {check!r}")
            length = int(value)
        elif name == "md5":
            if not re.fullmatch(r"[0-9A-Fa-f]{32}", value):
                raise ValueError(f"md5 must be 32 hex digits: {check!r}")
            md5 = value.lower()
        else:
            ignored.append(check)
            continue
        if cs:
            charset = cs
    return Rfc5147Fragment(m.group("scheme"), start, end, kind, length, md5, charset, tuple(ignored))


def rfc5147_length(canonical: Canonical) -> int:
    """RFC 5147 `length`: code points after BOM removal with each line ending as one character.

    STA-C14N already applies both rules, so the length is the code-point count
    of the canonical text.
    """
    return canonical.codepoints


def rfc5147_md5(text: str) -> str:
    """RFC 5147 `md5`: over the binary representation of the entity. STA fixes that to UTF-8 of the canonical form."""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def to_rfc5147(anchor: Anchor, canonical: Canonical, *, integrity: bool = True) -> Rfc5147Fragment:
    """The anchor as an RFC 5147 fragment over the whole canonical entity."""
    if integrity:
        return Rfc5147Fragment("char", anchor.start, anchor.end, "range", rfc5147_length(canonical), rfc5147_md5(canonical.text), "UTF-8")
    return Rfc5147Fragment("char", anchor.start, anchor.end, "range")


def to_textsurf_query(anchor: Anchor, *, excerpt_checks: bool = False) -> str:
    """textsurf moves the RFC 5147 fragment into the query string.

    textsurf 0.7.0 evaluates `length` and `md5` against the returned excerpt,
    not against the whole text (src/main.rs, get_text). With
    excerpt_checks=True the parameters are computed accordingly.
    """
    q = f"char={anchor.start},{anchor.end}"
    if excerpt_checks:
        q += f"&length={anchor.length}&md5={rfc5147_md5(anchor.exact)}"
    return q


def from_rfc5147(fragment: Rfc5147Fragment | str, canonical: Canonical, *, context: int = 32) -> tuple[Anchor | None, tuple[str, ...]]:
    """Turn a char fragment into an anchor on canonical text, reporting integrity results.

    RFC 5147 lets out-of-range positions clamp to the end of the entity. STA
    does not clamp: an out-of-range position is a finding.
    """
    frag = parse_rfc5147(fragment) if isinstance(fragment, str) else fragment
    notes: list[str] = []
    if frag.scheme != "char":
        return None, ("line scheme is not an STA anchor; map lines with LineNodes first",)
    if frag.length is not None and frag.length != rfc5147_length(canonical):
        notes.append(f"length check failed: fragment says {frag.length}, canonical text has {rfc5147_length(canonical)}")
    if frag.md5 is not None and frag.md5 != rfc5147_md5(canonical.text):
        notes.append("md5 check failed against UTF-8 of the canonical text")
    if frag.ignored:
        notes.append("ignored integrity checks (RFC 5147 section 3.1): " + ", ".join(frag.ignored))
    start = frag.start if frag.start is not None else 0
    end = frag.end if frag.end is not None else canonical.codepoints
    if end > canonical.codepoints or start > end:
        notes.append(f"range {start}..{end} out of range for {canonical.codepoints} code points; STA does not clamp")
        return None, tuple(notes)
    return make_anchor(canonical, start, end, context=context), tuple(notes)


# ------------------------------------------------------ CTS line nodes (annophis)

def _go_trim_space(s: str) -> str:
    """Approximates Go strings.TrimSpace for the characters that matter here."""
    return s.strip(" \t\n\v\f\r\u0085                 　")


@dataclass(frozen=True)
class LineNode:
    number: int  # 1-based, consecutive over non-empty lines
    text: str  # NFC, untrimmed
    start: int  # code-point offset of the line start in canonical text
    end: int  # exclusive, before the line's newline


class LineNodes:
    """The plain-text ingestion model of annophis-text-service applied to canonical text.

    Rules read from internal/server/txtindex.go (v0.6.2): split on LF, trim a
    trailing CR, skip lines that are empty after TrimSpace, number survivors
    consecutively from 1, store NFC, do not trim. Canonical text already has
    LF and NFC, so only the skipping and numbering remain.
    """

    def __init__(self, canonical: Canonical, *, namespace: str = "ns", work: str = "work"):
        self.canonical = canonical
        self.namespace = namespace
        self.work = work
        self.nodes: list[LineNode] = []
        offset, number = 0, 0
        for raw_line in canonical.text.split("\n"):
            end = offset + len(raw_line)
            if _go_trim_space(raw_line) != "":
                number += 1
                self.nodes.append(LineNode(number, raw_line, offset, end))
            offset = end + 1

    def urn(self, number: int, subref: str = "") -> str:
        return f"urn:cts:{self.namespace}:{self.work}.txtparsed:{number}{subref}"

    def node(self, number: int) -> LineNode:
        for n in self.nodes:
            if n.number == number:
                return n
        raise KeyError(number)

    def locate(self, cp: int) -> tuple[LineNode, int]:
        """(node, offset within node) for a canonical code-point offset."""
        for n in self.nodes:
            if n.start <= cp <= n.end:
                return n, cp - n.start
        raise ValueError(f"code point {cp} is not inside any non-empty line (newline or skipped line)")

    def to_subref(self, anchor: Anchor, *, case_insensitive: bool = True) -> tuple[str | None, tuple[str, ...]]:
        """`<line>@<needle>[k]` for an anchor inside one node, with ambiguity notes.

        The CTS URN specification defines k as the k-th occurrence of the
        literal string and says nothing about case or normalization;
        annophis-text-service matches case-insensitively on NFC text. Both
        readings are computed so that a divergence becomes visible.
        """
        notes: list[str] = []
        try:
            node, off = self.locate(anchor.start)
        except ValueError as exc:
            return None, (str(exc),)
        if anchor.end > node.end:
            return None, ("selection crosses a line node; express it as an anchored range, which STA 0.1 does not map",)
        needle = anchor.exact
        if "@" in needle or "[" in needle or "]" in needle or "-" in needle:
            notes.append("needle contains CTS delimiter characters (@ [ ] -); escaping is undefined in the specification")
        exact_hits = _occurrences(node.text, needle, case_insensitive=False)
        fold_hits = _occurrences(node.text, needle, case_insensitive=True)
        hits = fold_hits if case_insensitive else exact_hits
        if off not in hits:
            return None, (f"needle {needle!r} does not start at offset {off} under the chosen matching",)
        k = hits.index(off) + 1
        if len(fold_hits) != len(exact_hits):
            notes.append(
                f"case-sensitive count {len(exact_hits)} differs from case-insensitive count {len(fold_hits)}: "
                f"the index k means different occurrences in annophis (case-insensitive) and in a literal CTS reading"
            )
        return f"{node.number}@{needle}[{k}]", tuple(notes)

    def from_subref(self, subref: str, *, case_insensitive: bool = True, context: int = 32) -> Anchor:
        """Resolve `<line>@<needle>[k]` (k defaults to 1) to an STA anchor."""
        m = re.match(r"^(?P<line>\d+)@(?P<needle>.+?)(?:\[(?P<k>\d+)\])?$", subref)
        if not m:
            raise ValueError(f"not a line subreference: {subref!r}")
        node = self.node(int(m.group("line")))
        k = int(m.group("k") or 1)
        hits = _occurrences(node.text, m.group("needle"), case_insensitive=case_insensitive)
        if k < 1 or k > len(hits):
            raise ValueError(f"occurrence {k} of {m.group('needle')!r} not found in line {node.number} ({len(hits)} hits)")
        start = node.start + hits[k - 1]
        return make_anchor(self.canonical, start, start + len(m.group("needle")), context=context)


def _occurrences(haystack: str, needle: str, *, case_insensitive: bool) -> list[int]:
    """Non-overlapping occurrences, left to right, as a successive-Index loop finds them."""
    if not needle:
        return []
    if case_insensitive:
        h, n = haystack.casefold(), needle.casefold()
        if len(h) != len(haystack) or len(n) != len(needle):
            # casefold can change length (e.g. ß -> ss); fall back to lower(), which annophis uses
            h, n = haystack.lower(), needle.lower()
    else:
        h, n = haystack, needle
    out, pos = [], h.find(n)
    while pos >= 0:
        out.append(pos)
        pos = h.find(n, pos + len(n))
    return out


def annophis_hash(text: str, *, algorithm: str = "sha256", form: str = "NFC") -> str:
    """hex(algorithm(UTF-8(normalize(text)))) as computed by annophis-text-service (hash.go)."""
    import unicodedata

    normalized = unicodedata.normalize(form, text) if form in ("NFC", "NFD", "NFKC", "NFKD") else text
    data = normalized.encode("utf-8")
    if algorithm == "sha1":
        return hashlib.sha1(data).hexdigest()
    if algorithm == "sha256":
        return hashlib.sha256(data).hexdigest()
    raise ValueError("algorithm must be sha1 or sha256")


__all__ = [
    "LineNode",
    "LineNodes",
    "Rfc5147Fragment",
    "W3CResolution",
    "annophis_hash",
    "from_rfc5147",
    "from_w3c",
    "parse_rfc5147",
    "resolve_quote",
    "rfc5147_length",
    "rfc5147_md5",
    "to_rfc5147",
    "to_textsurf_query",
    "to_w3c",
]

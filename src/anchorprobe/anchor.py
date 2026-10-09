"""The Stable Text Anchor object and its verification.

An anchor binds a quotation to a position in a text whose canonical form is
identified by its SHA-256. Two independent witnesses are stored: the position
(start, end) and the quotation (exact, with optional prefix and suffix).
Verification asks both. Agreement is evidence; disagreement is a finding, never
something to repair silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .canon import Canonical

STA_VERSION = "0.1"
PROFILE = {"unit": "codepoint", "form": "NFC", "newline": "LF", "bom": "stripped"}
DEFAULT_CONTEXT = 32


class ProfileError(ValueError):
    """An anchor document does not conform to the STA profile."""


@dataclass(frozen=True)
class Anchor:
    text_sha256: str
    start: int
    end: int
    exact: str
    prefix: str = ""
    suffix: str = ""
    source: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.start, int) or not isinstance(self.end, int) or isinstance(self.start, bool) or isinstance(self.end, bool):
            raise ProfileError("start and end must be integers")
        if self.start < 0 or self.end < self.start:
            raise ProfileError(f"invalid range start={self.start} end={self.end}")
        if len(self.exact) != self.end - self.start:
            raise ProfileError(
                f"exact has {len(self.exact)} code points but end-start is {self.end - self.start}; "
                "an STA anchor counts code points of the NFC text"
            )
        if len(self.text_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.text_sha256):
            raise ProfileError("text_sha256 must be 64 lowercase hex digits")

    @property
    def length(self) -> int:
        return self.end - self.start

    def to_dict(self) -> dict:
        doc = {
            "sta": STA_VERSION,
            **PROFILE,
            "text_sha256": self.text_sha256,
            "start": self.start,
            "end": self.end,
            "exact": self.exact,
        }
        if self.prefix:
            doc["prefix"] = self.prefix
        if self.suffix:
            doc["suffix"] = self.suffix
        if self.source:
            doc["source"] = self.source
        return doc

    @classmethod
    def from_dict(cls, doc: dict) -> "Anchor":
        if doc.get("sta") not in (None, STA_VERSION):
            raise ProfileError(f"unsupported sta version {doc.get('sta')!r}")
        for key, expected in PROFILE.items():
            value = doc.get(key, expected)
            if value != expected:
                raise ProfileError(
                    f"{key}={value!r} is not part of STA {STA_VERSION} (expected {expected!r}); "
                    "convert the measurement first (see anchorprobe.units.Ruler)"
                )
        try:
            return cls(
                text_sha256=str(doc["text_sha256"]),
                start=doc["start"],
                end=doc["end"],
                exact=str(doc["exact"]),
                prefix=str(doc.get("prefix", "")),
                suffix=str(doc.get("suffix", "")),
                source=doc.get("source"),
            )
        except KeyError as exc:
            raise ProfileError(f"missing field {exc.args[0]!r}") from exc


def make_anchor(canonical: Canonical, start: int, end: int, *, context: int = DEFAULT_CONTEXT, source: str | None = None) -> Anchor:
    """Create an anchor for canonical.text[start:end] with prefix and suffix context."""
    text = canonical.text
    if not (0 <= start <= end <= len(text)):
        raise ProfileError(f"range {start}..{end} outside 0..{len(text)}")
    return Anchor(
        text_sha256=canonical.sha256,
        start=start,
        end=end,
        exact=text[start:end],
        prefix=text[max(0, start - context) : start],
        suffix=text[end : end + context],
        source=source,
    )


def anchor_for_exact(canonical: Canonical, exact: str, *, occurrence: int = 1, context: int = DEFAULT_CONTEXT, source: str | None = None) -> Anchor:
    """Anchor the n-th (1-based, non-overlapping) occurrence of `exact`."""
    if occurrence < 1:
        raise ProfileError("occurrence is 1-based")
    pos = -1
    for _ in range(occurrence):
        pos = canonical.text.find(exact, pos + max(1, len(exact)) if pos >= 0 else 0)
        if pos < 0:
            raise ProfileError(f"occurrence {occurrence} of {exact!r} not found")
    return make_anchor(canonical, pos, pos + len(exact), context=context, source=source)


@dataclass(frozen=True)
class Verdict:
    """Result of asking both witnesses of an anchor against a canonical text."""

    status: str
    hash_match: bool
    position_match: bool
    quote_occurrences: int
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "hash_match": self.hash_match,
            "position_match": self.position_match,
            "quote_occurrences": self.quote_occurrences,
            "notes": list(self.notes),
        }


def verify(anchor: Anchor, canonical: Canonical) -> Verdict:
    """Statuses:

    verified      hash equal, exact found at [start, end)
    stale_hash    text changed somewhere else, exact still at [start, end)
    drifted       hash differs and exact is not at [start, end); run forensics
    inconsistent  hash equal but exact not at [start, end): the anchor object itself is corrupt
    out_of_range  start or end beyond the text
    """
    text = canonical.text
    hash_match = anchor.text_sha256 == canonical.sha256
    notes: list[str] = []
    if anchor.end > len(text):
        return Verdict("out_of_range", hash_match, False, text.count(anchor.exact), (f"end {anchor.end} > length {len(text)}",))
    position_match = text[anchor.start : anchor.end] == anchor.exact
    occurrences = text.count(anchor.exact) if anchor.exact else 0
    if position_match and hash_match:
        status = "verified"
    elif position_match:
        status = "stale_hash"
        notes.append("the text changed elsewhere; the anchor still resolves but was recorded against another version")
    elif hash_match:
        status = "inconsistent"
        notes.append("hash matches but exact is not at the recorded position: the anchor fields disagree with each other")
    else:
        status = "drifted"
    if occurrences > 1 and position_match:
        notes.append(f"exact occurs {occurrences} times; prefix and suffix are needed for quote-only resolution")
    return Verdict(status, hash_match, position_match, occurrences, tuple(notes))

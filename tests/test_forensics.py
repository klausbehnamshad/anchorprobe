from __future__ import annotations

import unicodedata

from anchorprobe.anchor import Anchor, anchor_for_exact
from anchorprobe.canon import BOM, canonicalize
from anchorprobe.forensics import diagnose
from anchorprobe.units import Ruler

GERMAN = "Jena, den 1. August 1797\nSchiller schrieb an Göthe über die Universität und das Weiße Roß.\nGrüße aus Weimar.\n"
EMOJI = "Family: \U0001F468‍\U0001F469‍\U0001F467‍\U0001F466 flag: \U0001F1F1\U0001F1FA wave: \U0001F44B\U0001F3FD done.\n"


def _with_offsets(anchor: Anchor, start: int, end: int) -> Anchor:
    return Anchor(anchor.text_sha256, start, end, anchor.exact, anchor.prefix, anchor.suffix)


def test_verified_and_stale_pass_through():
    c = canonicalize(GERMAN)
    a = anchor_for_exact(c, "Göthe")
    assert diagnose(a, GERMAN).status == "verified"
    assert diagnose(a, GERMAN + "PS\n").status == "stale_hash"


def test_utf16_offsets_from_a_browser_are_recognised():
    c = canonicalize(EMOJI)
    true = anchor_for_exact(c, "done")
    r = Ruler(c.text)
    js = _with_offsets(true, r.from_codepoint(true.start, "utf16"), r.from_codepoint(true.end, "utf16"))
    d = diagnose(js, EMOJI)
    assert d.status == "measurement_drift"
    assert d.discriminating is True
    units = {e.params["unit"] for e in d.explanations}
    assert "utf16" in units
    assert d.candidate is not None and (d.candidate.start, d.candidate.end) == (true.start, true.end)
    assert d.to_dict()["review_required"] is True


def test_nfd_counted_offsets_are_recognised():
    c = canonicalize(GERMAN)
    true = anchor_for_exact(c, "Weiße Roß")  # no decomposable letters inside, two before it (ö, ü)
    nfd = unicodedata.normalize("NFD", c.text)
    s = nfd.index("Weiße Roß")
    wrong = _with_offsets(true, s, s + len("Weiße Roß"))
    d = diagnose(wrong, GERMAN)
    assert d.status == "measurement_drift"
    assert {"NFD", "NFKD"} & {e.params["form"] for e in d.explanations}
    assert d.candidate == anchor_for_exact(c, "Weiße Roß")


def test_bom_and_crlf_counting_are_recognised():
    raw = BOM + GERMAN.replace("\n", "\r\n")
    c = canonicalize(raw)
    true = anchor_for_exact(c, "Grüße")
    # someone counted on the stored bytes: BOM counted (+1) and two CRLF before the word (+2)
    wrong = _with_offsets(true, true.start + 3, true.end + 3)
    d = diagnose(wrong, raw)
    assert d.status == "measurement_drift"
    params = [e.params for e in d.explanations]
    assert any(p["bom"] == "kept" and p["newline"] == "raw" for p in params)
    assert d.candidate == true


def test_shifted_by_an_edit_before_the_anchor():
    c = canonicalize(GERMAN)
    a = anchor_for_exact(c, "Universität")
    edited = GERMAN.replace("Schiller schrieb", "Friedrich Schiller schrieb")
    d = diagnose(a, edited)
    assert d.status == "shifted"
    assert d.explanations[0].params["delta"] == len("Friedrich ")
    assert d.candidate.exact == "Universität"


def test_ambiguous_without_context():
    text = "Schiller. Schiller. Schiller."
    c = canonicalize(text)
    a = Anchor(c.sha256, 0, 8, "Schiller")  # no prefix/suffix
    d = diagnose(a, "x " + text)
    assert d.status == "ambiguous" and d.candidate is None and len(d.explanations) == 3


def test_prefix_suffix_disambiguate_shift():
    text = "Schiller. Schiller. Schiller."
    c = canonicalize(text)
    a = anchor_for_exact(c, "Schiller", occurrence=2)
    d = diagnose(a, "x " + text)
    assert d.status == "shifted" and d.candidate.start == 12


def test_whitespace_drift():
    c = canonicalize(GERMAN)
    a = anchor_for_exact(c, "Weiße Roß")
    d = diagnose(a, GERMAN.replace("Weiße Roß", "Weiße  Roß"))
    assert d.status == "whitespace_drift" and d.candidate.exact == "Weiße  Roß"


def test_edited_in_place():
    c = canonicalize(GERMAN)
    a = anchor_for_exact(c, "Universität")
    d = diagnose(a, GERMAN.replace("Universität", "Universitaet"))
    assert d.status == "edited"
    assert d.explanations[0].params["ratio"] > 0.6 and d.candidate is None


def test_missing():
    c = canonicalize(GERMAN)
    a = anchor_for_exact(c, "Universität")
    d = diagnose(a, "Etwas ganz anderes, ohne die Worte.\n")
    assert d.status == "missing"


def test_ascii_cannot_discriminate_units():
    text = "The quick brown fox jumps over the lazy dog.\n"
    c = canonicalize(text)
    a = anchor_for_exact(c, "lazy")
    wrong = _with_offsets(a, a.start + 2, a.end + 2)
    d = diagnose(wrong, text)
    assert d.discriminating is False
    assert d.status == "shifted"

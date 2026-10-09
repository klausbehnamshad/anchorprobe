from __future__ import annotations

import json

import pytest

from anchorprobe.anchor import PROFILE, Anchor, ProfileError, anchor_for_exact, make_anchor, verify
from anchorprobe.canon import canonicalize

TEXT = "Jena, den 1. August 1797\nSchiller schrieb an Göthe über die Universität.\n"


def test_make_anchor_and_round_trip():
    c = canonicalize(TEXT)
    a = anchor_for_exact(c, "Göthe", source="urn:example:letter")
    assert (a.start, a.end, a.exact) == (45, 50, "Göthe")
    assert a.prefix.endswith("an ") and a.suffix.startswith(" über")
    doc = a.to_dict()
    assert doc["sta"] == "0.1" and {k: doc[k] for k in PROFILE} == PROFILE
    assert Anchor.from_dict(json.loads(json.dumps(doc))) == a


def test_from_dict_rejects_other_measurements():
    doc = anchor_for_exact(canonicalize(TEXT), "Göthe").to_dict()
    doc["unit"] = "utf16"
    with pytest.raises(ProfileError, match="utf16"):
        Anchor.from_dict(doc)
    doc = anchor_for_exact(canonicalize(TEXT), "Göthe").to_dict()
    doc["form"] = "NFD"
    with pytest.raises(ProfileError, match="NFD"):
        Anchor.from_dict(doc)


def test_exact_length_must_equal_range():
    with pytest.raises(ProfileError, match="code points"):
        Anchor(text_sha256="0" * 64, start=0, end=6, exact="Göthe")


def test_bool_offsets_are_not_positions():
    with pytest.raises(ProfileError):
        Anchor(text_sha256="0" * 64, start=True, end=1, exact="a")


def test_occurrence_selection():
    c = canonicalize("a b a b a")
    assert anchor_for_exact(c, "a", occurrence=3).start == 8
    with pytest.raises(ProfileError):
        anchor_for_exact(c, "a", occurrence=4)


def test_verify_statuses():
    c = canonicalize(TEXT)
    a = anchor_for_exact(c, "Göthe")
    assert verify(a, c).status == "verified"
    appended = canonicalize(TEXT + "Ihr Schiller\n")
    assert verify(a, appended).status == "stale_hash"
    prepended = canonicalize("Brief\n" + TEXT)
    assert verify(a, prepended).status == "drifted"
    short = canonicalize("kurz")
    assert verify(a, short).status == "out_of_range"
    tampered = Anchor(a.text_sha256, a.start, a.end, "Gothe", a.prefix, a.suffix)
    assert verify(tampered, c).status == "inconsistent"


def test_verify_notes_multiple_occurrences():
    c = canonicalize("a b a")
    a = make_anchor(c, 0, 1)
    v = verify(a, c)
    assert v.status == "verified" and v.quote_occurrences == 2 and any("prefix" in n for n in v.notes)

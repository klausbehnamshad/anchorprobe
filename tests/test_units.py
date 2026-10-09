from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from anchorprobe.units import UNITS, BoundaryError, Ruler

FAMILY = "\U0001F468‍\U0001F469‍\U0001F467‍\U0001F466"


def test_family_emoji_is_one_grapheme_seven_codepoints_eleven_units():
    r = Ruler(FAMILY)
    assert r.length("codepoint") == 7
    assert r.length("utf16") == 11
    assert r.length("utf8") == 25
    assert r.length("grapheme") == 1


def test_lengths_match_python_encodings():
    text = "Göthe 𒀭 ᾱ́ x"
    r = Ruler(text)
    assert r.length("utf8") == len(text.encode("utf-8"))
    assert r.length("utf16") == len(text.encode("utf-16-le")) // 2
    assert r.length("codepoint") == len(text)


def test_offset_inside_multibyte_sequence_is_refused():
    r = Ruler("aä")
    assert r.to_codepoint(1, "utf8") == 1
    with pytest.raises(BoundaryError, match="inside code point"):
        r.to_codepoint(2, "utf8")
    assert r.to_codepoint(3, "utf8") == 2


def test_offset_between_surrogates_is_refused():
    r = Ruler("a\U0001F468b")
    assert r.to_codepoint(1, "utf16") == 1
    with pytest.raises(BoundaryError):
        r.to_codepoint(2, "utf16")
    assert r.to_codepoint(3, "utf16") == 2


def test_offset_inside_grapheme_cluster_is_refused_for_grapheme_unit():
    r = Ruler("x" + FAMILY + "y")
    assert r.from_codepoint(1, "grapheme") == 1
    with pytest.raises(BoundaryError, match="inside grapheme cluster"):
        r.from_codepoint(3, "grapheme")
    assert r.from_codepoint(8, "grapheme") == 2


def test_measure_reports_cluster_edges():
    r = Ruler("x" + FAMILY + "y")
    m = r.measure(1, 8)
    assert (m["grapheme"].start, m["grapheme"].end, m["grapheme"].on_boundary) == (1, 2, True)
    inside = r.measure(2, 8)
    assert inside["grapheme"].on_boundary is False
    assert inside["grapheme"].start == 1


def test_beyond_length_is_refused():
    r = Ruler("abc")
    with pytest.raises(BoundaryError):
        r.to_codepoint(4, "codepoint")
    with pytest.raises(BoundaryError):
        r.to_codepoint(9, "utf8")
    with pytest.raises(BoundaryError):
        r.from_codepoint(4, "utf16")


@settings(max_examples=300)
@given(st.text(max_size=120), st.data())
def test_round_trip_through_every_unit(text, data):
    r = Ruler(text)
    cp = data.draw(st.integers(min_value=0, max_value=len(text)))
    for unit in ("utf8", "utf16", "codepoint"):
        assert r.to_codepoint(r.from_codepoint(cp, unit), unit) == cp
    if r.grapheme_boundary(cp):
        assert r.to_codepoint(r.from_codepoint(cp, "grapheme"), "grapheme") == cp


@settings(max_examples=200)
@given(st.text(max_size=120))
def test_grapheme_count_never_exceeds_codepoints(text):
    r = Ruler(text)
    assert r.length("grapheme") <= r.length("codepoint") <= r.length("utf16") <= r.length("utf8")
    assert set(UNITS) == {"utf8", "utf16", "codepoint", "grapheme"}

from __future__ import annotations

import hashlib

import pytest

from anchorprobe.anchor import anchor_for_exact, make_anchor
from anchorprobe.canon import canonicalize
from anchorprobe.formats import (
    LineNodes,
    annophis_hash,
    from_rfc5147,
    from_w3c,
    parse_rfc5147,
    resolve_quote,
    rfc5147_length,
    rfc5147_md5,
    to_rfc5147,
    to_textsurf_query,
    to_w3c,
)

TEXT = "Jena, den 1. August 1797\r\nSchiller schrieb an Göthe über die Universität.\r\nIhr Schiller\r\n"


# ------------------------------------------------------------------ W3C

def test_w3c_export_has_two_witnesses_and_the_integrity_extension():
    c = canonicalize(TEXT)
    a = anchor_for_exact(c, "Göthe", source="urn:x:letter")
    doc = to_w3c(a)
    types = [s["type"] for s in doc["selector"]]
    assert types == ["TextQuoteSelector", "TextPositionSelector"]
    assert doc["sta:textSha256"] == c.sha256
    assert doc["source"] == "urn:x:letter"
    assert doc["@context"][0] == "http://www.w3.org/ns/anno.jsonld"


def test_w3c_round_trip_agrees():
    c = canonicalize(TEXT)
    a = anchor_for_exact(c, "Göthe")
    res = from_w3c(to_w3c(a), c)
    assert res.agreement == "agree" and res.anchor == a


def test_w3c_conflict_is_reported_not_resolved():
    c = canonicalize(TEXT)
    a = anchor_for_exact(c, "Göthe")
    doc = to_w3c(a)
    doc["selector"][1]["start"], doc["selector"][1]["end"] = 0, 5  # points at "Jena,"
    res = from_w3c(doc, c)
    assert res.agreement == "conflict" and res.anchor is None
    assert any("do not choose silently" in n for n in res.notes)


def test_w3c_quote_only_and_ambiguity():
    c = canonicalize("Schiller und Schiller")
    sel = [{"type": "TextQuoteSelector", "exact": "Schiller"}]
    assert from_w3c(sel, c).agreement == "conflict"
    sel[0]["prefix"] = "und "
    res = from_w3c(sel, c)
    assert res.agreement == "quote_only" and res.anchor.start == 13


def test_w3c_stale_hash_is_noted():
    c = canonicalize(TEXT)
    a = anchor_for_exact(c, "Göthe")
    doc = to_w3c(a)
    other = canonicalize(TEXT + "PS\n")
    res = from_w3c(doc, other)
    assert res.agreement == "agree" and any("another version" in n for n in res.notes)


def test_resolve_quote_prefix_suffix():
    assert resolve_quote("a b a b", "a", suffix=" b") == [(0, 1), (4, 5)]
    assert resolve_quote("a b a b", "a", prefix="b ") == [(4, 5)]


# ------------------------------------------------------------- RFC 5147

@pytest.mark.parametrize(
    "frag,kind,start,end",
    [
        ("char=0,10", "range", 0, 10),
        ("#char=100", "position", 100, 100),
        ("char=100,", "range", 100, None),
        ("char=,100", "range", None, 100),
        ("line=10,20", "range", 10, 20),
    ],
)
def test_parse_rfc5147_positions_and_ranges(frag, kind, start, end):
    f = parse_rfc5147(frag)
    assert (f.kind, f.start, f.end) == (kind, start, end)
    assert parse_rfc5147(str(f)) == f


def test_parse_rfc5147_integrity_and_unknown_checks():
    f = parse_rfc5147("char=0,10;length=200;md5=0123456789ABCDEF0123456789abcdef,UTF-8;sha256=deadbeef")
    assert f.length == 200 and f.md5 == "0123456789abcdef0123456789abcdef" and f.charset == "UTF-8"
    assert f.ignored == ("sha256=deadbeef",)
    assert str(f) == "char=0,10;length=200;md5=0123456789abcdef0123456789abcdef,UTF-8"


@pytest.mark.parametrize("bad", ["char=10,5", "chars=1,2", "char=a,b", "char=1,2;md5=xyz", ""])
def test_parse_rfc5147_rejects_malformed(bad):
    with pytest.raises(ValueError):
        parse_rfc5147(bad)


def test_rfc5147_length_and_md5_follow_the_rfc_rules_after_c14n():
    c = canonicalize(TEXT)
    assert rfc5147_length(c) == len(TEXT.replace("\r\n", "\n"))  # each line ending counts once
    assert rfc5147_md5(c.text) == hashlib.md5(c.text.encode("utf-8")).hexdigest()


def test_to_and_from_rfc5147():
    c = canonicalize(TEXT)
    a = anchor_for_exact(c, "Göthe")
    frag = to_rfc5147(a, c)
    assert str(frag).startswith(f"char={a.start},{a.end};length={c.codepoints};md5=")
    back, notes = from_rfc5147(str(frag), c)
    assert back == a and notes == ()
    other = canonicalize(TEXT + "x")
    back, notes = from_rfc5147(str(frag), other)
    assert back is not None and any("length check failed" in n for n in notes) and any("md5 check failed" in n for n in notes)


def test_from_rfc5147_does_not_clamp():
    c = canonicalize("short")
    a, notes = from_rfc5147("char=2,999", c)
    assert a is None and any("does not clamp" in n for n in notes)
    a, notes = from_rfc5147("char=2,", c)
    assert a is not None and (a.start, a.end) == (2, 5)


def test_textsurf_query_excerpt_checks():
    c = canonicalize(TEXT)
    a = anchor_for_exact(c, "Göthe")
    assert to_textsurf_query(a) == f"char={a.start},{a.end}"
    q = to_textsurf_query(a, excerpt_checks=True)
    assert f"length=5&md5={hashlib.md5('Göthe'.encode()).hexdigest()}" in q


# ------------------------------------------------------- CTS line nodes

LINES = "first\n\n   \nfourth has trailing spaces   \n\nlast Last LAST without newline"


def test_line_nodes_skip_blank_lines_and_number_consecutively():
    c = canonicalize(LINES)
    nodes = LineNodes(c, namespace="anchorprobe", work="empty-lines")
    assert [(n.number, n.text) for n in nodes.nodes] == [
        (1, "first"),
        (2, "fourth has trailing spaces   "),
        (3, "last Last LAST without newline"),
    ]
    assert nodes.urn(2) == "urn:cts:anchorprobe:empty-lines.txtparsed:2"
    node, off = nodes.locate(c.text.index("fourth"))
    assert (node.number, off) == (2, 0)
    with pytest.raises(ValueError):
        nodes.locate(6)  # the blank line


def test_subref_round_trip_and_case_ambiguity():
    c = canonicalize(LINES)
    nodes = LineNodes(c)
    a = anchor_for_exact(c, "LAST")
    sub, notes = nodes.to_subref(a, case_insensitive=True)
    assert sub == "3@LAST[3]"
    assert any("case-sensitive count 1 differs from case-insensitive count 3" in n for n in notes)
    sub_cs, _ = nodes.to_subref(a, case_insensitive=False)
    assert sub_cs == "3@LAST[1]"
    assert nodes.from_subref("3@LAST[3]", case_insensitive=True) == a
    assert nodes.from_subref("3@LAST", case_insensitive=False) == a
    assert nodes.from_subref("3@last[2]", case_insensitive=True).exact == "Last"
    with pytest.raises(ValueError):
        nodes.from_subref("3@LAST[2]", case_insensitive=False)


def test_subref_refuses_cross_line_selection():
    c = canonicalize("one\ntwo")
    a = make_anchor(c, 0, 7)
    sub, notes = LineNodes(c).to_subref(a)
    assert sub is None and "crosses a line node" in notes[0]


def test_annophis_hash_recipe():
    line = "Grüße"
    assert annophis_hash(line) == hashlib.sha256(line.encode()).hexdigest()
    assert annophis_hash("Grüße") == annophis_hash(line)  # NFD input, NFC hash
    assert annophis_hash(line, algorithm="sha1") == hashlib.sha1(line.encode()).hexdigest()

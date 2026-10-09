"""The manifest is written by tools/make_fixtures.py without importing anchorprobe.

These tests compare the library against that independent computation.
"""

from __future__ import annotations

import hashlib
import unicodedata

import pytest

from anchorprobe.anchor import anchor_for_exact
from anchorprobe.canon import canonicalize
from anchorprobe.matrix import hash_table, unit_matrix
from anchorprobe.units import Ruler


def _entries(manifest):
    return [pytest.param(e, id=e["id"]) for e in manifest["fixtures"]]


def test_manifest_lists_fourteen_fixtures(manifest, fixtures_dir):
    assert len(manifest["fixtures"]) == 14
    for e in manifest["fixtures"]:
        raw = (fixtures_dir / e["file"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == e["bytes_sha256"]


def test_canonical_values_agree(manifest, fixtures_dir):
    for e in manifest["fixtures"]:
        c = canonicalize((fixtures_dir / e["file"]).read_bytes())
        r = Ruler(c.text)
        assert c.codepoints == e["canonical"]["codepoints"], e["id"]
        assert c.sha256 == e["canonical"]["sha256"], e["id"]
        assert r.length("utf8") == e["canonical"]["utf8"], e["id"]
        assert r.length("utf16") == e["canonical"]["utf16"], e["id"]
        assert r.length("grapheme") == e["canonical"]["graphemes"], e["id"]
        assert c.bom_stripped == e["raw"]["has_bom"], e["id"]
        assert c.crlf_folded == e["raw"]["crlf"], e["id"]
        assert c.cr_folded == e["raw"]["lone_cr"], e["id"]


def test_selections_agree_in_every_unit(manifest, fixtures_dir):
    for e in manifest["fixtures"]:
        c = canonicalize((fixtures_dir / e["file"]).read_bytes())
        r = Ruler(c.text)
        for sel in e["selections"]:
            a = anchor_for_exact(c, sel["exact"])
            assert [a.start, a.end] == sel["canonical"], (e["id"], sel["exact"])
            measured = r.measure(a.start, a.end)
            for unit in ("utf8", "utf16", "codepoint"):
                assert measured[unit].as_list() == sel["measurements"][unit], (e["id"], sel["exact"], unit)
            want = sel["measurements"]["grapheme"]
            if want is None:
                assert measured["grapheme"].on_boundary is False
            else:
                assert measured["grapheme"].as_list() == want and measured["grapheme"].on_boundary
            nfd_rows = [row for row in unit_matrix(c.text, a.start, a.end) if row.form == "NFD" and row.unit == "codepoint"]
            assert [nfd_rows[0].start, nfd_rows[0].end] == sel["measurements"]["nfd_codepoint"], (e["id"], sel["exact"])


def test_nfc_and_nfd_fixtures_share_a_hash(manifest):
    by_id = {e["id"]: e for e in manifest["fixtures"]}
    assert by_id["german-nfc"]["canonical"]["sha256"] == by_id["german-nfd"]["canonical"]["sha256"] == by_id["crlf-windows"]["canonical"]["sha256"] == by_id["bom-utf8"]["canonical"]["sha256"]
    assert by_id["german-nfc"]["bytes_sha256"] != by_id["german-nfd"]["bytes_sha256"]


def test_ascii_fixture_coincides_in_all_units(manifest):
    e = {x["id"]: x for x in manifest["fixtures"]}["ascii-plain"]
    for sel in e["selections"]:
        m = sel["measurements"]
        assert m["utf8"] == m["utf16"] == m["codepoint"] == m["grapheme"] == m["nfd_codepoint"]


def test_emoji_fixture_separates_the_units(manifest):
    e = {x["id"]: x for x in manifest["fixtures"]}["emoji-zwj"]
    c = e["canonical"]
    assert c["graphemes"] < c["codepoints"] < c["utf16"] < c["utf8"]


def test_hash_table_collapses_encoding_variance(fixtures_dir):
    text = (fixtures_dir / "german-nfc.txt").read_text(encoding="utf-8")
    rows = hash_table(text)
    assert len(rows) == 16
    assert len({r.sha256 for r in rows}) == 16
    assert len({r.canonical_sha256 for r in rows}) == 2  # with and without trailing newline


def test_unicode_version_is_recorded(manifest):
    # The manifest records the Unicode version of the generating interpreter. Other
    # interpreters may run the tests; the values themselves are checked above.
    major, minor, _ = manifest["unicode_version"].split(".")
    assert major.isdigit() and minor.isdigit()
    assert tuple(map(int, unicodedata.unidata_version.split(".")[:2])) >= (14, 0)

from __future__ import annotations

import hashlib
import unicodedata

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from anchorprobe.canon import BOM, CanonError, canonicalize, sha256_hex, variant


def test_bom_only_at_start_is_stripped():
    c = canonicalize(BOM + "a" + BOM + "b")
    assert c.text == "a" + BOM + "b"
    assert c.bom_stripped is True
    assert c.raw_codepoints == 4
    assert c.codepoints == 3


def test_newlines_fold_and_are_counted():
    c = canonicalize("a\r\nb\rc\nd")
    assert c.text == "a\nb\nc\nd"
    assert (c.crlf_folded, c.cr_folded) == (1, 1)


def test_nfc_composes_and_flags_change():
    c = canonicalize("ä")
    assert c.text == "ä" and c.codepoints == 1
    assert c.form_changed is True
    assert canonicalize("ä").form_changed is False


def test_singletons_change_even_in_nfc():
    # The ohm sign and the angstrom sign have singleton canonical decompositions:
    # NFC maps them to the Greek omega and the Latin A with ring. Same for the Kelvin sign.
    assert canonicalize("Ω").text == "Ω"
    assert canonicalize("Å").text == "Å"
    assert canonicalize("K").text == "K"


def test_nfc_does_not_fold_compatibility_characters():
    c = canonicalize("ﬁ µ Ａ")
    assert c.text == "ﬁ µ Ａ"
    assert unicodedata.normalize("NFKC", c.text) == "fi μ A"


def test_nel_and_line_separator_are_content():
    c = canonicalize("a\u0085b c")
    assert c.text == "a\u0085b c"


def test_invalid_utf8_is_an_error():
    with pytest.raises(CanonError):
        canonicalize(b"ok \xff\xfe")


def test_sha_is_over_utf8_of_canonical_text():
    c = canonicalize("Göthe\r\n")
    assert c.sha256 == hashlib.sha256("Göthe\n".encode()).hexdigest() == sha256_hex("Göthe\n")


def test_nfc_and_nfd_inputs_share_one_hash():
    assert canonicalize(unicodedata.normalize("NFD", "Grüße")).sha256 == canonicalize("Grüße").sha256


def test_variant_reproduces_other_systems_choices():
    raw = BOM + "ä\r\nb"
    assert variant(raw, bom="kept", newline="raw", form="raw") == raw
    assert variant(raw, bom="stripped", newline="LF", form="NFC") == "ä\nb"
    assert variant(raw, bom="stripped", newline="raw", form="NFD") == "ä\r\nb"
    with pytest.raises(ValueError):
        variant(raw, form="latin-1")


@settings(max_examples=300)
@given(st.text(min_size=0, max_size=200))
def test_canonicalization_is_idempotent(text):
    once = canonicalize(text)
    twice = canonicalize(once.text)
    assert twice.text == once.text
    assert twice.sha256 == once.sha256
    assert twice.changed is False


@settings(max_examples=200)
@given(st.text(min_size=0, max_size=200))
def test_canonical_text_is_nfc_without_cr_or_leading_bom(text):
    c = canonicalize(text)
    assert unicodedata.is_normalized("NFC", c.text)
    assert "\r" not in c.text
    assert not c.text.startswith(BOM) or text.startswith(BOM + BOM)

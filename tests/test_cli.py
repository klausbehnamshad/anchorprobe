from __future__ import annotations

import json

from anchorprobe.cli import main

GERMAN = "Jena, den 1. August 1797\nSchiller schrieb an Göthe über die Universität und das Weiße Roß.\n"


def run(capsys, *argv) -> tuple[int, str]:
    code = main(list(argv))
    return code, capsys.readouterr().out


def test_canon_anchor_verify_diagnose(tmp_path, capsys):
    text = tmp_path / "t.txt"
    text.write_text(GERMAN, encoding="utf-8")
    code, out = run(capsys, "canon", str(text))
    assert code == 0 and json.loads(out)["codepoints"] == len(GERMAN)

    code, out = run(capsys, "anchor", str(text), "--exact", "Göthe", "--source", "urn:x:t")
    assert code == 0
    anchor = tmp_path / "a.json"
    anchor.write_text(out, encoding="utf-8")
    assert json.loads(out)["start"] == 45

    code, out = run(capsys, "verify", str(anchor), str(text))
    assert code == 0 and json.loads(out)["status"] == "verified"

    edited = tmp_path / "t2.txt"
    edited.write_text("PS. " + GERMAN, encoding="utf-8")
    code, out = run(capsys, "verify", str(anchor), str(edited))
    assert code == 1 and json.loads(out)["status"] == "drifted"
    code, out = run(capsys, "diagnose", str(anchor), str(edited))
    d = json.loads(out)
    assert code == 1 and d["status"] == "shifted" and d["candidate"]["start"] == 49


def test_convert_targets(tmp_path, capsys):
    text = tmp_path / "t.txt"
    text.write_text(GERMAN, encoding="utf-8")
    _, out = run(capsys, "anchor", str(text), "--exact", "Göthe")
    anchor = tmp_path / "a.json"
    anchor.write_text(out, encoding="utf-8")

    code, out = run(capsys, "convert", str(anchor), "--to", "w3c")
    assert code == 0 and json.loads(out)["type"] == "SpecificResource"
    code, out = run(capsys, "convert", str(anchor), "--to", "rfc5147", "--file", str(text))
    assert code == 0 and json.loads(out)["fragment"].startswith("#char=45,50;length=")
    code, out = run(capsys, "convert", str(anchor), "--to", "textsurf", "--excerpt-checks")
    assert code == 0 and json.loads(out)["query"].startswith("char=45,50&length=5&md5=")
    code, out = run(capsys, "convert", str(anchor), "--to", "cts", "--file", str(text), "--namespace", "demo", "--work", "letter")
    doc = json.loads(out)
    assert code == 0 and doc["subref"] == "2@Göthe[1]" and doc["urn"] == "urn:cts:demo:letter.txtparsed:2@Göthe[1]"
    code, out = run(capsys, "convert", str(anchor), "--to", "rfc5147")
    assert code == 2 and "error" in json.loads(out)


def test_imports(tmp_path, capsys):
    text = tmp_path / "t.txt"
    text.write_text(GERMAN, encoding="utf-8")
    code, out = run(capsys, "import-rfc5147", "char=45,50", str(text))
    assert code == 0 and json.loads(out)["anchor"]["exact"] == "Göthe"
    code, out = run(capsys, "import-cts", "2@göthe", str(text))
    assert code == 0 and json.loads(out)["exact"] == "Göthe"
    _, w3c = run(capsys, "convert", str(tmp_path / "x.json") if False else "-", "--to", "w3c") if False else (0, "")
    _, out = run(capsys, "anchor", str(text), "--exact", "Göthe")
    anchor = tmp_path / "a.json"
    anchor.write_text(out, encoding="utf-8")
    _, out = run(capsys, "convert", str(anchor), "--to", "w3c")
    doc = tmp_path / "w3c.json"
    doc.write_text(out, encoding="utf-8")
    code, out = run(capsys, "import-w3c", str(doc), str(text))
    assert code == 0 and json.loads(out)["agreement"] == "agree"


def test_measure_converts_a_utf16_measurement(tmp_path, capsys):
    text = tmp_path / "e.txt"
    text.write_text("Family: \U0001F468‍\U0001F469 done.\n", encoding="utf-8")
    # "Family: " is 8 code points, the two emoji with ZWJ are 3 code points but 5 UTF-16 units:
    # "done" starts at code point 12 but at UTF-16 unit 14
    code, out = run(capsys, "measure", str(text), "--start", "14", "--end", "18", "--unit", "utf16")
    doc = json.loads(out)
    assert code == 0 and doc["exact"] == "done" and doc["start"] == 12 and doc["converted_from"]["unit"] == "utf16"


def test_matrix_and_hashes(tmp_path, capsys):
    text = tmp_path / "t.txt"
    text.write_text(GERMAN, encoding="utf-8")
    code, out = run(capsys, "matrix", str(text), "--exact", "Weiße Roß")
    assert code == 0 and "| NFD | codepoint |" in out and "distinct (start, end) pairs" in out
    code, out = run(capsys, "hashes", str(text))
    assert code == 0 and "16 encodings of one paragraph: 16 distinct hashes" in out


def test_fixtures_cross_check(capsys):
    code, out = run(capsys, "fixtures")
    doc = json.loads(out)
    assert code == 0 and doc["ok"] is True and len(doc["fixtures"]) == 14


def test_errors_are_json(tmp_path, capsys):
    text = tmp_path / "t.txt"
    text.write_text(GERMAN, encoding="utf-8")
    code, out = run(capsys, "anchor", str(text), "--exact", "nicht da")
    assert code == 2 and "not found" in json.loads(out)["error"]

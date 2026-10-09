from __future__ import annotations

from anchorprobe.probe import AnnophisProbe, TextsurfProbe, load_fixtures, render_report, write_report

from .fake_services import FakeAnnophis, FakeTextsurf, client_for


def _by_id(report):
    return {c.id: c for c in report.checks}


def test_textsurf_probe_against_the_source_model(fixtures_dir):
    fixtures = load_fixtures(fixtures_dir)
    probe = TextsurfProbe("http://model.local", client=client_for(FakeTextsurf().handler))
    report = probe.run(fixtures)
    checks = _by_id(report)
    assert report.version == "0.7.0-model"
    # ASCII file: bytes == canonical UTF-8, so chars and checksum agree
    assert checks["ascii-plain/stat.chars"].verdict == "agrees"
    assert checks["ascii-plain/stat.checksum"].verdict == "agrees"
    # NFD file: chars differ (3 combining marks), checksum is of raw bytes
    assert checks["german-nfd/stat.chars"].verdict == "differs"
    assert checks["german-nfd/stat.checksum"].verdict == "differs"
    assert "file bytes" in checks["german-nfd/stat.checksum"].note
    # BOM counted as character 0; CRLF is two characters
    assert checks["bom-utf8/bom"].verdict == "differs"
    assert checks["crlf-windows/crlf"].verdict == "differs"
    # length is checked against the excerpt, not the entity; out-of-range clamps
    assert checks["german-nfc/length-scope"].verdict == "differs"
    assert checks["german-nfc/range"].verdict == "differs"
    assert report.summary()["error"] == 0


def test_textsurf_probe_reports_read_only_server(fixtures_dir):
    fixtures = load_fixtures(fixtures_dir, ["ascii-plain"])
    probe = TextsurfProbe("http://model.local", client=client_for(FakeTextsurf(writable=False).handler))
    report = probe.run(fixtures)
    assert report.checks[0].verdict == "error" and "read-only" in report.checks[0].note


def test_annophis_probe_against_the_source_model(fixtures_dir):
    fixtures = load_fixtures(fixtures_dir)
    fake = FakeAnnophis({"anchorprobe": {fx.id: fx.raw for fx in fixtures}})
    probe = AnnophisProbe("http://model.local", client=client_for(fake.handler))
    report = probe.run(fixtures)
    checks = _by_id(report)
    assert report.version == "0.6.2-model"
    assert checks["empty-lines/nodes"].verdict == "agrees"
    assert checks["german-nfd/nfc"].verdict == "agrees"  # stored NFC regardless of input form
    assert checks["german-nfd/hash"].verdict == "agrees"
    assert checks["german-nfd/normalize"].verdict == "agrees"
    assert checks["bom-utf8/nfc"].verdict == "differs" and "BOM survives" in checks["bom-utf8/nfc"].note
    assert checks["german-nfc/anchor-case"].verdict == "differs"
    assert checks["cuneiform-gothic/context-unit"].verdict == "agrees"
    assert report.summary()["error"] == 0


def test_report_rendering_and_writing(fixtures_dir, tmp_path):
    fixtures = load_fixtures(fixtures_dir, ["german-nfc", "bom-utf8"])
    report = TextsurfProbe("http://model.local", client=client_for(FakeTextsurf().handler)).run(fixtures)
    md = render_report(report)
    assert md.startswith("# Conformance probe: textsurf")
    assert "| bom-utf8/bom |" in md
    jpath, mpath = write_report(report, tmp_path)
    assert jpath.exists() and mpath.exists()
    assert '"service": "textsurf"' in jpath.read_text(encoding="utf-8")

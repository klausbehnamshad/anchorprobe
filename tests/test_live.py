"""Live probes. Skipped unless a service URL is given in the environment.

    ANCHORPROBE_TEXTSURF_URL=http://localhost:8080 pytest tests/test_live.py
    ANCHORPROBE_ANNOPHIS_URL=http://localhost:8081 pytest tests/test_live.py

Reports are written to reports/. A "differs" verdict is a finding, not a test
failure; only transport errors fail the test.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from anchorprobe.probe import AnnophisProbe, TextsurfProbe, load_fixtures, write_report

REPORTS = Path(__file__).resolve().parents[1] / "reports"


@pytest.mark.skipif(not os.environ.get("ANCHORPROBE_TEXTSURF_URL"), reason="no textsurf URL")
def test_live_textsurf(fixtures_dir):
    upload = os.environ.get("ANCHORPROBE_TEXTSURF_UPLOAD", "1") != "0"
    report = TextsurfProbe(os.environ["ANCHORPROBE_TEXTSURF_URL"], upload=upload).run(load_fixtures(fixtures_dir))
    write_report(report, REPORTS)
    assert report.checks
    assert report.summary()["error"] == 0, [c.to_dict() for c in report.checks if c.verdict == "error"]


@pytest.mark.skipif(not os.environ.get("ANCHORPROBE_ANNOPHIS_URL"), reason="no annophis URL")
def test_live_annophis(fixtures_dir):
    report = AnnophisProbe(os.environ["ANCHORPROBE_ANNOPHIS_URL"], namespace=os.environ.get("ANCHORPROBE_NAMESPACE", "anchorprobe")).run(load_fixtures(fixtures_dir))
    write_report(report, REPORTS)
    assert report.checks
    assert report.summary()["error"] == 0, [c.to_dict() for c in report.checks if c.verdict == "error"]

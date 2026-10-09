"""Command line interface. Every subcommand prints JSON or Markdown and nothing else."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .anchor import Anchor, ProfileError, anchor_for_exact, make_anchor, verify
from .canon import CanonError, canonicalize
from .forensics import diagnose
from .formats import LineNodes, from_rfc5147, from_w3c, to_rfc5147, to_textsurf_query, to_w3c
from .matrix import hash_table, render_hash_table, render_matrix, unit_matrix
from .units import UNITS, BoundaryError, Ruler

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"


def _read(path: str) -> bytes:
    return sys.stdin.buffer.read() if path == "-" else Path(path).read_bytes()


def _emit(obj, as_json: bool = True) -> None:
    if as_json:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
    else:
        print(obj)


def _load_anchor(path: str) -> Anchor:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(doc, dict) and doc.get("type") == "SpecificResource":
        raise ProfileError("this is a W3C SpecificResource; use `anchorprobe import-w3c` with the text first")
    return Anchor.from_dict(doc)


def _selection(args, canonical) -> tuple[int, int]:
    if args.exact is not None:
        a = anchor_for_exact(canonical, args.exact, occurrence=getattr(args, "occurrence", 1) or 1)
        return a.start, a.end
    if args.start is None or args.end is None:
        raise ProfileError("give --start and --end, or --exact")
    return args.start, args.end


def cmd_canon(args) -> int:
    c = canonicalize(_read(args.file))
    _emit(c.summary())
    return 0


def cmd_anchor(args) -> int:
    c = canonicalize(_read(args.file))
    s, e = _selection(args, c)
    a = make_anchor(c, s, e, context=args.context, source=args.source)
    _emit(a.to_dict())
    return 0


def cmd_measure(args) -> int:
    """Convert a foreign measurement (offsets in another unit or form) into an STA anchor."""
    from .canon import variant

    raw = _read(args.file)
    vt = variant(raw, bom=args.bom, newline=args.newline, form=args.form)
    ruler = Ruler(vt)
    s = ruler.to_codepoint(args.start, args.unit)
    e = ruler.to_codepoint(args.end, args.unit)
    piece = vt[s:e]
    c = canonicalize(raw)
    import unicodedata

    target = unicodedata.normalize("NFC", piece.replace("\r\n", "\n").replace("\r", "\n"))
    hits = [i for i in range(len(c.text)) if c.text.startswith(target, i)] if target else []
    if len(hits) != 1:
        _emit({"error": f"the measured text {target!r} occurs {len(hits)} times in the canonical text; cannot map uniquely", "measured": piece})
        return 1
    a = make_anchor(c, hits[0], hits[0] + len(target), context=args.context, source=args.source)
    doc = a.to_dict()
    doc["converted_from"] = {"unit": args.unit, "form": args.form, "newline": args.newline, "bom": args.bom, "start": args.start, "end": args.end}
    _emit(doc)
    return 0


def cmd_verify(args) -> int:
    a = _load_anchor(args.anchor)
    v = verify(a, canonicalize(_read(args.file)))
    _emit(v.to_dict())
    return 0 if v.status == "verified" else 1


def cmd_diagnose(args) -> int:
    a = _load_anchor(args.anchor)
    d = diagnose(a, _read(args.file))
    _emit(d.to_dict())
    return 0 if d.status in ("verified", "stale_hash") else 1


def cmd_convert(args) -> int:
    a = _load_anchor(args.anchor)
    if args.to == "w3c":
        _emit(to_w3c(a, source=args.source))
        return 0
    if args.to == "textsurf":
        _emit({"query": to_textsurf_query(a, excerpt_checks=args.excerpt_checks)})
        return 0
    if args.file is None:
        raise ProfileError(f"--to {args.to} needs the text file (--file) for integrity values")
    c = canonicalize(_read(args.file))
    if args.to == "rfc5147":
        frag = to_rfc5147(a, c, integrity=not args.no_integrity)
        _emit({"fragment": "#" + str(frag), "query": str(frag)})
        return 0
    if args.to == "cts":
        nodes = LineNodes(c, namespace=args.namespace, work=args.work)
        sub, notes = nodes.to_subref(a, case_insensitive=not args.case_sensitive)
        _emit({"subref": sub, "urn": nodes.urn(int(sub.split("@", 1)[0]), "@" + sub.split("@", 1)[1]) if sub else None, "notes": list(notes)})
        return 0 if sub else 1
    raise ProfileError(f"unknown target {args.to}")


def cmd_import_w3c(args) -> int:
    doc = json.loads(Path(args.document).read_text(encoding="utf-8"))
    res = from_w3c(doc, canonicalize(_read(args.file)))
    _emit(res.to_dict())
    return 0 if res.agreement in ("agree", "quote_only") else 1


def cmd_import_rfc5147(args) -> int:
    a, notes = from_rfc5147(args.fragment, canonicalize(_read(args.file)))
    _emit({"anchor": a.to_dict() if a else None, "notes": list(notes)})
    return 0 if a and not notes else 1


def cmd_import_cts(args) -> int:
    nodes = LineNodes(canonicalize(_read(args.file)), namespace=args.namespace, work=args.work)
    a = nodes.from_subref(args.subref, case_insensitive=not args.case_sensitive)
    _emit(a.to_dict())
    return 0


def cmd_matrix(args) -> int:
    c = canonicalize(_read(args.file))
    s, e = _selection(args, c)
    rows = unit_matrix(c.text, s, e)
    if args.json:
        _emit([r.__dict__ for r in rows])
    else:
        _emit(render_matrix(rows, c.text[s:e]), as_json=False)
    return 0


def cmd_hashes(args) -> int:
    rows = hash_table(_read(args.file).decode("utf-8"))
    if args.json:
        _emit([r.__dict__ for r in rows])
    else:
        _emit(render_hash_table(rows), as_json=False)
    return 0


def cmd_probe(args) -> int:
    from .probe import AnnophisProbe, TextsurfProbe, load_fixtures, render_report, write_report

    fixtures = load_fixtures(Path(args.fixtures), args.only)
    if args.prepare_txt_data:
        AnnophisProbe.write_txt_data(fixtures, Path(args.prepare_txt_data), args.namespace)
        _emit({"prepared": str(Path(args.prepare_txt_data) / args.namespace), "fixtures": [f.id for f in fixtures]})
        return 0
    if args.url is None:
        raise ProfileError("--url is required unless --prepare-txt-data is used")
    if args.service == "textsurf":
        report = TextsurfProbe(args.url, prefix=args.namespace, upload=not args.no_upload).run(fixtures)
    else:
        report = AnnophisProbe(args.url, namespace=args.namespace).run(fixtures)
    if args.out:
        jpath, mpath = write_report(report, Path(args.out))
        print(render_report(report))
        print(f"written: {jpath}\nwritten: {mpath}", file=sys.stderr)
    elif args.json:
        _emit(report.to_dict())
    else:
        print(render_report(report))
    return 0 if report.summary()["error"] == 0 else 1


def cmd_fixtures(args) -> int:
    """Cross-check the fixture manifest (built by an independent script) against this library."""
    directory = Path(args.dir)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    problems: list[str] = []
    rows: list[dict] = []
    for entry in manifest["fixtures"]:
        raw = (directory / entry["file"]).read_bytes()
        c = canonicalize(raw)
        ruler = Ruler(c.text)
        row = {"id": entry["id"], "codepoints": c.codepoints, "utf8": ruler.length("utf8"), "utf16": ruler.length("utf16"), "graphemes": ruler.length("grapheme"), "sha256": c.sha256[:12]}
        rows.append(row)
        exp = entry["canonical"]
        for key, got in (("codepoints", c.codepoints), ("sha256", c.sha256), ("utf8", ruler.length("utf8")), ("utf16", ruler.length("utf16")), ("graphemes", ruler.length("grapheme"))):
            if exp[key] != got:
                problems.append(f"{entry['id']}: canonical.{key} manifest={exp[key]} library={got}")
        for sel in entry["selections"]:
            a = anchor_for_exact(c, sel["exact"])
            if [a.start, a.end] != sel["canonical"]:
                problems.append(f"{entry['id']}/{sel['exact']!r}: position manifest={sel['canonical']} library={[a.start, a.end]}")
            for unit, m in ruler.measure(a.start, a.end).items():
                want = sel["measurements"].get(unit)
                if want is None:
                    if m.on_boundary and unit == "grapheme":
                        problems.append(f"{entry['id']}/{sel['exact']!r}: manifest says no grapheme boundary, library says boundary")
                    continue
                if [m.start, m.end] != want:
                    problems.append(f"{entry['id']}/{sel['exact']!r}: {unit} manifest={want} library={[m.start, m.end]}")
    _emit({"fixtures": rows, "problems": problems, "ok": not problems})
    return 0 if not problems else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="anchorprobe", description="Stable Text Anchor profile, drift forensics and conformance probes")
    p.add_argument("--version", action="version", version=f"anchorprobe {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("canon", help="canonicalize a text and print what changed")
    s.add_argument("file")
    s.set_defaults(func=cmd_canon)

    def sel(sp):
        sp.add_argument("--start", type=int)
        sp.add_argument("--end", type=int)
        sp.add_argument("--exact")
        sp.add_argument("--occurrence", type=int, default=1)

    s = sub.add_parser("anchor", help="create an STA anchor for a selection")
    s.add_argument("file")
    sel(s)
    s.add_argument("--context", type=int, default=32)
    s.add_argument("--source")
    s.set_defaults(func=cmd_anchor)

    s = sub.add_parser("measure", help="convert offsets counted in another unit or form into an STA anchor")
    s.add_argument("file")
    s.add_argument("--start", type=int, required=True)
    s.add_argument("--end", type=int, required=True)
    s.add_argument("--unit", choices=UNITS, default="utf16")
    s.add_argument("--form", choices=("NFC", "NFD", "NFKC", "NFKD", "raw"), default="raw")
    s.add_argument("--newline", choices=("LF", "raw"), default="raw")
    s.add_argument("--bom", choices=("stripped", "kept"), default="kept")
    s.add_argument("--context", type=int, default=32)
    s.add_argument("--source")
    s.set_defaults(func=cmd_measure)

    s = sub.add_parser("verify", help="ask both witnesses of an anchor against a text")
    s.add_argument("anchor")
    s.add_argument("file")
    s.set_defaults(func=cmd_verify)

    s = sub.add_parser("diagnose", help="explain why an anchor no longer matches")
    s.add_argument("anchor")
    s.add_argument("file")
    s.set_defaults(func=cmd_diagnose)

    s = sub.add_parser("convert", help="express an anchor as W3C, RFC 5147, textsurf query or CTS subreference")
    s.add_argument("anchor")
    s.add_argument("--to", choices=("w3c", "rfc5147", "textsurf", "cts"), required=True)
    s.add_argument("--file", help="text file; needed for rfc5147 and cts")
    s.add_argument("--source")
    s.add_argument("--no-integrity", action="store_true")
    s.add_argument("--excerpt-checks", action="store_true", help="textsurf: add length and md5 of the excerpt")
    s.add_argument("--namespace", default="ns")
    s.add_argument("--work", default="work")
    s.add_argument("--case-sensitive", action="store_true")
    s.set_defaults(func=cmd_convert)

    s = sub.add_parser("import-w3c", help="resolve a W3C SpecificResource against a text")
    s.add_argument("document")
    s.add_argument("file")
    s.set_defaults(func=cmd_import_w3c)

    s = sub.add_parser("import-rfc5147", help="resolve an RFC 5147 char fragment against a text")
    s.add_argument("fragment")
    s.add_argument("file")
    s.set_defaults(func=cmd_import_rfc5147)

    s = sub.add_parser("import-cts", help="resolve a line subreference (e.g. 3@needle[2]) against a text")
    s.add_argument("subref")
    s.add_argument("file")
    s.add_argument("--namespace", default="ns")
    s.add_argument("--work", default="work")
    s.add_argument("--case-sensitive", action="store_true")
    s.set_defaults(func=cmd_import_cts)

    s = sub.add_parser("matrix", help="one selection, eight numbers")
    s.add_argument("file")
    sel(s)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_matrix)

    s = sub.add_parser("hashes", help="one paragraph, sixteen hashes")
    s.add_argument("file")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_hashes)

    s = sub.add_parser("probe", help="run conformance checks against a live text service")
    s.add_argument("service", choices=("textsurf", "annophis"))
    s.add_argument("--url")
    s.add_argument("--fixtures", default=str(FIXTURES_DIR))
    s.add_argument("--only", nargs="*")
    s.add_argument("--namespace", default="anchorprobe")
    s.add_argument("--no-upload", action="store_true", help="textsurf: fixtures are already mounted")
    s.add_argument("--prepare-txt-data", help="annophis: write fixtures into this txt_data directory and exit")
    s.add_argument("--out", help="directory for JSON and Markdown reports")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_probe)

    s = sub.add_parser("fixtures", help="cross-check the fixture manifest against the library")
    s.add_argument("--dir", default=str(FIXTURES_DIR))
    s.set_defaults(func=cmd_fixtures)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ProfileError, CanonError, BoundaryError, ValueError) as exc:
        _emit({"error": str(exc)})
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

"""Conformance probes for running text services.

A probe sends fixture texts to a service and asks concrete questions whose
answers decide whether an STA anchor can be exchanged with it without a
conversion step. Every check records the request, the observed answer, the
STA expectation and a verdict:

  agrees      the service counts or hashes as STA does
  differs     the service answers differently; the report says how
  unsupported the service has no such feature
  error       the request failed; nothing can be concluded

The checks encode the behaviour read from the services' source code (textsurf
0.7.0, annophis-text-service 0.6.2). Running the probe against a live instance
turns that reading into a measurement.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .canon import BOM, canonicalize
from .formats import LineNodes, annophis_hash
from .units import Ruler


@dataclass
class Check:
    id: str
    question: str
    expectation: str
    observed: str = ""
    verdict: str = "error"
    request: str = ""
    note: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Report:
    service: str
    base_url: str
    checks: list[Check] = field(default_factory=list)
    version: str = ""
    started: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    def add(self, check: Check) -> Check:
        self.checks.append(check)
        return check

    def to_dict(self) -> dict:
        return {"service": self.service, "base_url": self.base_url, "version": self.version, "started": self.started, "checks": [c.to_dict() for c in self.checks]}

    def summary(self) -> dict[str, int]:
        out = {"agrees": 0, "differs": 0, "unsupported": 0, "error": 0}
        for c in self.checks:
            out[c.verdict] = out.get(c.verdict, 0) + 1
        return out


def render_report(report: Report) -> str:
    s = report.summary()
    lines = [
        f"# Conformance probe: {report.service}",
        "",
        f"Base URL: `{report.base_url}` · service version: {report.version or 'unknown'} · run: {report.started}",
        "",
        f"agrees {s['agrees']} · differs {s['differs']} · unsupported {s['unsupported']} · error {s['error']}",
        "",
        "| id | question | STA expectation | observed | verdict |",
        "|---|---|---|---|---|",
    ]
    for c in report.checks:
        obs = c.observed.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {c.id} | {c.question} | {c.expectation} | {obs} | **{c.verdict}** |")
    notes = [c for c in report.checks if c.note]
    if notes:
        lines += ["", "## Notes", ""]
        for c in notes:
            lines.append(f"- **{c.id}**: {c.note}")
    lines += ["", "## Requests", ""]
    for c in report.checks:
        if c.request:
            lines.append(f"- {c.id}: `{c.request}`")
    return "\n".join(lines) + "\n"


class Fixture:
    def __init__(self, path: Path):
        self.path = path
        self.id = path.stem
        self.raw = path.read_bytes()
        self.raw_text = self.raw.decode("utf-8")
        self.canonical = canonicalize(self.raw)


def load_fixtures(directory: Path, ids: list[str] | None = None) -> list[Fixture]:
    files = sorted(p for p in directory.glob("*.txt"))
    fx = [Fixture(p) for p in files]
    if ids:
        fx = [f for f in fx if f.id in ids]
    return fx


def _client(base_url: str, timeout: float):
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("probes need httpx: pip install 'anchorprobe[probe]'") from exc
    return httpx.Client(base_url=base_url, timeout=timeout, follow_redirects=True)


# ------------------------------------------------------------------- textsurf


class TextsurfProbe:
    """Probe a textsurf instance (Text Referencing API 1 and /stat).

    The fixtures must be present on the server under `<prefix>/<id>.txt`,
    either mounted as the document root or uploaded by the probe when the
    server runs with --writable.
    """

    def __init__(self, base_url: str, *, prefix: str = "anchorprobe", upload: bool = True, timeout: float = 10.0, client: Any = None):
        self.base_url = base_url.rstrip("/")
        self.prefix = prefix.strip("/")
        self.upload = upload
        self.client = client or _client(self.base_url, timeout)

    def _path(self, fixture_id: str) -> str:
        return f"/{self.prefix}/{fixture_id}.txt"

    def run(self, fixtures: list[Fixture]) -> Report:
        report = Report("textsurf", self.base_url)
        try:
            r = self.client.get("/api-doc/openapi.json")
            if r.status_code == 200:
                report.version = str(r.json().get("info", {}).get("version", ""))
        except Exception:  # noqa: BLE001
            pass
        for fx in fixtures:
            self._probe_fixture(report, fx)
        return report

    def _get(self, path: str, params: dict | None = None):
        return self.client.get(path, params=params, headers={"Accept": "text/plain"})

    def _probe_fixture(self, report: Report, fx: Fixture) -> None:
        path = self._path(fx.id)
        if self.upload:
            try:
                r = self.client.put(path, content=fx.raw, headers={"Content-Type": "text/plain; charset=utf-8"})
                if r.status_code >= 400:
                    report.add(Check(f"{fx.id}/upload", "upload fixture", "PUT accepted", f"HTTP {r.status_code}", "error", f"PUT {path}", "server is read-only or refused; mount fixtures as document root instead"))
                    return
            except Exception as exc:  # noqa: BLE001
                report.add(Check(f"{fx.id}/upload", "upload fixture", "PUT accepted", str(exc), "error", f"PUT {path}"))
                return

        raw_ruler = Ruler(fx.raw_text)
        canon = fx.canonical

        # stat: chars and checksum
        c = report.add(Check(f"{fx.id}/stat.chars", "what does `chars` count?", f"{canon.codepoints} code points after STA-C14N", request=f"GET /stat{path}"))
        try:
            st = self._get(f"/stat{path}").json()
            chars = int(st.get("chars", -1))
            c.observed = f"{chars} (raw code points incl. BOM/CR: {raw_ruler.codepoints})"
            if chars == canon.codepoints:
                c.verdict = "agrees"
            elif chars == raw_ruler.codepoints:
                c.verdict = "differs"
                c.note = "chars counts every code point of the stored bytes; a BOM or CR is counted, RFC 5147 would exclude the BOM and fold CRLF"
            else:
                c.verdict = "differs"
            ck = report.add(Check(f"{fx.id}/stat.checksum", "what is `checksum` computed over?", f"sha256 of canonical UTF-8 = {canon.sha256[:12]}", request=f"GET /stat{path}"))
            got = str(st.get("checksum", ""))
            raw_sha = hashlib.sha256(fx.raw).hexdigest()
            ck.observed = got[:12] + ("…" if got else "")
            if got == canon.sha256:
                ck.verdict = "agrees"
            elif got == raw_sha:
                ck.verdict = "differs"
                ck.note = "checksum is SHA-256 of the file bytes as stored (textframe PositionIndex); BOM, CRLF and NFD all change it"
            else:
                ck.verdict = "differs"
                ck.note = "checksum matches neither the raw bytes nor the canonical form"
        except Exception as exc:  # noqa: BLE001
            c.observed = str(exc)

        # excerpt by canonical offsets of the middle third
        n = canon.codepoints
        s, e = n // 3, min(n, n // 3 + 12)
        exact = canon.text[s:e]
        c = report.add(Check(f"{fx.id}/char", f"does `char={s},{e}` return canonical[{s}:{e}]?", repr(exact), request=f"GET {path}?char={s},{e}"))
        try:
            r = self._get(path, {"char": f"{s},{e}"})
            got = r.text
            c.observed = repr(got)
            if got == exact:
                c.verdict = "agrees"
            elif unicodedata.normalize("NFC", got.replace("\r\n", "\n")) == exact:
                c.verdict = "differs"
                c.note = "excerpt equals the canonical text only after NFC/newline folding: the service serves the stored encoding form"
            else:
                raw_slice = fx.raw_text[s:e]
                c.verdict = "differs"
                c.note = "offsets are applied to the stored text; stored[s:e]=" + repr(raw_slice)
        except Exception as exc:  # noqa: BLE001
            c.observed = str(exc)

        # BOM handling
        if fx.raw_text.startswith(BOM):
            c = report.add(Check(f"{fx.id}/bom", "is character 0 the BOM?", "no: RFC 5147 excludes the BOM; STA strips it", request=f"GET {path}?char=0,1"))
            try:
                got = self._get(path, {"char": "0,1"}).text
                c.observed = repr(got)
                c.verdict = "differs" if got == BOM else "agrees"
                if got == BOM:
                    c.note = "position 0 is U+FEFF; every anchor against this file is shifted by one against RFC 5147 counting"
            except Exception as exc:  # noqa: BLE001
                c.observed = str(exc)

        # CRLF handling
        if "\r\n" in fx.raw_text:
            i = fx.raw_text.index("\r\n")
            c = report.add(Check(f"{fx.id}/crlf", "how many characters is CRLF?", "1 (RFC 5147 section 4.1)", request=f"GET {path}?char={i},{i + 2}"))
            try:
                got = self._get(path, {"char": f"{i},{i + 2}"}).text
                c.observed = repr(got)
                c.verdict = "differs" if got == "\r\n" else "agrees"
                if got == "\r\n":
                    c.note = "CR and LF are two code points; textsurf's own API text requires LF files, so CRLF input is outside its contract"
            except Exception as exc:  # noqa: BLE001
                c.observed = str(exc)

        # length/md5 scope: excerpt or entity?
        c = report.add(Check(f"{fx.id}/length-scope", "does `length` refer to the excerpt or the whole entity?", "entity (RFC 5147 section 3.1)", request=f"GET {path}?char={s},{e}&length=…"))
        try:
            whole = self._get(path, {"char": f"{s},{e}", "length": str(raw_ruler.codepoints)})
            part = self._get(path, {"char": f"{s},{e}", "length": str(e - s)})
            c.observed = f"length=entity -> HTTP {whole.status_code}; length=excerpt -> HTTP {part.status_code}"
            if whole.status_code == 200 and part.status_code != 200:
                c.verdict = "agrees"
            elif part.status_code == 200 and whole.status_code != 200:
                c.verdict = "differs"
                c.note = "length is checked against the returned excerpt (src/main.rs get_text); to use it as an entity check, request the whole text"
            elif whole.status_code == 200 and part.status_code == 200:
                c.verdict = "unsupported"
                c.note = "both accepted: the check is not enforced"
        except Exception as exc:  # noqa: BLE001
            c.observed = str(exc)

        # out of range: clamp (RFC) or error (STA)?
        c = report.add(Check(f"{fx.id}/range", "out-of-range end: clamp or refuse?", "refuse (STA); RFC 5147 clamps", request=f"GET {path}?char={s},{n + 1000}"))
        try:
            r = self._get(path, {"char": f"{s},{n + 1000}"})
            c.observed = f"HTTP {r.status_code}, {len(r.text)} code points returned"
            c.verdict = "agrees" if r.status_code >= 400 else "differs"
            if r.status_code < 400:
                c.note = "positions beyond the text are clamped, which RFC 5147 section 4.2 permits; an STA verifier treats this as out_of_range"
        except Exception as exc:  # noqa: BLE001
            c.observed = str(exc)


# -------------------------------------------------------------------- annophis


class AnnophisProbe:
    """Probe an annophis-text-service instance serving fixtures via `txt_data`.

    The server must have been started with `txt_data` pointing at a directory
    that contains `<namespace>/<id>.txt` for each fixture (write_txt_data()
    prepares that layout).
    """

    def __init__(self, base_url: str, *, namespace: str = "anchorprobe", timeout: float = 10.0, client: Any = None):
        self.base_url = base_url.rstrip("/")
        self.namespace = namespace
        self.client = client or _client(self.base_url, timeout)

    @staticmethod
    def write_txt_data(fixtures: list[Fixture], txt_data: Path, namespace: str = "anchorprobe") -> Path:
        target = txt_data / namespace
        target.mkdir(parents=True, exist_ok=True)
        for fx in fixtures:
            (target / f"{fx.id}.txt").write_bytes(fx.raw)
        return target

    def _urn(self, fx: Fixture, ref: str) -> str:
        return f"urn:cts:{self.namespace}:{fx.id}.txtparsed:{ref}"

    def run(self, fixtures: list[Fixture]) -> Report:
        report = Report("annophis-text-service", self.base_url)
        try:
            r = self.client.get("/cite")
            if r.status_code == 200:
                report.version = str(r.json().get("versions", {}).get("texts", ""))
        except Exception:  # noqa: BLE001
            pass
        for fx in fixtures:
            self._probe_fixture(report, fx)
        return report

    def _nodes(self, fx: Fixture, ref: str, params: dict | None = None) -> tuple[Any, list[dict]]:
        r = self.client.get(f"/texts/{self._urn(fx, ref)}", params=params)
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        return r, data.get("nodes", []) or []

    def _probe_fixture(self, report: Report, fx: Fixture) -> None:
        model = LineNodes(fx.canonical, namespace=self.namespace, work=fx.id)
        if not model.nodes:
            return
        first = model.nodes[0]
        last = model.nodes[-1]

        # numbering and skipping of empty lines
        c = report.add(Check(f"{fx.id}/nodes", "how many line nodes, and is the last one numbered consecutively?", f"{len(model.nodes)} nodes, last = {last.number}", request=f"GET /texts/{self._urn(fx, str(last.number))}"))
        try:
            r, nodes = self._nodes(fx, str(last.number))
            beyond, nodes_beyond = self._nodes(fx, str(last.number + 1))
            c.observed = f"node {last.number}: HTTP {r.status_code}, text={nodes[0]['text'][0]!r}" if nodes else f"HTTP {r.status_code}, no node"
            ok = bool(nodes) and nodes[0]["text"][0] == last.text and not nodes_beyond
            c.verdict = "agrees" if ok else "differs"
            if not ok and nodes:
                c.note = "line numbering or empty-line skipping differs from the txtindex.go model"
        except Exception as exc:  # noqa: BLE001
            c.observed = str(exc)

        # NFC storage
        c = report.add(Check(f"{fx.id}/nfc", "is the served line NFC regardless of the file's form?", repr(first.text), request=f"GET /texts/{self._urn(fx, '1')}"))
        try:
            r, nodes = self._nodes(fx, "1")
            got = nodes[0]["text"][0] if nodes else ""
            c.observed = repr(got)
            if got == first.text:
                c.verdict = "agrees"
            elif got.startswith(BOM) and got[1:] == first.text:
                c.verdict = "differs"
                c.note = "the BOM survives into line 1: Go's TrimSpace does not treat U+FEFF as space and txtindex.go does not strip it"
            else:
                c.verdict = "differs"
        except Exception as exc:  # noqa: BLE001
            c.observed = str(exc)

        # normalize=nfd is response-time only
        c = report.add(Check(f"{fx.id}/normalize", "does ?normalize=nfd change the returned text but not the node identity?", repr(unicodedata.normalize("NFD", first.text)), request=f"GET /texts/{self._urn(fx, '1')}?normalize=nfd"))
        try:
            r, nodes = self._nodes(fx, "1", {"normalize": "nfd"})
            got = nodes[0]["text"][0] if nodes else ""
            c.observed = repr(got)
            c.verdict = "agrees" if got == unicodedata.normalize("NFD", first.text) or (got.startswith(BOM) and got[1:] == unicodedata.normalize("NFD", first.text)) else "differs"
        except Exception as exc:  # noqa: BLE001
            c.observed = str(exc)

        # hash recipe
        expected = annophis_hash(first.text, algorithm="sha256")
        c = report.add(Check(f"{fx.id}/hash", "is the sha256 node hash hex(sha256(UTF-8(NFC(line))))?", expected[:12], request=f"GET /texts/hash/{self._urn(fx, '1')}?algorithm=sha256"))
        try:
            r = self.client.get(f"/texts/hash/{self._urn(fx, '1')}", params={"algorithm": "sha256"})
            hashes = r.json().get("hashes", []) if r.status_code == 200 else []
            got = hashes[0]["hash"] if hashes else ""
            c.observed = got[:12]
            if got == expected:
                c.verdict = "agrees"
            elif got == annophis_hash(BOM + first.text, algorithm="sha256"):
                c.verdict = "differs"
                c.note = "hash includes the BOM kept in line 1"
            else:
                c.verdict = "differs" if got else "unsupported"
        except Exception as exc:  # noqa: BLE001
            c.observed = str(exc)

        # anchored subreference: case-insensitive?
        word = next((w for w in first.text.split() if w.isalpha() and w.lower() != w.upper() and len(w) > 2), None)
        if word:
            flipped = word.swapcase()
            c = report.add(Check(f"{fx.id}/anchor-case", f"does @{flipped}[1] match {word!r}?", "no under a literal CTS reading; annophis matches case-insensitively", request=f"GET /texts/{self._urn(fx, '1@' + flipped + '[1]')}"))
            try:
                r, nodes = self._nodes(fx, f"1@{flipped}[1]")
                got = nodes[0]["text"][0] if nodes else ""
                c.observed = f"HTTP {r.status_code}, text={got!r}"
                c.verdict = "differs" if nodes else "agrees"
                if nodes:
                    c.note = "subreference matching is case-insensitive (findAnchorMatch); the occurrence index k counts differently than a case-sensitive reader would"
            except Exception as exc:  # noqa: BLE001
                c.observed = str(exc)

        # context counts runes, not bytes
        astral = next(((i, ch) for i, ch in enumerate(first.text) if ord(ch) > 0x7F), None)
        if astral and word:
            c = report.add(Check(f"{fx.id}/context-unit", "is `context` counted in code points?", "code points (runes)", request=f"GET /texts/{self._urn(fx, '1@' + word + '[1]')}?context=2"))
            try:
                r, nodes = self._nodes(fx, f"1@{word}[1]", {"context": "2"})
                got = nodes[0]["text"][0] if nodes else ""
                idx = first.text.find(word)
                exp = first.text[max(0, idx - 2) : idx + len(word) + 2]
                c.observed = repr(got)
                c.verdict = "agrees" if got == exp else "differs"
            except Exception as exc:  # noqa: BLE001
                c.observed = str(exc)


def write_report(report: Report, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = report.started.replace(":", "").replace("+0000", "Z")
    base = out_dir / f"{report.service}-{stamp}"
    jpath = base.with_suffix(".json")
    mpath = base.with_suffix(".md")
    jpath.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    mpath.write_text(render_report(report), encoding="utf-8")
    return jpath, mpath

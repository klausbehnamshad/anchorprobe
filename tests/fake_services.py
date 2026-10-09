"""In-memory models of textsurf 0.7.0 and annophis-text-service 0.6.2.

Each model implements the behaviour read from the services' source code. The
probes are tested against these models offline; the live CI job runs the same
probes against the real binaries. Where the two disagree, the model, not the
binary, is wrong, and the report says so.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from urllib.parse import parse_qs, unquote

import httpx


class FakeTextsurf:
    """textsurf: code points of the stored bytes, raw SHA-256, excerpt-scoped length/md5, clamping."""

    def __init__(self, writable: bool = True):
        self.store: dict[str, bytes] = {}
        self.writable = writable

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = unquote(request.url.path)
        q = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        if path == "/api-doc/openapi.json":
            return httpx.Response(200, json={"info": {"version": "0.7.0-model"}})
        if request.method == "PUT":
            if not self.writable:
                return httpx.Response(403, json={"name": "PermissionDenied"})
            self.store[path] = request.content
            return httpx.Response(201)
        if path.startswith("/stat/"):
            key = path[len("/stat") :]
            if key not in self.store:
                return httpx.Response(404, json={"name": "NotFound"})
            text = self.store[key].decode("utf-8")
            return httpx.Response(200, json={"chars": len(text), "bytes": len(self.store[key]), "checksum": hashlib.sha256(self.store[key]).hexdigest(), "mtime": 0})
        if request.method == "GET":
            if path not in self.store:
                return httpx.Response(404, json={"name": "NotFound"})
            text = self.store[path].decode("utf-8")
            begin, end = 0, 0
            if "char" in q:
                a, _, b = q["char"].partition(",")
                begin, end = int(a or 0), int(b) if b else 0
            elif "begin" in q or "end" in q:
                begin, end = int(q.get("begin", 0)), int(q.get("end", 0))
            n = len(text)
            if begin < 0:
                begin = n + begin
            if end <= 0:
                end = n + end
            begin, end = min(max(begin, 0), n), min(max(end, 0), n)  # textframe clamps like RFC 5147
            excerpt = text[begin:end]
            if "length" in q and len(excerpt) != int(q["length"]):
                return httpx.Response(403, json={"name": "PermissionDenied", "message": "length check failed"})
            if "md5" in q and hashlib.md5(excerpt.encode()).hexdigest() != q["md5"].lower():
                return httpx.Response(403, json={"name": "PermissionDenied", "message": "md5 check failed"})
            return httpx.Response(200, content=excerpt.encode("utf-8"), headers={"content-type": "text/plain; charset=utf-8"})
        return httpx.Response(405)


class FakeAnnophis:
    """annophis-text-service plain-text ingestion: NFC lines, blank lines skipped, case-insensitive anchors, NFC hashes."""

    def __init__(self, txt_data: dict[str, dict[str, bytes]]):
        # {namespace: {work: raw bytes}}
        self.works: dict[tuple[str, str], list[str]] = {}
        for ns, works in txt_data.items():
            for work, raw in works.items():
                lines = []
                for raw_line in raw.decode("utf-8").split("\n"):
                    line = raw_line.rstrip("\r")
                    if _go_trim_space(line) == "":
                        continue
                    lines.append(unicodedata.normalize("NFC", line))
                self.works[(ns, work)] = lines

    def _resolve(self, urn: str) -> tuple[list[str], list[str], str, str, int, str | None, int] | None:
        m = re.match(r"^urn:cts:(?P<ns>[^:]+):(?P<work>.+?)\.txtparsed:(?P<ref>\d+)(?:@(?P<needle>.+?)(?:\[(?P<k>\d+)\])?)?$", urn)
        if not m:
            return None
        lines = self.works.get((m.group("ns"), m.group("work")))
        if lines is None:
            return None
        return lines, [], m.group("ns"), m.group("work"), int(m.group("ref")), m.group("needle"), int(m.group("k") or 1)

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = unquote(request.url.path)
        q = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        if path == "/cite":
            return httpx.Response(200, json={"status": "Success", "service": "/cite", "versions": {"texts": "0.6.2-model"}})
        is_hash = path.startswith("/texts/hash/")
        urn = path[len("/texts/hash/") :] if is_hash else path[len("/texts/") :]
        resolved = self._resolve(urn)
        if not resolved:
            return httpx.Response(404, json={"requestUrn": [urn], "status": "Exception", "service": "/texts", "message": "Not found."})
        lines, _, ns, work, ref, needle, k = resolved
        if ref < 1 or ref > len(lines):
            return httpx.Response(404, json={"requestUrn": [urn], "status": "Exception", "service": "/texts", "message": f"Node {ref} not found."})
        text = lines[ref - 1]
        complete = True
        if needle:
            needle = unicodedata.normalize("NFC", needle)
            hay, nd = text.lower(), needle.lower()
            hits, pos = [], hay.find(nd)
            while pos >= 0:
                hits.append(pos)
                pos = hay.find(nd, pos + len(nd))
            if k > len(hits):
                return httpx.Response(404, json={"requestUrn": [urn], "status": "Exception", "service": "/texts", "message": f'Substring "{needle}" (occurrence {k}) not found.'})
            start = hits[k - 1]
            end = start + len(needle)
            ctx = int(q.get("context", 0))
            s, e = max(0, start - ctx), min(len(text), end + ctx)
            text = text[s:e]
            complete = s == 0 and e == len(lines[ref - 1])
        mode = q.get("normalize", "nfc")
        if mode not in ("nfc", "nfd", "nfkc", "nfkd", "strip"):
            return httpx.Response(400, json={"status": "Exception", "message": "Unsupported normalize value."})
        if mode in ("nfd", "nfkc", "nfkd"):
            text = unicodedata.normalize(mode.upper(), text)
        node_urn = f"urn:cts:{ns}:{work}.txtparsed:{ref}"
        if is_hash:
            algo = q.get("algorithm", "sha1")
            data = text.encode("utf-8")
            digest = hashlib.sha256(data).hexdigest() if algo == "sha256" else hashlib.sha1(data).hexdigest()
            return httpx.Response(200, json={"requestUrn": [urn], "status": "Success", "service": "/texts/hash", "algorithm": algo, "hashes": [{"urn": node_urn, "hash": digest}]})
        node = {"urn": [node_urn], "text": [text], "sequence": ref, "complete": complete}
        return httpx.Response(200, json={"requestUrn": [urn], "status": "Success", "service": "/texts", "nodes": [node]})


def _go_trim_space(s: str) -> str:
    return s.strip(" \t\n\v\f\r\u0085                 　")


def client_for(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://model.local")


def pretty(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)

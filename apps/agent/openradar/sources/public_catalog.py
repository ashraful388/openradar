from __future__ import annotations
from dataclasses import dataclass, field
from html.parser import HTMLParser
import re
import time
from urllib.parse import unquote, urljoin

import httpx

URLS = {
    "p_groq": "https://console.groq.com/docs/rate-limits",
    "p_tokenrouter": "https://www.tokenrouter.com/models",
    "p_tabitoken": "https://tabitoken.com/models",
}
MAX_BYTES = 2_000_000
HEADERS = ["MODEL ID", "RPM", "RPD", "TPM", "TPD", "ASH", "ASD"]
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]*(?:/[A-Za-z0-9][A-Za-z0-9_.:-]*)*")
_LIMIT = re.compile(r"(?:-|[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?[KM]?)")
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


@dataclass
class CatalogRow:
    model_id: str
    free_limit: str = ""


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str | None] = field(default_factory=dict)
    parts: list[_Node | str] = field(default_factory=list)
    parent: _Node | None = field(default=None, repr=False)

    def find(self, tag: str, *, include_noscript: bool = False) -> list[_Node]:
        found = []
        excluded = {"script", "style", "template"}
        if not include_noscript:
            excluded.add("noscript")
        for part in self.parts:
            if isinstance(part, _Node) and part.tag not in excluded:
                if part.tag == tag:
                    found.append(part)
                found.extend(part.find(tag, include_noscript=include_noscript))
        return found

    def text(self) -> str:
        return " ".join("".join(
            part if isinstance(part, str) else part.text()
            for part in self.parts
            if isinstance(part, str) or part.tag not in {"script", "style", "svg", "template"}
        ).split())


class _Document(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("")
        self.current = self.root
        self.invalid = False

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, dict(attrs), parent=self.current)
        self.current.parts.append(node)
        if len(dict(attrs)) != len(attrs):
            self.invalid = True
        if tag not in _VOID:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.current.tag != tag:
            self.invalid = True
            return
        self.current = self.current.parent or self.root

    def handle_data(self, data):
        self.current.parts.append(data)


def _document(html: str) -> _Node:
    if len(html.encode("utf-8")) > MAX_BYTES:
        raise ValueError("public catalog exceeds size limit")
    parser = _Document()
    parser.feed(html)
    parser.close()
    if parser.invalid or parser.current is not parser.root:
        raise ValueError("invalid public catalog HTML")
    return parser.root


def parse_groq(html: str) -> list[CatalogRow]:
    root = _document(html)
    candidates = []
    for table in root.find("table"):
        buttons = table.find("button")
        if [b.text() for b in buttons] == ["Free Plan Limits", "Developer Plan Limits"]:
            candidates.append(table)
    if len(candidates) != 1:
        raise ValueError("missing or ambiguous Groq plan controls")
    header = candidates[0]
    free, developer = header.find("button")
    free_classes = (free.attrs.get("class") or "").split()
    developer_classes = (developer.attrs.get("class") or "").split()
    if not {"happy", "bg-black"}.issubset(free_classes) or {"happy", "bg-black"}.intersection(developer_classes):
        raise ValueError("Groq free plan is not selected")
    header_rows = header.find("tr")
    if len(header_rows) != 2 or [c.text() for c in header_rows[1].find("th")] != HEADERS:
        raise ValueError("unrecognized Groq rate limit columns")
    container = header.parent
    while container is not None and len(container.find("table")) < 2:
        container = container.parent
    tables = container.find("table") if container else []
    if (container is None or container.tag != "div"
            or "w-full" not in (container.attrs.get("class") or "").split()
            or len(tables) != 2 or tables[0] is not header or tables[1].find("th")):
        raise ValueError("unrecognized Groq free plan table scope")
    body = tables[1]
    if len(body.find("tbody")) != 1:
        raise ValueError("missing Groq free plan body")
    result = []
    seen = set()
    for row in body.find("tr"):
        nodes = row.find("td")
        cells = [c.text() for c in nodes]
        if any(c.attrs.get("colspan", "1") != "1" or c.attrs.get("rowspan", "1") != "1" for c in nodes):
            raise ValueError("unrecognized Groq model cell span")
        if len(cells) != 7 or not _MODEL_ID.fullmatch(cells[0]):
            raise ValueError("invalid Groq model row")
        if any(not _LIMIT.fullmatch(value) for value in cells[1:]):
            raise ValueError("invalid Groq rate limit")
        mid = cells[0]
        if mid.casefold() in seen:
            raise ValueError("duplicate Groq model row")
        seen.add(mid.casefold())
        limits = ", ".join(f"{name}: {value}" for name, value in zip(HEADERS[1:], cells[1:]))
        capacities = [float(value.replace(",", "").rstrip("KM")) for value in cells[1:] if value != "-"]
        available = bool(capacities) and all(value > 0 for value in capacities)
        result.append(CatalogRow(mid, f"Groq Free Plan Limits ({limits})" if available else ""))
    if not result:
        raise ValueError("empty Groq free plan table")
    return result


def parse_tokenrouter(html: str) -> list[CatalogRow]:
    root = _document(html)
    grids = [node for node in root.find("ul", include_noscript=True)
             if "tr-seo-grid" in (node.attrs.get("class") or "").split()]
    if len(grids) != 1:
        raise ValueError("missing TokenRouter public catalog")
    result = {}
    cards = grids[0].find("li")
    for card in cards:
        if "tr-seo-card" not in (card.attrs.get("class") or "").split():
            raise ValueError("unrecognized TokenRouter model card")
        headings = card.find("h2")
        links = headings[0].find("a") if len(headings) == 1 else []
        if len(links) != 1:
            raise ValueError("missing TokenRouter model link")
        link = links[0]
        href = link.attrs.get("href") or ""
        if not href.startswith("/models/") or not href.endswith("/"):
            raise ValueError("invalid TokenRouter model link")
        mid = unquote(href[len("/models/"):-1])
        if not _MODEL_ID.fullmatch(mid) or link.text() != mid or any(segment in {".", ".."} for segment in mid.split("/")):
            raise ValueError("invalid TokenRouter model id")
        result[mid.casefold()] = CatalogRow(mid)
    if not result:
        raise ValueError("empty TokenRouter public catalog")
    return list(result.values())


def fetch(provider_id: str, timeout: float = 15.0) -> list[CatalogRow]:
    url = URLS[provider_id]
    deadline = time.monotonic() + min(max(timeout, 0.1), 20.0)
    for attempt in range(2):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("public catalog timed out")
        with httpx.stream("GET", url, timeout=min(remaining, 10.0), follow_redirects=False,
                          trust_env=False, headers={"Accept": "text/html"}) as response:
            if response.status_code in {301, 302, 307, 308}:
                target = urljoin(url, response.headers.get("location", ""))
                if attempt == 0 and provider_id == "p_tokenrouter" and target == URLS[provider_id] + "/":
                    url = target
                    continue
                raise ValueError("public catalog redirect is not allowlisted")
            response.raise_for_status()
            if response.status_code != 200 or response.headers.get("content-type", "").split(";")[0].strip().lower() != "text/html":
                raise ValueError("public catalog did not return HTML")
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > MAX_BYTES or time.monotonic() > deadline:
                    raise ValueError("public catalog response exceeded limits")
            html = content.decode("utf-8", errors="strict")
        if provider_id == "p_groq":
            return parse_groq(html)
        if provider_id == "p_tokenrouter":
            return parse_tokenrouter(html)
        raise ValueError("no supported server-rendered public catalog")
    raise ValueError("public catalog redirect limit exceeded")

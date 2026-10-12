"""HTML → text with stable block structure (selectolax primary, BeautifulSoup fallback)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode as Node

_DROP = "script, style, noscript, template, svg, iframe"
_BLOCK = {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "header", "footer",
          "dt", "dd", "table", "ul", "ol", "br", "caption", "main", "nav", "aside", "summary", "details",
          "button", "label", "form", "figure", "figcaption", "blockquote"}
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.IGNORECASE)


def _is_hidden(node: Node) -> bool:
    a = node.attributes
    return ("hidden" in a or a.get("aria-hidden") == "true" or bool(_HIDDEN_STYLE.search(a.get("style") or "")))


@dataclass
class PageDoc:
    html: str
    tree: HTMLParser
    text: str  # visible text, one block per line
    hidden_text: str  # text of hidden elements (kept for classifier signals only)
    title: str = ""
    h1: list[str] = field(default_factory=list)

    def select(self, css: str) -> list[Node]:
        try:
            return self.tree.css(css)
        except Exception:  # invalid selector in rules → treat as no match
            return []

    def node_text(self, node: Node) -> str:
        return render_text(node)


def render_text(node: Node) -> str:
    parts: list[str] = []

    def walk(n: Node) -> None:
        if n.tag in {"script", "style", "noscript", "template", "svg", "iframe"} or _is_hidden(n):
            return
        if n.tag == "-text":
            parts.append(n.text_content or "")
            return
        block = n.tag in _BLOCK
        if block:
            parts.append("\n")
        child = n.child
        while child is not None:
            walk(child)
            child = child.next
        if n.tag in {"td", "th"}:
            parts.append(" \t ")
        if block:
            parts.append("\n")

    walk(node)
    text = "".join(parts).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def parse_html(html: str) -> PageDoc:
    tree = HTMLParser(html)
    title = tree.css_first("title")
    hidden_parts: list[str] = []
    for n in tree.css("[hidden], [aria-hidden=true], [style]"):
        if _is_hidden(n):
            hidden_parts.append(n.text(separator=" ", strip=True))
    body = tree.body or tree.root
    text = render_text(body) if body is not None else ""
    h1s = [render_text(h).replace("\n", " ") for h in tree.css("h1") if not _is_hidden(h)]
    return PageDoc(html=html, tree=tree, text=text, hidden_text=" ".join(hidden_parts),
                   title=(title.text(strip=True) if title else ""), h1=[h for h in h1s if h])


def table_rows(doc: PageDoc, css: str = "table tr") -> list[tuple[str, str]]:
    """(label, value) pairs from 2-column table rows, th/td or td/td, plus dl/dt/dd pairs."""
    rows: list[tuple[str, str]] = []
    for tr in doc.select(css):
        cells = [c for c in tr.iter() if c.tag in {"th", "td"}]
        if len(cells) >= 2:
            rows.append((render_text(cells[0]).replace("\n", " "), render_text(cells[1]).replace("\n", " ")))
    for dl in doc.select("dl"):
        dts = dl.css("dt")
        dds = dl.css("dd")
        for dt, dd in zip(dts, dds, strict=False):
            rows.append((render_text(dt).replace("\n", " "), render_text(dd).replace("\n", " ")))
    return rows

"""HTML → text with stable block structure (selectolax primary, BeautifulSoup fallback)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode as Node

_DROP = "script, style, noscript, template, svg, iframe"
_BLOCK = {
    "p",
    "div",
    "li",
    "tr",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "section",
    "article",
    "header",
    "footer",
    "dt",
    "dd",
    "table",
    "ul",
    "ol",
    "br",
    "caption",
    "main",
    "nav",
    "aside",
    "summary",
    "details",
    "button",
    "label",
    "form",
    "figure",
    "figcaption",
    "blockquote",
}
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.IGNORECASE)
# Struck-out values (a previous offer amount shown crossed out) and screen-reader-only labels ("Opens in a new
# window", "Strike through") are not part of what the page currently states, so they are kept out of the text.
_STRUCK_TAGS = {"s", "del", "strike"}
_NON_VISUAL_CLASS = re.compile(
    r"(?:^|\s)(?:strike-?through|visually-hidden|sr-only|screen-reader-only)(?:\s|$)", re.IGNORECASE
)
_MARKS = {"SM": "\u2120", "TM": "\u2122"}  # <sup>SM</sup> → ℠, <sup>TM</sup> → ™


def _is_hidden(node: Node, expandable: frozenset[str] = frozenset()) -> bool:
    a = node.attributes
    if node.tag in _STRUCK_TAGS or _NON_VISUAL_CLASS.search(a.get("class") or ""):
        return True
    if _is_panel(node, expandable):
        # A collapsed accordion / disclosure panel (FAQ answers, "Rates & Fees" sections): the page states it and a
        # visitor opens it with one click, so it is page content (spot-check round 2, E).
        return False
    return "hidden" in a or a.get("aria-hidden") == "true" or bool(_HIDDEN_STYLE.search(a.get("style") or ""))


def _is_panel(node: Node, expandable: frozenset[str]) -> bool:
    a = node.attributes
    return bool(
        (a.get("id") and a.get("id") in expandable)
        or (a.get("role") == "region" and a.get("aria-labelledby"))
    )


def expandable_ids(tree: HTMLParser) -> frozenset[str]:
    """Ids of panels opened by a disclosure control (``aria-controls`` + ``aria-expanded``, the WAI accordion
    pattern). Tabs (``role="tab"``) are excluded: a hidden tab panel can belong to another product."""
    out: set[str] = set()
    for n in tree.css("[aria-controls][aria-expanded]"):
        if n.attributes.get("role") == "tab":
            continue
        for i in (n.attributes.get("aria-controls") or "").split():
            out.add(i)
    return frozenset(out)


@dataclass
class PageDoc:
    html: str
    tree: HTMLParser
    text: str  # visible text, one block per line
    hidden_text: str  # text of hidden elements (kept for classifier signals only)
    title: str = ""
    h1: list[str] = field(default_factory=list)
    expandable: frozenset[str] = frozenset()

    def select(self, css: str) -> list[Node]:
        try:
            return self.tree.css(css)
        except Exception:  # invalid selector in rules → treat as no match
            return []

    def node_text(self, node: Node) -> str:
        return render_text(node, self.expandable)


def render_text(node: Node, expandable: frozenset[str] = frozenset()) -> str:
    parts: list[str] = []

    def walk(n: Node) -> None:
        if n.tag in {"script", "style", "noscript", "template", "svg", "iframe"} or _is_hidden(n, expandable):
            return
        if n.tag == "-text":
            parts.append(n.text_content or "")
            return
        if n.tag == "sup" and (mark := _MARKS.get((n.text(deep=True) or "").strip())):
            parts.append(mark)
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


def parse_html(html: str, expandable_extra: frozenset[str] = frozenset()) -> PageDoc:
    tree = HTMLParser(html)
    title = tree.css_first("title")
    hidden_parts: list[str] = []
    expandable = expandable_ids(tree) | expandable_extra
    for n in tree.css("[hidden], [aria-hidden=true], [style]"):
        if _is_hidden(n, expandable):
            hidden_parts.append(n.text(separator=" ", strip=True))
    body = tree.body or tree.root
    text = render_text(body, expandable) if body is not None else ""
    h1s = [
        render_text(h, expandable).replace("\n", " ") for h in tree.css("h1") if not _is_hidden(h, expandable)
    ]
    return PageDoc(
        html=html,
        tree=tree,
        text=text,
        hidden_text=" ".join(hidden_parts),
        title=(title.text(strip=True) if title else ""),
        h1=[h for h in h1s if h],
        expandable=expandable,
    )


def scoped(doc: PageDoc, css: str, exclude: str | None = None) -> PageDoc:
    """A PageDoc over only the nodes matching ``css`` (e.g. ``main``) minus those matching ``exclude``, so site
    navigation, category tag clouds and cross-sell blocks stay out of extraction. Falls back to the whole page when
    nothing matches. The scoped text is a subset of the full page text, so provenance spans still resolve against
    the snapshot."""
    nodes = doc.select(css)
    if not nodes:
        return doc
    tree = HTMLParser("<html><body>" + "".join(n.html or "" for n in nodes) + "</body></html>")
    if exclude:
        for n in tree.css(exclude):
            n.decompose()
    sub = parse_html(tree.html or "", doc.expandable)
    sub.title = doc.title
    return sub


def table_rows(doc: PageDoc, css: str = "table tr") -> list[tuple[str, str]]:
    """(label, value) pairs from 2-column table rows, th/td or td/td, plus dl/dt/dd pairs."""
    rows: list[tuple[str, str]] = []
    for tr in doc.select(css):
        cells = [c for c in tr.iter() if c.tag in {"th", "td"}]
        if len(cells) >= 2:
            rows.append(
                (
                    render_text(cells[0], doc.expandable).replace("\n", " "),
                    render_text(cells[1], doc.expandable).replace("\n", " "),
                )
            )
    for dl in doc.select("dl"):
        dts = dl.css("dt")
        dds = dl.css("dd")
        for dt, dd in zip(dts, dds, strict=False):
            rows.append(
                (
                    render_text(dt, doc.expandable).replace("\n", " "),
                    render_text(dd, doc.expandable).replace("\n", " "),
                )
            )
    return rows

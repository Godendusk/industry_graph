"""Text cleanup and paragraph splitting helpers for external RAG materials."""

from __future__ import annotations

import hashlib
import html
import re
from typing import Dict, Iterable, List

from bs4 import BeautifulSoup, NavigableString, Tag


MIN_PARAGRAPH_LEN = 100

_BLOCK_TAGS = [
    "p",
    "li",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "blockquote",
]


def normalize_text(text: object) -> str:
    if text is None:
        return ""
    value = html.unescape(str(text))
    value = value.replace("\u00a0", " ").replace("\u3000", " ")
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _dedupe_preserve_order(items: Iterable[str]) -> List[str]:
    seen = set()
    results: List[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        results.append(item)
    return results


def split_plain_paragraphs(text: object, min_len: int = MIN_PARAGRAPH_LEN) -> List[str]:
    value = normalize_text(text)
    if not value:
        return []

    parts = re.split(r"\n\s*\n|\r\n|\r|\n", value)
    paragraphs = [normalize_text(part) for part in parts]
    paragraphs = [part for part in paragraphs if len(part) >= min_len]

    if not paragraphs and len(value) >= min_len:
        return [value]
    return paragraphs


def html_to_paragraphs(raw_html: object, min_len: int = MIN_PARAGRAPH_LEN) -> List[str]:
    value = normalize_text(raw_html)
    if not value:
        return []

    if "<" not in value or ">" not in value:
        return split_plain_paragraphs(value, min_len=min_len)

    soup = BeautifulSoup(value, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    block_nodes = soup.find_all(_BLOCK_TAGS)
    if not block_nodes:
        block_nodes = soup.find_all(["div", "section", "article"])

    if block_nodes:
        paragraphs = [
            normalize_text(node.get_text(" ", strip=True))
            for node in block_nodes
        ]
    else:
        for br in soup.find_all("br"):
            br.replace_with("\n")
        paragraphs = split_plain_paragraphs(soup.get_text("\n", strip=True), min_len=min_len)

    paragraphs = [
        paragraph
        for paragraph in _dedupe_preserve_order(paragraphs)
        if len(paragraph) >= min_len
    ]

    if not paragraphs:
        fallback = normalize_text(soup.get_text("\n", strip=True))
        if len(fallback) >= min_len:
            return [fallback]
    return paragraphs


def _table_blocks(table: object) -> List[Dict[str, object]]:
    blocks: List[Dict[str, object]] = []
    caption = table.find("caption", recursive=False)
    caption_text = normalize_text(caption.get_text(" ", strip=True)) if caption else ""
    if caption_text:
        blocks.append({"kind": "paragraph", "text": caption_text})

    rows = [row for row in table.find_all("tr") if row.find_parent("table") is table]
    if not rows:
        return blocks

    header_row_index = next(
        (index for index, row in enumerate(rows) if row.find_all("th", recursive=False)),
        None,
    )
    if header_row_index is None:
        return blocks

    header_cells = rows[header_row_index].find_all(["th", "td"], recursive=False)
    headers = [normalize_text(cell.get_text(" ", strip=True)) for cell in header_cells]
    if not any(headers):
        return blocks

    for row in rows[header_row_index + 1 :]:
        cells = row.find_all(["th", "td"], recursive=False)
        values = [normalize_text(cell.get_text(" ", strip=True)) for cell in cells]
        pairs = [
            f"{header}：{value}"
            for header, value in zip(headers, values)
            if header and value
        ]
        if pairs:
            blocks.append({"kind": "table", "text": "；".join(pairs) + "。"})
    return blocks


_STRUCTURED_TAGS = set(_BLOCK_TAGS) | {"table"}
_CONTAINER_TAGS = {
    "[document]",
    "html",
    "body",
    "main",
    "div",
    "section",
    "article",
    "header",
    "footer",
    "aside",
    "nav",
    "ul",
    "ol",
}


def _append_structured_text(
    blocks: List[Dict[str, object]], kind: str, fragments: List[str]
) -> None:
    text = normalize_text("".join(fragments))
    if text:
        blocks.append({"kind": kind, "text": text})


def _walk_structured_children(
    parent: object,
    blocks: List[Dict[str, object]],
    default_kind: str = "paragraph",
) -> None:
    """Walk visible content once, flushing direct text around structural children."""
    fragments: List[str] = []

    def flush() -> None:
        nonlocal fragments
        _append_structured_text(blocks, default_kind, fragments)
        fragments = []

    for child in parent.children:
        if isinstance(child, NavigableString):
            fragments.append(str(child))
            continue
        if not isinstance(child, Tag):
            continue

        name = child.name.lower()
        if name == "table":
            flush()
            blocks.extend(_table_blocks(child))
        elif name in _BLOCK_TAGS and name.startswith("h"):
            flush()
            text = normalize_text(child.get_text(" ", strip=True))
            if text:
                blocks.append(
                    {"kind": "heading", "text": text, "level": int(name[1])}
                )
        elif name == "p":
            flush()
            _walk_structured_children(child, blocks, default_kind)
        elif name == "li":
            flush()
            _walk_structured_children(child, blocks, "list_item")
        elif name == "blockquote":
            flush()
            _walk_structured_children(child, blocks, "blockquote")
        elif name in _CONTAINER_TAGS or child.find(list(_STRUCTURED_TAGS)) is not None:
            flush()
            _walk_structured_children(child, blocks, default_kind)
        else:
            fragments.append(child.get_text("", strip=False))
    flush()


def html_to_structured_blocks(raw_html: object) -> List[Dict[str, object]]:
    """Extract ordered headings, text blocks, and header-bound HTML table rows."""
    value = normalize_text(raw_html)
    if not value:
        return []
    if "<" not in value or ">" not in value:
        return [
            {"kind": "paragraph", "text": paragraph}
            for paragraph in split_plain_paragraphs(value, min_len=1)
        ]

    soup = BeautifulSoup(value, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    blocks: List[Dict[str, object]] = []
    _walk_structured_children(soup, blocks)
    return blocks


def content_hash(paragraphs: Iterable[str]) -> str:
    joined = "\n".join(paragraphs)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def normalized_title(title: object) -> str:
    return normalize_text(title)

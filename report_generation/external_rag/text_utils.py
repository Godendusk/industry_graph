"""Text cleanup and paragraph splitting helpers for external RAG materials."""

from __future__ import annotations

import hashlib
import html
import re
from typing import Dict, Iterable, List

from bs4 import BeautifulSoup


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


def _text_without_nested_blocks(
    node: object, excluded_tags: Iterable[str] = _BLOCK_TAGS + ["table"]
) -> str:
    """Return a block's own text while leaving nested blocks for later emission."""
    excluded = set(excluded_tags)
    parts: List[str] = []
    for descendant in node.descendants:
        if getattr(descendant, "name", None) is not None:
            continue
        parent = descendant.parent
        nested = False
        while parent is not None and parent is not node:
            if parent.name in excluded:
                nested = True
                break
            parent = parent.parent
        if not nested:
            parts.append(str(descendant))
    return normalize_text(" ".join(parts))


def _table_blocks(table: object) -> List[Dict[str, object]]:
    rows = [row for row in table.find_all("tr") if row.find_parent("table") is table]
    if not rows:
        return []

    header_row_index = next(
        (index for index, row in enumerate(rows) if row.find_all("th", recursive=False)),
        None,
    )
    if header_row_index is None:
        return []

    header_cells = rows[header_row_index].find_all(["th", "td"], recursive=False)
    headers = [normalize_text(cell.get_text(" ", strip=True)) for cell in header_cells]
    if not any(headers):
        return []

    blocks: List[Dict[str, object]] = []
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
    selected_tags = set(_BLOCK_TAGS) | {"table"}
    kind_by_tag = {"p": "paragraph", "li": "list_item", "blockquote": "blockquote"}
    for node in soup.find_all(list(selected_tags)):
        if node.name != "table" and node.find_parent("table") is not None:
            continue
        selected_parent = node.find_parent(list(selected_tags))
        if selected_parent is not None and selected_parent.name != "li":
            continue
        if node.name == "table":
            if node.find_parent("table") is None:
                blocks.extend(_table_blocks(node))
            continue

        text = _text_without_nested_blocks(
            node,
            excluded_tags=("blockquote", "table")
            if node.name == "blockquote"
            else _BLOCK_TAGS + ["table"],
        )
        if not text:
            continue
        if node.name.startswith("h"):
            blocks.append({"kind": "heading", "text": text, "level": int(node.name[1])})
        else:
            blocks.append({"kind": kind_by_tag[node.name], "text": text})
    return blocks


def content_hash(paragraphs: Iterable[str]) -> str:
    joined = "\n".join(paragraphs)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def normalized_title(title: object) -> str:
    return normalize_text(title)

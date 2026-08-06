"""Text cleanup and paragraph splitting helpers for external RAG materials."""

from __future__ import annotations

import hashlib
import html
import re
from typing import Iterable, List

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


def content_hash(paragraphs: Iterable[str]) -> str:
    joined = "\n".join(paragraphs)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def normalized_title(title: object) -> str:
    return normalize_text(title)

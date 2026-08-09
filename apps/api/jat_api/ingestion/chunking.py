"""Deterministic, dependency-free text chunking for retrieval indexing.

Paragraphs are preferred boundaries; oversized paragraphs wrap on whitespace.
Adjacent chunks share a sliding character overlap so sentences split across
boundaries remain retrievable from at least one side.
"""

from __future__ import annotations

import re

from jat_api.ingestion.extraction import IngestionError
from jat_api.ingestion.policy import MAX_CHUNKS

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


def _wrap_long_paragraph(paragraph: str, max_chars: int, overlap: int) -> list[str]:
    pieces: list[str] = []
    position = 0
    length = len(paragraph)
    while position < length:
        end = min(position + max_chars, length)
        if end < length:
            window = paragraph[position:end]
            split_at = window.rfind(" ")
            if split_at > max_chars // 2:
                end = position + split_at + 1
        pieces.append(paragraph[position:end].strip())
        if end >= length:
            break
        position = max(end - overlap, position + 1)
    return [piece for piece in pieces if piece]


def chunk_text(text: str, max_chars: int = 1000, overlap: int = 200) -> list[str]:
    """Split text into bounded overlapping chunks; always deterministic."""
    if overlap >= max_chars:
        raise ValueError("Chunk overlap must be smaller than the chunk size")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise IngestionError("Document contains no extractable text")

    chunks: list[str] = []
    current = ""
    for paragraph in _PARAGRAPH_BREAK.split(normalized):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        segments = (
            [paragraph]
            if len(paragraph) <= max_chars
            else _wrap_long_paragraph(paragraph, max_chars, overlap)
        )
        for segment in segments:
            candidate = f"{current}\n\n{segment}".strip() if current else segment
            if current and len(candidate) > max_chars:
                chunks.append(current)
                tail = current[-overlap:] if overlap else ""
                glued = f"{tail}{segment}"
                current = glued if len(glued) <= max_chars else segment
            else:
                current = candidate
    if current:
        chunks.append(current)

    if len(chunks) > MAX_CHUNKS:
        raise IngestionError(f"Document exceeds the {MAX_CHUNKS}-chunk ingestion limit")
    return chunks

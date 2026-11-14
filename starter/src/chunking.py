"""Implement fixed-size and structure-aware chunking."""
import hashlib
import re

from .ingestion import ARTICLE, CHAPTER, SECTION, is_heading_line
from .models import Chunk, DocumentPage

SENTENCE_BREAK = re.compile(r"(?<=[.;:])\s+")


def _page_metadata(page: DocumentPage) -> dict:
    return {k: v for k, v in page.metadata.items() if k != "paragraphs"}


def _paragraph_offsets(page: DocumentPage) -> list[tuple[int, int, dict]]:
    """(start, end, paragraph) offsets inside page.text, which joins paragraphs with '\\n'."""
    offsets, cursor = [], 0
    for para in page.metadata["paragraphs"]:
        end = cursor + len(para["text"])
        offsets.append((cursor, end, para))
        cursor = end + 1
    return offsets


def _make_chunk(page: DocumentPage, strategy: str, index: int, text: str,
                start: int, paragraphs: list[dict]) -> Chunk:
    articles = sorted({p["article"] for p in paragraphs if p["article"] is not None})
    # A chunk opening with "Chương I" belongs to the first article it introduces.
    first = next((p for p in paragraphs if p["article"] is not None), paragraphs[0])
    return Chunk(
        chunk_id=f"{page.document_id}:p{page.page:03d}:{strategy}:{index:03d}",
        document_id=page.document_id,
        source=page.source,
        page=page.page,
        text=text,
        metadata={
            **_page_metadata(page),
            "chapter": first["chapter"],
            "section": first["section"],
            "article": first["article"],
            "article_title": first["article_title"],
            "articles": articles,
            "char_start": start,
            "char_end": start + len(text),
            "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
        },
    )


def fixed_size(page: DocumentPage, size: int, overlap: int) -> list[Chunk]:
    """Split page text into overlapping character windows, ignoring structure."""
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")
    offsets = _paragraph_offsets(page)
    chunks, start, index = [], 0, 0
    while start < len(page.text):
        end = min(start + size, len(page.text))
        text = page.text[start:end].strip()
        if text:
            covered = [p for s, e, p in offsets if s < end and e > start] or [offsets[-1][2]]
            chunks.append(_make_chunk(page, "fixed", index, text, start, covered))
            index += 1
        if end == len(page.text):
            break
        start = end - overlap
    return chunks


def _split_long(text: str, max_size: int) -> list[str]:
    """Split an oversized paragraph at sentence/clause boundaries, hard-cutting only as a last resort."""
    pieces, current = [], ""
    for sentence in SENTENCE_BREAK.split(text):
        while len(sentence) > max_size:
            pieces.extend([current] if current else [])
            pieces.append(sentence[:max_size])
            sentence, current = sentence[max_size:], ""
        if current and len(current) + 1 + len(sentence) > max_size:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


def by_paragraph(page: DocumentPage, max_size: int) -> list[Chunk]:
    """Group paragraphs into chunks that start at every Chương/Mục/Điều heading.

    Headings stay attached to the paragraphs that follow them, and oversized
    paragraphs are split at sentence boundaries.
    """
    chunks: list[Chunk] = []
    group: list[tuple[int, str, dict]] = []
    has_body = False

    def flush() -> None:
        nonlocal has_body
        if group:
            text = "\n".join(t for _, t, _ in group)
            chunks.append(_make_chunk(page, "struct", len(chunks), text, group[0][0],
                                      [p for _, _, p in group]))
            group.clear()
        has_body = False

    for start, _, para in _paragraph_offsets(page):
        text = para["text"]
        is_heading = bool(CHAPTER.match(text) or SECTION.match(text) or ARTICLE.match(text)
                          or is_heading_line(text))
        if is_heading and has_body:
            flush()
        for piece in _split_long(text, max_size) if len(text) > max_size else [text]:
            size = sum(len(t) + 1 for _, t, _ in group) + len(piece)
            if has_body and size > max_size:
                flush()
            group.append((start, piece, para))
            has_body = has_body or not is_heading
    flush()
    return chunks

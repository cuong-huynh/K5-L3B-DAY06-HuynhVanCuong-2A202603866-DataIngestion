"""Read and normalize source data with PyMuPDF, keeping page-level traceability."""
import re
import unicodedata
from pathlib import Path

import pymupdf

from .models import DocumentPage

GAZETTE_HEADER = re.compile(r"^CÔNG BÁO/Số .+/Ngày \d{1,2}-\d{1,2}-\d{4}$")
PAGE_NUMBER = re.compile(r"^\d{1,4}$")
SIGNATURE_STAMP = re.compile(
    r"^(Người ký: |Ký bởi: |Thời gian ký: |Email: thongtinchinhphu@chinhphu\.vn"
    r"|Cơ quan: Văn phòng Chính phủ)",
    re.IGNORECASE,
)
STAMP_TRAILING_PAGE = re.compile(r" (\d{1,4})$")
CHAPTER = re.compile(r"^Chương ([IVXLC]+)$")
SECTION = re.compile(r"^Mục (\d+)$")
ARTICLE = re.compile(r"^Điều (\d+)\.\s*(.*)$")
# A wrapped PDF line is joined to the previous one unless it opens a new legal unit.
PARAGRAPH_START = re.compile(r"^(Chương [IVXLC]+$|Mục \d+$|Điều \d+\.|\d{1,2}\.\s|[a-zđ]\)\s)")
EMPTY_PAGE_CHARS = 200


def normalize_text(text: str) -> str:
    """NFC-normalize, unify spaces and trim; keep line breaks."""
    text = unicodedata.normalize("NFC", text).replace("\u00a0", " ").replace("\u00ad", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(lines)


def is_heading_line(text: str) -> bool:
    """All-caps lines such as chapter titles or the signer's title."""
    letters = [c for c in text if c.isalpha()]
    return len(letters) >= 4 and all(c.isupper() for c in letters)


def _page_lines(pdf_page: pymupdf.Page) -> list[tuple[str, bool]]:
    """Return (normalized text, is_bold) for each visual line, in reading order."""
    lines = []
    for block in pdf_page.get_text("dict", sort=True)["blocks"]:
        for line in block.get("lines", []):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            text = normalize_text("".join(s["text"] for s in line["spans"]))
            bold = all((s["flags"] & 16) or "Bold" in s["font"] for s in spans)
            lines.append((text, bold))
    return lines


def _strip_page_furniture(lines: list[tuple[str, bool]]) -> tuple[list[tuple[str, bool]], int | None]:
    """Drop the gazette header, its page number and the e-signature stamp."""
    gazette_page = None
    kept = []
    for text, bold in lines:
        if GAZETTE_HEADER.match(text):
            continue
        if SIGNATURE_STAMP.match(text):
            if gazette_page is None and (m := STAMP_TRAILING_PAGE.search(text)):
                gazette_page = int(m.group(1))
            continue
        if len(kept) < 2 and gazette_page is None and PAGE_NUMBER.match(text):
            gazette_page = int(text)
            continue
        kept.append((text, bold))
    return kept, gazette_page


def to_paragraphs(lines: list[tuple[str, bool]]) -> list[str]:
    """Join wrapped lines; bold lines are headings (Chương, Mục, Điều title)."""
    paragraphs: list[str] = []
    previous_bold = None
    for text, bold in lines:
        continues_article_title = bold and previous_bold and ARTICLE.match(paragraphs[-1]) \
            and not PARAGRAPH_START.match(text)
        continues_body = not bold and previous_bold is False and not PARAGRAPH_START.match(text)
        if paragraphs and (continues_article_title or continues_body):
            paragraphs[-1] = f"{paragraphs[-1]} {text}"
        else:
            paragraphs.append(text)
        previous_bold = bold
    return paragraphs


def load_pdf(path: Path, document_id: str, source: str,
             doc_metadata: dict | None = None) -> tuple[list[DocumentPage], list[dict]]:
    """Return one DocumentPage per physical page plus an error log for unreadable pages.

    Chapter/article context is carried across pages, so a page that starts in the
    middle of an article still knows which article it belongs to.
    """
    pages: list[DocumentPage] = []
    errors: list[dict] = []
    chapter, section, article, article_title = None, None, None, None
    with pymupdf.open(path) as pdf:
        for index, pdf_page in enumerate(pdf, start=1):
            lines, gazette_page = _strip_page_furniture(_page_lines(pdf_page))
            paragraphs = []
            for text in to_paragraphs(lines):
                if m := CHAPTER.match(text):
                    chapter, section, article, article_title = m.group(1), None, None, None
                elif m := SECTION.match(text):
                    section, article, article_title = int(m.group(1)), None, None
                elif m := ARTICLE.match(text):
                    article, article_title = int(m.group(1)), m.group(2).strip()
                paragraphs.append({
                    "text": text,
                    "chapter": chapter,
                    "section": section,
                    "article": article,
                    "article_title": article_title,
                })
            text = "\n".join(p["text"] for p in paragraphs)
            if len(text) < EMPTY_PAGE_CHARS:
                errors.append({"document_id": document_id, "page": index,
                               "chars": len(text), "error": "empty_or_scanned_page"})
            pages.append(DocumentPage(
                document_id=document_id,
                source=source,
                page=index,
                text=text,
                metadata={**(doc_metadata or {}), "gazette_page": gazette_page,
                          "paragraphs": paragraphs},
            ))
    return pages, errors

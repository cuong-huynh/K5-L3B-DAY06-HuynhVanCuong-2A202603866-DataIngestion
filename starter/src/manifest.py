"""Load the corpus, write data/manifest.json, normalized pages and the ingestion error log.

Run from starter/: python -m src.manifest
"""
import hashlib
import json
import re
from datetime import date

from .corpus import DATA_DIR, DOCUMENTS, LICENSE_NOTE, RAW_DIR, RESULTS_DIR
from .ingestion import EMPTY_PAGE_CHARS, load_pdf
from .models import DocumentPage

ACCESSED_AT = "2026-11-14"
PASSED = re.compile(r"thông qua ngày (\d{1,2}) tháng (\d{1,2}) năm (\d{4})")
EFFECTIVE = re.compile(r"có hiệu lực thi hành từ ngày (\d{1,2}) tháng (\d{1,2}) năm (\d{4})")
COUNTING_RULE = (
    "Đếm trang vật lý của PDF (bắt đầu từ 1). Một trang được tính là trang nội dung nếu sau "
    f"chuẩn hóa còn ít nhất {EMPTY_PAGE_CHARS} ký tự văn bản luật; tiêu đề Công báo, số trang "
    "Công báo và dấu chữ ký số đã bị loại trước khi đếm. Mỗi file chỉ chứa đúng một luật, "
    "không có bìa hay mục lục."
)


def _find_date(pattern: re.Pattern, pages: list[DocumentPage]) -> str | None:
    for page in pages:
        if m := pattern.search(page.text):
            day, month, year = (int(x) for x in m.groups())
            return date(year, month, day).isoformat()
    return None


def load_corpus() -> tuple[list[DocumentPage], list[dict], list[dict]]:
    """Return all pages, per-document manifest entries and the error log."""
    all_pages, entries, errors = [], [], []
    for doc in DOCUMENTS:
        path = RAW_DIR / doc["file"]
        source = f"data/raw/{doc['file']}"
        pages, doc_errors = load_pdf(path, doc["document_id"], source)
        passed = _find_date(PASSED, pages)
        effective = _find_date(EFFECTIVE, pages)
        doc_meta = {
            "law_title": doc["title"],
            "law_number": doc["law_number"],
            "year": int(passed[:4]) if passed else None,
            "effective_date": effective,
        }
        for page in pages:
            page.metadata.update(doc_meta)
        counted = [p.page for p in pages if len(p.text) >= EMPTY_PAGE_CHARS]
        entries.append({
            "source_id": doc["document_id"],
            "title": f"{doc['title']} số {doc['law_number']}",
            "source_path_or_url": doc["url"],
            "landing_page": doc["landing_page"],
            "local_path": source,
            "snapshot": doc["gazette"],
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "license_or_permission": LICENSE_NOTE,
            "accessed_at": ACCESSED_AT,
            "passed_date": passed,
            "effective_date": effective,
            "physical_pages": len(pages),
            "content_pages": len(counted),
            "pages": [{"page": p.page, "gazette_page": p.metadata["gazette_page"],
                       "chars": len(p.text), "counted": p.page in counted} for p in pages],
            "total_chars": sum(len(p.text) for p in pages),
        })
        all_pages.extend(pages)
        errors.extend(doc_errors)
    return all_pages, entries, errors


def main() -> None:
    pages, entries, errors = load_corpus()
    total_content = sum(e["content_pages"] for e in entries)
    manifest = {
        "corpus": "Ba luật Việt Nam về không gian số (An ninh mạng, Giao dịch điện tử, "
                  "Bảo vệ dữ liệu cá nhân)",
        "extraction": "PyMuPDF get_text('dict'), Unicode NFC; không cần OCR",
        "counting_rule": COUNTING_RULE,
        "total_physical_pages": sum(e["physical_pages"] for e in entries),
        "total_content_pages": total_content,
        "documents": entries,
    }
    if total_content < 30:
        raise SystemExit(f"Corpus has only {total_content} content pages (< 30).")

    (DATA_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    processed = DATA_DIR / "processed"
    processed.mkdir(exist_ok=True)
    with (processed / "pages.jsonl").open("w", encoding="utf-8") as f:
        for p in pages:
            meta = {k: v for k, v in p.metadata.items() if k != "paragraphs"}
            f.write(json.dumps({"document_id": p.document_id, "source": p.source,
                                "page": p.page, **meta, "text": p.text},
                               ensure_ascii=False) + "\n")
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "ingestion_errors.json").write_text(
        json.dumps(errors, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for e in entries:
        print(f"{e['source_id']}: {e['content_pages']}/{e['physical_pages']} pages, "
              f"{e['total_chars']} chars, passed {e['passed_date']}, effective {e['effective_date']}")
    print(f"Total content pages: {total_content}; errors: {len(errors)}")


if __name__ == "__main__":
    main()

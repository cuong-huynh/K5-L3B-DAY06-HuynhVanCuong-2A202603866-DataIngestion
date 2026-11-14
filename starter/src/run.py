"""Day 06 pipeline: ingest three laws, index three strategies, run the benchmark.

Run from starter/: python -m src.run
"""
import csv
import json
import os
import platform
import statistics
import time
from datetime import datetime
from importlib.metadata import version

from dotenv import load_dotenv

from .chunking import by_paragraph, fixed_size
from .corpus import BENCHMARK_DIR, RESULTS_DIR
from .embeddings import E5Embedder
from .evaluation import evaluate_query, summarize, verify_benchmark
from .manifest import load_corpus
from .store import PgVectorStore

MODEL_NAME = "intfloat/multilingual-e5-small"
TOP_K = 3
STRATEGIES = {
    "A_fixed": {"chunker": "fixed_size", "size": 1000, "overlap": 150, "use_filter": False,
                "hypothesis": "Baseline: cửa sổ ký tự cố định, bỏ qua cấu trúc Điều/khoản."},
    "B_struct": {"chunker": "by_paragraph", "max_size": 1000, "use_filter": False,
                 "hypothesis": "Cắt theo Điều/khoản giữ trọn ý nên tăng Hit@1 và coherence so với A."},
    "C_struct_filter": {"chunker": "by_paragraph", "max_size": 1000, "use_filter": True,
                        "hypothesis": "Như B nhưng lọc document_id khi câu hỏi có phạm vi văn bản; "
                                      "sửa các câu mơ hồ giữa ba luật."},
}
# Fixed before looking at any score: mid-page positions spread over the three laws.
COHERENCE_POSITIONS = [("luat-anm-2025", p) for p in (5, 15, 25, 35)] + \
                      [("luat-gddt-2023", p) for p in (5, 15, 25)] + \
                      [("luat-bvdlcn-2025", p) for p in (5, 15, 20)]


def build_chunks(pages, config):
    if config["chunker"] == "fixed_size":
        return [c for p in pages for c in fixed_size(p, config["size"], config["overlap"])]
    return [c for p in pages for c in by_paragraph(p, config["max_size"])]


def chunk_stats(chunks):
    lengths = [len(c.text) for c in chunks]
    return {"chunks": len(chunks), "total_chars": sum(lengths), "min_chars": min(lengths),
            "median_chars": statistics.median(lengths), "mean_chars": round(statistics.mean(lengths), 1),
            "max_chars": max(lengths), "chunks_without_article": sum(c.metadata["article"] is None for c in chunks)}


def write_jsonl(path, rows):
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def export_manual_templates(pages, chunks_by_strategy, traces):
    """Templates for the human audit: coherence (10 positions) and test-set metadata/grounding."""
    manual = RESULTS_DIR / "manual"
    manual.mkdir(exist_ok=True)
    page_text = {(p.document_id, p.page): p.text for p in pages}
    with (manual / "coherence_labels.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["position_id", "document_id", "page", "offset", "strategy", "chunk_id",
                    "chunk_text", "label_0_2", "reason"])
        for i, (doc, page) in enumerate(COHERENCE_POSITIONS, start=1):
            offset = len(page_text[(doc, page)]) // 2
            for strategy, chunks in chunks_by_strategy.items():
                candidates = [c for c in chunks if c.document_id == doc and c.page == page
                              and c.metadata["char_start"] <= offset]
                chunk = max(candidates, key=lambda c: c.metadata["char_start"])
                w.writerow([f"pos{i:02d}", doc, page, offset, strategy, chunk.chunk_id,
                            chunk.text, "", ""])
    with (manual / "test_audit.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["strategy", "question_id", "filter", "rank", "chunk_id", "document_id", "page",
                    "article", "evidence_hit_auto", "metadata_correct_0_1", "grounding_0_2", "reason"])
        for t in traces:
            if t["split"] != "test":
                continue
            for r in t["results"]:
                w.writerow([t["strategy"], t["id"], json.dumps(t["filter"], ensure_ascii=False),
                            r["rank"], r["chunk_id"], r["document_id"], r["page"], r["article"],
                            int(r["evidence_hit"]), "", "", ""])


def main() -> None:
    load_dotenv()
    database_url = os.environ["DATABASE_URL"]
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "traces").mkdir(exist_ok=True)

    pages, entries, errors = load_corpus()
    content_pages = sum(e["content_pages"] for e in entries)
    if content_pages < 30:
        raise SystemExit(f"Only {content_pages} content pages")
    questions = [json.loads(line) for line in (BENCHMARK_DIR / "questions.jsonl").open(encoding="utf-8")]
    problems = verify_benchmark(questions, pages)
    if problems:
        raise SystemExit("Benchmark verification failed:\n" + "\n".join(problems))

    started = time.perf_counter()
    embedder = E5Embedder(MODEL_NAME)
    model_load_s = time.perf_counter() - started
    store = PgVectorStore(database_url, embedder.dimensions)
    store.create_schema()

    run_log = {
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "content_pages": content_pages, "ingestion_errors": len(errors),
        "embedding": {"provider": "local sentence-transformers", "model": MODEL_NAME,
                      "dimensions": embedder.dimensions, "max_seq_length": embedder.max_seq_length,
                      "document_prefix": "passage: ", "query_prefix": "query: ",
                      "normalized": True, "device": "cpu", "cost_usd": 0.0},
        "vector_store": {"backend": "PostgreSQL 16 + pgvector 0.8.7 (Docker)",
                         "table": store.table, "metric": "cosine", "search": "exact (no ANN index)"},
        "versions": {pkg: version(pkg) for pkg in
                     ("sentence-transformers", "torch", "transformers", "pymupdf", "psycopg")},
        "python": platform.python_version(),
        "model_load_seconds": round(model_load_s, 2),
        "strategies": {},
    }

    all_traces, chunks_by_strategy = [], {}
    for name, config in STRATEGIES.items():
        chunks = build_chunks(pages, config)
        chunks_by_strategy[name] = chunks
        texts = [c.text for c in chunks]
        t0 = time.perf_counter()
        vectors = embedder.embed_documents(texts)
        embed_s = time.perf_counter() - t0
        t0 = time.perf_counter()
        first = store.upsert(name, chunks, vectors)
        upsert_s = time.perf_counter() - t0
        count_after_first = store.count(name)
        second = store.upsert(name, chunks, vectors)
        count_after_second = store.count(name)
        if count_after_first != len(chunks) or count_after_second != len(chunks):
            raise SystemExit(f"{name}: row count mismatch after re-ingest")

        traces, t0 = [], time.perf_counter()
        for q in questions:
            filters = q["filter"] if config["use_filter"] and q.get("filter") else None
            hits = store.search(name, embedder.embed_query(q["question"]), TOP_K, filters)
            trace = evaluate_query(q, hits)
            trace["strategy"] = name
            trace["applied_filter"] = filters
            traces.append(trace)
        query_s = time.perf_counter() - t0
        write_jsonl(RESULTS_DIR / "traces" / f"{name}.jsonl", traces)
        all_traces.extend(traces)

        run_log["strategies"][name] = {
            "config": config, "stats": chunk_stats(chunks),
            "truncated_passages": embedder.count_truncated(texts),
            "embed_seconds": round(embed_s, 2), "upsert_seconds": round(upsert_s, 2),
            "query_seconds_20q": round(query_s, 2),
            "reingest_check": {"rows_after_first": count_after_first, "first": first,
                               "rows_after_second": count_after_second, "second": second},
        }
        print(f"{name}: {len(chunks)} chunks, embed {embed_s:.1f}s, rows {count_after_first}"
              f" -> {count_after_second} after re-ingest")

    summary = summarize(all_traces)
    (RESULTS_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                                              encoding="utf-8")
    run_log["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    (RESULTS_DIR / "run_log.json").write_text(json.dumps(run_log, ensure_ascii=False, indent=2) + "\n",
                                              encoding="utf-8")
    export_manual_templates(pages, chunks_by_strategy, all_traces)

    print(f"\n{'strategy':<17}{'split':<6}{'Hit@1':>8}{'Hit@3':>8}{'filter ok':>11}")
    for name, splits in summary.items():
        for split in ("dev", "test", "all"):
            b = splits[split]
            fq = f"{b['filter_respected']}/{b['filter_questions']}" if b["filter_questions"] else "N/A"
            print(f"{name:<17}{split:<6}{b['hit_at_1']:>4}/{b['n']:<3}{b['hit_at_3']:>4}/{b['n']:<3}{fq:>11}")


if __name__ == "__main__":
    main()

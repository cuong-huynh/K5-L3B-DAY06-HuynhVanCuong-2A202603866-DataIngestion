"""Evaluate retrieved evidence and preserve per-query traces."""
import re
import unicodedata
from typing import Any

from .models import DocumentPage


def normalize_for_match(text: str) -> str:
    text = unicodedata.normalize("NFC", text).lower()
    return re.sub(r"\s+", " ", text).strip()


def gold_targets(question: dict[str, Any]) -> list[dict[str, Any]]:
    """Primary gold plus any documented alternative evidence locations."""
    primary = {"source_id": question["gold_source_id"], "page": question["gold_page"],
               "evidence_quote": question["evidence_quote"]}
    return [primary, *question.get("alternative_gold", [])]


def verify_benchmark(questions: list[dict[str, Any]], pages: list[DocumentPage]) -> list[str]:
    """Return problems: evidence missing from its gold page, bad split or too few filters."""
    by_key = {(p.document_id, p.page): normalize_for_match(p.text) for p in pages}
    problems = []
    for q in questions:
        for gold in gold_targets(q):
            page_text = by_key.get((gold["source_id"], gold["page"]))
            if page_text is None:
                problems.append(f"{q['id']}: unknown page {gold['source_id']} p{gold['page']}")
            elif normalize_for_match(gold["evidence_quote"]) not in page_text:
                problems.append(f"{q['id']}: evidence not found on {gold['source_id']} p{gold['page']}")
    splits = [q["split"] for q in questions]
    if splits.count("dev") < 15 or splits.count("test") < 5:
        problems.append(f"split too small: {splits.count('dev')} dev / {splits.count('test')} test")
    filtered = [q for q in questions if q.get("filter")]
    if len(filtered) < 3 or not any(q["split"] == "test" for q in filtered):
        problems.append("need >= 3 filter questions with >= 1 in test")
    return problems


def is_evidence_hit(question: dict[str, Any], hit: dict[str, Any]) -> bool:
    """A hit is a chunk from a gold source/page that contains the full evidence quote."""
    chunk_text = normalize_for_match(hit["text"])
    return any(
        hit["document_id"] == gold["source_id"] and hit["page"] == gold["page"]
        and normalize_for_match(gold["evidence_quote"]) in chunk_text
        for gold in gold_targets(question)
    )


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep the full top-k trace plus automatic Hit@1 / Evidence Hit@3.

    Human grounding and coherence labels are recorded separately, not inferred here.
    """
    flags = [is_evidence_hit(question, h) for h in hits]
    on_gold_page = [
        any(h["document_id"] == g["source_id"] and h["page"] == g["page"] for g in gold_targets(question))
        for h in hits
    ]
    filter_ok = None
    if question.get("filter"):
        filter_ok = all(all(h.get(k) == v for k, v in question["filter"].items()) for h in hits)
    return {
        "id": question["id"],
        "split": question["split"],
        "type": question.get("type"),
        "question": question["question"],
        "filter": question.get("filter"),
        "gold_source_id": question["gold_source_id"],
        "gold_page": question["gold_page"],
        "evidence_quote": question["evidence_quote"],
        "hit_at_1": bool(flags[:1] and flags[0]),
        "hit_at_3": any(flags[:3]),
        "gold_page_at_3": any(on_gold_page[:3]),
        "first_hit_rank": flags.index(True) + 1 if True in flags else None,
        "filter_respected": filter_ok,
        "results": [
            {"rank": i + 1, "evidence_hit": flag, **h} for i, (flag, h) in enumerate(zip(flags, hits))
        ],
    }


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate Hit@1 and Evidence Hit@3 by strategy and split, as counts and rates."""
    summary: dict[str, Any] = {}
    for trace in traces:
        for split in (trace["split"], "all"):
            bucket = summary.setdefault(trace["strategy"], {}).setdefault(
                split, {"n": 0, "hit_at_1": 0, "hit_at_3": 0, "gold_page_at_3": 0,
                        "filter_questions": 0, "filter_respected": 0})
            bucket["n"] += 1
            bucket["hit_at_1"] += trace["hit_at_1"]
            bucket["hit_at_3"] += trace["hit_at_3"]
            bucket["gold_page_at_3"] += trace["gold_page_at_3"]
            if trace["filter"]:
                bucket["filter_questions"] += 1
                bucket["filter_respected"] += bool(trace["filter_respected"])
    for splits in summary.values():
        for bucket in splits.values():
            n = bucket["n"]
            bucket["hit_at_1_rate"] = round(bucket["hit_at_1"] / n, 3)
            bucket["hit_at_3_rate"] = round(bucket["hit_at_3"] / n, 3)
    return summary

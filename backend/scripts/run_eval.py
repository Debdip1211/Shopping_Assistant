"""Phase 2 evaluation runner.

Asks every question in tests/eval_questions.json (with no chat history) and
writes the answers and sources to tests/eval_raw_<label>.md, ready for grading
by hand. Grades then go into tests/eval_results.md.

Run from the backend/ folder (with the virtual environment active):
    python -m scripts.run_eval --label baseline

To test one change, override a setting for this run only, e.g.:
    PER_PRODUCT_K=3 python -m scripts.run_eval --label per_product_k_3

Note: settings that change how chunks are MADE (CHUNK_SIZE, CHUNK_OVERLAP)
also need a fresh DATA_DIR, because unchanged products are "cached" and would
keep their old chunks, e.g.:
    CHUNK_SIZE=400 DATA_DIR=./data/eval_chunk400 python -m scripts.run_eval --label chunk_400

Each question costs a small amount of Hugging Face credits.
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone

from langchain_core.documents import Document

from app.config import BACKEND_DIR, settings
from app.ingest import SAMPLES_DIR, ingest_product
from app.product_id import make_product_id
from app.product_store import get_product
from app.rag.chain import NoProductsError, answer_current, answer_history
from app.rag.llm import LLMError
from app.rag.section_router import route_sections
from app.schemas import ProductIn

QUESTIONS_PATH = BACKEND_DIR / "tests" / "eval_questions.json"
PREVIEW_CHARS = 150


def ingest_samples_by_filename() -> dict[str, str]:
    """Ingest every sample and return {file name: product_id}."""
    ids = {}
    for path in sorted(SAMPLES_DIR.glob("*.json")):
        product = ProductIn.model_validate_json(path.read_text(encoding="utf-8"))
        ingest_product(product)
        ids[path.name] = make_product_id(product.url, product.site)
    return ids


def ask(item: dict, product_ids: dict[str, str]) -> tuple[str, str, list[Document]]:
    """Ask one evaluation question. Returns (answer, mode, sources)."""
    if item["scope"] == "history":
        return answer_history(item["question"], [])
    record = get_product(product_ids[item["product"]])
    if record is None:
        raise ValueError(f"Sample {item['product']} is not stored.")
    return answer_current(record, item["question"], [])


def quote(text: str) -> str:
    """Format text as a markdown blockquote (every line starts with '> ')."""
    return "\n".join(f"> {line}" if line else ">" for line in text.splitlines())


def settings_summary() -> str:
    """The settings that affect answers, recorded so runs can be compared."""
    return (
        f"- Model: `{settings.llm_model}` (routing: {settings.llm_routing or 'default'}, "
        f"max tokens {settings.llm_max_tokens})\n"
        f"- CHUNK_SIZE={settings.chunk_size}, CHUNK_OVERLAP={settings.chunk_overlap}, "
        f"FULL_CONTEXT_CHAR_LIMIT={settings.full_context_char_limit}\n"
        f"- CURRENT_TOP_K={settings.current_top_k}, PER_PRODUCT_K={settings.per_product_k}, "
        f"MAX_COMPARE_PRODUCTS={settings.max_compare_products}\n"
        f"- DATA_DIR=`{settings.data_dir}`"
    )


def format_result(number: int, item: dict, result: tuple | str) -> str:
    """Markdown block for one question: expected answer, actual answer, sources."""
    where = item["product"] or "all products"
    lines = [
        f"## {number}. [{item['scope']} · {where}] {item['question']}",
        "",
        f"**Expected:** {item['expected_answer']}",
        "",
        f"**Sections routed:** {route_sections(item['question']) or 'none (no filter)'}",
        "",
    ]
    if isinstance(result, str):  # an error message
        lines += [f"**Error:** {result}", ""]
    else:
        answer, mode, sources = result
        lines += [f"**Mode:** {mode}", "", "**Answer:**", "", quote(answer), "", "**Sources:**", ""]
        for i, doc in enumerate(sources, start=1):
            meta = doc.metadata
            preview = " ".join(meta["body"].split())[:PREVIEW_CHARS]
            lines.append(f"{i}. {meta['title'][:40]} · `{meta['section']}` · {preview}…")
        lines.append("")
    lines += ["**Grade:** correct / partly / wrong — **Citations:** ok / missing / wrong — **Notes:**", ""]
    return "\n".join(lines)


def parse_selection(text: str | None, total: int) -> list[int]:
    """Question numbers to run: "10-14", "3,5,8", or None for all (1..total)."""
    if not text:
        return list(range(1, total + 1))
    numbers: list[int] = []
    for part in text.split(","):
        start, _, end = part.strip().partition("-")
        numbers.extend(range(int(start), int(end or start) + 1))
    invalid = [n for n in numbers if not 1 <= n <= total]
    if invalid:
        raise SystemExit(f"Question numbers must be between 1 and {total}: {invalid}")
    return sorted(set(numbers))


def main() -> int:
    """Run the evaluation questions and write the raw results file."""
    parser = argparse.ArgumentParser(description="Run the evaluation questions.")
    parser.add_argument("--label", required=True, help="Name of this run, e.g. baseline")
    parser.add_argument(
        "--questions",
        help='Only run these questions, e.g. "10-14" or "3,5,8" (saves credits). Default: all.',
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)

    questions = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    selected = parse_selection(args.questions, len(questions))
    out_path = BACKEND_DIR / "tests" / f"eval_raw_{args.label}.md"
    print("Ingesting samples...")
    product_ids = ingest_samples_by_filename()

    blocks = []
    for number in selected:
        item = questions[number - 1]
        print(f"[{number}/{len(questions)}] {item['question']}")
        try:
            result: tuple | str = ask(item, product_ids)
        except (LLMError, NoProductsError, ValueError) as error:
            result = str(error)
            print(f"   Error: {error}")
        blocks.append(format_result(number, item, result))

    started = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    which = f"questions {args.questions}" if args.questions else "all questions"
    header = f"# Eval run: {args.label} ({which})\n\nRun at {started}\n\n{settings_summary()}\n"
    out_path.write_text(header + "\n" + "\n".join(blocks), encoding="utf-8")
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

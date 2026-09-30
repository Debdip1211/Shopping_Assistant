"""Phase 1 terminal interface for the RAG pipeline.

Run from the backend/ folder (with the virtual environment active):
    python -m scripts.rag_cli

It ingests all sample products, lets you pick a scope (one product or all
products), then answers your questions with sources. Type `exit` to quit.
"""

import logging
import sys

from app.ingest import ingest_product, load_samples
from app.product_store import ProductRecord, get_product
from app.rag.chain import Answer, NoProductsError, answer_current, answer_history
from app.rag.llm import LLMError

PREVIEW_CHARS = 150
EXIT_WORDS = {"exit", "quit"}


def ingest_samples() -> list[ProductRecord]:
    """Ingest the samples, print a summary line for each, return their records."""
    print("Ingesting sample products (the first run downloads the ~90 MB embedding model)...\n")
    records = []
    for product in load_samples():
        result = ingest_product(product)
        status = "cached" if result.cached else "ingested"
        print(f"  {result.title[:45]:45}  id={result.product_id}  "
              f"mode={result.mode:12}  chunks={result.num_chunks:3}  ({status})")
        record = get_product(result.product_id)
        if record is not None:
            records.append(record)
    print()
    return records


def choose_scope(records: list[ProductRecord]) -> ProductRecord | None:
    """Ask which scope to use. Returns a product, or None for "all products"."""
    print("Choose a scope:")
    for number, record in enumerate(records, start=1):
        print(f"  {number}. This product: {record.title[:60]}")
    print("  a. All viewed products")
    while True:
        choice = input("Scope> ").strip().lower()
        if choice == "a":
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(records):
            return records[int(choice) - 1]
        print(f"Please type a number from 1 to {len(records)}, or 'a'.")


def print_answer(answer: Answer) -> None:
    """Print the answer text, the mode, and the numbered sources."""
    text, mode, sources = answer
    print(f"\nAssistant ({mode}):\n{text}\n")
    print("Sources:")
    for number, doc in enumerate(sources, start=1):
        meta = doc.metadata
        preview = " ".join(meta["body"].split())[:PREVIEW_CHARS]
        print(f"  [{number}] {meta['title'][:40]} | {meta['section']} | {preview}...")
    print()


def chat_loop(scope: ProductRecord | None) -> None:
    """Read questions until `exit`, keeping this session's chat history."""
    label = scope.title if scope else "All viewed products"
    print(f"\nScope: {label}\nAsk a question (or type 'exit').\n")
    history: list[dict[str, str]] = []
    while True:
        question = input("You> ").strip()
        if not question:
            continue
        if question.lower() in EXIT_WORDS:
            return
        try:
            if scope is None:
                answer = answer_history(question, history)
            else:
                answer = answer_current(scope, question, history)
        except (LLMError, NoProductsError) as error:
            print(f"\nError: {error}\n")
            continue
        print_answer(answer)
        history += [
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer[0]},
        ]


def main() -> int:
    """Ingest samples, choose a scope, then chat."""
    logging.basicConfig(level=logging.WARNING)
    records = ingest_samples()
    try:
        chat_loop(choose_scope(records))
    except (KeyboardInterrupt, EOFError):
        print()
    print("Bye!")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""System prompts (CLAUDE.md Section 9) and helpers that format the context.

The "context" is the product information we paste into the system prompt.
Retrieved chunks are shown as numbered excerpts [1], [2], ... so the LLM can
cite them, and the same numbers map back to the `sources` we return.
"""

from datetime import datetime

from langchain_core.documents import Document

from app.product_store import ProductRecord
from app.rag.documents import SECTION_NAMES, section_texts

CURRENT_SYSTEM_PROMPT = """You are a helpful shopping assistant. You answer questions about the product page the user is viewing on {site}.

Rules:
- Use ONLY the product information provided below. Do not use outside knowledge about this product, brand, or market.
- If the information isn't provided, say: "I couldn't find that on this product page." Then briefly mention what related information is available.
- Prices, offers, and stock were captured at {captured_at} and may have changed. Mention this when you state a price or offer.
- When summarizing reviews, reflect the balance of opinions honestly (both praise and complaints), and note that only the reviews loaded on the page were available.
- Cite the numbered excerpts you used in square brackets, like [1] or [2][3].
- Be concise. Use short paragraphs or bullet points when it helps.
- Never invent specifications, prices, ratings, or review content.
- Keep a professional tone: do not use emojis or decorative symbols.

Product information:
{context}"""

HISTORY_SYSTEM_PROMPT = """You are a helpful shopping assistant. The user has viewed several products, and you answer questions that may compare them.

Rules:
- Use ONLY the product information provided below. Do not use outside knowledge.
- Always refer to products by their names. When comparing, a short table or a clear point-by-point comparison is welcome.
- If some products lack the information needed (e.g. a spec isn't listed), say so for those products instead of guessing.
- Prices and offers were captured when each product was viewed and may have changed. Say so when comparing prices.
- Only the most relevant excerpts from each product are shown, so if the evidence is thin, say so.
- If asked which product to buy, compare them on what the user cares about based on the data, and leave the final decision to the user.
- Cite the numbered excerpts you used in square brackets, like [1] or [4][5].
- Never invent specifications, prices, ratings, or review content.
- Keep a professional tone: do not use emojis or decorative symbols.

Products:
{context}"""

SITE_NAMES = {"amazon": "Amazon", "flipkart": "Flipkart", "other": "a shopping website"}
NOT_LISTED = "not listed"


def site_display_name(site: str) -> str:
    """Human-friendly site name for the prompt."""
    return SITE_NAMES.get(site, "a shopping website")


def format_date(value: datetime) -> str:
    """Format a timestamp like '2026-09-24 10:30 UTC'."""
    return value.strftime("%Y-%m-%d %H:%M UTC")


def format_card_line(record: ProductRecord) -> str:
    """One line with price, rating and capture date (the 'summary card')."""
    rating = record.rating or NOT_LISTED
    if record.rating and record.rating_count:
        rating = f"{record.rating} ({record.rating_count})"
    return (
        f"Price: {record.price or NOT_LISTED} | Rating: {rating} | "
        f"Captured: {format_date(record.captured_at)}"
    )


def format_excerpt(number: int, document: Document) -> str:
    """One numbered excerpt, e.g. '[3] (reviews) Great battery life...'."""
    meta = document.metadata
    return f"[{number}] ({meta['section']}) {meta['body']}"


def format_full_text(record: ProductRecord) -> str:
    """All section text, each under a heading like '## Specs'."""
    texts = section_texts(record)
    order = [name for name in SECTION_NAMES if name in texts] + [
        name for name in texts if name not in SECTION_NAMES
    ]
    return "\n\n".join(f"## {name.capitalize()}\n{texts[name]}" for name in order)


def build_current_context(
    record: ProductRecord, documents: list[Document], full_context: bool
) -> str:
    """Context for "This product": summary card, full text (if full_context), excerpts."""
    parts = [
        f"Product: {record.title} ({record.site})\n{format_card_line(record)}"
    ]
    if full_context:
        parts.append(format_full_text(record))
    excerpts = "\n\n".join(
        format_excerpt(i, doc) for i, doc in enumerate(documents, start=1)
    )
    parts.append(f"Numbered excerpts (cite these):\n{excerpts or '(none)'}")
    return "\n\n".join(parts)


def build_history_context(
    groups: list[tuple[ProductRecord, list[Document]]],
) -> str:
    """Context for "All viewed products": one block per product.

    Excerpt numbers run continuously across products ([1], [2] for product 1,
    [3], ... for product 2), in the same order as the returned sources.
    """
    blocks = []
    number = 1
    for index, (record, documents) in enumerate(groups, start=1):
        lines = [
            f"### Product {index}: {record.title} ({record.site})",
            format_card_line(record),
        ]
        for document in documents:
            lines.append(format_excerpt(number, document))
            number += 1
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)

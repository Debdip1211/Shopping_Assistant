"""The core question-answering logic ("the chain").

Each answer follows the RAG steps:
  1. Route:    decide which sections the question is about.
  2. Retrieve: find the most relevant chunks (R of RAG).
  3. Augment:  put them, numbered, into the system prompt (A).
  4. Generate: ask the LLM to answer using only that context (G).
Retrieved chunks are returned as `sources` in the same order as their numbers.
"""

import logging
import re
from collections.abc import Mapping, Sequence

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from app.config import settings
from app.product_store import ProductRecord
from app.rag.documents import Product, compute_char_count
from app.rag.llm import invoke_llm
from app.rag.prompts import (
    CURRENT_SYSTEM_PROMPT,
    HISTORY_SYSTEM_PROMPT,
    build_current_context,
    build_history_context,
    format_date,
    site_display_name,
)
from app.rag.retriever import retrieve_across_products, retrieve_for_product
from app.rag.section_router import route_sections
from app.schemas import Mode

logger = logging.getLogger(__name__)

# (answer text, mode used, source chunks in excerpt-number order)
Answer = tuple[str, Mode, list[Document]]

# Emoji and decorative symbols, removed from answers as a safety net (the prompts
# already ask for none). Unicode blocks: emoji/pictographs U+1F000-U+1FAFF, misc
# symbols + dingbats U+2600-U+27BF (e.g. a green check mark), stars/arrows
# U+2B00-U+2BFF, plus the invisible joiner/variation characters emoji use.
# Built with chr() so this file stays plain ASCII; the rupee sign is not affected.
_EMOJI = re.compile(
    "["
    + chr(0x1F000) + "-" + chr(0x1FAFF)
    + chr(0x2600) + "-" + chr(0x27BF)
    + chr(0x2B00) + "-" + chr(0x2BFF)
    + chr(0x200D) + chr(0xFE0F)
    + "]"
)


def clean_answer(text: str) -> str:
    """Remove emoji from the LLM's answer and tidy the spaces they leave behind."""
    without_emoji = _EMOJI.sub("", text)
    lines = [re.sub(r"[ \t]{2,}", " ", line).rstrip() for line in without_emoji.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


class NoProductsError(Exception):
    """Raised when "All viewed products" is asked but nothing is saved yet."""


def decide_mode(product: Product) -> Mode:
    """Short products fit in the prompt whole; long ones use retrieved chunks only."""
    if compute_char_count(product) <= settings.full_context_char_limit:
        return "full_context"
    return "rag"


def trim_history(history: Sequence[Mapping[str, str]]) -> list[BaseMessage]:
    """Keep the last MAX_HISTORY_MESSAGES chat messages as LangChain messages.

    Older messages are dropped to keep the prompt short (and cheap). Messages
    with an unknown role or empty content are skipped.
    """
    limit = settings.max_history_messages
    recent = list(history)[-limit:] if limit > 0 else []
    messages: list[BaseMessage] = []
    for item in recent:
        role, content = item.get("role"), (item.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
    return messages


def build_messages(
    system_template: str,
    variables: dict[str, str],
    history: Sequence[Mapping[str, str]],
    question: str,
) -> list[BaseMessage]:
    """System prompt, then previous chat turns, then the new question.

    MessagesPlaceholder inserts the history as real user/assistant messages, so
    the LLM sees a proper conversation and can resolve follow-ups like "and
    what about its camera?".
    """
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_template),
        MessagesPlaceholder("history"),
        ("human", "{question}"),
    ])
    return prompt.format_messages(
        **variables, history=trim_history(history), question=question
    )


def answer_current(
    product: ProductRecord, question: str, history: Sequence[Mapping[str, str]]
) -> Answer:
    """Answer a question about one product ("This product" scope)."""
    sections = route_sections(question)
    documents = retrieve_for_product(
        product.product_id, question, settings.current_top_k, sections
    )
    mode = decide_mode(product)
    logger.info("current: product=%s mode=%s sections=%s chunks=%d",
                product.product_id, mode, sections, len(documents))
    context = build_current_context(product, documents, mode == "full_context")
    messages = build_messages(
        CURRENT_SYSTEM_PROMPT,
        {
            "site": site_display_name(product.site),
            "captured_at": format_date(product.captured_at),
            "context": context,
        },
        history,
        question,
    )
    return clean_answer(invoke_llm(messages)), mode, documents


def answer_history(
    question: str, history: Sequence[Mapping[str, str]]
) -> Answer:
    """Answer a question across recently viewed products ("All viewed products")."""
    sections = route_sections(question)
    groups = retrieve_across_products(question, sections)
    if not groups:
        raise NoProductsError("No products saved yet. Open a product page first.")
    # Flatten in the same order the excerpts are numbered in the context.
    sources = [doc for _, documents in groups for doc in documents]
    logger.info("history: products=%d sections=%s chunks=%d",
                len(groups), sections, len(sources))
    messages = build_messages(
        HISTORY_SYSTEM_PROMPT,
        {"context": build_history_context(groups)},
        history,
        question,
    )
    return clean_answer(invoke_llm(messages)), "rag", sources

"""Retrieval: find the chunks most relevant to a question.

Similarity search embeds the question and returns the k stored chunks whose
embeddings are closest to it. A metadata filter restricts WHICH chunks may be
returned, e.g. only chunks of product X, and only its review chunks.
"""

import logging

from langchain_core.documents import Document

from app.config import settings
from app.product_store import ProductRecord, list_products
from app.rag.vectorstore import get_vectorstore

logger = logging.getLogger(__name__)


def _build_filter(product_id: str, sections: list[str] | None) -> dict:
    """Chroma filter: this product, and (optionally) only these sections."""
    if sections is None:
        return {"product_id": product_id}
    return {"$and": [{"product_id": product_id}, {"section": {"$in": sections}}]}


def retrieve_for_product(
    product_id: str, question: str, k: int, sections: list[str] | None
) -> list[Document]:
    """Return up to k chunks of one product, most similar first.

    If the section filter finds nothing (e.g. the question is about reviews but
    this product has no reviews), retry without it so we still return the
    closest chunks the product does have.
    """
    store = get_vectorstore()
    results = store.similarity_search(
        question, k=k, filter=_build_filter(product_id, sections)
    )
    if not results and sections is not None:
        logger.info("No %s chunks for %s; retrying without section filter",
                    sections, product_id)
        results = store.similarity_search(
            question, k=k, filter=_build_filter(product_id, None)
        )
    return results


def retrieve_across_products(
    question: str, sections: list[str] | None
) -> list[tuple[ProductRecord, list[Document]]]:
    """Retrieve PER_PRODUCT_K chunks separately for each recent product.

    Why not one global search? The top chunks might all come from one product
    (e.g. the one with 60 reviews), and the LLM would then know nothing about
    the others. Searching per product guarantees every product is represented.
    """
    products = list_products(limit=settings.max_compare_products)
    return [
        (record, retrieve_for_product(
            record.product_id, question, settings.per_product_k, sections))
        for record in products
    ]

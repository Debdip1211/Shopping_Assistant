"""Tests for chunking products into Documents (app/rag/documents.py)."""

from app.config import settings
from app.product_id import make_product_id
from app.rag.documents import (
    chunk_header,
    compute_char_count,
    product_to_documents,
    section_texts,
)
from app.schemas import ProductIn, ProductSections

REQUIRED_METADATA = {
    "product_id", "site", "title", "section", "chunk_index", "start_index", "body",
}


def make_long_product() -> ProductIn:
    """A product whose sections are long enough to need several chunks each."""
    return ProductIn(
        url="https://www.amazon.in/dp/B0TESTTEST",
        site="amazon",
        title="Test Phone",
        sections=ProductSections(
            description="A great phone with many features. " * 60,
            specs="\n".join(f"Spec {i}: value number {i}" for i in range(120)),
            offers="10% instant discount on bank cards. " * 40,
            reviews=[f"Review {i}: the battery and camera are fine. " * 4 for i in range(40)],
        ),
        raw_text="Visible page text " * 50,
    )


def test_chunks_never_mix_sections() -> None:
    product = make_long_product()
    texts = section_texts(product)
    documents = product_to_documents(product)
    assert {d.metadata["section"] for d in documents} == set(texts)
    for doc in documents:
        # Every chunk body is a piece of exactly the section it is labeled with.
        assert doc.metadata["body"] in texts[doc.metadata["section"]]


def test_metadata_is_complete_and_chunk_indexes_are_consecutive() -> None:
    product = make_long_product()
    documents = product_to_documents(product)
    expected_id = make_product_id(product.url, product.site)
    for index, doc in enumerate(documents):
        assert REQUIRED_METADATA <= set(doc.metadata)
        assert doc.metadata["product_id"] == expected_id
        assert doc.metadata["site"] == "amazon"
        assert doc.metadata["title"] == "Test Phone"
        assert doc.metadata["chunk_index"] == index


def test_start_index_points_to_body_in_section_text() -> None:
    product = make_long_product()
    texts = section_texts(product)
    for doc in product_to_documents(product):
        start, body = doc.metadata["start_index"], doc.metadata["body"]
        assert texts[doc.metadata["section"]][start:start + len(body)] == body


def test_body_respects_chunk_size_and_header_is_prepended() -> None:
    for doc in product_to_documents(make_long_product()):
        body = doc.metadata["body"]
        assert len(body) <= settings.chunk_size
        header = chunk_header("Test Phone", doc.metadata["section"])
        assert doc.page_content == f"{header}\n{body}"


def test_general_fallback_when_all_sections_empty() -> None:
    product = ProductIn(
        url="https://shop.example/item/1",
        site="other",
        title="Mystery Item",
        raw_text="Some visible page text about the item. " * 5,
    )
    documents = product_to_documents(product)
    assert documents
    assert {d.metadata["section"] for d in documents} == {"general"}


def test_no_documents_when_product_has_no_text() -> None:
    product = ProductIn(url="https://shop.example/empty", site="other")
    assert product_to_documents(product) == []


def test_char_count_ignores_raw_text_when_sections_exist() -> None:
    product = ProductIn(
        url="https://shop.example/item/2",
        site="other",
        sections=ProductSections(specs="Battery: 5000 mAh", reviews=["Good", "Bad"]),
        raw_text="x" * 5000,
    )
    # "Battery: 5000 mAh" (17) + "Good\n\nBad" (9); raw_text not counted.
    assert compute_char_count(product) == 17 + 9


def test_char_count_uses_raw_text_when_sections_empty() -> None:
    product = ProductIn(url="https://shop.example/item/3", site="other", raw_text="y" * 500)
    assert compute_char_count(product) == 500

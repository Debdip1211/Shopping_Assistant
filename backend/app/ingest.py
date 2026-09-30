"""Ingest: store a product so it can be searched and answered about later.

Shared by the CLI, Streamlit, and (Phase 3) FastAPI, so the steps from
CLAUDE.md Section 7 `POST /ingest` exist in exactly one place:
  1. reject pages with too little information / too much text
  2. compute the stable product_id and a hash of the content
  3. unchanged content → only refresh metadata (no re-embedding): "cached"
  4. changed or new → replace the product's chunks in Chroma, save the record
"""

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from app.config import BACKEND_DIR, settings
from app.product_id import make_product_id, make_product_key
from app.product_store import ProductRecord, get_product, upsert_product
from app.rag.chain import decide_mode
from app.rag.documents import compute_char_count, product_to_documents, section_texts
from app.rag.vectorstore import add_documents, delete_product_chunks
from app.schemas import Mode, ProductIn

logger = logging.getLogger(__name__)

MIN_CHARS_WITHOUT_TITLE = 200
SAMPLES_DIR = BACKEND_DIR / "samples" / "products"


class NotEnoughContentError(Exception):
    """The page has no title and almost no text (→ HTTP 400 in the API)."""


class ProductTooLargeError(Exception):
    """The page has more text than MAX_PRODUCT_CHARS (→ HTTP 413 in the API)."""


@dataclass
class IngestResult:
    """What ingest reports back (matches the /ingest response in Section 7)."""

    product_id: str
    title: str
    mode: Mode
    num_chunks: int
    char_count: int
    sections_found: list[str]
    cached: bool


def payload_char_count(product: ProductIn) -> int:
    """Every character received: all sections + raw_text (for the size limit)."""
    s = product.sections
    return (
        len(s.description) + len(s.specs) + len(s.offers)
        + sum(len(r) for r in s.reviews) + len(product.raw_text)
    )


def content_hash(product: ProductIn) -> str:
    """Fingerprint of the page content (sections + raw_text).

    If the hash is unchanged, the chunks would be identical, so re-embedding
    can be skipped. Price/title aren't included: they live in the record, not
    in the chunks. (Edge case: if ONLY the title changes, old chunk headers keep
    the old title; harmless, since answers show titles from the record.)
    """
    content = {"sections": product.sections.model_dump(), "raw_text": product.raw_text}
    encoded = json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate(product: ProductIn, char_count: int) -> None:
    """Raise if the product can't be ingested."""
    if not product.title.strip() and char_count < MIN_CHARS_WITHOUT_TITLE:
        raise NotEnoughContentError("Not enough product information on this page.")
    if payload_char_count(product) > settings.max_product_chars:
        raise ProductTooLargeError(
            f"This page has more than {settings.max_product_chars:,} characters of text."
        )


def _result(record: ProductRecord, cached: bool) -> IngestResult:
    """Build the IngestResult for a stored record."""
    return IngestResult(
        product_id=record.product_id,
        title=record.title,
        mode=decide_mode(record),
        num_chunks=record.num_chunks,
        char_count=record.char_count,
        sections_found=record.sections_found,
        cached=cached,
    )


def load_samples() -> list[ProductIn]:
    """Read and validate every sample product JSON file (used by CLI and Streamlit)."""
    paths = sorted(SAMPLES_DIR.glob("*.json"))
    return [ProductIn.model_validate_json(p.read_text(encoding="utf-8")) for p in paths]


def ingest_product(product: ProductIn) -> IngestResult:
    """Store (or refresh) one product. See the module docstring for the steps."""
    char_count = compute_char_count(product)
    _validate(product, char_count)

    product_id = make_product_id(product.url, product.site)
    new_hash = content_hash(product)
    now = datetime.now(timezone.utc)
    existing = get_product(product_id)
    metadata = {
        "url": product.url,
        "title": product.title,
        "price": product.price,
        "rating": product.rating,
        "rating_count": product.rating_count,
        "captured_at": product.captured_at,
        "last_seen": now,
    }

    if existing is not None and existing.content_hash == new_hash:
        # Same content: keep the chunks, just refresh price/title/timestamps.
        record = existing.model_copy(update=metadata)
        upsert_product(record)
        logger.info("Ingest %s: content unchanged (cached)", product_id)
        return _result(record, cached=True)

    # New or changed content: replace this product's chunks.
    documents = product_to_documents(product)
    delete_product_chunks(product_id)
    add_documents(documents)

    found = list(section_texts(product))
    record = ProductRecord(
        product_id=product_id,
        key=make_product_key(product.url, product.site),
        site=product.site,
        content_hash=new_hash,
        char_count=char_count,
        num_chunks=len(documents),
        sections_found=found,
        first_seen=existing.first_seen if existing else now,
        sections=product.sections,
        # raw_text is only needed when it IS the content (the `general` section).
        raw_text=product.raw_text if found == ["general"] else "",
        **metadata,
    )
    upsert_product(record)
    logger.info("Ingest %s: %d chunks stored", product_id, len(documents))
    return _result(record, cached=False)

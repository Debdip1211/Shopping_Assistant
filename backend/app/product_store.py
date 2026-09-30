"""Product metadata storage in a local JSON file (data/products.json).

Chroma stores the chunks and their embeddings; this file stores everything
else we know about each product: title, price, timestamps, and the full
section text (needed for `full_context` mode, where the LLM sees the whole
product instead of retrieved chunks).

The file looks like: {"<product_id>": {...record...}, ...}
"""

import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from app.config import settings
from app.schemas import ProductSections, Site

logger = logging.getLogger(__name__)


class ProductRecord(BaseModel):
    """Everything stored about one product (one entry in products.json)."""

    product_id: str
    key: str  # readable key the ID was made from, e.g. "amazon:B0ABCDEFGH"
    url: str
    site: Site
    title: str
    price: str | None = None
    rating: str | None = None
    rating_count: str | None = None
    content_hash: str
    char_count: int
    num_chunks: int
    sections_found: list[str]
    captured_at: datetime
    first_seen: datetime
    last_seen: datetime
    sections: ProductSections = Field(default_factory=ProductSections)
    # Only kept when all sections are empty (it then becomes the `general` section).
    raw_text: str = ""


def _store_path() -> Path:
    """Path of products.json inside DATA_DIR."""
    return settings.data_dir / "products.json"


def _load_all() -> dict[str, ProductRecord]:
    """Read every record from disk. A missing file means 'no products yet'."""
    path = _store_path()
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {pid: ProductRecord.model_validate(rec) for pid, rec in data.items()}


def _save_all(records: dict[str, ProductRecord]) -> None:
    """Write every record to disk atomically.

    We write to a temporary file first and then rename it over the real file.
    A rename is atomic, so if the program crashes mid-write, products.json is
    never left half-written.
    """
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {pid: rec.model_dump(mode="json") for pid, rec in records.items()}
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            json.dump(data, tmp, ensure_ascii=False, indent=2)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def upsert_product(record: ProductRecord) -> None:
    """Insert a new record or replace the existing one with the same product_id."""
    records = _load_all()
    records[record.product_id] = record
    _save_all(records)
    logger.info("Saved product %s (%s)", record.product_id, record.title[:60])


def get_product(product_id: str) -> ProductRecord | None:
    """Return one record, or None if the product isn't stored."""
    return _load_all().get(product_id)


def list_products(limit: int | None = None) -> list[ProductRecord]:
    """Return records sorted by last_seen, newest first (optionally only `limit`)."""
    records = sorted(_load_all().values(), key=lambda r: r.last_seen, reverse=True)
    return records[:limit] if limit is not None else records


def delete_product(product_id: str) -> bool:
    """Delete one record. Returns False if it didn't exist."""
    records = _load_all()
    if product_id not in records:
        return False
    del records[product_id]
    _save_all(records)
    return True


def delete_all() -> int:
    """Delete every record. Returns how many were deleted."""
    count = len(_load_all())
    _save_all({})
    return count

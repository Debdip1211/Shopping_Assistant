"""Pydantic models describing the data that enters and leaves the backend.

Pydantic checks data for us: if a product JSON is missing `url` or has
`reviews` that isn't a list, we get a clear error instead of a confusing crash
later. It also turns JSON into Python objects with typed attributes
(`product.title` instead of `product["title"]`).

FastAPI uses these same models to validate every request body, to shape every
response, and to generate the interactive API docs at /docs.
(CLAUDE.md Section 7 is the contract these models follow.)
"""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

Site = Literal["amazon", "flipkart", "other"]
Mode = Literal["full_context", "rag"]
Scope = Literal["current", "history"]


# ---------- products (used since Phase 1) ----------

class ProductSections(BaseModel):
    """The labeled parts of a product page. Any of them may be empty."""

    description: str = ""
    specs: str = ""
    offers: str = ""
    reviews: list[str] = Field(default_factory=list)


class ProductIn(BaseModel):
    """One product as extracted by the extension (or loaded from a sample JSON)."""

    url: str
    site: Site
    title: str = ""
    price: str | None = None
    rating: str | None = None
    rating_count: str | None = None
    sections: ProductSections = Field(default_factory=ProductSections)
    raw_text: str = ""
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------- API responses and requests (Phase 3) ----------

class IngestResponse(BaseModel):
    """Response of POST /ingest."""

    product_id: str
    title: str
    mode: Mode
    num_chunks: int
    char_count: int
    sections_found: list[str]
    cached: bool


class ProductSummary(BaseModel):
    """One entry in the GET /products list."""

    product_id: str
    title: str
    site: Site
    url: str
    price: str | None
    rating: str | None
    last_seen: datetime
    num_chunks: int


class ChatMessage(BaseModel):
    """One earlier message of the conversation, sent by the extension."""

    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    """Body of POST /chat."""

    scope: Scope
    product_id: str | None = None  # required when scope is "current"
    question: str
    history: list[ChatMessage] = Field(default_factory=list)


class Source(BaseModel):
    """One retrieved chunk used for the answer (for citations and highlighting)."""

    product_id: str
    product_title: str
    section: str
    chunk_index: int
    text: str  # the chunk body, without the "Product: ... | Section: ..." header


class ChatResponse(BaseModel):
    """Response of POST /chat. `sources[0]` is excerpt [1], and so on."""

    answer: str
    scope: Scope
    mode: Mode
    sources: list[Source]

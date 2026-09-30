"""Turn a product into chunks (LangChain Documents) ready for embedding.

Why chunk at all? An embedding summarises the meaning of a piece of text as a
list of numbers. One embedding for a whole product page would blur everything
together ("battery", "bank offer", "screen cracked" all mixed), so searching
for "battery complaints" would match poorly. Small chunks (~800 characters)
each carry one focused meaning, so the search can find exactly the right part.

Why split each section SEPARATELY? So a chunk never mixes, say, the end of the
specs with the start of the reviews. Every chunk then belongs to exactly one
section, and we can label it (metadata `section`) and later filter by it.
"""

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings
from app.product_id import make_product_id
from app.product_store import ProductRecord
from app.schemas import ProductIn

# Order in which sections are chunked and shown.
SECTION_NAMES = ("description", "specs", "offers", "reviews")
# Used only when every section above is empty (e.g. an unknown shopping site).
GENERAL_SECTION = "general"

Product = ProductIn | ProductRecord


def section_texts(product: Product) -> dict[str, str]:
    """Return {section_name: text} for the non-empty sections of a product.

    Reviews arrive as a list; we join them with blank lines so the splitter
    (which prefers to cut at blank lines) tends to keep each review whole.
    If every section is empty, `raw_text` becomes a single `general` section.
    """
    sections = product.sections
    texts = {
        "description": sections.description.strip(),
        "specs": sections.specs.strip(),
        "offers": sections.offers.strip(),
        "reviews": "\n\n".join(r.strip() for r in sections.reviews if r.strip()),
    }
    found = {name: text for name, text in texts.items() if text}
    if not found and product.raw_text.strip():
        found = {GENERAL_SECTION: product.raw_text.strip()}
    return found


def compute_char_count(product: Product) -> int:
    """Total characters of section text (raw_text counts only as a fallback).

    On real pages raw_text repeats the sections, so counting both would make
    almost every product look "long" (see CLAUDE.md, Section 3 point 5).
    """
    return sum(len(text) for text in section_texts(product).values())


def _make_splitter() -> RecursiveCharacterTextSplitter:
    """Create the text splitter.

    "Recursive" means it first tries to cut at blank lines (paragraphs), then
    single newlines, then spaces, and only cuts mid-word as a last resort.
    `chunk_overlap` repeats the last ~100 characters of one chunk at the start
    of the next, so a sentence cut at a boundary still appears whole somewhere.
    `add_start_index` records where each chunk starts in the section text.
    """
    return RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        add_start_index=True,
    )


def chunk_header(title: str, section: str) -> str:
    """Header line prepended to each chunk so its embedding 'knows' its context."""
    return f"Product: {title or 'Unknown product'} | Section: {section}"


def product_to_documents(product: ProductIn) -> list[Document]:
    """Split a product into Documents (one per chunk) with metadata.

    page_content = header line + chunk body  (this is what gets embedded)
    metadata['body'] = chunk body only        (used for sources/highlighting)
    """
    product_id = make_product_id(product.url, product.site)
    splitter = _make_splitter()
    documents: list[Document] = []
    for section, text in section_texts(product).items():
        # Split the body FIRST, so CHUNK_SIZE limits the body; header added after.
        for piece in splitter.create_documents([text]):
            body = piece.page_content
            documents.append(
                Document(
                    page_content=f"{chunk_header(product.title, section)}\n{body}",
                    metadata={
                        "product_id": product_id,
                        "site": product.site,
                        "title": product.title,
                        "section": section,
                        "chunk_index": len(documents),  # 0..n across the product
                        "start_index": piece.metadata["start_index"],
                        "body": body,
                    },
                )
            )
    return documents

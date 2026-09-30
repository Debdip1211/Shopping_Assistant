"""Chroma, our vector store: stores chunks + their embeddings on disk and finds
the chunks whose embeddings are closest to a question's embedding.

Everything is saved in DATA_DIR/chroma, so products survive a restart.
"""

from functools import lru_cache

import chromadb
from langchain_chroma import Chroma
from langchain_core.documents import Document

from app.config import settings
from app.rag.embeddings import get_embeddings

COLLECTION_NAME = "products"


@lru_cache(maxsize=1)
def get_vectorstore() -> Chroma:
    """Open (or create) the persisted Chroma collection once and reuse it."""
    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=get_embeddings(),
        persist_directory=str(settings.data_dir / "chroma"),
        # Compare vectors by the angle between them (cosine), the usual choice
        # for sentence embeddings: direction = meaning, length doesn't matter.
        collection_metadata={"hnsw:space": "cosine"},
        # All data stays local: don't send Chroma's anonymous usage statistics.
        client_settings=chromadb.config.Settings(anonymized_telemetry=False),
    )


def chunk_id(document: Document) -> str:
    """Deterministic chunk ID '<product_id>:<chunk_index>'."""
    return f"{document.metadata['product_id']}:{document.metadata['chunk_index']}"


def add_documents(documents: list[Document]) -> None:
    """Embed the documents and store them. Same IDs overwrite, never duplicate."""
    if documents:
        get_vectorstore().add_documents(documents, ids=[chunk_id(d) for d in documents])


def delete_product_chunks(product_id: str) -> None:
    """Remove every chunk of one product (used before re-ingesting it)."""
    get_vectorstore().delete(where={"product_id": product_id})

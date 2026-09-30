"""The embedding model: turns text into vectors (lists of numbers).

Texts with similar meaning get vectors that point in similar directions, so
"How long does the battery last?" lands close to a review saying "easily lasts
a full day". That closeness is what similarity search uses.

all-MiniLM-L6-v2 is small (~90 MB), free, and runs locally on the CPU, so
product text is never sent anywhere just to be embedded. It is downloaded from
Hugging Face once, on first use, and cached on disk after that.
"""

from functools import lru_cache

from langchain_huggingface import HuggingFaceEmbeddings

from app.config import settings


@lru_cache(maxsize=1)
def get_embeddings() -> HuggingFaceEmbeddings:
    """Load the embedding model once and reuse it (loading takes a few seconds)."""
    return HuggingFaceEmbeddings(model_name=settings.embedding_model)

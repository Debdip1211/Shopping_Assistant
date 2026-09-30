"""The HTTP API (FastAPI) that the Chrome extension talks to.

An API is a set of URLs ("endpoints") that other programs can call. Each
endpoint here is thin: it checks the request, calls the functions in app/ that
do the real work (the same ones the CLI and Streamlit use), and turns the
result, or an error, into an HTTP response with the right status code.

Run from the backend/ folder (with the virtual environment active):
    uvicorn app.main:app --reload --port 8000
Then open http://localhost:8000/docs to try every endpoint in the browser.

Endpoints are plain `def` (not `async def`) on purpose: embedding and LLM calls
are slow, blocking work, and FastAPI runs plain `def` endpoints in a thread pool
so one slow request doesn't freeze the whole server.
"""

import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.documents import Document

from app.ingest import NotEnoughContentError, ProductTooLargeError, ingest_product
from app.product_store import delete_all, delete_product, get_product, list_products
from app.rag.chain import NoProductsError, answer_current, answer_history
from app.rag.llm import LLMError
from app.rag.vectorstore import delete_product_chunks
from app.schemas import (
    ChatRequest,
    ChatResponse,
    IngestResponse,
    ProductIn,
    ProductSummary,
    Source,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

PRODUCT_NOT_FOUND = "Product not found. Please re-ingest."

app = FastAPI(
    title="Shopping Assistant API",
    description="Stores products viewed in the browser and answers questions about them (RAG).",
    version="1.0.0",
)

# CORS: browsers block a web page from calling a server on a different origin
# unless the server explicitly allows it. The side panel runs on
# chrome-extension://<id> and Streamlit on localhost:8501, so we allow exactly
# those origins, methods, and header, and nothing else.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^chrome-extension://.*$",
    allow_origins=["http://localhost:8501"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)


def document_to_source(document: Document) -> Source:
    """Convert a retrieved chunk into the API's Source format."""
    meta = document.metadata
    return Source(
        product_id=meta["product_id"],
        product_title=meta["title"],
        section=meta["section"],
        chunk_index=meta["chunk_index"],
        text=meta["body"],
    )


@app.get("/health")
def health() -> dict[str, str]:
    """Lets the extension check that the backend is running."""
    return {"status": "ok"}


@app.post("/ingest", response_model=IngestResponse)
def ingest(product: ProductIn) -> IngestResponse:
    """Store (or refresh) one product extracted from a page."""
    try:
        result = ingest_product(product)
    except NotEnoughContentError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
    except ProductTooLargeError as error:
        raise HTTPException(status_code=413, detail=str(error)) from None
    return IngestResponse(**vars(result))


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    """Answer a question about the current product or all viewed products."""
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Please type a question.")
    history = [message.model_dump() for message in request.history]

    try:
        if request.scope == "current":
            if not request.product_id:
                raise HTTPException(
                    status_code=400, detail="product_id is required for scope 'current'."
                )
            record = get_product(request.product_id)
            if record is None:
                raise HTTPException(status_code=404, detail=PRODUCT_NOT_FOUND)
            answer, mode, documents = answer_current(record, question, history)
        else:
            answer, mode, documents = answer_history(question, history)
    except NoProductsError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
    except LLMError as error:
        # The message is already friendly and never contains the token.
        raise HTTPException(status_code=502, detail=str(error)) from None

    return ChatResponse(
        answer=answer,
        scope=request.scope,
        mode=mode,
        sources=[document_to_source(d) for d in documents],
    )


@app.get("/products", response_model=list[ProductSummary])
def products() -> list[ProductSummary]:
    """All saved products, most recently seen first."""
    return [ProductSummary(**record.model_dump()) for record in list_products()]


@app.delete("/products/{product_id}")
def delete_one(product_id: str) -> dict[str, bool]:
    """Forget one product: its record and all its chunks."""
    if not delete_product(product_id):
        raise HTTPException(status_code=404, detail=PRODUCT_NOT_FOUND)
    delete_product_chunks(product_id)
    logger.info("Deleted product %s", product_id)
    return {"deleted": True}


@app.delete("/products")
def delete_everything() -> dict[str, int]:
    """Forget every product."""
    for record in list_products():
        delete_product_chunks(record.product_id)
    count = delete_all()
    logger.info("Deleted all %d products", count)
    return {"deleted_count": count}

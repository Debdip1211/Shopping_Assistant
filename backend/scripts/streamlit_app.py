"""Phase 2 prototype UI: a quick web page to try the RAG pipeline.

Run from the backend/ folder (with the virtual environment active):
    python -m streamlit run scripts/streamlit_app.py --browser.gatherUsageStats false

How Streamlit works: it re-runs this whole script from top to bottom every time
you click something or send a message. Anything that must survive between
re-runs (like the chat messages) is kept in `st.session_state`.

All the real work is done by functions from app/, the same ones the CLI uses.
"""

from typing import Any

import streamlit as st
from pydantic import ValidationError

from app.ingest import (
    IngestResult,
    NotEnoughContentError,
    ProductTooLargeError,
    ingest_product,
    load_samples,
)
from app.product_store import ProductRecord, list_products
from app.rag.chain import NoProductsError, answer_current, answer_history, decide_mode
from app.rag.llm import LLMError
from app.schemas import ProductIn

ALL_SCOPE = "all"  # scope key for "All viewed products"; otherwise a product_id
MODE_LABELS = {"full_context": "Full product", "rag": "RAG"}

# One chat message as stored in session_state:
# {"role": "user" | "assistant", "content": str, "mode": str, "sources": [dict]}
Message = dict[str, Any]


# ---------- session state ----------

def get_chat(scope: str) -> list[Message]:
    """Return the message list for a scope (each scope has its own chat)."""
    chats: dict[str, list[Message]] = st.session_state.setdefault("chats", {})
    return chats.setdefault(scope, [])


def history_for_llm(messages: list[Message]) -> list[dict[str, str]]:
    """Only role + content, which is what the chain expects as history."""
    return [{"role": m["role"], "content": m["content"]} for m in messages]


# ---------- sidebar: ingesting products ----------

def ingest_line(result: IngestResult) -> str:
    """One readable line describing an ingest result."""
    status = "cached" if result.cached else "ingested"
    return (f"**{result.title[:40]}** — {MODE_LABELS[result.mode]}, "
            f"{result.num_chunks} chunks ({status})")


def ingest_samples_button() -> None:
    """Button that ingests every sample product."""
    if st.button("Ingest sample products", use_container_width=True):
        with st.spinner("Ingesting (the first time loads the embedding model)..."):
            st.session_state["ingest_log"] = [
                ingest_line(ingest_product(p)) for p in load_samples()
            ]


def upload_product_form() -> None:
    """File uploader for one product JSON in the ProductIn format."""
    uploaded = st.file_uploader("Or upload a product JSON", type="json")
    if uploaded is None or not st.button("Ingest uploaded file", use_container_width=True):
        return
    try:
        product = ProductIn.model_validate_json(uploaded.getvalue())
        with st.spinner("Ingesting..."):
            st.session_state["ingest_log"] = [ingest_line(ingest_product(product))]
    except ValidationError as error:
        st.error(f"This file isn't a valid product JSON:\n\n{error}")
    except (NotEnoughContentError, ProductTooLargeError) as error:
        st.error(str(error))


def render_sidebar() -> None:
    """Sidebar: ingest controls, last ingest results, saved products."""
    with st.sidebar:
        st.header("Products")
        ingest_samples_button()
        upload_product_form()
        for line in st.session_state.get("ingest_log", []):
            st.markdown(f"- {line}")
        st.divider()
        # Read after the buttons above, so a fresh ingest shows up immediately.
        records = list_products()
        st.subheader(f"Saved products ({len(records)})")
        for record in records:
            st.caption(f"{record.title[:50]} · {record.site} · {record.price or '—'}")


# ---------- main area: chat ----------

def choose_scope(records: list[ProductRecord]) -> str:
    """Dropdown to pick the scope. Returns ALL_SCOPE or a product_id."""
    titles = {r.product_id: r.title for r in records}
    return st.selectbox(
        "Scope",
        options=[ALL_SCOPE, *titles],
        format_func=lambda key: (
            "All viewed products" if key == ALL_SCOPE else f"This product: {titles[key]}"
        ),
    )


def render_sources(sources: list[dict[str, str]]) -> None:
    """Expandable list of sources, numbered like the citations in the answer."""
    if not sources:
        return
    with st.expander(f"Sources ({len(sources)})"):
        for number, source in enumerate(sources, start=1):
            st.markdown(f"**[{number}] {source['title']}** · `{source['section']}`")
            st.caption(source["body"])


def render_message(message: Message) -> None:
    """Show one chat message (and its sources, for the assistant)."""
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] == "assistant":
            st.caption(f"Mode: {MODE_LABELS[message['mode']]}")
            render_sources(message["sources"])


def ask(scope: str, record: ProductRecord | None, question: str) -> Message | None:
    """Run the chain for the question. Returns the assistant message, or None on error."""
    history = history_for_llm(get_chat(scope))
    try:
        with st.spinner("Thinking..."):
            if record is None:
                answer, mode, documents = answer_history(question, history)
            else:
                answer, mode, documents = answer_current(record, question, history)
    except (LLMError, NoProductsError) as error:
        st.error(str(error))
        return None
    sources = [
        {"title": d.metadata["title"], "section": d.metadata["section"],
         "body": d.metadata["body"]}
        for d in documents
    ]
    return {"role": "assistant", "content": answer, "mode": mode, "sources": sources}


def render_chat(records: list[ProductRecord]) -> None:
    """Scope picker, the chat so far, and the input box."""
    scope = choose_scope(records)
    record = next((r for r in records if r.product_id == scope), None)
    if record is not None:
        st.caption(f"{record.price or 'Price not listed'} · {record.rating or 'No rating'} · "
                   f"Mode: {MODE_LABELS[decide_mode(record)]}")

    chat = get_chat(scope)
    for message in chat:
        render_message(message)

    question = st.chat_input("Ask a question about the product(s)")
    if question and question.strip():
        user_message: Message = {"role": "user", "content": question.strip()}
        render_message(user_message)
        reply = ask(scope, record, question.strip())
        if reply is not None:
            chat.extend([user_message, reply])
            render_message(reply)

    if chat and st.button("Clear chat"):
        chat.clear()
        st.rerun()


def main() -> None:
    """Build the page."""
    st.set_page_config(page_title="Shopping Assistant (prototype)", page_icon="🛒")
    st.title("🛒 Shopping Assistant — prototype")
    render_sidebar()
    records = list_products()
    if not records:
        st.info("No products saved yet. Use **Ingest sample products** in the sidebar.")
        return
    render_chat(records)


main()

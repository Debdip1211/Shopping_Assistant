"""Tests for the answering logic (app/rag/chain.py).

The LLM and the vector search are replaced with fakes ("mocks") using pytest's
`monkeypatch`, so these tests never call the real API, never spend credits,
and don't need the embedding model or a .env file.
"""

import dataclasses
from datetime import datetime, timezone
from pathlib import Path

import pytest
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.config import BACKEND_DIR, settings
from app.product_store import ProductRecord
from app.rag import chain
from app.schemas import ProductIn, ProductSections

NOW = datetime(2026, 9, 24, 10, 30, tzinfo=timezone.utc)


def make_record(product_id: str = "p1", title: str = "Nimbus X5", specs: str = "Battery: 5000 mAh") -> ProductRecord:
    """A small stored product for tests."""
    return ProductRecord(
        product_id=product_id, key=f"test:{product_id}", url="https://shop.example/p",
        site="amazon", title=title, price="₹18,999", rating="4.1 out of 5",
        rating_count="100 ratings", content_hash="h", char_count=len(specs),
        num_chunks=1, sections_found=["specs"], captured_at=NOW, first_seen=NOW,
        last_seen=NOW, sections=ProductSections(specs=specs),
    )


def make_doc(product_id: str, index: int, body: str, section: str = "specs") -> Document:
    """A fake retrieved chunk."""
    return Document(
        page_content=f"header\n{body}",
        metadata={"product_id": product_id, "title": "t", "section": section,
                  "chunk_index": index, "start_index": 0, "body": body},
    )


class FakeLLM:
    """Stands in for invoke_llm: records the messages and returns a fixed answer."""

    def __init__(self) -> None:
        self.messages: list[BaseMessage] = []

    def __call__(self, messages: list[BaseMessage]) -> str:
        self.messages = messages
        return "fake answer [1]"


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> FakeLLM:
    fake = FakeLLM()
    monkeypatch.setattr(chain, "invoke_llm", fake)
    return fake


# ---------- decide_mode ----------

def test_decide_mode_short_product_is_full_context() -> None:
    record = make_record(specs="x" * settings.full_context_char_limit)
    assert chain.decide_mode(record) == "full_context"


def test_decide_mode_long_product_is_rag() -> None:
    record = make_record(specs="x" * (settings.full_context_char_limit + 1))
    assert chain.decide_mode(record) == "rag"


def test_sample_products_modes() -> None:
    samples = Path(BACKEND_DIR) / "samples" / "products"
    modes = {
        path.name: chain.decide_mode(ProductIn.model_validate_json(path.read_text()))
        for path in samples.glob("*.json")
    }
    assert modes == {
        "phone_a.json": "rag",
        "phone_b.json": "full_context",
        "phone_c.json": "full_context",
        "laptop_a.json": "full_context",
    }


# ---------- history trimming ----------

def make_history(count: int) -> list[dict[str, str]]:
    roles = ["user", "assistant"]
    return [{"role": roles[i % 2], "content": f"message {i}"} for i in range(count)]


def test_trim_history_keeps_only_most_recent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chain, "settings", dataclasses.replace(settings, max_history_messages=4))
    trimmed = chain.trim_history(make_history(10))
    assert [m.content for m in trimmed] == ["message 6", "message 7", "message 8", "message 9"]


def test_trim_history_converts_roles_and_skips_bad_items() -> None:
    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "system", "content": "ignore me"},
        {"role": "user", "content": "   "},
    ]
    trimmed = chain.trim_history(history)
    assert [type(m) for m in trimmed] == [HumanMessage, AIMessage]


def test_trim_history_zero_limit_keeps_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chain, "settings", dataclasses.replace(settings, max_history_messages=0))
    assert chain.trim_history(make_history(4)) == []


# ---------- answer_current / answer_history (LLM + retrieval mocked) ----------

def test_answer_current_builds_prompt_and_returns_sources(
    monkeypatch: pytest.MonkeyPatch, fake_llm: FakeLLM
) -> None:
    docs = [make_doc("p1", 0, "Battery: 5000 mAh"), make_doc("p1", 1, "Great battery life", "reviews")]
    monkeypatch.setattr(chain, "retrieve_for_product", lambda *args: docs)
    history = [{"role": "user", "content": "earlier q"}, {"role": "assistant", "content": "earlier a"}]

    answer, mode, sources = chain.answer_current(make_record(), "How is the battery?", history)

    assert (answer, mode, sources) == ("fake answer [1]", "full_context", docs)
    system, *middle, last = fake_llm.messages
    assert isinstance(system, SystemMessage)
    assert "[1] (specs) Battery: 5000 mAh" in system.content
    assert "[2] (reviews) Great battery life" in system.content
    assert "## Specs" in system.content  # full_context includes the whole text
    assert [m.content for m in middle] == ["earlier q", "earlier a"]
    assert isinstance(last, HumanMessage) and last.content == "How is the battery?"


def test_answer_history_numbers_excerpts_across_products(
    monkeypatch: pytest.MonkeyPatch, fake_llm: FakeLLM
) -> None:
    groups = [
        (make_record("p1", "Phone One"), [make_doc("p1", 0, "one-a"), make_doc("p1", 1, "one-b")]),
        (make_record("p2", "Phone Two"), [make_doc("p2", 0, "two-a")]),
    ]
    monkeypatch.setattr(chain, "retrieve_across_products", lambda *args: groups)

    _, mode, sources = chain.answer_history("Compare them", [])

    assert mode == "rag"
    assert [d.metadata["body"] for d in sources] == ["one-a", "one-b", "two-a"]
    system = fake_llm.messages[0].content
    assert "### Product 1: Phone One" in system and "### Product 2: Phone Two" in system
    assert system.index("[3] (specs) two-a") > system.index("### Product 2")


def test_answer_history_without_products_raises(monkeypatch: pytest.MonkeyPatch, fake_llm: FakeLLM) -> None:
    monkeypatch.setattr(chain, "retrieve_across_products", lambda *args: [])
    with pytest.raises(chain.NoProductsError):
        chain.answer_history("Compare them", [])
    assert fake_llm.messages == []  # the LLM was never called


# ---------- answer cleanup ----------

def test_clean_answer_removes_emoji_but_keeps_rupee_and_markdown() -> None:
    check, phone, star = chr(0x2705), chr(0x1F4F1), chr(0x2B50)
    rupee = chr(0x20B9)
    raw = f"Best pick {check}\n\n\n**Nimbus X5** {phone} costs {rupee}18,999 [1] {star}"
    assert chain.clean_answer(raw) == f"Best pick\n\n**Nimbus X5** costs {rupee}18,999 [1]"


def test_answers_are_cleaned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chain, "retrieve_for_product", lambda *args: [make_doc("p1", 0, "Battery: 5000 mAh")])
    monkeypatch.setattr(chain, "invoke_llm", lambda messages: "Great battery " + chr(0x2705))
    answer, _, _ = chain.answer_current(make_record(), "How is the battery?", [])
    assert answer == "Great battery"

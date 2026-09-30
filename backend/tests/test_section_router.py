"""Tests for the keyword section router (app/rag/section_router.py)."""

import pytest

from app.rag.section_router import route_sections


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("What do reviewers complain about?", ["reviews"]),
        ("What is the overall customer feedback?", ["reviews"]),
        ("How big is the battery?", ["specs"]),
        ("Does it have a 120Hz display?", ["specs"]),
        ("How much RAM and storage does it have?", ["specs"]),
        ("Does it support 5G?", ["specs"]),
        ("Is there a bank offer?", ["offers"]),
        ("Can I buy it on no cost EMI?", ["offers"]),
        ("Any exchange discount?", ["offers"]),
        ("What do customers say about the camera?", ["reviews", "specs"]),
        ("Which has better reviews and a better deal?", ["reviews", "offers"]),
    ],
)
def test_questions_route_to_expected_sections(
    question: str, expected: list[str]
) -> None:
    assert route_sections(question) == expected


@pytest.mark.parametrize(
    "question",
    [
        "What is the price?",
        "Tell me about this product.",
        "Compare the last three phones I looked at.",
        # Keywords hidden inside other words must NOT match:
        "Is this a premium phone?",       # "emi" inside "premium"
        "Is it good for programming?",    # "ram" inside "programming"
        "Would this be an ideal gift?",   # "deal" inside "ideal"
    ],
)
def test_unrelated_questions_return_none(question: str) -> None:
    assert route_sections(question) is None

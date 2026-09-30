"""Section router: guess which product sections a question is about.

"What do reviewers complain about?" should search only review chunks;
"How big is the battery?" only spec chunks. Restricting the search this way
(metadata filtering) stops, e.g., a spec table from crowding out reviews.

This is a deliberately simple first version: plain keyword rules that are easy
to read and test. A possible later improvement is asking an LLM to classify the
question, which handles unusual wording better but is slower and costs credits.
"""

import re

# Keywords per section (lowercase). A question may match several sections.
SECTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "reviews": (
        "review", "reviewer", "customers", "people say", "complain",
        "complaint", "feedback", "experience", "users say",
    ),
    "specs": (
        "spec", "battery", "mah", "ram", "storage", "processor", "chip",
        "display", "screen", "hz", "refresh rate", "camera", "weight",
        "dimension", "size", "charging", "5g", "warranty",
    ),
    "offers": (
        "offer", "discount", "bank", "emi", "coupon", "cashback", "exchange", "deal",
    ),
}


def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    """Match a keyword at the START of a word.

    `(?<![a-z])` means "not preceded by a letter", so:
      - "reviews" matches "review" and "120hz" matches "hz" (plural / after digits)
      - "premium" does NOT match "emi", "program" does NOT match "ram"
    """
    return re.compile(r"(?<![a-z])" + re.escape(keyword))


_PATTERNS = {
    section: [_keyword_pattern(k) for k in keywords]
    for section, keywords in SECTION_KEYWORDS.items()
}


def route_sections(question: str) -> list[str] | None:
    """Return the sections the question is about, or None for "search everything"."""
    text = question.lower()
    matched = [
        section
        for section, patterns in _PATTERNS.items()
        if any(p.search(text) for p in patterns)
    ]
    return matched or None

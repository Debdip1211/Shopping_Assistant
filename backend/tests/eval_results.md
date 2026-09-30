# Evaluation results

Manual evaluation of the RAG pipeline on the 14 questions in `eval_questions.json`,
using the fictional sample products. Raw answers and sources for each run are in
`eval_raw_<label>.md`.

**Grading scale**
- Answer: ✅ correct (key facts right, nothing invented) · ⚠️ partly (something important missing, or a prompt rule broken) · ❌ wrong (incorrect or invented facts)
- Citations: ✅ the `[n]` numbers point to chunks that contain the facts · ⚠️ some missing or wrong · ❌ none / all wrong · — not applicable

## Run 1: baseline (Qwen3-235B-A22B-Instruct-2507)

Settings: `CHUNK_SIZE=800`, `CHUNK_OVERLAP=100`, `FULL_CONTEXT_CHAR_LIMIT=12000`,
`CURRENT_TOP_K=5`, `PER_PRODUCT_K=2`, `MAX_COMPARE_PRODUCTS=8`, `LLM_MAX_TOKENS=512`.
Questions 1–11 run on 2026-09-27 (`eval_raw_baseline_qwen.md`); questions 12–14 hit HTTP 402
that day and were run on 2026-09-28 (`eval_raw_baseline_qwen_q12-14.md`). Two differences for
12–14: the prompts now include the no-emoji rule, and two real products (vivo S2, Samsung A56)
were saved, so "All viewed products" compared six products instead of four.

| # | Scope | Type | Question | Answer | Citations | Notes |
|---|---|---|---|---|---|---|
| 1 | current (Nimbus, rag) | reviews | What do reviewers complain about? | ✅ | ✅ | Heating, bloatware/ads, low-light camera, weak vibration, defective unit; mentions balance with praise. Misses fingerprint, headphone jack, network, after-sales: those reviews weren't in the top 5 chunks (rag-mode limit). |
| 2 | current (Nimbus, rag) | reviews | What do people say about the battery life? | ✅ | ✅ | Accurate and well cited. Misses "drains on weak 5G" (not retrieved). |
| 3 | current (Vortex, full) | reviews | What do reviewers say about charging? | ✅ | ✅ | 10W charger, ~3 hours, 18W sold separately; quotes the review and cites it correctly. |
| 4 | current (Nimbus, rag) | specs | Does this phone have a headphone jack? | ✅ | ✅ | Cites the spec [3] and the review [2]. |
| 5 | current (Kairo, full) | specs | How fast does it charge? | ✅ | ⚠️ | Facts correct; cites the review [1] but not the description/spec for 67W / 42 min. |
| 6 | current (laptop, full) | specs | Can I upgrade the RAM or storage later? | ✅ | ✅ | RAM soldered, SSD in M.2 slot up to 2 TB. |
| 7 | current (Vortex, full) | offers | Is there any bank offer? | ✅ | ✅ | Both Axis offers; states they were available at capture time (2026-09-23). |
| 8 | current (Nimbus, rag) | not in data | Is this phone waterproof? What is its IP rating? | ✅ | — | "I couldn't find that"; nothing invented. |
| 9 | current (Kairo, full) | not in data | Does it support wireless charging? | ✅ | — | "I couldn't find that", mentions 67W wired instead. |
| 10 | history | cross-product specs | Which of these phones has a 120Hz display? | ✅ | ✅ | Kairo 144Hz, Nimbus 120Hz, Vortex 90Hz, each cited. |
| 11 | history | cross-product specs | Compare the three phones on battery capacity and charging speed. | ⚠️ | ⚠️ | Table fully correct, but the answer is **cut off mid-sentence** (hit `LLM_MAX_TOKENS=512`). Cites [4] for Vortex's 6000 mAh; it's in [3]. |
| 12 | history | cross-product (price) | Which product is the cheapest? | ✅ | ⚠️ | Vortex Neo 12 at ₹16,499, all six prices listed, notes prices may have changed. Prices come from the (unnumbered) summary cards, so the cited excerpts don't contain them. |
| 13 | history | cross-product reviews | Which phone do reviewers praise most for battery life? | ✅ | ⚠️ | Vortex ("Battery king", standby), Nimbus also mentioned. Overstates Kairo ("positive remarks about battery"; its reviews call it average). One claim uncited. |
| 14 | history | cross-product specs | Which of these products have a 3.5mm headphone jack? | ⚠️ | ✅ | Vortex yes, Nimbus no: correct. Kairo "not confirmed" and laptop "not applicable": both have the answer in spec chunks that weren't retrieved (2 chunks per product, and "headphone jack" doesn't trigger the specs filter). Honest about missing evidence. |

**Final baseline score (14 questions):** answers 12 ✅ / 2 ⚠️ / 0 ❌ · citations 8 ✅ / 4 ⚠️ / 0 ❌ (2 n/a)

### Observations
- **Retrieval works:** in every answered question the needed facts were in the retrieved chunks, except details that simply didn't make the top-k in `rag` mode (questions 1 and 2).
- **"Not in the data" handled correctly:** both unanswerable questions were refused without inventing facts.
- **New issue: answer length.** Qwen writes longer, more structured answers (tables, summaries); the 512-token cap truncated question 11.
- **Section router gaps:** "headphone jack", "waterproof", "IP rating", and "charge" match no keywords, so those questions searched all sections. For single products this didn't matter, but it contributed to question 14: without the specs filter, review chunks took some of the only 2 slots per product.
- **Cross-product retrieval depth:** with `PER_PRODUCT_K=2`, facts buried in long spec lists (question 14) can be missed. The model then correctly says "not confirmed" instead of guessing.
- **Price citations:** price answers come from the summary cards, which have no excerpt number, so citations for prices point at unrelated chunks (question 12).

**Candidates for the one change** (each targets an observed failure): `PER_PRODUCT_K` 2 → 3 (question 14),
adding router keywords like "jack", "charge", "waterproof" (question 14), or `LLM_MAX_TOKENS` 512 → 1024 (question 11).

### Context: partial Llama 3.1 8B run (before switching models)
An earlier run with `meta-llama/Llama-3.1-8B-Instruct` (`eval_raw_baseline.md`, questions 1–9 only)
scored answers 4 ✅ / 5 ⚠️ on the same questions. The retrieved chunks were almost identical;
the difference was the model: Llama said "I couldn't find that" before correct answers (Q4, Q6),
missed citations (Q5), and ignored the "offers may have changed" rule (Q7). On the same
questions Qwen scored 9 ✅. This is why the project switched models (decision #15 in CLAUDE.md).

## Run 2: one change — `PER_PRODUCT_K` 2 → 3 (in progress)

`PER_PRODUCT_K` only affects "All viewed products", so only questions 10–14 are compared.
Both runs use a separate data folder holding only the four samples (`DATA_DIR=./data/eval`), so
the set of products is identical. Everything else as in Run 1 (including the no-emoji prompt rule).

Both runs use `LLM_ROUTING=cheapest` (decision #19), so the same provider serves both.

### Before: `PER_PRODUCT_K=2` (`eval_raw_samples_k2.md`, 2026-09-29 06:29 UTC, routing: cheapest)

| # | Question | Answer | Citations | Notes |
|---|---|---|---|---|
| 10 | Which of these phones has a 120Hz display? | ✅ | ✅ | Kairo 144Hz, Nimbus 120Hz, Vortex 90Hz, each cited to the right spec chunk. |
| 11 | Compare the three phones on battery capacity and charging speed. | ✅ | ✅ | Table fully correct and cited per cell (incl. Vortex's 10W in-box charger); not cut off this time. |
| 12 | Which product is the cheapest? | ✅ | ⚠️ | Correct price table, notes prices may have changed; the one citation points at an offers chunk without prices (prices come from the summary cards). |
| 13 | Which phone do reviewers praise most for battery life? | ✅ | ✅ | Vortex, with accurate quotes; Kairo correctly described as average, with the fast charging noted. |
| 14 | Which of these products have a 3.5mm headphone jack? | — | — | Pending (HTTP 402). |

(An earlier run the same morning with default routing gave the same grades except question 11,
which was cut off at 512 tokens; its raw file was overwritten by this run.)

### After: `PER_PRODUCT_K=3`

Pending (HTTP 402 on 2026-09-29).

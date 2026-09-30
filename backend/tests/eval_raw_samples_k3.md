# Eval run: samples_k3 (questions 10-14)

Run at 2026-09-29 06:29 UTC

- Model: `Qwen/Qwen3-235B-A22B-Instruct-2507` (routing: cheapest, max tokens 512)
- CHUNK_SIZE=800, CHUNK_OVERLAP=100, FULL_CONTEXT_CHAR_LIMIT=12000
- CURRENT_TOP_K=5, PER_PRODUCT_K=3, MAX_COMPARE_PRODUCTS=8
- DATA_DIR=`/Users/debdipchoudhuri/Desktop/shopping-assistant/backend/data/eval`

## 10. [history · all products] Which of these phones has a 120Hz display?

**Expected:** Nimbus X5 5G has 120Hz. Kairo Z3 Pro has 144Hz (even higher). Vortex Neo 12 has 90Hz. (The laptop is 60Hz.)

**Sections routed:** ['specs']

**Error:** Your Hugging Face inference credits are used up or you're being rate-limited. Check your billing page.

**Grade:** correct / partly / wrong — **Citations:** ok / missing / wrong — **Notes:**

## 11. [history · all products] Compare the three phones on battery capacity and charging speed.

**Expected:** Nimbus X5: 5000 mAh, 33W. Vortex Neo 12: 6000 mAh, 18W supported but only a 10W charger in the box. Kairo Z3 Pro: 4500 mAh, 67W.

**Sections routed:** ['specs']

**Error:** Your Hugging Face inference credits are used up or you're being rate-limited. Check your billing page.

**Grade:** correct / partly / wrong — **Citations:** ok / missing / wrong — **Notes:**

## 12. [history · all products] Which product is the cheapest?

**Expected:** Vortex Neo 12 5G at Rs 16,499 (Nimbus Rs 18,999, Kairo Rs 21,999, Aerolite laptop Rs 54,990). Should note prices were captured when viewed and may have changed.

**Sections routed:** none (no filter)

**Error:** Your Hugging Face inference credits are used up or you're being rate-limited. Check your billing page.

**Grade:** correct / partly / wrong — **Citations:** ok / missing / wrong — **Notes:**

## 13. [history · all products] Which phone do reviewers praise most for battery life?

**Expected:** Vortex Neo 12 (lasts about two days, 'battery king') and Nimbus X5 (full day of heavy use). Kairo Z3 Pro's battery is called average, saved by fast charging. Should say evidence is limited to a few excerpts.

**Sections routed:** ['reviews', 'specs']

**Error:** Your Hugging Face inference credits are used up or you're being rate-limited. Check your billing page.

**Grade:** correct / partly / wrong — **Citations:** ok / missing / wrong — **Notes:**

## 14. [history · all products] Which of these products have a 3.5mm headphone jack?

**Expected:** Vortex Neo 12 (yes) and the Aerolite laptop (3.5mm audio jack). Nimbus X5 and Kairo Z3 Pro do not.

**Sections routed:** none (no filter)

**Error:** Your Hugging Face inference credits are used up or you're being rate-limited. Check your billing page.

**Grade:** correct / partly / wrong — **Citations:** ok / missing / wrong — **Notes:**

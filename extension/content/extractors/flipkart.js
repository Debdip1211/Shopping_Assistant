// Flipkart product-page extractor.
//
// Flipkart's class names are auto-generated (e.g. "css-146c3p1 r-dnmrzs") and
// change often, so this file never uses them. Order of preference: JSON-LD data
// -> the page's <h1> -> finding a section by its heading TEXT or by a typical
// label ("Display Size") and reading the text around it. All patterns live in
// SELECTORS; they were verified in Chrome DevTools on 2026-09-27 and will need
// re-checking when Flipkart changes its layout.

(() => {
  const SA = window.__SA__;
  const RUPEE = String.fromCharCode(0x20b9); // the "₹" sign

  const SELECTORS = {
    title: ["h1"],
    pricePattern: new RegExp(`^${RUPEE}\\s?[\\d,]+(\\.\\d+)?$`), // a price on its own: "₹16,499"
    ratingPattern: /^[1-5](\.\d)?$/, // e.g. "4.3" next to the title
    ratingCountPattern: /^[\d,]+\s+ratings\b/i, // e.g. "8,210 Ratings & 612 Reviews"
    // Verified 2026-09-27: "Key Highlights" / "Product highlights" / "Description".
    highlightsHeading: /^(key highlights|product highlights|highlights)$/i,
    descriptionHeading: /^(product )?description$/i,
    specsHeading: /^specifications$/i,
    allDetailsHeading: /^all details$/i, // the tabbed details section below the buy area
    // Verified 2026-09-30: variant rows have a text label ("Selected Color:", "Variant:",
    // "Color") next to links to each variant's own page (<a href="...pid=...">). Storage
    // links read "128 GB ₹69,900"; colour swatches are images whose text is just "Image".
    variantLabel: /^(selected\s+)?(colou?r|variant|storage|ram|size)\s*:?$/i,
    variantLink: 'a[href*="pid="]',
    unnamedOption: /^(image)?$/i,
    // Verified 2026-09-27: specs are no longer a <table>. Each spec is a <div> with two
    // children, label + value ("Display Size" / "15.49 cm (6.1 inch)"). These common
    // labels locate the specs area.
    specAnchorLabels: /^(model number|model name|display size|ram|internal storage|battery capacity|operating system|processor brand|brand)$/i,
    // Verified 2026-09-27: heading changed from "Available offers".
    offersHeading: /^(available offers|apply offers for unbeatable deal)$/i,
    // Verified 2026-09-27: offers sit under "Bank offers" / "Exchange offer" / "View EMI offers".
    offerAnchor: /bank offer|cashback|no cost emi|emi offer|exchange offer|special price/i,
    // Verified 2026-09-27: every review card has "Verified Buyer" ("Certified Buyer" before).
    // \W* allows a check-mark symbol in front of the label.
    reviewMarker: /^\W*(verified|certified) buyer/i,
    reviewStars: /^[1-5](\.\d)?\W?$/, // "5" or "5★" at the top of a card
    // Lines inside a review card that aren't the review itself.
    reviewNoise: /^(read more|more|report abuse|permalink|\W*(verified|certified) buyer.*|\d+|\d+ (days?|months?|years?) ago|[a-z]{3}, \d{4})$/i,
  };

  const MAX_BLOCK_LINES = 60;
  // A block must have at least this much real text to count (highlights are short lists).
  const MIN_DESCRIPTION_CHARS = 80;
  const MIN_HIGHLIGHTS_CHARS = 20;
  // Tab and section names (and rating fragments like "4.6", "| 1.9L+") that sit next to
  // headings but aren't content. Verified 2026-09-27 on the "All details" tab bar.
  const NOT_CONTENT = /^(showcase|specifications|description|warranty|manufacturer info|all details|highlights|key highlights|product highlights|other details|[\d.,|+ lk]+)$/i;

  /** Leaf elements (no child elements) whose text matches a pattern. */
  const leavesMatching = (pattern, root = document) =>
    [...root.querySelectorAll("div, span, p")].filter(
      (el) => el.childElementCount === 0 && pattern.test(SA.cleanLine(el.textContent))
    );

  /** Keep only elements that come after `anchor` in the page. */
  const after = (anchor, elements) =>
    anchor
      ? elements.filter((el) => anchor.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING)
      : elements;

  const linesOf = (el) => SA.cleanBlock(el.innerText).split("\n").filter(Boolean);

  // ---------- price and rating (used only when JSON-LD is missing) ----------

  /** Among the first prices after the title, the one in the biggest font. */
  const extractPrice = (titleEl) => {
    const candidates = after(titleEl, leavesMatching(SELECTORS.pricePattern)).slice(0, 15);
    let best = null;
    let bestSize = 0;
    candidates.forEach((el) => {
      const size = parseFloat(getComputedStyle(el).fontSize) || 0;
      if (size > bestSize) {
        best = el;
        bestSize = size;
      }
    });
    return best ? SA.cleanLine(best.textContent) : null;
  };

  const extractRating = (titleEl) => {
    const el = after(titleEl, leavesMatching(SELECTORS.ratingPattern))[0];
    return el ? `${SA.cleanLine(el.textContent)} out of 5` : null;
  };

  const extractRatingCount = () => {
    const el = [...document.querySelectorAll("span, div")].find((candidate) => {
      const text = SA.cleanLine(candidate.textContent);
      return text.length < 60 && SELECTORS.ratingCountPattern.test(text);
    });
    return el ? SA.cleanLine(el.textContent) : null;
  };

  // ---------- text blocks under a heading (description, offers) ----------

  /**
   * Text under a heading, for description-like sections. Ignored: tab names,
   * rating fragments, and lines already used as specs (`skip`). A block counts
   * once it holds `minChars` of real text; we never climb into the title area.
   */
  const blockUnder = (pattern, minChars, skip) => {
    const heading = SA.findHeading(pattern);
    const titleEl = document.querySelector("h1");
    if (!heading) return "";
    let el = heading.parentElement;
    for (let level = 0; el && el !== document.body && level < 6; level += 1, el = el.parentElement) {
      if (titleEl && el.contains(titleEl)) break;
      const lines = linesOf(el).filter((line) => !NOT_CONTENT.test(line) && !skip.has(line));
      if (lines.length > MAX_BLOCK_LINES) break;
      if (lines.join(" ").length >= minChars) return SA.unique(lines).join("\n");
    }
    return "";
  };

  /** Highlights + description. `specs` lines are passed in so they aren't repeated. */
  const extractDescription = (specs) => {
    const skip = new Set();
    specs.split("\n").forEach((line) => {
      const [label, ...rest] = line.split(": ");
      skip.add(label);
      skip.add(rest.join(": "));
    });
    return [
      blockUnder(SELECTORS.highlightsHeading, MIN_HIGHLIGHTS_CHARS, skip),
      blockUnder(SELECTORS.descriptionHeading, MIN_DESCRIPTION_CHARS, skip),
    ]
      .filter(Boolean)
      .join("\n\n");
  };

  /**
   * Lines of the biggest box around `start` that still doesn't contain `stopAt`
   * (the product title), capped at MAX_BLOCK_LINES.
   */
  const linesBelow = (start, stopAt) => {
    let lines = [];
    let el = start;
    for (let level = 0; el && el !== document.body && level < 8; level += 1, el = el.parentElement) {
      if (stopAt && el.contains(stopAt)) break;
      const next = linesOf(el);
      if (next.length > MAX_BLOCK_LINES) break;
      lines = next;
    }
    return lines;
  };

  const extractOffers = () => {
    // Old layout: <li> items under "Available offers".
    const heading = SA.findHeading(SELECTORS.offersHeading);
    const list = heading && SA.containerWith(heading, "li", 3);
    const items = list
      ? [...list.querySelectorAll("li")]
          .map((li) => SA.cleanLine(li.innerText).replace(/\s*T&C$/i, ""))
          .filter(Boolean)
      : [];
    if (items.length) return SA.unique(items).join("\n");
    // 2026 layout: offers are separate boxes ("Bank offers", "Exchange offer", "View EMI
    // offers") in the buy area. Collect the box around EVERY offer label above "All
    // details"; labels further down belong to "similar products" carousels.
    const titleEl = document.querySelector("h1");
    const allDetails = SA.findHeading(SELECTORS.allDetailsHeading);
    const allAnchors = leavesMatching(SELECTORS.offerAnchor);
    const aboveDetails = allAnchors.filter(
      (el) => !allDetails || el.compareDocumentPosition(allDetails) & Node.DOCUMENT_POSITION_FOLLOWING
    );
    // Fallback for other layouts: the first few offer labels anywhere on the page.
    const anchors = aboveDetails.length ? aboveDetails.slice(0, 10) : allAnchors.slice(0, 3);
    const lines = anchors.flatMap((anchor) => linesBelow(anchor, titleEl));
    return SA.unique(lines).slice(0, MAX_BLOCK_LINES).join("\n");
  };

  // ---------- specs ----------

  /**
   * "Label: value" lines from <div>s holding exactly two children: a short
   * one-line label that starts with a letter, and a short value.
   */
  const labelValuePairs = (container) => {
    // Pass 1: <div>s with exactly two children that contain text (empty divider
    // lines are ignored): a short one-line label and a value.
    const candidates = [];
    container.querySelectorAll("div").forEach((el) => {
      const parts = [...el.children].filter((child) => SA.cleanLine(child.innerText));
      if (parts.length !== 2) return;
      const [label, value] = parts.map((child) => SA.cleanBlock(child.innerText));
      const labelOk =
        /^[a-z]/i.test(label) && !label.includes("\n") && !label.includes(RUPEE) && label.length <= 40;
      const valueOk = value && value !== label && value.length <= 600;
      if (labelOk && valueOk) candidates.push({ el, valueEl: parts[1], label, value });
    });
    // Pass 2: a group ("Dimensions" + all its specs) looks like a pair too; skip any
    // candidate whose value contains other candidates.
    const lines = candidates
      .filter((c) => !candidates.some((other) => other !== c && c.valueEl.contains(other.el)))
      .map((c) => `${c.label}: ${c.value.split("\n").join(", ")}`);
    // A group title plus its only spec ("Memory" + "Internal Storage / 128 GB") also
    // looks like a pair ("Memory: Internal Storage, 128 GB"); drop those duplicates.
    const unique = SA.unique(lines);
    const pairSet = new Set(unique);
    return unique.filter((line) => {
      const [, first, rest] = line.match(/^[^:]+: ([^,]+), (.+)$/) || [];
      return !(first && pairSet.has(`${first}: ${rest}`));
    });
  };

  /**
   * Climb from a spec label and keep the ancestor with the most label/value pairs
   * (so every spec group is included), but never climb into the part of the page
   * that holds the title, price and offers.
   */
  const bestSpecsContainer = (start, stopAt) => {
    let best = null;
    let bestCount = 0;
    let el = start;
    for (let level = 0; el && el !== document.body && level < 12; level += 1, el = el.parentElement) {
      if (stopAt && el.contains(stopAt)) break;
      const count = labelValuePairs(el).length;
      if (count > bestCount) {
        best = el;
        bestCount = count;
      }
    }
    return bestCount >= 3 ? best : null;
  };

  // ---------- variants (colour / storage options) ----------

  const MAX_VARIANT_LINKS = 15; // more links than this means we climbed into a product carousel

  const pidOf = (url) => SA.safely(() => new URL(url, location.href).searchParams.get("pid"), null);

  /** "128 GB ₹69,900" -> "128 GB (₹69,900)"; "512 GB Out of stock" -> "512 GB (out of stock)". */
  const optionText = (text) =>
    text
      .replace(/\s*out of stock$/i, " (out of stock)")
      .replace(new RegExp(`\\s*(${RUPEE}[\\d,]+)`), " ($1)");

  /** From a label like "Variant:", climb to the nearest box holding variant links. */
  const variantLinksNear = (label) => {
    let el = label.parentElement;
    for (let level = 0; el && el !== document.body && level < 6; level += 1, el = el.parentElement) {
      const links = el.querySelectorAll(SELECTORS.variantLink);
      if (links.length > MAX_VARIANT_LINKS) return null;
      if (links.length) return { container: el, links: [...links] };
    }
    return null;
  };

  /** "Available Variant: 128 GB (₹69,900) (selected), ..." lines. */
  const extractVariants = () => {
    const currentPid = pidOf(location.href);
    const groups = new Map(); // container -> {name, selectedName, links}
    leavesMatching(SELECTORS.variantLabel).forEach((label) => {
      const found = variantLinksNear(label);
      if (!found) return;
      const labelText = SA.cleanLine(label.textContent).replace(/:$/, "");
      const name = labelText.replace(/^selected\s+/i, "");
      // "Selected Color: Teal": the selected value is the rest of the label's parent text.
      const rest = SA.cleanLine(label.parentElement.textContent).slice(labelText.length).replace(/^:\s*/, "");
      const group = groups.get(found.container) || { name, selectedName: "", links: found.links };
      if (/^selected/i.test(labelText) && rest) group.selectedName = rest;
      groups.set(found.container, group);
    });

    const lines = [];
    groups.forEach(({ name, selectedName, links }) => {
      const byPid = new Map(); // one entry per variant page
      links.forEach((link) => {
        const pid = pidOf(link.href);
        if (pid && !byPid.has(pid)) byPid.set(pid, SA.cleanLine(link.innerText));
      });
      const named = [];
      let unnamedOthers = 0;
      byPid.forEach((text, pid) => {
        const selected = pid === currentPid;
        if (SELECTORS.unnamedOption.test(text)) {
          if (selected && selectedName) named.unshift(`${selectedName} (selected)`);
          else if (!selected) unnamedOthers += 1;
        } else {
          named.push(`${optionText(text)}${selected ? " (selected)" : ""}`);
        }
      });
      if (!named.length && selectedName) named.push(`${selectedName} (selected)`);
      if (unnamedOthers) {
        const others = `${unnamedOthers} other option${unnamedOthers > 1 ? "s" : ""}`;
        named.push(`plus ${others} (names not shown on the page)`);
      }
      if (named.length) lines.push(`Available ${name}: ${named.join(", ")}`);
    });
    return lines;
  };

  const extractSpecs = () => {
    const variants = SA.safely(extractVariants, []);
    const specs = SA.safely(extractSpecLines, "");
    return [...variants, specs].filter(Boolean).join("\n");
  };

  const extractSpecLines = () => {
    // Old layout: a <table> under a "Specifications" heading.
    const heading = SA.findHeading(SELECTORS.specsHeading);
    const table = heading && SA.containerWith(heading, "tr", 4);
    if (table) return SA.unique(SA.rowsToLines(table)).join("\n");
    // 2026 layout: label/value <div> pairs, located via a typical spec label.
    const start = leavesMatching(SELECTORS.specAnchorLabels)[0] || heading;
    const container = start && bestSpecsContainer(start, document.querySelector("h1"));
    return container ? labelValuePairs(container).join("\n") : "";
  };

  // ---------- reviews ----------

  const markerCount = (el) => linesOf(el).filter((line) => SELECTORS.reviewMarker.test(line)).length;

  /** The largest box around a "Verified Buyer" label that holds only that one review. */
  const reviewCardOf = (marker) => {
    let card = null;
    let el = marker;
    for (let level = 0; el && el !== document.body && level < 10; level += 1, el = el.parentElement) {
      if (markerCount(el) > 1) break;
      card = el;
    }
    return card;
  };

  const cardToReview = (card) => {
    const lines = linesOf(card);
    const stars = SELECTORS.reviewStars.test(lines[0]) ? lines.shift().replace(/\W$/, "") : null;
    // The reviewer's name is the last non-number line before "Verified Buyer"
    // (like/dislike counts can sit in between): leave it out.
    let nameIndex = lines.findIndex((line) => SELECTORS.reviewMarker.test(line)) - 1;
    while (nameIndex >= 0 && /^\d+$/.test(lines[nameIndex])) nameIndex -= 1;
    const text = lines
      .filter((line, index) => index !== nameIndex && !SELECTORS.reviewNoise.test(line))
      .map((line) => line.replace(/\.{3}\s*more$/i, "..."))
      .join(" | ");
    return text ? (stars ? `${stars} stars | ${text}` : text) : "";
  };

  // "Verified Buyer" only appears on review cards, so we search the whole page for it.
  const extractReviews = () => {
    const cards = SA.unique(leavesMatching(SELECTORS.reviewMarker).map(reviewCardOf).filter(Boolean));
    return SA.unique(cards.map(cardToReview).filter(Boolean));
  };

  // ---------- put it together ----------

  SA.extractors.flipkart = () => {
    const product = SA.emptyProduct("flipkart");
    const titleEl = document.querySelector(SELECTORS.title[0]);
    const pageTitle = titleEl ? SA.cleanLine(titleEl.textContent) : "";
    let ld = SA.safely(() => SA.jsonLdSummary(SA.readJsonLdProduct()), {});
    // Flipkart swaps page content without reloading, and the previous product's
    // JSON-LD can be left behind. Only trust JSON-LD whose name matches the <h1>.
    if (pageTitle && ld.title && !SA.sameProduct(ld.title, pageTitle)) ld = {};

    product.title = ld.title || SA.safely(() => SA.cleanLine(SA.firstText(SELECTORS.title)), "");
    product.price = ld.price || SA.safely(() => extractPrice(titleEl), null);
    product.rating = ld.rating || SA.safely(() => extractRating(titleEl), null);
    product.rating_count = ld.rating_count || SA.safely(extractRatingCount, null);
    product.sections.specs = SA.safely(extractSpecs, "");
    product.sections.description = SA.safely(() => extractDescription(product.sections.specs), "");
    product.sections.offers = SA.safely(extractOffers, "");
    product.sections.reviews = SA.safely(extractReviews, []);
    product.raw_text = SA.safely(SA.pageText, "");
    return product;
  };
})();

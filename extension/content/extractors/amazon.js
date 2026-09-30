// Amazon product-page extractor (amazon.in, and other Amazon domains).
//
// Amazon's HTML changes often. Every selector lives in SELECTORS below, so
// fixing a broken one means editing only this object. These are STARTING
// POINTS to verify in Chrome DevTools, not facts.

(() => {
  const SA = window.__SA__;

  const SELECTORS = {
    title: ["#productTitle"],
    price: [
      "#corePrice_feature_div .a-offscreen",
      "#corePriceDisplay_desktop_feature_div .a-offscreen",
      ".a-price .a-offscreen",
    ],
    rating: "#acrPopover", // "4.1 out of 5 stars" in its title attribute
    ratingCount: "#acrCustomerReviewText", // "12,345 ratings"
    description: ["#feature-bullets", "#productDescription"],
    specTables: [
      "#productDetails_techSpec_section_1",
      "#productDetails_detailBullets_sections1",
      "#prodDetails table",
    ],
    detailBullets: "#detailBullets_feature_div li",
    // Verified 2026-09-30: variant pickers are rows "inline-twister-row-<dimension>"
    // (size_name, style_name, color_name). Real options are <li data-asin="...">;
    // colour names are in the swatch image's alt text. Older layout: "variation_<dimension>".
    variantRows: '[id^="inline-twister-row-"], [id^="variation_"]',
    variantOption: "li[data-asin]",
    offers: "#vsxoffers_feature_div",
    offersHeading: /^offers$/i,
    // Verified 2026-09-27 on amazon.in: review text moved from "review-body" to "reviewText".
    review: '[data-hook="review"], [data-hook="reviewContainer"]',
    reviewBody: '[data-hook="reviewText"], [data-hook="review-body"]',
    reviewTitle: '[data-hook="reviewTitle"], [data-hook="review-title"]',
    reviewStars: '[data-hook="review-star-rating"], [data-hook="cmps-review-star-rating"]',
  };

  const extractRating = () => {
    const el = document.querySelector(SELECTORS.rating);
    if (!el) return null;
    const text = SA.cleanLine(el.getAttribute("title") || el.textContent);
    return text ? text.replace(/\s*stars?$/i, "") : null;
  };

  // "12,345 ratings" stays as is; Amazon's short form "(2)" becomes "2 ratings".
  const extractRatingCount = () => {
    const text = SA.cleanLine(SA.textOf(SELECTORS.ratingCount));
    const bare = text.match(/^\(?([\d,]+)\)?$/);
    return bare ? `${bare[1]} ratings` : text || null;
  };

  const extractDescription = () =>
    SELECTORS.description.map((selector) => SA.textOf(selector)).filter(Boolean).join("\n\n");

  /** "color_name" -> "Colour", "size_name" -> "Size", "style_name" -> "Style". */
  const dimensionLabel = (rowId) => {
    const name = rowId.replace(/^(inline-twister-row-|variation_)/, "").replace(/_name$/, "");
    if (name === "color") return "Colour";
    return name.charAt(0).toUpperCase() + name.slice(1).replace(/_/g, " ");
  };

  /** The visible name of one option button (image alt, title, or its first line of text). */
  const optionLabel = (option) => {
    const alt = option.querySelector("img")?.getAttribute("alt");
    const title = option.getAttribute("title")?.replace(/^click to select\s*/i, "");
    const text = SA.cleanBlock(option.innerText).split("\n")[0];
    return SA.cleanLine(alt || title || text);
  };

  /**
   * "Available Colour: Violet Shadow (selected), Cream, Graphite" lines, so
   * questions like "which colours are available?" can be answered.
   */
  const extractVariants = () => {
    const lines = [];
    document.querySelectorAll(SELECTORS.variantRows).forEach((row) => {
      const options = [...row.querySelectorAll(SELECTORS.variantOption)]
        .map((option) => {
          const label = optionLabel(option);
          if (!label || !/[a-z]/i.test(label)) return "";
          const selected = option.dataset.initiallyselected === "true" ? " (selected)" : "";
          const unavailable = option.dataset.initiallyunavailable === "true" ? " (unavailable)" : "";
          return `${label}${selected}${unavailable}`;
        })
        .filter(Boolean);
      if (options.length) lines.push(`Available ${dimensionLabel(row.id)}: ${SA.unique(options).join(", ")}`);
    });
    return SA.unique(lines);
  };

  const extractSpecs = () => {
    const lines = [...SA.safely(extractVariants, [])];
    SELECTORS.specTables.forEach((selector) => {
      document.querySelectorAll(selector).forEach((table) => lines.push(...SA.rowsToLines(table)));
    });
    document.querySelectorAll(SELECTORS.detailBullets).forEach((item) => {
      // Detail bullets look like "Item Weight : 192 g"; normalise to "Item Weight: 192 g".
      const line = SA.cleanLine(item.innerText).replace(/\s*:\s*/, ": ");
      if (line) lines.push(line);
    });
    return SA.unique(lines).join("\n");
  };

  const extractOffers = () => {
    const direct = SA.textOf(SELECTORS.offers);
    if (direct) return direct;
    const heading = SA.findHeading(SELECTORS.offersHeading);
    const container = heading && SA.containerWith(heading, "li, .a-carousel-card");
    return container ? SA.textOf(container) : "";
  };

  const extractReviews = () => {
    const reviews = [];
    document.querySelectorAll(SELECTORS.reviewBody).forEach((body) => {
      const text = SA.cleanBlock(body.innerText).replace(/\s*Read more$/i, "");
      if (!text) return;
      const card = body.closest(SELECTORS.review);
      const stars = SA.cleanLine(card?.querySelector(SELECTORS.reviewStars)?.textContent);
      // The title element often repeats the star text ("5.0 out of 5 stars Great phone").
      const title = SA.cleanLine(card?.querySelector(SELECTORS.reviewTitle)?.innerText)
        .replace(stars, "")
        .trim();
      const parts = [stars, title, text].filter(Boolean);
      reviews.push(parts.join(" | "));
    });
    return SA.unique(reviews); // Amazon sometimes repeats reviews in hidden carousels
  };

  SA.extractors.amazon = () => {
    const product = SA.emptyProduct("amazon");
    product.title = SA.safely(() => SA.cleanLine(SA.firstText(SELECTORS.title)), "");
    product.price = SA.safely(() => SA.cleanLine(SA.firstText(SELECTORS.price)) || null, null);
    product.rating = SA.safely(extractRating, null);
    product.rating_count = SA.safely(extractRatingCount, null);
    product.sections.description = SA.safely(extractDescription, "");
    product.sections.specs = SA.safely(extractSpecs, "");
    product.sections.offers = SA.safely(extractOffers, "");
    product.sections.reviews = SA.safely(extractReviews, []);
    product.raw_text = SA.safely(SA.pageText, "");
    return product;
  };
})();

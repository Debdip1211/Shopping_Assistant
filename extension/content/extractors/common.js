// Shared helpers for all product extractors.
//
// Content scripts run inside the shopping website's page, in an "isolated
// world": they can read the page's HTML, but their JavaScript variables are
// separate from the website's own scripts. All our content-script files share
// ONE scope, so everything is kept inside one namespace object, window.__SA__,
// and each file is wrapped in (() => { ... })() so its local names can't clash.
//
// Rule for every extractor: never throw into the page. Each step is wrapped
// so a broken selector gives partial data instead of an error.

(() => {
  const SA = (window.__SA__ = window.__SA__ || {});
  SA.extractors = SA.extractors || {};

  // Keep in sync with MAX_PRODUCT_CHARS in backend/.env (default 300000).
  SA.MAX_PRODUCT_CHARS = 300000;

  // Zero-width and direction-marker characters Amazon puts inside labels.
  const INVISIBLE_CHARS = /[\u200b-\u200f\u202a-\u202e\u2060\ufeff]/g;

  /** Collapse all whitespace (including newlines) into single spaces. */
  SA.cleanLine = (text) =>
    String(text ?? "").replace(INVISIBLE_CHARS, "").replace(/\s+/g, " ").trim();

  /** Tidy each line but keep line breaks; drop empty lines. */
  SA.cleanBlock = (text) =>
    String(text ?? "")
      .replace(INVISIBLE_CHARS, "")
      .split("\n")
      .map((line) => line.replace(/\s+/g, " ").trim())
      .filter(Boolean)
      .join("\n");

  /** Cut text to at most `max` characters. */
  SA.capText = (text, max = SA.MAX_PRODUCT_CHARS) =>
    text.length > max ? text.slice(0, max) : text;

  /** Remove duplicates while keeping the original order. */
  SA.unique = (items) => [...new Set(items)];

  /** Run fn(); if it throws or returns null/undefined, return `fallback`. */
  SA.safely = (fn, fallback) => {
    try {
      const value = fn();
      return value ?? fallback;
    } catch (error) {
      console.debug("[Shopping Assistant] extractor step failed:", error);
      return fallback;
    }
  };

  /** Visible text of an element (or of the first match of a selector), tidied. */
  SA.textOf = (target, root = document) =>
    SA.safely(() => {
      const el = typeof target === "string" ? root.querySelector(target) : target;
      return el ? SA.cleanBlock(el.innerText || el.textContent || "") : "";
    }, "");

  /** Text of the first selector in the list that finds non-empty text. */
  SA.firstText = (selectors, root = document) => {
    for (const selector of selectors) {
      const text = SA.textOf(selector, root);
      if (text) return text;
    }
    return "";
  };

  /** Turn table rows into "Label: value" lines. */
  SA.rowsToLines = (root) => {
    const lines = [];
    root.querySelectorAll("tr").forEach((row) => {
      const cells = [...row.querySelectorAll("th, td")]
        .map((cell) => SA.cleanLine(cell.innerText || cell.textContent))
        .filter(Boolean);
      if (cells.length >= 2) lines.push(`${cells[0]}: ${cells.slice(1).join(", ")}`);
      else if (cells.length === 1) lines.push(cells[0]);
    });
    return lines;
  };

  /**
   * Find a short element whose whole text matches `pattern`, e.g. /^specifications$/i.
   * Used when a site has no stable IDs: headings' TEXT changes less than class names.
   */
  SA.findHeading = (pattern, root = document) => {
    for (const el of root.querySelectorAll("h1, h2, h3, h4, h5, h6, div, span, p")) {
      const text = SA.cleanLine(el.textContent);
      if (text && text.length <= 40 && pattern.test(text)) return el;
    }
    return null;
  };

  /** Walk up from `start` to the nearest ancestor that contains `selector`. */
  SA.containerWith = (start, selector, maxLevels = 6) => {
    let el = start;
    for (let level = 0; el && level < maxLevels; level += 1, el = el.parentElement) {
      if (el.querySelector(selector)) return el;
    }
    return null;
  };

  /** "amazon", "flipkart" or "other", from the page's hostname. */
  SA.detectSite = () => {
    const host = location.hostname.toLowerCase();
    if (/(^|\.)amazon\./.test(host)) return "amazon";
    if (/(^|\.)flipkart\.com$/.test(host)) return "flipkart";
    return "other";
  };

  /**
   * Does the address look like a product page? true / false for Amazon and
   * Flipkart (their product URLs have a clear pattern), null for other sites.
   * Flipkart and Amazon update the page without reloading it (single-page app),
   * so the URL is more trustworthy than leftover page content.
   */
  SA.isProductUrl = () => {
    const path = location.pathname;
    switch (SA.detectSite()) {
      case "amazon":
        return /\/(dp|gp\/product)\/[A-Z0-9]{10}/.test(path);
      case "flipkart":
        return /\/p\/itm/i.test(path);
      default:
        return null;
    }
  };

  /** Do two product names refer to the same product? (loose, case-insensitive) */
  SA.sameProduct = (a, b) => {
    const norm = (text) => SA.cleanLine(text).toLowerCase().slice(0, 25);
    const [x, y] = [norm(a), norm(b)];
    return Boolean(x && y && (x.includes(y) || y.includes(x)));
  };

  // ---------- JSON-LD ----------
  // Many shops embed machine-readable product data for search engines in
  // <script type="application/ld+json">. It's the most stable source we have.

  const isProductType = (type) =>
    (Array.isArray(type) ? type : [type]).some((t) => String(t).toLowerCase() === "product");

  const findProductNode = (node) => {
    if (!node || typeof node !== "object") return null;
    if (Array.isArray(node)) {
      for (const item of node) {
        const found = findProductNode(item);
        if (found) return found;
      }
      return null;
    }
    if (isProductType(node["@type"])) return node;
    return node["@graph"] ? findProductNode(node["@graph"]) : null;
  };

  /** The first JSON-LD object with @type "Product", or null. */
  SA.readJsonLdProduct = () => {
    for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
      const found = SA.safely(() => findProductNode(JSON.parse(script.textContent)), null);
      if (found) return found;
    }
    return null;
  };

  const formatPrice = (price, currency) => {
    const amount = Number(price);
    if (!Number.isFinite(amount)) return SA.cleanLine(price);
    if (!currency || currency === "INR") return `\u20B9${amount.toLocaleString("en-IN")}`;
    return `${currency} ${amount.toLocaleString()}`;
  };

  /** {title, price, rating, rating_count} from a JSON-LD Product (missing → null). */
  SA.jsonLdSummary = (node) => {
    if (!node) return { title: "", price: null, rating: null, rating_count: null };
    const offers = (Array.isArray(node.offers) ? node.offers[0] : node.offers) || {};
    const rating = node.aggregateRating || {};
    const price = offers.price ?? offers.lowPrice;
    const count = rating.ratingCount ?? rating.reviewCount;
    return {
      title: SA.cleanLine(node.name),
      price: price != null ? formatPrice(price, offers.priceCurrency) : null,
      rating: rating.ratingValue != null ? `${rating.ratingValue} out of ${rating.bestRating || 5}` : null,
      rating_count: count != null ? `${Number(count).toLocaleString("en-IN")} ratings` : null,
    };
  };

  // ---------- page text and the empty product ----------

  /** Visible main text of the page, tidied and capped (the raw_text fallback). */
  SA.pageText = () =>
    SA.capText(
      SA.cleanBlock(document.querySelector("main")?.innerText || document.body?.innerText || "")
    );

  /** A product with every field present but empty (same shape as ProductIn). */
  SA.emptyProduct = (site) => ({
    url: location.href,
    site,
    title: "",
    price: null,
    rating: null,
    rating_count: null,
    sections: { description: "", specs: "", offers: "", reviews: [] },
    raw_text: "",
    captured_at: new Date().toISOString(),
  });
})();

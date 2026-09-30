// Generic extractor for any other shopping site (and the fallback when the
// Amazon/Flipkart extractor finds no title).
//
// It only fills title/price/rating and raw_text. Sections stay empty; the
// backend then puts raw_text into a single "general" section.

(() => {
  const SA = window.__SA__;

  const SELECTORS = {
    ogTitle: 'meta[property="og:title"]',
    heading: "h1",
  };

  const metaContent = (selector) =>
    SA.cleanLine(document.querySelector(selector)?.getAttribute("content"));

  SA.extractors.generic = () => {
    const product = SA.emptyProduct(SA.detectSite());
    const ld = SA.safely(() => SA.jsonLdSummary(SA.readJsonLdProduct()), {});

    // Title: JSON-LD name → og:title → first <h1> → the browser tab title.
    product.title =
      ld.title ||
      SA.safely(() => metaContent(SELECTORS.ogTitle), "") ||
      SA.safely(() => SA.cleanLine(SA.textOf(SELECTORS.heading)), "") ||
      SA.cleanLine(document.title);
    product.price = ld.price ?? null;
    product.rating = ld.rating ?? null;
    product.rating_count = ld.rating_count ?? null;
    product.raw_text = SA.safely(SA.pageText, "");
    return product;
  };
})();

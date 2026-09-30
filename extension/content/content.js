// Content script entry point: answers messages from the side panel.
//
// The side panel can't read the web page (it's a separate page). So it sends
// a message to this script, which runs inside the page, and this script replies
// with the extracted data. This is "message passing".
//
// Messages handled:
//   {type: "EXTRACT_PRODUCT"}        -> {ok, product, is_product_page}
//   {type: "HIGHLIGHT_SOURCE", text, hint} -> {found}  (marks the passage on the page;
//                                            hint = the question, to pick the right part)

(() => {
  const SA = window.__SA__;
  if (SA.listening) return; // don't register twice if the script is injected again
  SA.listening = true;

  /** Shorten raw_text so sections + raw_text stay under the backend's size limit. */
  const fitToLimit = (product) => {
    const { description, specs, offers, reviews } = product.sections;
    const sectionChars =
      description.length + specs.length + offers.length + reviews.reduce((n, r) => n + r.length, 0);
    const room = Math.max(0, SA.MAX_PRODUCT_CHARS - sectionChars);
    product.raw_text = SA.capText(product.raw_text, room);
    return product;
  };

  /** Pick the site's extractor; fall back to the generic one if it finds no title. */
  const extractProduct = () => {
    const site = SA.detectSite();
    const siteExtractor = SA.extractors[site];
    let product = siteExtractor ? SA.safely(siteExtractor, null) : null;
    if (!product || !product.title) {
      product = SA.safely(SA.extractors.generic, SA.emptyProduct(site));
    }
    // Amazon/Flipkart: decide by the URL pattern (leftover content from a previous
    // page can't fool it). Other sites: a title and a price, or JSON-LD product data.
    const urlSaysProduct = SA.safely(SA.isProductUrl, null);
    const hasJsonLdProduct = SA.safely(() => Boolean(SA.readJsonLdProduct()), false);
    const isProductPage =
      urlSaysProduct !== null
        ? urlSaysProduct && Boolean(product.title)
        : Boolean((product.title && product.price) || hasJsonLdProduct);
    return { product: fitToLimit(product), is_product_page: isProductPage };
  };

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === "EXTRACT_PRODUCT") {
      try {
        sendResponse({ ok: true, ...extractProduct() });
      } catch (error) {
        sendResponse({ ok: false, error: String(error) });
      }
    } else if (message?.type === "HIGHLIGHT_SOURCE") {
      sendResponse({ found: SA.highlightText(message.text || "", message.hint || "") });
    }
    return false; // we replied synchronously
  });
})();

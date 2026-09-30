// Side panel logic.
//
// Flow (CLAUDE.md Section 8):
//   1. check the backend is running (GET /health)
//   2. ask the content script in the active tab to extract the product
//   3. if it's a product page, save it (POST /ingest) and show the product card
//   4. chat: POST /chat for "This product" or "All viewed products"; each
//      conversation is saved in chrome.storage.local (storage.js)
//   5. source chips highlight the passage on the page
//   6. a second view lists saved products, with delete / delete all
//   7. the page is re-read on tab switch, navigation and "Refresh page data";
//      a 404 from /chat re-saves the product and retries once
//
// Security note: text from websites and from the LLM is always inserted with
// textContent / createElement, never innerHTML, so it can't run as code here.

import {
  ApiError,
  chat,
  deleteAllProducts,
  deleteProduct,
  health,
  ingestProduct,
  listProducts,
  UNREACHABLE_MESSAGE,
} from "./api.js";
import {
  ALL_PRODUCTS_CHAT_KEY,
  clearAllChats,
  clearChat,
  loadChat,
  productChatKey,
  saveChat,
} from "./storage.js";

// Pages where Chrome doesn't let extensions run content scripts.
const RESTRICTED_URL =
  /^(chrome|chrome-extension|chrome-search|edge|about|devtools|view-source|file):|^https:\/\/(chrome\.google\.com\/webstore|chromewebstore\.google\.com)|\.pdf($|[?#])/i;

const MESSAGES = {
  loading: "Reading this page…",
  saving: "Saving this product…",
  restricted: "This page can't be read by extensions.",
  notProduct: "This doesn't look like a product page. You can still ask about all viewed products.",
  reload: "Please reload this page. (The extension was installed or updated after the page was opened.)",
  llmFailed: "The AI service had a problem. Please try again.",
  notOnPage: "Couldn't locate this passage on the page.",
  emptyCurrent: "Ask anything about this product: specs, offers, or what reviewers say.",
  emptyHistory: "Ask across every product you've viewed, e.g. \"Compare their battery life\".",
  emptyNoProducts: "No products saved yet. Open a product page first.",
  noSavedProducts: "No saved products yet. Open a product page to save one.",
  currentDeleted: "This product was removed from your saved products. Reload the page to save it again.",
  allDeleted: "All saved products were deleted. Reload a product page to save it again.",
};
const SITE_LABELS = { amazon: "Amazon", flipkart: "Flipkart", other: "Other shop" };
const MODE_LABELS = { full_context: "Full product", rag: "RAG" };
const HISTORY_TO_SEND = 10; // the backend keeps only the last MAX_HISTORY_MESSAGES anyway
const CHIP_TOOLTIP_CHARS = 300;
const TOAST_MS = 3500;

const el = {
  notice: document.getElementById("sa-notice"),
  noticeText: document.getElementById("sa-notice-text"),
  retry: document.getElementById("sa-retry"),
  card: document.getElementById("sa-card"),
  site: document.getElementById("sa-site"),
  mode: document.getElementById("sa-mode"),
  title: document.getElementById("sa-title"),
  price: document.getElementById("sa-price"),
  rating: document.getElementById("sa-rating"),
  saved: document.getElementById("sa-saved"),
  scopeCurrent: document.getElementById("sa-scope-current"),
  scopeHistory: document.getElementById("sa-scope-history"),
  chat: document.getElementById("sa-chat"),
  chatEmpty: document.getElementById("sa-chat-empty"),
  toast: document.getElementById("sa-toast"),
  form: document.getElementById("sa-form"),
  input: document.getElementById("sa-input"),
  send: document.getElementById("sa-send"),
  clear: document.getElementById("sa-clear"),
  refresh: document.getElementById("sa-refresh"),
  viewChatBtn: document.getElementById("sa-view-chat-btn"),
  viewProductsBtn: document.getElementById("sa-view-products-btn"),
  viewChat: document.getElementById("sa-view-chat"),
  viewProducts: document.getElementById("sa-view-products"),
  productsStatus: document.getElementById("sa-products-status"),
  products: document.getElementById("sa-products"),
  deleteAll: document.getElementById("sa-delete-all"),
  deleteAllConfirm: document.getElementById("sa-delete-all-confirm"),
  deleteAllQuestion: document.getElementById("sa-delete-all-question"),
  deleteAllYes: document.getElementById("sa-delete-all-yes"),
  deleteAllNo: document.getElementById("sa-delete-all-no"),
};

// ---------- module state ----------

let backendOk = false;
let currentTabId = null; // the tab whose page the card and highlights belong to
let currentProduct = null; // {product_id, title, site, ...} of the open tab, if saved
let scope = "current"; // "current" | "history"
let productCount = 0;
let savedProducts = []; // GET /products, newest first
let view = "chat"; // "chat" | "products"
let waiting = false;
// Conversations in memory, keyed like their storage keys ("chat:product:<id>",
// "chat:all"). Loaded from chrome.storage.local the first time they're needed,
// saved back after every answer. Each is a list of messages:
// {role: "user" | "assistant" | "error", content, sources?, failed?}
const chats = new Map();

const chatKey = () =>
  scope === "current" ? productChatKey(currentProduct?.product_id) : ALL_PRODUCTS_CHAT_KEY;
const currentChat = () => {
  if (!chats.has(chatKey())) chats.set(chatKey(), []);
  return chats.get(chatKey());
};

/** Load a saved conversation into memory (once per panel session). */
async function ensureChatLoaded(key) {
  if (!chats.has(key)) chats.set(key, await loadChat(key));
}

// ---------- small formatter for LLM answers (bold, headings, bullets, tables) ----------

/** Append `text` to `parent`, turning **bold** into <strong>. */
function appendInline(parent, text) {
  text.split(/(\*\*[^*]+\*\*)/g).forEach((part) => {
    if (/^\*\*[^*]+\*\*$/.test(part)) {
      const strong = document.createElement("strong");
      strong.textContent = part.slice(2, -2);
      parent.append(strong);
    } else if (part) {
      parent.append(document.createTextNode(part));
    }
  });
}

const tableCells = (line) => line.trim().replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim());
const isTableDivider = (line) => /^\|?\s*:?-{2,}/.test(line.trim());

/** Build a <table> from markdown table lines ("| a | b |"). */
function buildTable(lines) {
  const table = document.createElement("table");
  lines
    .filter((line) => !isTableDivider(line))
    .forEach((line, rowIndex) => {
      const row = table.insertRow();
      tableCells(line).forEach((cell) => {
        const td = document.createElement(rowIndex === 0 ? "th" : "td");
        appendInline(td, cell);
        row.append(td);
      });
    });
  const wrap = document.createElement("div");
  wrap.className = "sa-table-wrap";
  wrap.append(table);
  return wrap;
}

/** Turn the LLM's markdown-ish answer into safe DOM nodes. */
function formatAnswer(text) {
  const fragment = document.createDocumentFragment();
  const lines = text.split("\n");
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    if (line.trim().startsWith("|")) {
      // Collect every consecutive table line, then build one <table>.
      const block = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        block.push(lines[i]);
        i += 1;
      }
      i -= 1; // the for-loop's i += 1 then moves to the first line after the table
      fragment.append(buildTable(block));
      continue;
    }
    const heading = line.match(/^#{1,6}\s+(.*)$/);
    const bullet = line.match(/^\s*[-*]\s+(.*)$/);
    const p = document.createElement("p");
    if (heading) {
      p.className = "sa-answer-heading";
      appendInline(p, heading[1]);
    } else if (bullet) {
      p.className = "sa-answer-bullet";
      appendInline(p, bullet[1]);
    } else if (line.trim()) {
      appendInline(p, line);
    } else {
      continue; // blank line: spacing comes from CSS
    }
    fragment.append(p);
  }
  return fragment;
}

// ---------- rendering ----------

/** Show a page-level message. `tone`: "info", "warning" or "error" (errors offer "Try again"). */
function showNotice(message, tone = "info") {
  el.noticeText.textContent = message;
  el.notice.dataset.tone = tone;
  el.notice.hidden = false;
  el.retry.hidden = tone === "info";
}

function hideNotice() {
  el.notice.hidden = true;
}

function showCard(product, ingest) {
  el.site.textContent = SITE_LABELS[product.site] || product.site;
  el.mode.textContent = MODE_LABELS[ingest.mode] || ingest.mode;
  el.mode.title =
    ingest.mode === "rag"
      ? "Long page: answers use the most relevant excerpts"
      : "Short page: answers see the whole product";
  el.title.textContent = ingest.title || product.title;
  el.price.textContent = product.price || "Price not found";
  el.rating.textContent = product.rating
    ? [product.rating, product.rating_count].filter(Boolean).join(" · ")
    : "No rating found";
  el.saved.textContent = ingest.cached
    ? "Already saved · no changes since your last visit"
    : `Saved · ${ingest.num_chunks} chunks`;
  el.card.hidden = false;
}

/** Show a short message above the input for a few seconds. */
let toastTimer = null;
function showToast(message) {
  el.toast.textContent = message;
  el.toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    el.toast.hidden = true;
  }, TOAST_MS);
}

const isFromCurrentProduct = (source) =>
  Boolean(currentProduct) && source.product_id === currentProduct.product_id;

/**
 * A chip per source. Chips from the product on the open page are buttons that
 * highlight the passage on the page; chips from other products only show the
 * product name, with the chunk text as a tooltip.
 */
function sourceChip(source, number, question) {
  const fromCurrent = isFromCurrentProduct(source);
  const chip = document.createElement(fromCurrent ? "button" : "span");
  chip.className = fromCurrent ? "sa-chip sa-chip-link" : "sa-chip";
  const shortTitle = source.product_title.split(/[(|,]/)[0].trim();
  chip.textContent = fromCurrent
    ? `[${number}] ${source.section}`
    : `[${number}] ${shortTitle} · ${source.section}`;
  chip.title = fromCurrent ? "Show this passage on the page" : source.text.slice(0, CHIP_TOOLTIP_CHARS);
  if (fromCurrent) {
    chip.type = "button";
    chip.addEventListener("click", () => highlightSource(source, question, true));
  }
  return chip;
}

/**
 * Ask the content script to highlight a source on the page. The question is
 * sent as a hint so the relevant part of a mixed chunk is chosen.
 */
async function highlightSource(source, question, reportMissing) {
  if (!currentTabId) return;
  try {
    const { found } = await chrome.tabs.sendMessage(currentTabId, {
      type: "HIGHLIGHT_SOURCE",
      text: source.text,
      hint: question || "",
    });
    if (!found && reportMissing) showToast(MESSAGES.notOnPage);
  } catch {
    if (reportMissing) showToast(MESSAGES.notOnPage);
  }
}

function renderMessage(message) {
  const bubble = document.createElement("div");
  bubble.className = `sa-msg sa-msg-${message.role}`;
  if (message.role === "assistant") {
    bubble.append(formatAnswer(message.content));
    if (message.sources?.length) {
      const chips = document.createElement("div");
      chips.className = "sa-chips";
      message.sources.forEach((source, index) =>
        chips.append(sourceChip(source, index + 1, message.question))
      );
      bubble.append(chips);
    }
  } else {
    bubble.textContent = message.content;
  }
  return bubble;
}

function renderChat() {
  const messages = currentChat();
  el.chat.replaceChildren(el.chatEmpty);
  const empty =
    scope === "current" ? MESSAGES.emptyCurrent : productCount ? MESSAGES.emptyHistory : MESSAGES.emptyNoProducts;
  el.chatEmpty.textContent = empty;
  el.chatEmpty.hidden = messages.length > 0;
  messages.forEach((message) => el.chat.append(renderMessage(message)));
  if (waiting) {
    const thinking = document.createElement("div");
    thinking.className = "sa-msg sa-msg-thinking";
    thinking.textContent = "Thinking";
    el.chat.append(thinking);
  }
  el.chat.scrollTop = el.chat.scrollHeight;
}

function renderScope() {
  el.scopeCurrent.disabled = !currentProduct;
  el.scopeHistory.textContent = `All viewed products (${productCount})`;
  el.scopeCurrent.setAttribute("aria-checked", String(scope === "current"));
  el.scopeHistory.setAttribute("aria-checked", String(scope === "history"));
}

function renderInput() {
  const canAsk = backendOk && !waiting && (scope === "history" ? productCount > 0 : Boolean(currentProduct));
  el.input.disabled = !canAsk;
  el.send.disabled = !canAsk;
  el.clear.disabled = waiting || currentChat().length === 0;
}

function renderViews() {
  el.viewChat.hidden = view !== "chat";
  el.viewProducts.hidden = view !== "products";
  el.viewChatBtn.setAttribute("aria-pressed", String(view === "chat"));
  el.viewProductsBtn.setAttribute("aria-pressed", String(view === "products"));
  el.viewProductsBtn.textContent = `Saved products (${productCount})`;
}

function render() {
  renderViews();
  renderScope();
  renderChat();
  renderInput();
  renderProducts();
}

async function setScope(next) {
  if (next === "current" && !currentProduct) return;
  scope = next;
  await ensureChatLoaded(chatKey());
  render();
  el.input.focus();
}

/** Empty the conversation of the selected scope, on screen and in storage. */
async function clearCurrentChat() {
  const key = chatKey();
  chats.set(key, []);
  await clearChat(key);
  render();
}

// ---------- talking to the page ----------

/** The tab the user is looking at in this window. */
async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

/** Ask the content script for the product. Returns {product, is_product_page}. */
async function extractFromTab(tab) {
  try {
    const response = await chrome.tabs.sendMessage(tab.id, { type: "EXTRACT_PRODUCT" });
    if (!response?.ok) throw new Error(response?.error || "no response");
    return response;
  } catch (error) {
    const reloadNeeded = String(error?.message).includes("Receiving end does not exist");
    throw new Error(reloadNeeded ? MESSAGES.reload : `Couldn't read this page: ${error.message}`);
  }
}

/** Reload the list of saved products from the backend. */
async function refreshProducts() {
  savedProducts = await listProducts();
  productCount = savedProducts.length;
}

// ---------- loading the current page ----------

/**
 * Read the active tab, save its product, and update the card.
 *
 * It runs when the panel opens, on tab switches and navigation (Phase 5d), and on
 * "Refresh page data". Several runs can overlap (e.g. quick tab switches), so
 * each run gets a number and only the newest one may change the panel.
 */
let loadRun = 0;
async function loadCurrentPage() {
  const run = (loadRun += 1);
  const isLatest = () => run === loadRun;
  const previousProductId = currentProduct?.product_id;
  const previousScope = scope;

  backendOk = false;
  currentProduct = null;
  currentTabId = null;
  el.card.hidden = true;
  showNotice(MESSAGES.loading);
  render();
  try {
    await health();
    if (!isLatest()) return;
    backendOk = true;
    await refreshProducts();

    const tab = await getActiveTab();
    if (!isLatest()) return;
    if (!tab?.id || !tab.url || RESTRICTED_URL.test(tab.url)) {
      showNotice(MESSAGES.restricted, "warning");
      return;
    }
    currentTabId = tab.id;
    const { product, is_product_page: isProductPage } = await extractFromTab(tab);
    if (!isLatest()) return;
    if (!isProductPage) {
      showNotice(MESSAGES.notProduct, "warning");
      return;
    }

    showNotice(MESSAGES.saving);
    const ingest = await ingestProduct(product);
    if (!isLatest()) return;
    currentProduct = { ...product, product_id: ingest.product_id, mode: ingest.mode };
    await refreshProducts();
    showCard(product, ingest);
    hideNotice();
  } catch (error) {
    // Every message here is already written for people (ApiError messages and ours above).
    if (isLatest()) showNotice(error.message, "error");
  } finally {
    if (isLatest()) {
      // Same product as before (e.g. "Refresh page data"): keep the user's scope.
      // Otherwise: "This product" on a product page, else "All viewed products".
      const sameProduct = currentProduct && currentProduct.product_id === previousProductId;
      scope = sameProduct ? previousScope : currentProduct ? "current" : "history";
      await ensureChatLoaded(chatKey());
      render();
    }
  }
}

/** The product as the backend expects it (ProductIn), without our extra fields. */
function asProductIn(product) {
  const { product_id: _id, mode: _mode, ...productIn } = product;
  return productIn;
}

// ---------- following the user's tabs (Phase 5d) ----------

const RELOAD_DELAY_MS = 800; // let the page settle; also merges bursts of events
let reloadTimer = null;
let panelWindowId = null; // the side panel belongs to one browser window

function scheduleReload() {
  clearTimeout(reloadTimer);
  reloadTimer = setTimeout(loadCurrentPage, RELOAD_DELAY_MS);
}

/** Re-read the page when the user switches tabs or the page changes. */
async function followTabs() {
  panelWindowId = (await chrome.windows.getCurrent()).id;
  chrome.tabs.onActivated.addListener(({ windowId }) => {
    if (windowId === panelWindowId) scheduleReload();
  });
  chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
    if (!tab.active || tab.windowId !== panelWindowId) return;
    // A normal page load ends with status "complete". Flipkart/Amazon sometimes
    // change the page in place (single-page app): then only the URL changes.
    if (changeInfo.status === "complete" || changeInfo.url) scheduleReload();
  });
}

// ---------- asking a question ----------

/** Earlier successful turns of this conversation, as the backend expects them. */
function historyFor(messages) {
  return messages
    .filter((m) => (m.role === "user" && !m.failed) || m.role === "assistant")
    .slice(-HISTORY_TO_SEND)
    .map(({ role, content }) => ({ role, content }));
}

/** A readable error message for a failed /chat request. */
function chatErrorMessage(error) {
  if (!(error instanceof ApiError)) return `Something went wrong: ${error.message}`;
  if (error.kind === "unreachable") return UNREACHABLE_MESSAGE;
  if (error.status === 502) return `${MESSAGES.llmFailed}\n${error.message}`;
  return error.message; // 400 / 404 / others: the backend's own message
}

async function ask(question) {
  const key = chatKey(); // remember which conversation this belongs to (scope may change while waiting)
  const messages = currentChat();
  const history = historyFor(messages);
  const userMessage = { role: "user", content: question };
  messages.push(userMessage);
  waiting = true;
  render();
  const askScope = scope;
  const product = askScope === "current" ? currentProduct : null;
  const send = () =>
    chat({ scope: askScope, productId: product?.product_id ?? null, question, history });
  try {
    let response;
    try {
      response = await send();
    } catch (error) {
      // 404: the backend doesn't know this product any more (e.g. it was deleted).
      // Save it again from the data we already extracted, then retry once, silently.
      const notFound = error instanceof ApiError && error.status === 404;
      if (!notFound || !product) throw error;
      await ingestProduct(asProductIn(product));
      await refreshProducts();
      response = await send();
    }
    // `question` is kept with the answer so its chips can highlight the right part later.
    messages.push({ role: "assistant", content: response.answer, sources: response.sources, question });
    await saveChat(key, messages);
    // Highlight the top source from the open page automatically (quietly if not found).
    const topSource = response.sources.find(isFromCurrentProduct);
    if (topSource) highlightSource(topSource, question, false);
  } catch (error) {
    userMessage.failed = true; // don't send an unanswered question as history later
    messages.push({ role: "error", content: chatErrorMessage(error) });
  } finally {
    waiting = false;
    render();
    el.input.focus();
  }
}

// ---------- saved products view ----------

/** "just now", "5 min ago", "3 h ago", "2 days ago", or a date. */
function timeAgo(isoDate) {
  const minutes = Math.round((Date.now() - new Date(isoDate).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 60 * 24) return `${Math.round(minutes / 60)} h ago`;
  if (minutes < 60 * 24 * 7) return `${Math.round(minutes / (60 * 24))} days ago`;
  return new Date(isoDate).toLocaleDateString();
}

/** One row of the saved products list. */
function productRow(product) {
  const item = document.createElement("li");
  item.className = "sa-product";

  const info = document.createElement("div");
  info.className = "sa-product-info";
  const title = document.createElement("p");
  title.className = "sa-product-title";
  title.textContent = product.title;
  title.title = product.title;
  const meta = document.createElement("p");
  meta.className = "sa-muted";
  meta.textContent = [
    SITE_LABELS[product.site] || product.site,
    product.price,
    product.rating,
    `viewed ${timeAgo(product.last_seen)}`,
  ]
    .filter(Boolean)
    .join(" · ");
  info.append(title, meta);

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "sa-danger";
  remove.textContent = "Delete";
  remove.setAttribute("aria-label", `Delete ${product.title}`);
  remove.addEventListener("click", () => deleteOne(product.product_id, remove));

  item.append(info, remove);
  return item;
}

function renderProducts() {
  el.products.replaceChildren(...savedProducts.map(productRow));
  el.productsStatus.textContent = savedProducts.length
    ? `${savedProducts.length} saved · most recently viewed first`
    : MESSAGES.noSavedProducts;
  el.deleteAll.hidden = savedProducts.length === 0 || !el.deleteAllConfirm.hidden;
}

/** The product on the open page no longer exists in the backend. */
function forgetCurrentProduct(message) {
  currentProduct = null;
  el.card.hidden = true;
  scope = "history";
  showNotice(message, "warning");
}

/** Delete one product (and its saved chat). */
async function deleteOne(productId, button) {
  button.disabled = true;
  button.textContent = "Deleting…";
  try {
    await deleteProduct(productId);
  } catch (error) {
    // 404 = already gone, which is what we wanted anyway.
    if (!(error instanceof ApiError && error.status === 404)) {
      el.productsStatus.textContent = error.message;
      button.disabled = false;
      button.textContent = "Delete";
      return;
    }
  }
  const key = productChatKey(productId);
  chats.delete(key);
  await clearChat(key);
  if (currentProduct?.product_id === productId) forgetCurrentProduct(MESSAGES.currentDeleted);
  await refreshProducts().catch(() => {});
  render();
}

/** Step 1 of "Delete all": ask for confirmation inside the panel. */
function askDeleteAll() {
  const count = savedProducts.length;
  const what = count === 1 ? "the 1 saved product and its chat" : `all ${count} saved products and their chats`;
  el.deleteAllQuestion.textContent = `Delete ${what}? This can't be undone.`;
  el.deleteAllConfirm.hidden = false;
  el.deleteAll.hidden = true;
  el.deleteAllNo.focus();
}

function cancelDeleteAll() {
  el.deleteAllConfirm.hidden = true;
  renderProducts();
}

/** Step 2 of "Delete all": the user confirmed. */
async function confirmDeleteAll() {
  el.deleteAllYes.disabled = true;
  try {
    await deleteAllProducts();
    chats.clear();
    await clearAllChats();
    if (currentProduct) forgetCurrentProduct(MESSAGES.allDeleted);
    await refreshProducts();
  } catch (error) {
    el.productsStatus.textContent = error.message;
  } finally {
    el.deleteAllYes.disabled = false;
    el.deleteAllConfirm.hidden = true;
    render();
  }
}

/** Switch between the chat and the saved products list. */
async function showView(next) {
  view = next;
  if (view === "products") {
    try {
      await refreshProducts();
    } catch (error) {
      savedProducts = [];
      render();
      el.productsStatus.textContent = error.message; // e.g. "Can't reach the backend..."
      return;
    }
  } else {
    await ensureChatLoaded(chatKey());
  }
  render();
}

// ---------- events ----------

el.form.addEventListener("submit", (event) => {
  event.preventDefault();
  const question = el.input.value.trim();
  if (!question || waiting) return;
  el.input.value = "";
  ask(question);
});

// Enter sends; Shift+Enter makes a new line.
el.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    el.form.requestSubmit();
  }
});

el.scopeCurrent.addEventListener("click", () => setScope("current"));
el.scopeHistory.addEventListener("click", () => setScope("history"));
el.retry.addEventListener("click", loadCurrentPage);
el.refresh.addEventListener("click", loadCurrentPage);
el.clear.addEventListener("click", clearCurrentChat);
el.viewChatBtn.addEventListener("click", () => showView("chat"));
el.viewProductsBtn.addEventListener("click", () => showView("products"));
el.deleteAll.addEventListener("click", askDeleteAll);
el.deleteAllNo.addEventListener("click", cancelDeleteAll);
el.deleteAllYes.addEventListener("click", confirmDeleteAll);

followTabs();
loadCurrentPage();

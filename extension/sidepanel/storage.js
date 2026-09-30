// Chat history saved in chrome.storage.local.
//
// chrome.storage.local is a small key-value store that Chrome keeps on this
// computer for our extension. It survives closing the side panel and
// restarting Chrome, and nothing in it leaves the computer. (The backend is
// stateless about conversations; see CLAUDE.md Section 3, point 7.)
//
// Keys (CLAUDE.md Section 5):
//   "chat:product:<product_id>"  one conversation per product ("This product")
//   "chat:all"                   the "All viewed products" conversation

const MAX_SAVED_MESSAGES = 60; // keep storage small: older messages are dropped

export const productChatKey = (productId) => `chat:product:${productId}`;
export const ALL_PRODUCTS_CHAT_KEY = "chat:all";

/** The saved messages for a conversation (an empty list if none). */
export async function loadChat(key) {
  const stored = await chrome.storage.local.get(key);
  return Array.isArray(stored[key]) ? stored[key] : [];
}

/**
 * Save a conversation. Error bubbles and questions that failed aren't worth
 * keeping, so only successful turns are stored.
 */
export async function saveChat(key, messages) {
  const worthKeeping = messages
    .filter((m) => m.role === "assistant" || (m.role === "user" && !m.failed))
    .slice(-MAX_SAVED_MESSAGES);
  await chrome.storage.local.set({ [key]: worthKeeping });
}

/** Delete a saved conversation. */
export async function clearChat(key) {
  await chrome.storage.local.remove(key);
}

/** Delete every saved conversation (used by "Delete all" products). */
export async function clearAllChats() {
  const everything = await chrome.storage.local.get(null);
  const chatKeys = Object.keys(everything).filter((key) => key.startsWith("chat:"));
  if (chatKeys.length) await chrome.storage.local.remove(chatKeys);
}

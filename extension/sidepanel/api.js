// One function per backend endpoint (CLAUDE.md Section 7).
//
// Every function either returns the backend's JSON or throws an ApiError whose
// `kind` tells the side panel what went wrong:
//   "unreachable" - the backend isn't running (or the request timed out)
//   "client"      - a 4xx error: our request was refused (message from the backend)
//   "server"      - a 5xx error: the backend or the LLM behind it failed

import { BACKEND_URL } from "../config.js";

const TIMEOUT_MS = 90_000; // LLM answers can take a while; the first ingest loads a model

export const UNREACHABLE_MESSAGE =
  "Can't reach the backend. Is the server running on localhost:8000?";

export class ApiError extends Error {
  constructor(kind, message, status = null) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
  }
}

/** Pick a readable message out of a FastAPI error body. */
function errorMessage(data, status) {
  if (typeof data?.detail === "string") return data.detail;
  if (Array.isArray(data?.detail)) return "The data sent to the backend was not in the expected format.";
  return `The backend returned an error (HTTP ${status}).`;
}

/** Send one request and turn every kind of failure into an ApiError. */
async function request(method, path, body = undefined) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  let response;
  try {
    response = await fetch(`${BACKEND_URL}${path}`, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
  } catch {
    throw new ApiError("unreachable", UNREACHABLE_MESSAGE);
  } finally {
    clearTimeout(timer);
  }

  const data = await response.json().catch(() => null);
  if (response.ok) return data;
  const kind = response.status >= 500 ? "server" : "client";
  throw new ApiError(kind, errorMessage(data, response.status), response.status);
}

/** GET /health → {status: "ok"} */
export const health = () => request("GET", "/health");

/** POST /ingest → {product_id, title, mode, num_chunks, char_count, sections_found, cached} */
export const ingestProduct = (product) => request("POST", "/ingest", product);

/** POST /chat → {answer, scope, mode, sources} */
export const chat = ({ scope, productId = null, question, history = [] }) =>
  request("POST", "/chat", { scope, product_id: productId, question, history });

/** GET /products → list of saved products, newest first */
export const listProducts = () => request("GET", "/products");

/** DELETE /products/{id} → {deleted: true} */
export const deleteProduct = (productId) =>
  request("DELETE", `/products/${encodeURIComponent(productId)}`);

/** DELETE /products → {deleted_count: n} */
export const deleteAllProducts = () => request("DELETE", "/products");

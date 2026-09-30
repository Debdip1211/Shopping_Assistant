"""Stable product IDs.

The same product can be opened through many different URLs, e.g.
    https://www.amazon.in/Some-Phone/dp/B0ABCDEFGH?ref=sr_1_3
    https://www.amazon.in/dp/B0ABCDEFGH?th=1&psc=1
Tracking parameters change every visit, so we can't use the raw URL as an ID.
Instead we pick the part of the URL that identifies the product (Amazon's ASIN,
Flipkart's `pid`, or the clean URL for other sites) as a readable "key", and
hash that key into a short, fixed-length ID.
"""

import hashlib
import re
from urllib.parse import parse_qs, urlsplit

# Amazon product IDs (ASINs) are 10 uppercase letters/digits after /dp/ or /gp/product/.
AMAZON_ASIN_RE = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})")


def _url_without_query(url: str) -> str:
    """Return the URL with its query string (?...) and fragment (#...) removed."""
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/") or "/"
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}{path}"


def make_product_key(url: str, site: str) -> str:
    """Return the readable key that identifies a product, e.g. 'amazon:B0ABCDEFGH'."""
    if site == "amazon":
        match = AMAZON_ASIN_RE.search(url)
        if match:
            return f"amazon:{match.group(1)}"
    elif site == "flipkart":
        pid = parse_qs(urlsplit(url).query).get("pid")
        if pid and pid[0].strip():
            return f"flipkart:{pid[0].strip()}"
        path = urlsplit(url).path.rstrip("/")
        if path:
            return f"flipkart:{path}"
    # Other sites (and Amazon/Flipkart URLs without a recognisable ID).
    return _url_without_query(url)


def make_product_id(url: str, site: str) -> str:
    """Return a short stable ID: the first 16 hex characters of sha256(key)."""
    key = make_product_key(url, site)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]

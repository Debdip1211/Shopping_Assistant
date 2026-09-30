"""Tests for stable product IDs (app/product_id.py)."""

import re

from app.product_id import make_product_id, make_product_key

ASIN = "B0ABCDEFGH"


def test_amazon_tracking_params_and_url_forms_give_same_id() -> None:
    urls = [
        f"https://www.amazon.in/Some-Phone-8GB/dp/{ASIN}?ref=sr_1_3&keywords=phone",
        f"https://www.amazon.in/dp/{ASIN}?th=1&psc=1",
        f"https://www.amazon.in/Other-Slug/dp/{ASIN}/ref=abc#reviews",
        f"https://www.amazon.in/gp/product/{ASIN}?tag=deals-21",
    ]
    ids = {make_product_id(url, "amazon") for url in urls}
    assert len(ids) == 1
    assert make_product_key(urls[0], "amazon") == f"amazon:{ASIN}"


def test_amazon_different_asins_give_different_ids() -> None:
    first = make_product_id("https://www.amazon.in/dp/B0AAAAAAAA", "amazon")
    second = make_product_id("https://www.amazon.in/dp/B0BBBBBBBB", "amazon")
    assert first != second


def test_id_is_16_hex_characters() -> None:
    product_id = make_product_id(f"https://www.amazon.in/dp/{ASIN}", "amazon")
    assert re.fullmatch(r"[0-9a-f]{16}", product_id)


def test_amazon_without_asin_falls_back_to_clean_url() -> None:
    key = make_product_key("https://www.amazon.in/s?k=phones", "amazon")
    assert key == "https://www.amazon.in/s"


def test_flipkart_uses_pid() -> None:
    base = "https://www.flipkart.com/vortex-neo-12/p/itm123"
    first = f"{base}?pid=MOBH7VNX12ABCD34&lid=AAA&marketplace=FLIPKART"
    second = f"{base}?lid=BBB&pid=MOBH7VNX12ABCD34&srno=s_1_2"
    assert make_product_key(first, "flipkart") == "flipkart:MOBH7VNX12ABCD34"
    assert make_product_id(first, "flipkart") == make_product_id(second, "flipkart")


def test_flipkart_without_pid_uses_path() -> None:
    first = "https://www.flipkart.com/vortex-neo-12/p/itm123?lid=AAA"
    second = "https://www.flipkart.com/vortex-neo-12/p/itm123?srno=xyz#reviews"
    assert make_product_key(first, "flipkart") == "flipkart:/vortex-neo-12/p/itm123"
    assert make_product_id(first, "flipkart") == make_product_id(second, "flipkart")


def test_generic_site_ignores_query_and_fragment() -> None:
    first = "https://shop.example/laptops/book-14?utm_source=google#reviews"
    second = "https://SHOP.example/laptops/book-14/?variant=silver"
    assert make_product_key(first, "other") == "https://shop.example/laptops/book-14"
    assert make_product_id(first, "other") == make_product_id(second, "other")


def test_generic_different_paths_give_different_ids() -> None:
    first = make_product_id("https://shop.example/laptops/book-14", "other")
    second = make_product_id("https://shop.example/laptops/book-15", "other")
    assert first != second

from price_monitor_v4.shops import find_product_url, parse_product


def test_product_json_ld_and_search_link_parsing() -> None:
    product_html = """
    <html><head><script type="application/ld+json">
    {"@type":"Product","name":"TCL 55P7L television","offers":{"@type":"Offer","price":"630.00","priceCurrency":"EUR","availability":"https://schema.org/InStock"}}
    </script></head><body>Available</body></html>
    """
    result = parse_product(product_html, "https://shop.example/tcl-55p7l", "55P7L")
    assert result is not None
    assert result["price_eur"] == 630.0
    assert result["availability"] == "IN_STOCK"

    search_html = '<a href="/products/tcl-55p7l">TCL television 55P7L</a>'
    assert find_product_url(search_html, "https://shop.example/search?q=55P7L", "55P7L") == "https://shop.example/products/tcl-55p7l"

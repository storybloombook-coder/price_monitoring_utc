from price_monitor_v4.sources import SOURCE_BY_KEY, search_phrase


def test_discovery_queries_add_tcl_once() -> None:
    assert search_phrase("65C8L") == "TCL 65C8L"
    assert search_phrase("TCL 65C8L") == "TCL 65C8L"
    assert search_phrase("TCL65C8L") == "TCL 65C8L"
    assert SOURCE_BY_KEY["varle"].search_url("65C8L").endswith("q=TCL+65C8L")
    assert SOURCE_BY_KEY["salidzini"].search_url("TCL 25G64").endswith("q=TCL+25G64")

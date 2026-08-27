from pathlib import Path

import pytest
from openpyxl import Workbook

from price_monitor_v4.catalog import CatalogStore


def make_source_workbook(path: Path) -> None:
    workbook = Workbook()
    tv = workbook.active
    tv.title = "TV"
    tv.append(["Customer", "Model"])
    tv.append(["UTC", "55P7L"])
    sb = workbook.create_sheet("SB")
    sb.append(["Model"])
    sb.append(["Q65H"])
    workbook.create_sheet("Monitors").append(["Model"])
    workbook.save(path)


def make_stock_workbook(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Stock"
    sheet.append([None, "Main Warehouse", None, None])
    sheet.append([None, "TV TCL 55P7L", 3, 310.5])
    sheet.append([None, "Unknown accessory", 7, 12])
    workbook.save(path)


def test_import_edit_pause_trash_and_restore(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path / "catalog.sqlite3")
    source_path = tmp_path / "source.xlsx"
    stock_path = tmp_path / "stock.xlsx"
    make_source_workbook(source_path)
    make_stock_workbook(stock_path)

    source_result = store.import_source_workbook(source_path, "source.xlsx")
    stock_result = store.import_stock_workbook(stock_path, "stock.xlsx")

    assert source_result == {"imported": 2, "inserted": 2, "updated": 0}
    assert stock_result == {"imported": 2, "matched": 1}
    source = store.list_items("source")[0]
    edited = store.update_item(source["id"], {"model": "55P7L Pro", "paused": True})
    assert edited["model"] == "55P7L Pro"
    assert edited["paused"] is True
    assert edited["origin"] == "manual"

    trashed = store.trash_item(source["id"])
    assert trashed["state"] == "trash"
    assert source["id"] not in {item["id"] for item in store.list_items("source", "active")}
    restored = store.restore_item(source["id"])
    assert restored["state"] == "paused"

    other = next(item for item in store.list_items("source") if item["id"] != source["id"])
    with pytest.raises(ValueError, match="already exists"):
        store.update_item(other["id"], {"model": restored["model"]})


def test_prepare_legacy_filters_paused_and_trashed_items(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path / "catalog.sqlite3")
    active = store.create_item("source", {"model": "55P7L", "source_sheets": ["TV"]})
    paused = store.create_item("source", {"model": "Q65H", "source_sheets": ["SB"], "paused": True})
    stock = store.create_item(
        "stock",
        {"nomenclature": "TCL 55P7L", "model": "55P7L", "warehouse": "Main", "quantity": 2, "unit_cost_eur": 300},
    )
    store.create_item(
        "stock",
        {"nomenclature": "Paused", "model": "Q65H", "quantity": 5, "unit_cost_eur": 100, "paused": True},
    )

    legacy_db = tmp_path / "legacy.sqlite3"
    active_book = tmp_path / "active.xlsx"
    store.prepare_legacy(tmp_path / "missing.sqlite3", legacy_db, active_book)

    from openpyxl import load_workbook
    import sqlite3

    workbook = load_workbook(active_book, data_only=True)
    assert [row[0].value for row in workbook["TV"].iter_rows(min_row=2)] == [active["model"]]
    assert [row[0].value for row in workbook["SB"].iter_rows(min_row=2)] == []
    with sqlite3.connect(legacy_db) as db:
        rows = db.execute("SELECT nomenclature, canonical_model FROM stock_items").fetchall()
    assert rows == [(stock["nomenclature"], "55P7L")]


def test_source_toggles_and_manual_shop_links_are_persisted(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path / "catalog.sqlite3")
    item = store.create_item(
        "source",
        {"model": "55P7L", "shop_links": {"varle": "https://www.varle.lt/example.html"}},
    )
    assert item["shop_links"] == {"varle": "https://www.varle.lt/example.html"}

    store.update_item(item["id"], {"shop_links": {"elesen": "https://www.elesen.lt/example"}})
    assert store.get_item(item["id"])["shop_links"] == {"elesen": "https://www.elesen.lt/example"}

    store.update_source("senukai", False)
    store.update_source_master("shop", False)
    senukai = next(source for source in store.list_sources() if source["key"] == "senukai")
    assert senukai["enabled"] is False
    assert senukai["master_enabled"] is False
    assert senukai["effective_enabled"] is False

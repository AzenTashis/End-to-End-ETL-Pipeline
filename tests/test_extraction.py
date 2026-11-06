"""Tests for the extraction stage: CSV files, customer file, and the product API."""

from __future__ import annotations

import threading

import pytest
import requests

from src.exceptions import APIExtractionError, SourceFileError
from src.extraction.check_sources import check_data_sources
from src.extraction.extract_api import fetch_all_products, get_products, load_snapshot
from src.extraction.extract_csv import extract_branch_sales, extract_sales, read_csv_safely
from src.extraction.extract_customers import extract_customers
from tests.conftest import SALES_HEADER

# ------------------------------------------------------------------ CSV ----


def test_extract_sales_combines_all_three_branches(source_files, tmp_path):
    result = extract_sales(source_files, tmp_path / "raw")
    assert result["sales_extracted"] == 3
    assert result["sales_extracted_per_branch"] == {"B1": 1, "B2": 1, "B3": 1}
    assert (tmp_path / "raw" / "sales_raw.csv").exists()


def test_extracted_values_stay_as_raw_text(source_files):
    frame = extract_branch_sales(source_files)
    # Nothing is cleaned yet: the messy category keeps its trailing space.
    assert "Beauty " in set(frame["category"])
    assert list(frame["source_row_number"]) == [2, 2, 2]


def test_missing_file_raises_clear_error(source_files):
    (source_files / "sales_branch_2.csv").unlink()
    with pytest.raises(SourceFileError, match="not found"):
        extract_branch_sales(source_files)


def test_empty_file_raises(source_files):
    (source_files / "sales_branch_1.csv").write_text("")
    with pytest.raises(SourceFileError, match="empty"):
        extract_branch_sales(source_files)


def test_corrupted_binary_file_raises(source_files):
    (source_files / "sales_branch_3.csv").write_bytes(b"\xff\xfe\x00\x81garbage\x00\xff")
    with pytest.raises(SourceFileError):
        extract_branch_sales(source_files)


def test_missing_columns_raise(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("transaction_id,quantity\nT1,2\n")
    with pytest.raises(SourceFileError, match="missing required columns"):
        read_csv_safely(path, SALES_HEADER)


def test_extract_customers(source_files, tmp_path):
    result = extract_customers(source_files, tmp_path / "raw")
    assert result["customers_extracted"] == 3


# ------------------------------------------------------------------ API ----

class FakeResponse:
    def __init__(self, payload=None, status=200, bad_json=False):
        self._payload, self.status_code, self._bad_json = payload, status, bad_json
        self.url = "http://fake/products"

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    """Pretends to be requests.Session and returns pre-made pages."""

    def __init__(self, products, page_size=2):
        self.products, self.page_size, self.calls = products, page_size, 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        skip = params["skip"]
        page = self.products[skip: skip + params["limit"]]
        return FakeResponse({"products": page, "total": len(self.products), "skip": skip, "limit": len(page)})


PRODUCTS = [{"id": i, "title": f"P{i}", "category": "beauty", "price": 1.5 * i, "description": "x"}
            for i in range(1, 6)]


def test_api_pagination_fetches_every_page():
    session = FakeSession(PRODUCTS)
    products = fetch_all_products("http://fake", page_size=2, session=session)
    assert [p["id"] for p in products] == [1, 2, 3, 4, 5]
    assert session.calls == 3          # pages of 2 + 2 + 1


def test_api_timeout_becomes_api_error():
    class TimeoutSession:
        def get(self, *args, **kwargs):
            raise requests.exceptions.Timeout("too slow")

    with pytest.raises(APIExtractionError, match="timed out"):
        fetch_all_products("http://fake", session=TimeoutSession())


@pytest.mark.parametrize("response, message", [
    (FakeResponse(bad_json=True), "not valid JSON"),
    (FakeResponse({"items": []}), "no 'products'"),
    (FakeResponse({"products": [], "total": 0}), "zero products"),
    (FakeResponse({"products": [{"id": 1}], "total": 1}), "missing fields"),
    (FakeResponse({}, status=500), "HTTP 500"),
])
def test_invalid_api_responses_are_rejected(response, message):
    class OneShot:
        def get(self, *args, **kwargs):
            return response

    with pytest.raises(APIExtractionError, match=message):
        fetch_all_products("http://fake", session=OneShot())


def test_unreachable_api_falls_back_to_snapshot(data_root):
    products, source = get_products()
    assert source == "snapshot"
    assert len(products) > 0


def test_unreachable_api_without_fallback_raises(data_root):
    with pytest.raises(APIExtractionError):
        get_products(allow_fallback=False)


def test_snapshot_file_is_valid():
    from config.config import get_settings
    assert len(load_snapshot(get_settings().products_snapshot_path)) >= 20


def test_local_mock_api_end_to_end():
    """Start the real mock server on a free port and fetch through HTTP."""
    from scripts.mock_api import create_server

    server = create_server(port=0, host="127.0.0.1")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        products = fetch_all_products(f"http://127.0.0.1:{port}", page_size=7, timeout=5, max_retries=0)
        assert len(products) >= 20
        assert products[0]["id"] == 1
    finally:
        server.shutdown()


# ---------------------------------------------------------- source check ----

def test_check_data_sources_passes_with_snapshot(source_files):
    result = check_data_sources()
    assert result["api_reachable"] is False
    assert result["snapshot_available"] is True
    assert "customers.csv" in result["files_checked"]


def test_check_data_sources_fails_for_missing_file(source_files):
    (source_files / "customers.csv").unlink()
    with pytest.raises(SourceFileError):
        check_data_sources()

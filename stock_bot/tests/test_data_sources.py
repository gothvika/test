"""
Tests for data_sources.py's get_top_movers() (mocked HTTP) and the
query-batching helper (pure function, no I/O).
"""

from unittest.mock import MagicMock, patch

import data_sources


def _mock_response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    else:
        resp.raise_for_status.return_value = None
    return resp


def test_get_top_movers_returns_gainer_symbols():
    body = {"gainers": [{"symbol": "AAA", "percent_change": 12.0}, {"symbol": "BBB", "percent_change": 8.0}],
            "losers": [{"symbol": "ZZZ", "percent_change": -9.0}]}
    with patch("data_sources.requests.get", return_value=_mock_response(body)):
        symbols = data_sources.get_top_movers(limit=10)

    assert symbols == ["AAA", "BBB"]


def test_get_top_movers_fails_soft_on_error():
    with patch("data_sources.requests.get", side_effect=Exception("network error")):
        symbols = data_sources.get_top_movers(limit=10)

    assert symbols == []


def test_get_top_movers_disabled_with_zero_limit():
    with patch("data_sources.requests.get") as mock_get:
        symbols = data_sources.get_top_movers(limit=0)

    assert symbols == []
    mock_get.assert_not_called()


def test_batch_symbols_for_query_respects_length_cap():
    symbols = [f"SYM{i}" for i in range(100)]
    batches = data_sources._batch_symbols_for_query(symbols, max_query_len=50)

    # Every symbol should appear exactly once across all batches.
    flattened = [s for batch in batches for s in batch]
    assert flattened == symbols
    # No batch should wildly exceed the cap (allowing for the one term that
    # pushed it over, per the batching logic's own boundary check).
    for batch in batches:
        query_len = sum(len(f'"${s}" OR ') for s in batch)
        assert query_len <= 50 + len('"$SYM99" OR ')

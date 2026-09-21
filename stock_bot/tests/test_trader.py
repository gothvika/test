"""
Tests for trader.py's stop-loss / take-profit logic. Alpaca's HTTP API is
mocked — these test the decision logic, not live API integration.
"""

from unittest.mock import MagicMock, patch

import config
import trader


def _mock_response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    else:
        resp.raise_for_status.return_value = None
    return resp


def test_stop_loss_triggers_sell():
    positions = [
        {"symbol": "AAA", "qty": "1", "avg_entry_price": "10", "unrealized_plpc": "-0.25"},
        {"symbol": "BBB", "qty": "1", "avg_entry_price": "10", "unrealized_plpc": "0.05"},
    ]
    with patch.object(config, "STOP_LOSS_PCT", -0.20), \
         patch.object(config, "TAKE_PROFIT_PCT", 0), \
         patch("trader.requests.get", return_value=_mock_response(positions)), \
         patch("trader.requests.delete", return_value=_mock_response({"id": "order-1"})) as mock_delete:

        results = trader.apply_stop_loss_and_take_profit()

    assert results["AAA"]["action"] == "sold_stop_loss"
    assert "BBB" not in results
    mock_delete.assert_called_once()


def test_take_profit_triggers_sell_when_enabled():
    positions = [{"symbol": "CCC", "qty": "1", "avg_entry_price": "10", "unrealized_plpc": "0.45"}]
    with patch.object(config, "STOP_LOSS_PCT", -0.20), \
         patch.object(config, "TAKE_PROFIT_PCT", 0.40), \
         patch("trader.requests.get", return_value=_mock_response(positions)), \
         patch("trader.requests.delete", return_value=_mock_response({"id": "order-2"})):

        results = trader.apply_stop_loss_and_take_profit()

    assert results["CCC"]["action"] == "sold_take_profit"


def test_take_profit_disabled_by_default_does_not_sell_winners():
    positions = [{"symbol": "DDD", "qty": "1", "avg_entry_price": "10", "unrealized_plpc": "0.90"}]
    with patch.object(config, "STOP_LOSS_PCT", -0.20), \
         patch.object(config, "TAKE_PROFIT_PCT", 0), \
         patch("trader.requests.get", return_value=_mock_response(positions)), \
         patch("trader.requests.delete") as mock_delete:

        results = trader.apply_stop_loss_and_take_profit()

    assert results == {}
    mock_delete.assert_not_called()


def test_no_action_when_within_thresholds():
    positions = [{"symbol": "EEE", "qty": "1", "avg_entry_price": "10", "unrealized_plpc": "-0.05"}]
    with patch.object(config, "STOP_LOSS_PCT", -0.20), \
         patch.object(config, "TAKE_PROFIT_PCT", 0.40), \
         patch("trader.requests.get", return_value=_mock_response(positions)), \
         patch("trader.requests.delete") as mock_delete:

        results = trader.apply_stop_loss_and_take_profit()

    assert results == {}
    mock_delete.assert_not_called()


def test_position_fetch_failure_returns_empty_without_raising():
    with patch("trader.requests.get", side_effect=Exception("network error")):
        results = trader.apply_stop_loss_and_take_profit()

    assert results == {}


def test_buy_dollar_amount_captures_immediate_fill_price():
    post_resp = _mock_response({"id": "o1", "filled_avg_price": "12.34"})
    with patch("trader.requests.post", return_value=post_resp), \
         patch("trader.requests.get") as mock_get:
        order = trader.buy_dollar_amount("GOOD", 2.0)

    assert order["filled_avg_price"] == "12.34"
    mock_get.assert_not_called()  # already filled — no need to poll


def test_buy_dollar_amount_polls_for_delayed_fill_price():
    post_resp = _mock_response({"id": "o2", "filled_avg_price": None})
    filled_resp = _mock_response({"id": "o2", "filled_avg_price": "5.00"})
    with patch("trader.requests.post", return_value=post_resp), \
         patch("trader.requests.get", return_value=filled_resp), \
         patch("trader.time.sleep"):
        order = trader.buy_dollar_amount("GOOD", 2.0)

    assert order["filled_avg_price"] == "5.00"


def test_buy_dollar_amount_gives_up_after_max_attempts_without_raising():
    post_resp = _mock_response({"id": "o3", "filled_avg_price": None})
    still_pending_resp = _mock_response({"id": "o3", "filled_avg_price": None})
    with patch("trader.requests.post", return_value=post_resp), \
         patch("trader.requests.get", return_value=still_pending_resp) as mock_get, \
         patch("trader.time.sleep"):
        order = trader.buy_dollar_amount("GOOD", 2.0)

    assert order["filled_avg_price"] is None
    assert mock_get.call_count == 3  # max_attempts, then gives up

"""
Tests for app.py's three-step flow (landing -> generate report -> confirm
& execute) using Flask's test client. All data sources and the broker are
mocked — no live network or real orders.
"""

from unittest.mock import patch

import pytest

import app as app_module
import config
import history


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Isolate history.py's writes to a tmp dir — without this, every test
    # that hits /report or /execute would write real files into the
    # project's actual stock_bot/history/.
    monkeypatch.setattr(history, "HISTORY_DIR", str(tmp_path))

    app_module.app.config["TESTING"] = True
    app_module._last_report.clear()
    with app_module.app.test_client() as c:
        yield c
    app_module._last_report.clear()


FAKE_PICKS = [
    {
        "symbol": "GOOD", "final_score": 0.75, "price": 12.0,
        "volume_score": 0.5, "mention_score": 0.4, "mention_count": 3,
        "momentum_score": 0.6, "momentum_pct": 0.05,
        "roe": 0.18, "roe_score": 0.8,
        "ai_score": 0.82, "ai_summary": "Solid fundamentals.",
        "ai_sources": ["https://example.com/article"],
    },
]


def _patch_env_ok():
    return (
        patch.object(config, "ALPACA_API_KEY", "key"),
        patch.object(config, "ALPACA_SECRET_KEY", "secret"),
        patch.object(config, "ANTHROPIC_API_KEY", "key"),
        patch.object(config, "FMP_API_KEY", "key"),
    )


def test_index_shows_missing_env_error(client):
    with patch.object(config, "ALPACA_API_KEY", ""):
        resp = client.get("/")
    assert resp.status_code == 200
    assert b"Missing required environment variables" in resp.data


def test_index_renders_when_configured(client):
    with patch.object(config, "ALPACA_API_KEY", "key"), \
         patch.object(config, "ALPACA_SECRET_KEY", "secret"), \
         patch.object(config, "ANTHROPIC_API_KEY", "key"), \
         patch.object(config, "FMP_API_KEY", "key"), \
         patch("app.check_market_open", return_value=True), \
         patch("app._already_ran_today", return_value=False):
        resp = client.get("/")

    assert resp.status_code == 200
    assert b"Generate report" in resp.data


def test_report_shows_confirm_form_when_market_open_and_not_run_today(client):
    with patch.object(config, "ALPACA_API_KEY", "key"), \
         patch.object(config, "ALPACA_SECRET_KEY", "secret"), \
         patch.object(config, "ANTHROPIC_API_KEY", "key"), \
         patch.object(config, "FMP_API_KEY", "key"), \
         patch("app.check_market_open", return_value=True), \
         patch("app._already_ran_today", return_value=False), \
         patch("app.apply_stop_loss_and_take_profit", return_value={}), \
         patch("app.pick_top_stocks", return_value=(FAKE_PICKS, FAKE_PICKS)):
        resp = client.post("/report")

    assert resp.status_code == 200
    assert b"GOOD" in resp.data
    assert b"Confirm &amp; buy" in resp.data
    assert len(app_module._last_report) == 1


def test_report_disables_confirm_when_market_closed(client):
    with patch.object(config, "ALPACA_API_KEY", "key"), \
         patch.object(config, "ALPACA_SECRET_KEY", "secret"), \
         patch.object(config, "ANTHROPIC_API_KEY", "key"), \
         patch.object(config, "FMP_API_KEY", "key"), \
         patch("app.check_market_open", return_value=False), \
         patch("app._already_ran_today", return_value=False), \
         patch("app.pick_top_stocks", return_value=(FAKE_PICKS, FAKE_PICKS)):
        resp = client.post("/report")

    assert resp.status_code == 200
    assert b"disabled" in resp.data
    assert b'name="run_id"' not in resp.data


def test_execute_places_orders_for_cached_picks(client):
    with patch.object(config, "ALPACA_API_KEY", "key"), \
         patch.object(config, "ALPACA_SECRET_KEY", "secret"), \
         patch.object(config, "ANTHROPIC_API_KEY", "key"), \
         patch.object(config, "FMP_API_KEY", "key"), \
         patch("app.check_market_open", return_value=True), \
         patch("app._already_ran_today", return_value=False), \
         patch("app.apply_stop_loss_and_take_profit", return_value={}), \
         patch("app.pick_top_stocks", return_value=(FAKE_PICKS, FAKE_PICKS)):
        report_resp = client.post("/report")

    run_id = list(app_module._last_report.keys())[0]

    with patch("app.check_market_open", return_value=True), \
         patch("app._already_ran_today", return_value=False), \
         patch("app.buy_dollar_amount", return_value={"id": "order-123"}) as mock_buy, \
         patch("app._save_state") as mock_save:
        exec_resp = client.post("/execute", data={"run_id": run_id})

    assert exec_resp.status_code == 200
    assert b"order-123" in exec_resp.data
    mock_buy.assert_called_once_with("GOOD", config.DOLLARS_PER_STOCK)
    mock_save.assert_called_once()
    # run_id is single-use
    assert run_id not in app_module._last_report


def test_execute_rejects_invalid_run_id(client):
    resp = client.post("/execute", data={"run_id": "does-not-exist"})
    assert resp.status_code == 200
    assert b"expired" in resp.data


def test_execute_refuses_when_market_closed(client):
    app_module._last_report["abc"] = {"picks": FAKE_PICKS, "sell_results": {}}

    with patch("app._already_ran_today", return_value=False), \
         patch("app.check_market_open", return_value=False), \
         patch("app.buy_dollar_amount") as mock_buy:
        resp = client.post("/execute", data={"run_id": "abc"})

    assert resp.status_code == 200
    assert b"Market is closed" in resp.data
    mock_buy.assert_not_called()


def test_execute_refuses_double_buy_same_day(client):
    app_module._last_report["abc"] = {"picks": FAKE_PICKS, "sell_results": {}}

    with patch("app._already_ran_today", return_value=True), \
         patch("app.buy_dollar_amount") as mock_buy:
        resp = client.post("/execute", data={"run_id": "abc"})

    assert resp.status_code == 200
    assert b"twice" in resp.data
    mock_buy.assert_not_called()


FAKE_POSITIONS = [
    {
        "symbol": "GOOD", "qty": 0.1667, "avg_entry_price": 12.0, "unrealized_plpc": 0.083,
        "current_price": 13.0, "market_value": 2.1667, "unrealized_pl": 0.1667, "cost_basis": 2.0,
    },
]
FAKE_ACCOUNT = {"cash": 950.0, "portfolio_value": 952.17, "equity": 952.17, "buying_power": 1900.0}


def test_portfolio_shows_positions_and_sector(client):
    with patch.object(config, "ALPACA_API_KEY", "key"), \
         patch.object(config, "ALPACA_SECRET_KEY", "secret"), \
         patch.object(config, "ANTHROPIC_API_KEY", "key"), \
         patch.object(config, "FMP_API_KEY", "key"), \
         patch("app.get_positions", return_value=FAKE_POSITIONS), \
         patch("app.get_account", return_value=FAKE_ACCOUNT), \
         patch("app.get_company_profile", return_value={"sector": "Technology"}):
        resp = client.get("/portfolio")

    assert resp.status_code == 200
    assert b"GOOD" in resp.data
    assert b"Technology" in resp.data
    assert b"Refresh" in resp.data


def test_portfolio_handles_no_positions(client):
    with patch.object(config, "ALPACA_API_KEY", "key"), \
         patch.object(config, "ALPACA_SECRET_KEY", "secret"), \
         patch.object(config, "ANTHROPIC_API_KEY", "key"), \
         patch.object(config, "FMP_API_KEY", "key"), \
         patch("app.get_positions", return_value=[]), \
         patch("app.get_account", return_value=FAKE_ACCOUNT):
        resp = client.get("/portfolio")

    assert resp.status_code == 200
    assert b"No open positions" in resp.data


def test_portfolio_flags_sector_concentration(client):
    concentrated = [
        {"symbol": "A", "qty": 1, "avg_entry_price": 10.0, "unrealized_plpc": 0.0,
         "current_price": 10.0, "market_value": 10.0, "unrealized_pl": 0.0, "cost_basis": 10.0},
        {"symbol": "B", "qty": 1, "avg_entry_price": 10.0, "unrealized_plpc": 0.0,
         "current_price": 10.0, "market_value": 10.0, "unrealized_pl": 0.0, "cost_basis": 10.0},
    ]
    with patch.object(config, "ALPACA_API_KEY", "key"), \
         patch.object(config, "ALPACA_SECRET_KEY", "secret"), \
         patch.object(config, "ANTHROPIC_API_KEY", "key"), \
         patch.object(config, "FMP_API_KEY", "key"), \
         patch("app.get_positions", return_value=concentrated), \
         patch("app.get_account", return_value=FAKE_ACCOUNT), \
         patch("app.get_company_profile", return_value={"sector": "Technology"}):
        resp = client.get("/portfolio")

    assert resp.status_code == 200
    assert b"over 40%" in resp.data


def test_history_list_empty(client):
    resp = client.get("/history")
    assert resp.status_code == 200
    assert b"No reports generated yet" in resp.data


def test_history_list_shows_recorded_days(client):
    history.record_report(FAKE_PICKS, {}, True, "PAPER", full_shortlist=FAKE_PICKS, day="2026-01-05")

    resp = client.get("/history")

    assert resp.status_code == 200
    assert b"2026-01-05" in resp.data


def test_history_detail_shows_shortlist_and_execution(client):
    history.record_report(FAKE_PICKS, {}, True, "PAPER", full_shortlist=FAKE_PICKS, day="2026-01-05")
    history.record_execution(
        {"GOOD": {"status": "submitted", "order_id": "o1", "scored_price": 12.0, "filled_avg_price": "12.10"}},
        day="2026-01-05",
    )

    with patch("app.get_latest_prices", return_value={"GOOD": 13.0}):
        resp = client.get("/history/2026-01-05")

    assert resp.status_code == 200
    assert b"GOOD" in resp.data
    assert b"Bought" in resp.data
    assert b"o1" in resp.data


def test_history_detail_missing_day_shows_error(client):
    resp = client.get("/history/2099-01-01")
    assert resp.status_code == 200
    assert b"No history record found" in resp.data

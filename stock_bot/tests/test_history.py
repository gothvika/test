"""
Tests for history.py's record/load round-trip. Uses a temp directory
(monkeypatched onto history.HISTORY_DIR) so tests never touch the real
local history/.
"""

import json
import os

import history


def test_record_report_then_execution_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_DIR", str(tmp_path))

    picks = [{"symbol": "GOOD", "price": 10.0, "ai_score": 0.8, "final_score": 0.7}]
    sell_results = {"OLD": {"action": "sold_stop_loss", "unrealized_plpc": -0.21}}

    history.record_report(picks, sell_results, market_open=True, mode="PAPER", day="2026-01-05")

    path = os.path.join(str(tmp_path), "2026-01-05.json")
    assert os.path.exists(path)
    with open(path) as f:
        record = json.load(f)
    assert record["picks"] == picks
    assert record["sell_results"] == sell_results
    assert record["executed"] is False
    assert record["execution"] is None

    execution_results = {"GOOD": {"status": "submitted", "order_id": "order-1"}}
    history.record_execution(execution_results, day="2026-01-05")

    with open(path) as f:
        record = json.load(f)
    assert record["executed"] is True
    assert record["execution"] == execution_results
    # the report data from the earlier call should still be intact
    assert record["picks"] == picks


def test_record_execution_without_prior_report_still_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_DIR", str(tmp_path))

    history.record_execution({"AAA": {"status": "submitted"}}, day="2026-01-06")

    path = os.path.join(str(tmp_path), "2026-01-06.json")
    assert os.path.exists(path)
    with open(path) as f:
        record = json.load(f)
    assert record["executed"] is True
    assert record["execution"] == {"AAA": {"status": "submitted"}}


def test_load_all_returns_sorted_records(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_DIR", str(tmp_path))

    history.record_report([], {}, True, "PAPER", day="2026-01-10")
    history.record_report([], {}, True, "PAPER", day="2026-01-02")

    records = history.load_all()
    assert [r["date"] for r in records] == ["2026-01-02", "2026-01-10"]


def test_load_all_empty_dir_returns_empty_list(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_DIR", str(tmp_path / "does-not-exist"))
    assert history.load_all() == []


def test_load_all_skips_unreadable_file(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_DIR", str(tmp_path))
    with open(os.path.join(str(tmp_path), "2026-01-03.json"), "w") as f:
        f.write("not valid json{{{")

    assert history.load_all() == []

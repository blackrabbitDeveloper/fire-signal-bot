import json
import os
import tempfile
import pytest


def test_load_state_returns_default_when_file_missing():
    from check_signal import load_state
    result = load_state("/nonexistent/path/state.json")
    assert result == {
        "signal": None,
        "last_check": None,
        "last_price": None,
        "last_sma": None,
        "diff_pct": None,
        "last_change": None,
    }


def test_load_state_reads_existing_file():
    from check_signal import load_state
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"signal": "RISK_ON", "last_check": "2025-04-07",
                    "last_price": 480.25, "last_sma": 455.30,
                    "diff_pct": 5.5, "last_change": "2025-03-15"}, f)
        path = f.name
    try:
        result = load_state(path)
        assert result["signal"] == "RISK_ON"
        assert result["last_price"] == 480.25
    finally:
        os.unlink(path)


def test_load_state_returns_default_on_corrupt_json():
    from check_signal import load_state
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write("not valid json{{{")
        path = f.name
    try:
        result = load_state(path)
        assert result["signal"] is None
    finally:
        os.unlink(path)


def test_save_state_writes_json():
    from check_signal import save_state
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        path = f.name
    try:
        state = {"signal": "RISK_OFF", "last_check": "2025-04-07",
                 "last_price": 420.10, "last_sma": 455.30,
                 "diff_pct": -7.7, "last_change": "2025-04-07"}
        save_state(path, state)
        with open(path) as f:
            saved = json.load(f)
        assert saved["signal"] == "RISK_OFF"
        assert saved["diff_pct"] == -7.7
    finally:
        os.unlink(path)


from unittest.mock import patch, MagicMock
import json as json_mod


def _make_yahoo_response(closes: list[float]) -> bytes:
    """Helper: Yahoo Finance API 응답 JSON을 생성한다."""
    data = {
        "chart": {
            "result": [{
                "indicators": {
                    "adjclose": [{"adjclose": closes}]
                }
            }],
            "error": None
        }
    }
    return json_mod.dumps(data).encode("utf-8")


def test_fetch_price_data_parses_closes():
    from check_signal import fetch_price_data
    closes = [100.0 + i for i in range(250)]
    mock_response = MagicMock()
    mock_response.read.return_value = _make_yahoo_response(closes)
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("check_signal.urlopen", return_value=mock_response):
        result = fetch_price_data("QQQ", days=300)
    assert result == closes


def test_fetch_price_data_retries_on_failure():
    from check_signal import fetch_price_data
    closes = [100.0] * 250
    mock_ok = MagicMock()
    mock_ok.read.return_value = _make_yahoo_response(closes)
    mock_ok.__enter__ = lambda s: s
    mock_ok.__exit__ = MagicMock(return_value=False)

    with patch("check_signal.urlopen", side_effect=[Exception("fail"), Exception("fail"), mock_ok]):
        result = fetch_price_data("QQQ", days=300)
    assert len(result) == 250


def test_fetch_price_data_raises_after_max_retries():
    from check_signal import fetch_price_data
    with patch("check_signal.urlopen", side_effect=Exception("HTTP 503")):
        with pytest.raises(Exception, match="3회 재시도 후 실패"):
            fetch_price_data("QQQ", days=300)

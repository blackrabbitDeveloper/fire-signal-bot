import json
from datetime import datetime
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

    with patch("check_signal.urlopen", side_effect=[Exception("fail"), Exception("fail"), mock_ok]), \
         patch("check_signal.time.sleep"):
        result = fetch_price_data("QQQ", days=300)
    assert len(result) == 250


def test_fetch_price_data_raises_after_max_retries():
    from check_signal import fetch_price_data
    with patch("check_signal.urlopen", side_effect=Exception("HTTP 503")), \
         patch("check_signal.time.sleep"):
        with pytest.raises(Exception, match="3회 재시도 후 실패"):
            fetch_price_data("QQQ", days=300)


def test_calculate_sma_200():
    from check_signal import calculate_sma
    prices = [float(i) for i in range(1, 251)]  # 1.0 ~ 250.0
    sma = calculate_sma(prices, period=200)
    # 마지막 200개: 51~250, 평균 = (51+250)/2 = 150.5
    assert sma == 150.5


def test_calculate_sma_rounds_to_2_decimals():
    from check_signal import calculate_sma
    prices = [1.0, 2.0, 3.0]
    sma = calculate_sma(prices, period=3)
    assert sma == 2.0


def test_calculate_sma_raises_if_insufficient_data():
    from check_signal import calculate_sma
    prices = [100.0] * 100
    with pytest.raises(ValueError, match="200일"):
        calculate_sma(prices, period=200)


def test_determine_signal_risk_on():
    from check_signal import determine_signal
    assert determine_signal(price=480.0, sma=455.0) == "RISK_ON"


def test_determine_signal_risk_off_when_equal():
    from check_signal import determine_signal
    assert determine_signal(price=455.0, sma=455.0) == "RISK_OFF"


def test_determine_signal_risk_off_when_below():
    from check_signal import determine_signal
    assert determine_signal(price=420.0, sma=455.0) == "RISK_OFF"


def test_determine_signal_diff_pct():
    from check_signal import calculate_diff_pct
    result = calculate_diff_pct(price=480.25, sma=455.30)
    assert result == 5.48  # (480.25 - 455.30) / 455.30 * 100 = 5.479...


def test_build_signal_change_embed_risk_on():
    from check_signal import build_signal_change_embed
    embed = build_signal_change_embed(
        signal="RISK_ON", price=480.25, sma=455.30, diff_pct=5.48
    )
    assert embed["title"] == "🟢 RISK-ON 전환!"
    assert embed["color"] == 3066993
    field_names = [f["name"] for f in embed["fields"]]
    assert "QQQ 종가" in field_names
    assert "200일 SMA" in field_names
    assert "F1 (보수적)" in field_names
    assert "F2 (공격적)" in field_names
    assert "Phase 2 (배당추세 안정전략)" in field_names


def test_build_signal_change_embed_risk_off():
    from check_signal import build_signal_change_embed
    embed = build_signal_change_embed(
        signal="RISK_OFF", price=420.10, sma=455.30, diff_pct=-7.73
    )
    assert embed["title"] == "🔴 RISK-OFF 전환!"
    assert embed["color"] == 15158332
    fields = {f["name"]: f["value"] for f in embed["fields"]}
    assert fields["F1 (보수적)"] == "DBMF 30% + XLU 15% + GLD 55%"
    assert fields["F2 (공격적)"] == "DBMF 45% + GLD 55%"
    assert fields["Phase 2 (배당추세 안정전략)"] == "GLD 50% + BIL 50%"


def test_build_monthly_report_embed():
    from check_signal import build_monthly_report_embed
    embed = build_monthly_report_embed(
        signal="RISK_ON", price=480.25, sma=455.30,
        diff_pct=5.48, last_change="2025-03-15", check_date="2025-04-01"
    )
    assert embed["title"] == "📊 월간 F전략 시그널 리포트"
    assert embed["color"] == 3447003
    field_names = [f["name"] for f in embed["fields"]]
    assert "현재 시그널" in field_names
    assert "시그널 유지" in field_names


def test_build_error_embed():
    from check_signal import build_error_embed
    embed = build_error_embed("HTTP 503 Service Unavailable")
    assert embed["title"] == "⚠️ 시그널 체크 실패"
    assert embed["color"] == 16776960


def test_send_discord_notification():
    from check_signal import send_discord_notification
    embed = {"title": "test", "color": 0}
    mock_response = MagicMock()
    mock_response.status = 204
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("check_signal.urlopen", return_value=mock_response) as mock_urlopen:
        send_discord_notification("https://discord.com/api/webhooks/test/test", embed)
    call_args = mock_urlopen.call_args[0][0]
    body = json.loads(call_args.data.decode("utf-8"))
    assert body["embeds"][0]["title"] == "test"


def test_main_first_run_saves_state_no_notification(tmp_path):
    """최초 실행: state.json signal=null → 상태 저장만, 알림 미전송."""
    from check_signal import main
    state_path = str(tmp_path / "state.json")
    json.dump({"signal": None, "last_check": None, "last_price": None,
               "last_sma": None, "diff_pct": None, "last_change": None},
              open(state_path, "w"))

    closes = [450.0] * 199 + [480.0]  # 200개, SMA≈450.15, 종가=480.0
    mock_resp = MagicMock()
    mock_resp.read.return_value = _make_yahoo_response(closes)
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("check_signal.urlopen", return_value=mock_resp), \
         patch("check_signal.send_discord_notification") as mock_notify, \
         patch("check_signal.STATE_FILE", state_path):
        result = main()

    mock_notify.assert_not_called()
    with open(state_path) as f:
        saved = json.load(f)
    assert saved["signal"] == "RISK_ON"


def test_main_signal_change_sends_notification(tmp_path):
    """시그널 변경: RISK_ON → RISK_OFF → 알림 전송."""
    from check_signal import main
    state_path = str(tmp_path / "state.json")
    json.dump({"signal": "RISK_ON", "last_check": "2025-04-06", "last_price": 480.0,
               "last_sma": 455.0, "diff_pct": 5.49, "last_change": "2025-03-15"},
              open(state_path, "w"))

    # SMA will be 450.15, close=420 → RISK_OFF
    closes = [450.0] * 199 + [420.0]
    mock_resp = MagicMock()
    mock_resp.read.return_value = _make_yahoo_response(closes)
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("check_signal.urlopen", return_value=mock_resp), \
         patch("check_signal.send_discord_notification") as mock_notify, \
         patch("check_signal.STATE_FILE", state_path), \
         patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/test/test"}):
        result = main()

    mock_notify.assert_called_once()
    embed = mock_notify.call_args[0][1]
    assert "RISK-OFF" in embed["title"]


def test_main_no_change_sends_monthly_report(tmp_path):
    """시그널 유지: 월간 리포트 전송."""
    from check_signal import main
    state_path = str(tmp_path / "state.json")
    json.dump({"signal": "RISK_ON", "last_check": "2025-04-06", "last_price": 480.0,
               "last_sma": 455.0, "diff_pct": 5.49, "last_change": "2025-03-15"},
              open(state_path, "w"))

    closes = [450.0] * 199 + [480.0]  # still RISK_ON
    mock_resp = MagicMock()
    mock_resp.read.return_value = _make_yahoo_response(closes)
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("check_signal.urlopen", return_value=mock_resp), \
         patch("check_signal.send_discord_notification") as mock_notify, \
         patch("check_signal.STATE_FILE", state_path), \
         patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/test/test"}):
        result = main()

    mock_notify.assert_called_once()
    embed = mock_notify.call_args[0][1]
    assert "월간" in embed["title"]


def test_main_monthly_report_on_first_of_month(tmp_path):
    """매월 1일: 시그널 변경 없어도 월간 리포트 전송."""
    from check_signal import main
    state_path = str(tmp_path / "state.json")
    json.dump({"signal": "RISK_ON", "last_check": "2025-03-31", "last_price": 480.0,
               "last_sma": 455.0, "diff_pct": 5.49, "last_change": "2025-03-15"},
              open(state_path, "w"))

    closes = [450.0] * 199 + [480.0]
    mock_resp = MagicMock()
    mock_resp.read.return_value = _make_yahoo_response(closes)
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    fake_now = datetime(2025, 4, 1, 22, 0, 0)
    with patch("check_signal.urlopen", return_value=mock_resp), \
         patch("check_signal.send_discord_notification") as mock_notify, \
         patch("check_signal.STATE_FILE", state_path), \
         patch("check_signal.datetime") as mock_dt, \
         patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/test/test"}):
        mock_dt.now.return_value = fake_now
        mock_dt.strptime = datetime.strptime
        result = main()

    mock_notify.assert_called_once()
    embed = mock_notify.call_args[0][1]
    assert "월간" in embed["title"]

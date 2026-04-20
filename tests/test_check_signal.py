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


# ============================================================
# D3 Daily Escape Tests
# ============================================================

class TestCalculateDeviation:
    """calculate_deviation 경계값 테스트."""

    def test_deviation_minus_5_pct(self):
        from check_signal import calculate_deviation
        assert abs(calculate_deviation(950.0, 1000.0) - (-0.05)) < 1e-9

    def test_deviation_minus_9_9_pct(self):
        from check_signal import calculate_deviation
        assert abs(calculate_deviation(901.0, 1000.0) - (-0.099)) < 1e-9

    def test_deviation_minus_10_0_pct(self):
        from check_signal import calculate_deviation
        assert abs(calculate_deviation(900.0, 1000.0) - (-0.10)) < 1e-9

    def test_deviation_minus_10_1_pct(self):
        from check_signal import calculate_deviation
        assert abs(calculate_deviation(899.0, 1000.0) - (-0.101)) < 1e-9

    def test_deviation_minus_15_pct(self):
        from check_signal import calculate_deviation
        assert abs(calculate_deviation(850.0, 1000.0) - (-0.15)) < 1e-9


class TestCheckDailyEscape:
    """check_daily_escape 상태 조건 및 통합 테스트."""

    def _make_state(self, signal="RISK_ON", trigger=None, daily_escape_date=None):
        return {
            "signal": signal,
            "last_check": "2026-04-19",
            "last_price": 500.0,
            "last_sma": 550.0,
            "diff_pct": -9.09,
            "last_change": "2026-04-01",
            "trigger": trigger,
            "daily_escape_date": daily_escape_date,
        }

    def _mock_prices(self, close_price, sma_target=1000.0, n=250):
        """Generate prices where SMA200 == sma_target exactly, with final = close_price.

        Last 200 prices: 199 × fill + close_price, where
        fill = (sma_target * 200 - close_price) / 199
        """
        fill = (sma_target * 200 - close_price) / 199
        prices = [fill] * (n - 1) + [close_price]
        return prices

    def test_triggers_when_on_and_deviation_at_threshold(self, tmp_path):
        """On 상태 + deviation == -10% → 발동."""
        from check_signal import check_daily_escape
        state_path = str(tmp_path / "state.json")
        json.dump(self._make_state(), open(state_path, "w"))

        closes = self._mock_prices(900.0, sma_target=1000.0)
        mock_resp = MagicMock()
        mock_resp.read.return_value = _make_yahoo_response(closes)
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("check_signal.urlopen", return_value=mock_resp), \
             patch("check_signal.send_discord_notification") as mock_notify, \
             patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://test"}):
            result = check_daily_escape(state_path)

        assert result["signal"] == "RISK_OFF"
        assert result["trigger"] == "daily_escape"
        assert result["daily_escape_date"] is not None
        mock_notify.assert_called_once()

    def test_triggers_when_deviation_below_threshold(self, tmp_path):
        """On 상태 + deviation = -10.1% → 발동."""
        from check_signal import check_daily_escape
        state_path = str(tmp_path / "state.json")
        json.dump(self._make_state(), open(state_path, "w"))

        closes = self._mock_prices(899.0, sma_target=1000.0)
        mock_resp = MagicMock()
        mock_resp.read.return_value = _make_yahoo_response(closes)
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("check_signal.urlopen", return_value=mock_resp), \
             patch("check_signal.send_discord_notification") as mock_notify, \
             patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://test"}):
            result = check_daily_escape(state_path)

        assert result["signal"] == "RISK_OFF"
        mock_notify.assert_called_once()

    def test_no_trigger_when_deviation_above_threshold(self, tmp_path):
        """On 상태 + deviation = -9.9% → 스킵."""
        from check_signal import check_daily_escape
        state_path = str(tmp_path / "state.json")
        json.dump(self._make_state(), open(state_path, "w"))

        closes = self._mock_prices(901.0, sma_target=1000.0)
        mock_resp = MagicMock()
        mock_resp.read.return_value = _make_yahoo_response(closes)
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("check_signal.urlopen", return_value=mock_resp), \
             patch("check_signal.send_discord_notification") as mock_notify, \
             patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://test"}):
            result = check_daily_escape(state_path)

        assert result["signal"] == "RISK_ON"
        mock_notify.assert_not_called()

    def test_no_trigger_when_deviation_minus_5_pct(self, tmp_path):
        """On 상태 + deviation = -5% → 스킵."""
        from check_signal import check_daily_escape
        state_path = str(tmp_path / "state.json")
        json.dump(self._make_state(), open(state_path, "w"))

        closes = self._mock_prices(950.0, sma_target=1000.0)
        mock_resp = MagicMock()
        mock_resp.read.return_value = _make_yahoo_response(closes)
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("check_signal.urlopen", return_value=mock_resp), \
             patch("check_signal.send_discord_notification") as mock_notify, \
             patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://test"}):
            result = check_daily_escape(state_path)

        assert result["signal"] == "RISK_ON"
        mock_notify.assert_not_called()

    def test_skip_when_already_off(self, tmp_path):
        """Off 상태에서 발동 안 함."""
        from check_signal import check_daily_escape
        state_path = str(tmp_path / "state.json")
        json.dump(self._make_state(signal="RISK_OFF", trigger="monthly"), open(state_path, "w"))

        with patch("check_signal.send_discord_notification") as mock_notify:
            result = check_daily_escape(state_path)

        assert result["signal"] == "RISK_OFF"
        mock_notify.assert_not_called()

    def test_skip_same_month_retrigger(self, tmp_path):
        """같은 달 재발동 방지."""
        from check_signal import check_daily_escape
        state_path = str(tmp_path / "state.json")
        today_ym = datetime.now().strftime("%Y-%m")
        json.dump(
            self._make_state(signal="RISK_ON", daily_escape_date=f"{today_ym}-05"),
            open(state_path, "w"),
        )

        with patch("check_signal.send_discord_notification") as mock_notify:
            result = check_daily_escape(state_path)

        assert result["signal"] == "RISK_ON"
        mock_notify.assert_not_called()

    def test_allows_trigger_different_month(self, tmp_path):
        """전달 발동 이력 있어도 다른 달이면 발동 허용."""
        from check_signal import check_daily_escape
        state_path = str(tmp_path / "state.json")
        json.dump(
            self._make_state(signal="RISK_ON", daily_escape_date="2025-01-15"),
            open(state_path, "w"),
        )

        closes = self._mock_prices(850.0, sma_target=1000.0)
        mock_resp = MagicMock()
        mock_resp.read.return_value = _make_yahoo_response(closes)
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("check_signal.urlopen", return_value=mock_resp), \
             patch("check_signal.send_discord_notification") as mock_notify, \
             patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://test"}):
            result = check_daily_escape(state_path)

        assert result["signal"] == "RISK_OFF"
        assert result["trigger"] == "daily_escape"
        mock_notify.assert_called_once()

    def test_skip_insufficient_data(self, tmp_path):
        """SMA200 데이터 부족 (200일 미만) 시 안전 스킵."""
        from check_signal import check_daily_escape
        state_path = str(tmp_path / "state.json")
        json.dump(self._make_state(), open(state_path, "w"))

        closes = [500.0] * 100
        mock_resp = MagicMock()
        mock_resp.read.return_value = _make_yahoo_response(closes)
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("check_signal.urlopen", return_value=mock_resp), \
             patch("check_signal.send_discord_notification") as mock_notify:
            result = check_daily_escape(state_path)

        assert result["signal"] == "RISK_ON"
        mock_notify.assert_not_called()

    def test_backward_compat_no_trigger_field(self, tmp_path):
        """state.json에 trigger 필드 없을 때 하위 호환."""
        from check_signal import check_daily_escape
        state_path = str(tmp_path / "state.json")
        json.dump({
            "signal": "RISK_ON", "last_check": "2026-04-19",
            "last_price": 500.0, "last_sma": 550.0,
            "diff_pct": -9.09, "last_change": "2026-04-01",
        }, open(state_path, "w"))

        closes = self._mock_prices(900.0, sma_target=1000.0)
        mock_resp = MagicMock()
        mock_resp.read.return_value = _make_yahoo_response(closes)
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("check_signal.urlopen", return_value=mock_resp), \
             patch("check_signal.send_discord_notification") as mock_notify, \
             patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://test"}):
            result = check_daily_escape(state_path)

        assert result["signal"] == "RISK_OFF"
        assert result["trigger"] == "daily_escape"

    def test_api_failure_sends_error_notification(self, tmp_path):
        """Yahoo API 실패 시 에러 알림."""
        from check_signal import check_daily_escape
        state_path = str(tmp_path / "state.json")
        json.dump(self._make_state(), open(state_path, "w"))

        with patch("check_signal.urlopen", side_effect=Exception("HTTP 503")), \
             patch("check_signal.time.sleep"), \
             patch("check_signal.send_discord_notification") as mock_notify, \
             patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://test"}):
            with pytest.raises(Exception, match="3회 재시도 후 실패"):
                check_daily_escape(state_path)

        mock_notify.assert_called_once()
        embed = mock_notify.call_args[0][1]
        assert "실패" in embed["title"]


class TestBuildDailyEscapeEmbed:
    """긴급 탈출 embed 내용 검증."""

    def test_embed_contains_portfolio_instructions(self):
        from check_signal import build_daily_escape_embed
        embed = build_daily_escape_embed(
            price=900.0, sma=1000.0, deviation=-0.10, check_date="2026-04-20"
        )
        assert "긴급 탈출" in embed["title"]
        fields = {f["name"]: f["value"] for f in embed["fields"]}
        assert "TQQQ" in fields["매도"]
        assert "XLU" in fields["매도"]
        assert "DBMF" in fields["매수"]
        assert "GLD" in fields["유지"]
        assert "DBMF 45% + GLD 55%" in fields["최종 포트폴리오"]
        assert "-10.0" in fields["이격도"]


class TestMainTriggerField:
    """main()의 trigger/daily_escape_date 필드 처리."""

    def test_main_on_to_off_sets_monthly_trigger(self, tmp_path):
        """월말 체크 ON→OFF 전환 시 trigger=monthly."""
        from check_signal import main
        state_path = str(tmp_path / "state.json")
        json.dump({"signal": "RISK_ON", "last_check": "2026-04-06",
                    "last_price": 480.0, "last_sma": 455.0, "diff_pct": 5.49,
                    "last_change": "2026-03-15", "trigger": None,
                    "daily_escape_date": None},
                  open(state_path, "w"))

        closes = [450.0] * 199 + [420.0]
        mock_resp = MagicMock()
        mock_resp.read.return_value = _make_yahoo_response(closes)
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("check_signal.urlopen", return_value=mock_resp), \
             patch("check_signal.send_discord_notification"), \
             patch("check_signal.STATE_FILE", state_path), \
             patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://test"}):
            result = main()

        assert result["signal"] == "RISK_OFF"
        assert result["trigger"] == "monthly"

    def test_main_off_to_on_resets_escape_fields(self, tmp_path):
        """월말 체크 OFF→ON 복귀 시 trigger=null, daily_escape_date=null."""
        from check_signal import main
        state_path = str(tmp_path / "state.json")
        json.dump({"signal": "RISK_OFF", "last_check": "2026-04-06",
                    "last_price": 420.0, "last_sma": 455.0, "diff_pct": -7.7,
                    "last_change": "2026-04-06", "trigger": "daily_escape",
                    "daily_escape_date": "2026-04-05"},
                  open(state_path, "w"))

        closes = [450.0] * 199 + [480.0]
        mock_resp = MagicMock()
        mock_resp.read.return_value = _make_yahoo_response(closes)
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("check_signal.urlopen", return_value=mock_resp), \
             patch("check_signal.send_discord_notification"), \
             patch("check_signal.STATE_FILE", state_path), \
             patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://test"}):
            result = main()

        assert result["signal"] == "RISK_ON"
        assert result["trigger"] is None
        assert result["daily_escape_date"] is None

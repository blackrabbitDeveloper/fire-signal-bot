"""signal_checker 핵심 로직 단위 테스트."""

import json
import sys
from pathlib import Path

import pytest

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import EMERGENCY_EXIT_THRESHOLD, GOLDEN_CROSS_ENTRY_THRESHOLD
from signal_checker import check_signals, compute_indicators, is_last_trading_day, load_state, save_state

# ── 헬퍼 ──

def make_indicators(close=500.0, sma200=480.0, sma50=490.0, rsi=50.0):
    """테스트용 indicators dict 생성."""
    deviation = (close - sma200) / sma200
    return {
        "close": close,
        "sma200": sma200,
        "sma50": sma50,
        "deviation": deviation,
        "deviation_pct": deviation * 100,
        "rsi": rsi,
        "above_sma200": close > sma200,
        "golden_cross": sma50 > sma200,
    }


def make_state(state="On", exit_count=0, entry_count=0):
    return {
        "state": state,
        "last_check": None,
        "last_action": None,
        "last_action_date": None,
        "exit_count": exit_count,
        "entry_count": entry_count,
    }


# ── 긴급 탈출 (D3) ──

class TestEmergencyExit:
    def test_triggers_when_on_and_deviation_below_minus10(self):
        """On 상태 + 편차 ≤ -10% → 긴급 탈출."""
        indicators = make_indicators(close=430.0, sma200=480.0)  # -10.4%
        assert indicators["deviation"] <= EMERGENCY_EXIT_THRESHOLD

        actions = check_signals(make_state("On"), indicators)
        assert len(actions) == 1
        assert actions[0]["type"] == "EMERGENCY_EXIT"
        assert actions[0]["urgency"] == "CRITICAL"
        assert actions[0]["new_state"] == "Off"

    def test_exact_minus10_triggers(self):
        """편차 정확히 -10% → 발동."""
        sma200 = 500.0
        close = sma200 * 0.90  # 정확히 -10%
        indicators = make_indicators(close=close, sma200=sma200)

        actions = check_signals(make_state("On"), indicators)
        assert actions[0]["type"] == "EMERGENCY_EXIT"

    def test_does_not_trigger_when_off(self):
        """Off 상태에서는 긴급 탈출 미발동."""
        indicators = make_indicators(close=430.0, sma200=480.0)
        actions = check_signals(make_state("Off"), indicators)
        assert actions[0]["type"] != "EMERGENCY_EXIT"

    def test_does_not_trigger_above_threshold(self):
        """편차 > -10% → 미발동."""
        indicators = make_indicators(close=440.0, sma200=480.0)  # -8.3%
        assert indicators["deviation"] > EMERGENCY_EXIT_THRESHOLD

        actions = check_signals(make_state("On"), indicators)
        assert actions[0]["type"] == "DAILY_STATUS"


# ── 골든크로스 Entry (GCE) ──

class TestGoldenCrossEntry:
    def test_triggers_when_off_deviation_above_1pct_and_gc(self):
        """Off + 편차 ≥ +1% + SMA50>SMA200 → GCE 발동."""
        indicators = make_indicators(close=490.0, sma200=480.0, sma50=485.0)
        assert indicators["deviation"] >= GOLDEN_CROSS_ENTRY_THRESHOLD
        assert indicators["golden_cross"]

        actions = check_signals(make_state("Off"), indicators)
        assert len(actions) == 1
        assert actions[0]["type"] == "GOLDEN_CROSS_ENTRY"
        assert actions[0]["urgency"] == "HIGH"
        assert actions[0]["new_state"] == "On"

    def test_does_not_trigger_without_golden_cross(self):
        """편차 ≥ +1%이지만 SMA50 < SMA200 → 미발동."""
        indicators = make_indicators(close=490.0, sma200=480.0, sma50=475.0)
        assert indicators["deviation"] >= GOLDEN_CROSS_ENTRY_THRESHOLD
        assert not indicators["golden_cross"]

        actions = check_signals(make_state("Off"), indicators)
        assert actions[0]["type"] == "DAILY_STATUS"

    def test_does_not_trigger_below_1pct(self):
        """편차 < +1% → 미발동 (GC 있어도)."""
        indicators = make_indicators(close=484.0, sma200=480.0, sma50=485.0)
        assert indicators["deviation"] < GOLDEN_CROSS_ENTRY_THRESHOLD

        actions = check_signals(make_state("Off"), indicators)
        assert actions[0]["type"] == "DAILY_STATUS"

    def test_does_not_trigger_when_on(self):
        """On 상태에서는 GCE 미발동."""
        indicators = make_indicators(close=490.0, sma200=480.0, sma50=485.0)
        actions = check_signals(make_state("On"), indicators)
        assert actions[0]["type"] == "DAILY_STATUS"


# ── 월말 On/Off ──

class TestMonthlySignal:
    def test_monthly_off_when_on_and_below_sma200(self):
        """On + 월말 + QQQ < SMA200 → Off 전환."""
        indicators = make_indicators(close=475.0, sma200=480.0)
        actions = check_signals(make_state("On"), indicators, is_month_end=True)
        assert actions[0]["type"] == "MONTHLY_OFF"
        assert actions[0]["new_state"] == "Off"

    def test_monthly_on_when_off_and_above_sma200(self):
        """Off + 월말 + QQQ > SMA200 (GCE 미충족) → MONTHLY_ON."""
        # sma50 < sma200 → 골든크로스 없음 → GCE 미발동 → 월말 On
        indicators = make_indicators(close=490.0, sma200=480.0, sma50=475.0)
        actions = check_signals(make_state("Off"), indicators, is_month_end=True)
        assert actions[0]["type"] == "MONTHLY_ON"
        assert actions[0]["new_state"] == "On"

    def test_monthly_on_without_gce(self):
        """Off + 월말 + QQQ > SMA200, GCE 미충족 → MONTHLY_ON."""
        # 편차 < 1% → GCE 미발동, 월말 On 발동
        indicators = make_indicators(close=481.0, sma200=480.0, sma50=475.0)
        actions = check_signals(make_state("Off"), indicators, is_month_end=True)
        assert actions[0]["type"] == "MONTHLY_ON"
        assert actions[0]["new_state"] == "On"

    def test_monthly_no_change(self):
        """On + 월말 + QQQ > SMA200 → 유지."""
        indicators = make_indicators(close=500.0, sma200=480.0)
        actions = check_signals(make_state("On"), indicators, is_month_end=True)
        assert actions[0]["type"] == "DAILY_STATUS"


# ── 우선순위 ──

class TestPriority:
    def test_emergency_exit_beats_monthly(self):
        """긴급 탈출이 월말보다 우선."""
        indicators = make_indicators(close=430.0, sma200=480.0)
        actions = check_signals(make_state("On"), indicators, is_month_end=True)
        assert actions[0]["type"] == "EMERGENCY_EXIT"

    def test_gce_beats_monthly(self):
        """GCE가 월말보다 우선."""
        indicators = make_indicators(close=490.0, sma200=480.0, sma50=485.0)
        actions = check_signals(make_state("Off"), indicators, is_month_end=True)
        assert actions[0]["type"] == "GOLDEN_CROSS_ENTRY"


# ── 상태 파일 ──

class TestStateIO:
    def test_load_save_roundtrip(self, tmp_path):
        import signal_checker
        path = tmp_path / "test_state.json"
        original_file = signal_checker.STATE_FILE

        signal_checker.STATE_FILE = path

        state = {"state": "Off", "last_check": "2026-04-23", "last_action": "EMERGENCY_EXIT",
                 "last_action_date": "2026-04-23", "exit_count": 1, "entry_count": 0}
        save_state(state)
        loaded = load_state()
        assert loaded == state

        signal_checker.STATE_FILE = original_file

    def test_load_default_when_missing(self, tmp_path):
        import signal_checker
        original_file = signal_checker.STATE_FILE
        signal_checker.STATE_FILE = tmp_path / "nonexistent.json"

        state = load_state()
        assert state["state"] == "On"

        signal_checker.STATE_FILE = original_file

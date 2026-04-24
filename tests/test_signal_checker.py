"""signal_checker 핵심 로직 단위 테스트."""

import json
import sys
from pathlib import Path

import pytest

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (
    EMERGENCY_EXIT_THRESHOLD, GOLDEN_CROSS_ENTRY_THRESHOLD,
    PRE_VIX_THRESHOLD, PRE_COOLDOWN, PRE_MONTHLY_COOLDOWN,
)
from signal_checker import check_signals, compute_indicators, is_last_trading_day, load_state, save_state

# ── 헬퍼 ──

def make_indicators(close=500.0, sma200=480.0, sma50=490.0, rsi=50.0,
                    vix=15.0, vix_drop=0.0):
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
        "vix": vix,
        "vix_drop": vix_drop,
    }


def make_state(state="On", exit_count=0, entry_count=0,
               in_pre=False, pre_entry_day_idx=-1, pre_entry_price=0.0,
               last_pre_trigger_idx=-10000, day_idx=100):
    return {
        "state": state,
        "last_check": None,
        "last_action": None,
        "last_action_date": None,
        "exit_count": exit_count,
        "entry_count": entry_count,
        "in_pre": in_pre,
        "pre_entry_day_idx": pre_entry_day_idx,
        "pre_entry_price": pre_entry_price,
        "last_pre_trigger_idx": last_pre_trigger_idx,
        "day_idx": day_idx,
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


# ── PRE Entry ──

class TestPREEntry:
    def test_triggers_when_all_conditions_met(self):
        """Off + 편차≤-10% + VIX>40 + VIX drop≥5 + 쿨다운 경과 → PRE 발동."""
        indicators = make_indicators(close=430.0, sma200=480.0, vix=52.0, vix_drop=8.0)
        state = make_state("Off", day_idx=200, last_pre_trigger_idx=0)
        actions = check_signals(state, indicators)
        assert len(actions) == 1
        assert actions[0]["type"] == "PRE_ENTRY"
        assert actions[0]["urgency"] == "CRITICAL"
        assert actions[0]["new_state"] == "On"
        assert actions[0]["set_pre"] is True

    def test_does_not_trigger_when_on(self):
        """On 상태에서는 PRE 미발동."""
        indicators = make_indicators(close=430.0, sma200=480.0, vix=52.0, vix_drop=8.0)
        state = make_state("On", day_idx=200, last_pre_trigger_idx=0)
        actions = check_signals(state, indicators)
        assert actions[0]["type"] == "EMERGENCY_EXIT"  # 긴급 탈출 발동

    def test_does_not_trigger_vix_below_40(self):
        """VIX < 40 → PRE 미발동."""
        indicators = make_indicators(close=430.0, sma200=480.0, vix=35.0, vix_drop=8.0)
        state = make_state("Off", day_idx=200, last_pre_trigger_idx=0)
        actions = check_signals(state, indicators)
        assert actions[0]["type"] == "DAILY_STATUS"

    def test_does_not_trigger_vix_drop_below_5(self):
        """VIX drop < 5 → PRE 미발동."""
        indicators = make_indicators(close=430.0, sma200=480.0, vix=52.0, vix_drop=3.0)
        state = make_state("Off", day_idx=200, last_pre_trigger_idx=0)
        actions = check_signals(state, indicators)
        assert actions[0]["type"] == "DAILY_STATUS"

    def test_does_not_trigger_deviation_above_minus10(self):
        """편차 > -10% → PRE 미발동."""
        indicators = make_indicators(close=440.0, sma200=480.0, vix=52.0, vix_drop=8.0)
        state = make_state("Off", day_idx=200, last_pre_trigger_idx=0)
        actions = check_signals(state, indicators)
        assert actions[0]["type"] != "PRE_ENTRY"

    def test_does_not_trigger_within_cooldown(self):
        """쿨다운 60일 이내 → PRE 미발동."""
        indicators = make_indicators(close=430.0, sma200=480.0, vix=52.0, vix_drop=8.0)
        state = make_state("Off", day_idx=100, last_pre_trigger_idx=50)  # 50일 경과
        actions = check_signals(state, indicators)
        assert actions[0]["type"] == "DAILY_STATUS"


# ── PRE 가격 Exit ──

class TestPREPriceExit:
    def test_triggers_when_price_below_entry(self):
        """PRE 보유 중 QQQ < 진입가 → 가격 Exit."""
        indicators = make_indicators(close=420.0, sma200=480.0)
        state = make_state("On", in_pre=True, pre_entry_day_idx=90,
                          pre_entry_price=430.0, day_idx=100)
        actions = check_signals(state, indicators)
        assert actions[0]["type"] == "PRE_PRICE_EXIT"
        assert actions[0]["urgency"] == "CRITICAL"
        assert actions[0]["new_state"] == "Off"
        assert actions[0]["clear_pre"] is True

    def test_does_not_trigger_above_entry_price(self):
        """PRE 보유 중 QQQ ≥ 진입가 → 유지."""
        indicators = make_indicators(close=435.0, sma200=480.0)
        state = make_state("On", in_pre=True, pre_entry_day_idx=95,
                          pre_entry_price=430.0, day_idx=100)
        actions = check_signals(state, indicators)
        assert actions[0]["type"] != "PRE_PRICE_EXIT"


# ── PRE 자동 해제 ──

class TestPREAutoRelease:
    def test_releases_after_20_days_positive_deviation(self):
        """PRE 20일+ 보유 + 편차 > 0 + 비월말 → 자동 해제."""
        indicators = make_indicators(close=490.0, sma200=480.0)
        state = make_state("On", in_pre=True, pre_entry_day_idx=75,
                          pre_entry_price=430.0, day_idx=100)
        actions = check_signals(state, indicators, is_month_end=False)
        assert actions[0]["type"] == "PRE_AUTO_RELEASE"
        assert actions[0]["clear_pre"] is True
        assert actions[0]["new_state"] == "On"  # 상태 유지

    def test_does_not_release_before_20_days(self):
        """PRE 20일 미만 → 해제 안 됨."""
        indicators = make_indicators(close=490.0, sma200=480.0)
        state = make_state("On", in_pre=True, pre_entry_day_idx=85,
                          pre_entry_price=430.0, day_idx=100)
        actions = check_signals(state, indicators, is_month_end=False)
        assert actions[0]["type"] == "DAILY_STATUS"

    def test_does_not_release_negative_deviation(self):
        """PRE 20일+ 보유지만 편차 < 0 → 해제 안 됨."""
        indicators = make_indicators(close=470.0, sma200=480.0)
        state = make_state("On", in_pre=True, pre_entry_day_idx=75,
                          pre_entry_price=430.0, day_idx=100)
        actions = check_signals(state, indicators, is_month_end=False)
        assert actions[0]["type"] == "DAILY_STATUS"


# ── PRE 월말 쿨타임 ──

class TestPREMonthlyCooldown:
    def test_monthly_check_disabled_during_pre_cooldown(self):
        """PRE 20일 이내 → 월말 체크 비활성."""
        # On + 월말 + QQQ < SMA200 → 보통이면 Off, PRE 쿨타임이면 유지
        indicators = make_indicators(close=475.0, sma200=480.0)
        state = make_state("On", in_pre=True, pre_entry_day_idx=90,
                          pre_entry_price=430.0, day_idx=100)
        actions = check_signals(state, indicators, is_month_end=True)
        # 월말 Off 미발동, DAILY_STATUS여야 함
        assert actions[0]["type"] == "DAILY_STATUS"

    def test_monthly_check_active_after_pre_cooldown(self):
        """PRE 20일+ → 월말 체크 활성."""
        indicators = make_indicators(close=470.0, sma200=480.0)
        state = make_state("On", in_pre=True, pre_entry_day_idx=75,
                          pre_entry_price=430.0, day_idx=100)
        actions = check_signals(state, indicators, is_month_end=True)
        # 편차 < 0이므로 PRE 자동 해제 안 됨, 월말 Off 발동
        assert any(a["type"] == "MONTHLY_OFF" for a in actions)


# ── PRE 우선순위 ──

class TestPREPriority:
    def test_pre_price_exit_beats_emergency(self):
        """PRE 가격 Exit이 긴급 탈출보다 우선."""
        indicators = make_indicators(close=420.0, sma200=480.0)
        state = make_state("On", in_pre=True, pre_entry_day_idx=90,
                          pre_entry_price=430.0, day_idx=100)
        actions = check_signals(state, indicators)
        assert actions[0]["type"] == "PRE_PRICE_EXIT"

    def test_emergency_exit_not_triggered_during_pre(self):
        """PRE 보유 중에는 긴급 탈출 미발동 (가격 Exit만)."""
        # QQQ가 진입가 위에 있지만 편차 ≤ -10%
        indicators = make_indicators(close=432.0, sma200=480.0)
        state = make_state("On", in_pre=True, pre_entry_day_idx=90,
                          pre_entry_price=430.0, day_idx=100)
        actions = check_signals(state, indicators)
        # 진입가(430) 이상이므로 PRE 가격 Exit 미발동, 긴급탈출도 in_pre라 미발동
        assert actions[0]["type"] == "DAILY_STATUS"

    def test_pre_entry_beats_gce(self):
        """PRE Entry가 GCE보다 우선 (조건 동시 충족 시)."""
        # 편차 ≤ -10% + VIX > 40 + drop ≥ 5 → PRE
        # 이 조건에서 GCE 조건(편차 ≥ +1%)은 절대 동시 충족 불가
        # 대신 PRE Entry가 GCE보다 먼저 체크됨을 검증
        indicators = make_indicators(close=430.0, sma200=480.0, vix=52.0, vix_drop=8.0)
        state = make_state("Off", day_idx=200, last_pre_trigger_idx=0)
        actions = check_signals(state, indicators)
        assert actions[0]["type"] == "PRE_ENTRY"

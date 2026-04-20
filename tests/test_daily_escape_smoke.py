"""Smoke tests for D3 daily escape logic using real historical QQQ data.

These tests hit the Yahoo Finance API via yfinance and verify that
the escape logic would have triggered on known historical crash events.

Run with: pytest tests/test_daily_escape_smoke.py -v -m smoke
"""

import pytest
import yfinance as yf
from check_signal import calculate_sma, calculate_deviation, DAILY_ESCAPE_THRESHOLD


pytestmark = pytest.mark.smoke


def _get_qqq_history(start: str, end: str) -> list[dict]:
    """Fetch QQQ adjusted close prices and return list of {date, close, sma200, deviation}."""
    ticker = yf.Ticker("QQQ")
    # Fetch extra history before start for SMA200 warmup
    import pandas as pd
    warmup_start = (pd.Timestamp(start) - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
    df = ticker.history(start=warmup_start, end=end, auto_adjust=True)
    if df.empty:
        pytest.skip("Yahoo Finance returned no data")

    closes = df["Close"].tolist()
    dates = df.index.tolist()

    results = []
    for i in range(200, len(closes)):
        sma = sum(closes[i - 200:i]) / 200
        price = closes[i]
        deviation = (price - sma) / sma
        date = dates[i]
        # Only include dates within requested range
        date_str = date.strftime("%Y-%m-%d")
        if date_str >= start:
            results.append({
                "date": date_str,
                "close": round(price, 2),
                "sma200": round(sma, 2),
                "deviation": round(deviation, 4),
            })
    return results


def _find_triggers(history: list[dict]) -> list[dict]:
    """Simulate D3 logic: find days where deviation <= threshold, respecting once-per-month."""
    triggers = []
    last_trigger_ym = None
    is_on = True  # assume RISK_ON at start

    for day in history:
        if not is_on:
            # Check if recovered (price > sma → back to ON)
            if day["deviation"] > 0:
                is_on = True
                last_trigger_ym = None
            continue

        if day["deviation"] <= DAILY_ESCAPE_THRESHOLD:
            current_ym = day["date"][:7]
            if current_ym != last_trigger_ym:
                triggers.append(day)
                last_trigger_ym = current_ym
                is_on = False

    return triggers


class TestCoronaCrash2020:
    """2020-03 코로나 급락 시 D3 발동 검증."""

    def test_triggers_during_corona_crash(self):
        history = _get_qqq_history("2020-02-01", "2020-05-01")
        triggers = _find_triggers(history)

        assert len(triggers) >= 1, "코로나 급락 시 최소 1회 발동 예상"

        # At least one trigger should be in March 2020
        march_triggers = [t for t in triggers if t["date"].startswith("2020-03")]
        assert len(march_triggers) >= 1, f"2020-03에 발동 예상, got: {triggers}"

        for t in triggers:
            print(f"  TRIGGER: {t['date']}, close={t['close']}, sma={t['sma200']}, dev={t['deviation']:.4f}")


class TestBearMarket2022:
    """2022 상반기 하락장 시 D3 다수 발동 검증."""

    def test_triggers_during_2022_bear(self):
        history = _get_qqq_history("2022-01-01", "2022-12-31")
        triggers = _find_triggers(history)

        assert len(triggers) >= 2, f"2022년 다수 발동 예상, got {len(triggers)}: {triggers}"

        for t in triggers:
            print(f"  TRIGGER: {t['date']}, close={t['close']}, sma={t['sma200']}, dev={t['deviation']:.4f}")


class TestFullPeriodTriggerCount:
    """2012~2026 전체 기간 총 발동 횟수 검증 (~18회 근처)."""

    def test_total_triggers_in_range(self):
        history = _get_qqq_history("2012-01-01", "2026-04-20")
        triggers = _find_triggers(history)

        print(f"\n  Total triggers (2012-2026): {len(triggers)}")
        for t in triggers:
            print(f"  TRIGGER: {t['date']}, close={t['close']}, sma={t['sma200']}, dev={t['deviation']:.4f}")

        # ~18회는 Bootstrap 1000경로 평균; 실제 단일 역사 경로는 더 적음
        # 실측: 6회 (2016, 2018, 2020, 2022×2, 2025). 허용 범위 3~15.
        assert 3 <= len(triggers) <= 15, (
            f"전체 기간 3~15회 예상, got {len(triggers)}"
        )

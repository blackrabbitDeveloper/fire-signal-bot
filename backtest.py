"""H 전략 시그널 백테스트 -가이드 10장 검증용.

과거 QQQ 데이터로 signal_checker 로직을 날짜별 시뮬레이션하여
D3 긴급 탈출, GCE 진입, 월말 On/Off 발동 이력을 검증한다.

Usage:
    python backtest.py                  # 기본 (2012~현재)
    python backtest.py --start 2010-01-01
    python backtest.py --csv results.csv
"""

import argparse
import csv
import sys
from datetime import date, timedelta
from pathlib import Path

import yfinance as yf
import pandas as pd
import numpy as np

# 프로젝트 모듈 임포트
sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import (
    EMERGENCY_EXIT_THRESHOLD, GOLDEN_CROSS_ENTRY_THRESHOLD,
    SMA200_PERIOD, SMA50_PERIOD, RSI_PERIOD, TICKER,
)


def download_history(start: str = "2000-01-01") -> pd.Series:
    """QQQ 전체 종가 시리즈 다운로드."""
    print(f"데이터 다운로드: {TICKER} ({start} ~ 현재) ...")
    qqq = yf.download(TICKER, start=start, auto_adjust=True, progress=False)
    if isinstance(qqq.columns, pd.MultiIndex):
        close = qqq[("Close", TICKER)].dropna()
    else:
        close = qqq["Close"].dropna()
    close = close.astype(float)
    print(f"  → {len(close)}일 로드 완료 ({close.index[0].date()} ~ {close.index[-1].date()})")
    return close


def compute_all_indicators(close: pd.Series) -> pd.DataFrame:
    """전체 기간 지표를 한번에 계산 (벡터화)."""
    sma200 = close.rolling(SMA200_PERIOD).mean()
    sma50 = close.rolling(SMA50_PERIOD).mean()
    deviation = (close - sma200) / sma200

    # RSI(14)
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(RSI_PERIOD).mean()
    loss = (-delta.clip(upper=0)).rolling(RSI_PERIOD).mean()
    rs = gain / loss
    rsi = 100 - 100 / (1 + rs)

    df = pd.DataFrame({
        "close": close,
        "sma200": sma200,
        "sma50": sma50,
        "deviation": deviation,
        "deviation_pct": deviation * 100,
        "rsi": rsi,
        "above_sma200": close > sma200,
        "golden_cross": sma50 > sma200,
    })
    return df.dropna()


def find_month_end_trading_days(dates: pd.DatetimeIndex) -> set:
    """각 월의 마지막 거래일 집합을 반환."""
    month_ends = set()
    for i in range(len(dates) - 1):
        if dates[i].month != dates[i + 1].month:
            month_ends.add(dates[i].date())
    # 마지막 날짜도 포함 (현재 월의 마지막 거래일일 수 있음)
    month_ends.add(dates[-1].date())
    return month_ends


def run_backtest(close: pd.Series, start_date: str = "2012-01-01") -> list[dict]:
    """날짜별 시그널 시뮬레이션."""
    indicators_df = compute_all_indicators(close)
    month_ends = find_month_end_trading_days(indicators_df.index)

    # 시작일 필터
    start = pd.Timestamp(start_date)
    indicators_df = indicators_df[indicators_df.index >= start]

    if indicators_df.empty:
        print("ERROR: 시작일 이후 데이터 없음")
        return []

    # 초기 상태 -첫 날 SMA200 기준으로 설정
    first_row = indicators_df.iloc[0]
    initial_state = "On" if first_row["above_sma200"] else "Off"

    state = {
        "state": initial_state,
        "exit_count": 0,
        "entry_count": 0,
    }

    events = []
    daily_states = []
    total_days = len(indicators_df)

    for i, (dt, row) in enumerate(indicators_df.iterrows()):
        today = dt.date()
        is_month_end = today in month_ends
        current = state["state"]

        indicators = row.to_dict()
        action = None

        # 1. 긴급 탈출 (On → Off)
        if current == "On" and indicators["deviation"] <= EMERGENCY_EXIT_THRESHOLD:
            action = {
                "date": today,
                "type": "EMERGENCY_EXIT",
                "from": "On",
                "to": "Off",
                "close": indicators["close"],
                "sma200": indicators["sma200"],
                "sma50": indicators["sma50"],
                "deviation_pct": indicators["deviation_pct"],
                "rsi": indicators["rsi"],
                "golden_cross": indicators["golden_cross"],
            }
            state["state"] = "Off"
            state["exit_count"] += 1

        # 2. 골든크로스 Entry (Off → On)
        elif current == "Off" and indicators["deviation"] >= GOLDEN_CROSS_ENTRY_THRESHOLD and indicators["golden_cross"]:
            action = {
                "date": today,
                "type": "GOLDEN_CROSS_ENTRY",
                "from": "Off",
                "to": "On",
                "close": indicators["close"],
                "sma200": indicators["sma200"],
                "sma50": indicators["sma50"],
                "deviation_pct": indicators["deviation_pct"],
                "rsi": indicators["rsi"],
                "golden_cross": indicators["golden_cross"],
            }
            state["state"] = "On"
            state["entry_count"] += 1

        # 3. 월말 On/Off
        elif is_month_end:
            if current == "On" and not indicators["above_sma200"]:
                action = {
                    "date": today,
                    "type": "MONTHLY_OFF",
                    "from": "On",
                    "to": "Off",
                    "close": indicators["close"],
                    "sma200": indicators["sma200"],
                    "sma50": indicators["sma50"],
                    "deviation_pct": indicators["deviation_pct"],
                    "rsi": indicators["rsi"],
                    "golden_cross": indicators["golden_cross"],
                }
                state["state"] = "Off"
            elif current == "Off" and indicators["above_sma200"]:
                action = {
                    "date": today,
                    "type": "MONTHLY_ON",
                    "from": "Off",
                    "to": "On",
                    "close": indicators["close"],
                    "sma200": indicators["sma200"],
                    "sma50": indicators["sma50"],
                    "deviation_pct": indicators["deviation_pct"],
                    "rsi": indicators["rsi"],
                    "golden_cross": indicators["golden_cross"],
                }
                state["state"] = "On"

        if action:
            events.append(action)

        daily_states.append(state["state"])

    # 최종 상태
    state["end_date"] = indicators_df.index[-1].date()
    state["start_date"] = indicators_df.index[0].date()
    state["total_days"] = total_days

    return events, state, daily_states


def compute_performance(indicators_df: pd.DataFrame, daily_states: list[str]) -> dict:
    """On=QQQ 보유, Off=현금 기준 수익률/MDD/체류기간 계산."""
    close = indicators_df["close"]
    returns = close.pct_change().fillna(0)

    # 전략 수익률: On일 때만 QQQ 수익 반영
    state_series = pd.Series(daily_states, index=indicators_df.index)
    strategy_returns = returns.copy()
    strategy_returns[state_series == "Off"] = 0.0

    # 누적 수익률
    strategy_cum = (1 + strategy_returns).cumprod()
    bh_cum = (1 + returns).cumprod()

    # CAGR
    years = (close.index[-1] - close.index[0]).days / 365.25
    strategy_cagr = (strategy_cum.iloc[-1] ** (1 / years) - 1) * 100
    bh_cagr = (bh_cum.iloc[-1] ** (1 / years) - 1) * 100

    # MDD
    def calc_mdd(cum_series):
        peak = cum_series.cummax()
        dd = (cum_series - peak) / peak
        return dd.min() * 100

    strategy_mdd = calc_mdd(strategy_cum)
    bh_mdd = calc_mdd(bh_cum)

    # 체류 기간 분석
    on_days = sum(1 for s in daily_states if s == "On")
    off_days = sum(1 for s in daily_states if s == "Off")
    total = on_days + off_days

    # 연속 체류 구간
    on_streaks = []
    off_streaks = []
    current_streak = 1
    for i in range(1, len(daily_states)):
        if daily_states[i] == daily_states[i - 1]:
            current_streak += 1
        else:
            if daily_states[i - 1] == "On":
                on_streaks.append(current_streak)
            else:
                off_streaks.append(current_streak)
            current_streak = 1
    # 마지막 구간
    if daily_states[-1] == "On":
        on_streaks.append(current_streak)
    else:
        off_streaks.append(current_streak)

    return {
        "strategy_cum": strategy_cum,
        "bh_cum": bh_cum,
        "strategy_total_return": (strategy_cum.iloc[-1] - 1) * 100,
        "bh_total_return": (bh_cum.iloc[-1] - 1) * 100,
        "strategy_cagr": strategy_cagr,
        "bh_cagr": bh_cagr,
        "strategy_mdd": strategy_mdd,
        "bh_mdd": bh_mdd,
        "on_days": on_days,
        "off_days": off_days,
        "on_pct": on_days / total * 100,
        "on_streaks": on_streaks,
        "off_streaks": off_streaks,
        "years": years,
    }


def print_results(events: list[dict], state: dict, perf: dict | None = None) -> None:
    """백테스트 결과 출력."""
    period = f"{state['start_date']} ~ {state['end_date']}"
    years = (state['end_date'] - state['start_date']).days / 365.25

    print(f"\n{'='*60}")
    print(f"  H 전략 백테스트 결과 ({period})")
    print(f"  기간: {years:.1f}년 / 거래일: {state['total_days']}일")
    print(f"{'='*60}\n")

    # 유형별 분류
    emergency = [e for e in events if e["type"] == "EMERGENCY_EXIT"]
    gce = [e for e in events if e["type"] == "GOLDEN_CROSS_ENTRY"]
    monthly_off = [e for e in events if e["type"] == "MONTHLY_OFF"]
    monthly_on = [e for e in events if e["type"] == "MONTHLY_ON"]

    print(f"── 발동 횟수 요약 ──")
    print(f"  긴급 탈출 (D3):     {len(emergency)}회")
    print(f"  골든크로스 Entry:   {len(gce)}회")
    print(f"  월말 Off:           {len(monthly_off)}회")
    print(f"  월말 On:            {len(monthly_on)}회")
    print(f"  전체 상태 전환:     {len(events)}회")
    print()

    # D3 긴급 탈출 상세
    if emergency:
        print(f"── D3 긴급 탈출 상세 ──")
        for e in emergency:
            print(f"  {e['date']}  QQQ={e['close']:>8.2f}  SMA200={e['sma200']:>8.2f}  편차={e['deviation_pct']:>+7.2f}%")
        print()

    # GCE 상세
    if gce:
        print(f"── 골든크로스 Entry 상세 ──")
        for e in gce:
            gc = "Y" if e["golden_cross"] else "N"
            print(f"  {e['date']}  QQQ={e['close']:>8.2f}  SMA200={e['sma200']:>8.2f}  편차={e['deviation_pct']:>+7.2f}%  GC={gc}")
        print()

    # 월말 전환 상세
    if monthly_off or monthly_on:
        print(f"── 월말 On/Off 전환 ──")
        monthly_all = sorted(monthly_off + monthly_on, key=lambda e: e["date"])
        for e in monthly_all:
            label = "Off" if e["type"] == "MONTHLY_OFF" else "On"
            print(f"  {e['date']}  {label:>3}  QQQ={e['close']:>8.2f}  SMA200={e['sma200']:>8.2f}  편차={e['deviation_pct']:>+7.2f}%")
        print()

    # 가이드 10장 대조
    print(f"── 가이드 10장 검증 대조 ──")
    print(f"  {'항목':<20} {'가이드':<12} {'백테스트':<12} {'일치'}")
    print(f"  {'─'*56}")

    # D3 연도 추출
    d3_years = sorted(set(e["date"].year for e in emergency))
    guide_d3_years = [2018, 2020, 2022]

    print(f"  {'D3 긴급 탈출':<20} {'3회':<12} {f'{len(emergency)}회':<12} {'O' if len(emergency) == 3 else 'X'}")
    print(f"  {'D3 발동 연도':<20} {str(guide_d3_years):<12} {str(d3_years):<12} {'O' if d3_years == guide_d3_years else '~'}")
    print(f"  {'GCE 진입':<20} {'4회':<12} {f'{len(gce)}회':<12} {'O' if len(gce) == 4 else '~'}")
    print(f"  {'월말 On/Off':<20} {'~33회':<12} {f'{len(monthly_off)+len(monthly_on)}회':<12} {'O' if abs(len(monthly_off)+len(monthly_on) - 33) <= 5 else '~'}")
    print()

    # 전체 이벤트 타임라인
    print(f"── 전체 이벤트 타임라인 ──")
    type_labels = {
        "EMERGENCY_EXIT": "[!!] D3 Exit",
        "GOLDEN_CROSS_ENTRY": "[**] GCE Entry",
        "MONTHLY_OFF": "[--] Monthly Off",
        "MONTHLY_ON": "[++] Monthly On",
    }
    for e in events:
        label = type_labels[e["type"]]
        print(f"  {e['date']}  {label:<12}  {e['from']}→{e['to']}  QQQ={e['close']:>8.2f}  편차={e['deviation_pct']:>+7.2f}%")
    print()

    # 수익률/MDD/체류기간
    if perf:
        print(f"{'='*60}")
        print(f"  수익률 분석 (On=QQQ, Off=현금)")
        print(f"{'='*60}\n")

        print(f"── 수익률 ──")
        print(f"  {'':20} {'전략':>12} {'QQQ B&H':>12}")
        print(f"  {'─'*44}")
        print(f"  {'총 수익률':20} {perf['strategy_total_return']:>+11.1f}% {perf['bh_total_return']:>+11.1f}%")
        print(f"  {'CAGR':20} {perf['strategy_cagr']:>+11.2f}% {perf['bh_cagr']:>+11.2f}%")
        print(f"  {'MDD':20} {perf['strategy_mdd']:>+11.2f}% {perf['bh_mdd']:>+11.2f}%")
        print()

        print(f"── 체류 기간 ──")
        print(f"  On:  {perf['on_days']:>5}일 ({perf['on_pct']:.1f}%)")
        print(f"  Off: {perf['off_days']:>5}일 ({100 - perf['on_pct']:.1f}%)")
        print()

        if perf["on_streaks"]:
            avg_on = sum(perf["on_streaks"]) / len(perf["on_streaks"])
            max_on = max(perf["on_streaks"])
            min_on = min(perf["on_streaks"])
            print(f"  On 구간:  {len(perf['on_streaks'])}회 / 평균 {avg_on:.0f}일 / 최소 {min_on}일 / 최대 {max_on}일")

        if perf["off_streaks"]:
            avg_off = sum(perf["off_streaks"]) / len(perf["off_streaks"])
            max_off = max(perf["off_streaks"])
            min_off = min(perf["off_streaks"])
            print(f"  Off 구간: {len(perf['off_streaks'])}회 / 평균 {avg_off:.0f}일 / 최소 {min_off}일 / 최대 {max_off}일")
        print()

        # MDD 방어 효과
        mdd_saved = perf["strategy_mdd"] - perf["bh_mdd"]
        print(f"── 요약 ──")
        print(f"  MDD 방어: 전략 {perf['strategy_mdd']:+.2f}% vs B&H {perf['bh_mdd']:+.2f}% (차이 {mdd_saved:+.2f}%p)")
        print(f"  시장 노출: {perf['on_pct']:.1f}% 기간만 QQQ 보유하고 CAGR {perf['strategy_cagr']:+.2f}% 달성")
        print()


def save_csv(events: list[dict], filepath: str) -> None:
    """이벤트 이력을 CSV로 저장."""
    if not events:
        return
    fields = ["date", "type", "from", "to", "close", "sma200", "sma50", "deviation_pct", "rsi", "golden_cross"]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for e in events:
            writer.writerow({k: e.get(k) for k in fields})
    print(f"CSV 저장: {filepath}")


def _calc_portfolio_return(rets_df: pd.DataFrame, start: pd.Timestamp,
                           end: pd.Timestamp) -> float | None:
    """On 구간 포트폴리오(TQQQ30+XLU15+GLD55) 누적 수익률 계산."""
    if rets_df is None:
        return None
    mask = (rets_df.index >= start) & (rets_df.index <= end)
    seg = rets_df.loc[mask]
    if len(seg) < 2:
        return None
    port_daily = (0.30 * seg["TQQQ"] + 0.15 * seg["XLU"] + 0.55 * seg["GLD"])
    cum = (1 + port_daily).cumprod()
    return round((cum.iloc[-1] - 1) * 100, 2)


def build_trade_log(events: list[dict], indicators_df: pd.DataFrame,
                    port_rets: pd.DataFrame | None = None) -> list[dict]:
    """이벤트를 진입/청산 페어링하여 매매 로그 생성.

    On 진입 -> Off 청산을 한 쌍으로 묶어 구간 수익률 계산.
    port_rets가 주어지면 실제 포트폴리오 수익률도 계산.
    """
    trades = []
    entry = None

    for e in events:
        if e["to"] == "On":
            entry = e
        elif e["to"] == "Off" and entry is not None:
            entry_date = pd.Timestamp(entry["date"])
            exit_date = pd.Timestamp(e["date"])

            # QQQ 수익률
            mask = (indicators_df.index >= entry_date) & (indicators_df.index <= exit_date)
            segment = indicators_df.loc[mask, "close"]
            if len(segment) >= 2:
                qqq_return = (segment.iloc[-1] / segment.iloc[0] - 1) * 100
            else:
                qqq_return = 0.0

            holding_days = (e["date"] - entry["date"]).days

            trade = {
                "trade_no": len(trades) + 1,
                "entry_date": entry["date"],
                "entry_type": entry["type"],
                "entry_price": entry["close"],
                "exit_date": e["date"],
                "exit_type": e["type"],
                "exit_price": e["close"],
                "holding_days": holding_days,
                "qqq_return_pct": round(qqq_return, 2),
                "port_return_pct": _calc_portfolio_return(port_rets, entry_date, exit_date),
                "entry_deviation": round(entry["deviation_pct"], 2),
                "exit_deviation": round(e["deviation_pct"], 2),
            }
            trades.append(trade)
            entry = None

    # 미청산 포지션
    if entry is not None:
        entry_date = pd.Timestamp(entry["date"])
        last_date = indicators_df.index[-1]
        segment = indicators_df.loc[indicators_df.index >= entry_date, "close"]
        if len(segment) >= 2:
            qqq_return = (segment.iloc[-1] / segment.iloc[0] - 1) * 100
        else:
            qqq_return = 0.0
        holding_days = (last_date.date() - entry["date"]).days

        trades.append({
            "trade_no": len(trades) + 1,
            "entry_date": entry["date"],
            "entry_type": entry["type"],
            "entry_price": entry["close"],
            "exit_date": "OPEN",
            "exit_type": "HOLDING",
            "exit_price": float(indicators_df["close"].iloc[-1]),
            "holding_days": holding_days,
            "qqq_return_pct": round(qqq_return, 2),
            "port_return_pct": _calc_portfolio_return(port_rets, entry_date, last_date),
            "entry_deviation": round(entry["deviation_pct"], 2),
            "exit_deviation": None,
        })

    return trades


def print_trade_log(trades: list[dict]) -> None:
    """매매 로그 출력."""
    if not trades:
        return

    has_port = any(t.get("port_return_pct") is not None for t in trades)

    print(f"\n{'='*96}")
    print(f"  매매 로그 (On 진입 -> Off 청산 페어링)")
    print(f"{'='*96}\n")

    if has_port:
        print(f"  {'#':>3}  {'진입일':10} {'진입유형':12} {'진입가':>9}  {'청산일':10} {'청산유형':12} {'청산가':>9}  {'일수':>5}  {'QQQ':>8} {'PORT':>8}")
        print(f"  {'='*96}")
    else:
        print(f"  {'#':>3}  {'진입일':10} {'진입유형':12} {'진입가':>9}  {'청산일':10} {'청산유형':12} {'청산가':>9}  {'일수':>5}  {'QQQ':>8}")
        print(f"  {'='*88}")

    wins_q = 0
    losses_q = 0
    total_q = 0.0
    wins_p = 0
    losses_p = 0
    total_p = 0.0

    for t in trades:
        exit_date = str(t["exit_date"])[:10]
        exit_type = t["exit_type"][:12]
        q_str = f"{t['qqq_return_pct']:+.2f}%"

        line = (
            f"  {t['trade_no']:>3}  {str(t['entry_date']):10} {t['entry_type']:12} "
            f"${t['entry_price']:>8.2f}  {exit_date:10} {exit_type:12} "
            f"${t['exit_price']:>8.2f}  {t['holding_days']:>5}  {q_str:>8}"
        )

        if has_port:
            p = t.get("port_return_pct")
            p_str = f"{p:+.2f}%" if p is not None else "   N/A"
            line += f" {p_str:>8}"

        print(line)

        if t["exit_type"] != "HOLDING":
            total_q += t["qqq_return_pct"]
            if t["qqq_return_pct"] >= 0:
                wins_q += 1
            else:
                losses_q += 1
            p = t.get("port_return_pct")
            if p is not None:
                total_p += p
                if p >= 0:
                    wins_p += 1
                else:
                    losses_p += 1

    closed = wins_q + losses_q
    print()
    if closed > 0:
        avg_q = total_q / closed
        wr_q = wins_q / closed * 100
        avg_hold = sum(t["holding_days"] for t in trades if t["exit_type"] != "HOLDING") / closed
        print(f"  QQQ:  {closed}건 | 승률 {wr_q:.1f}% | 평균 {avg_q:+.2f}% | 평균 보유 {avg_hold:.0f}일")

    closed_p = wins_p + losses_p
    if closed_p > 0:
        avg_p = total_p / closed_p
        wr_p = wins_p / closed_p * 100
        print(f"  PORT: {closed_p}건 | 승률 {wr_p:.1f}% | 평균 {avg_p:+.2f}%")
    print()


def save_trade_log_csv(trades: list[dict], filepath: str) -> None:
    """매매 로그를 CSV로 저장."""
    if not trades:
        return
    fields = [
        "trade_no", "entry_date", "entry_type", "entry_price",
        "exit_date", "exit_type", "exit_price",
        "holding_days", "qqq_return_pct", "port_return_pct",
        "entry_deviation", "exit_deviation",
    ]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for t in trades:
            writer.writerow({k: t.get(k) for k in fields})
    print(f"매매 로그 CSV 저장: {filepath}")


def download_multi(tickers: list[str], start: str) -> pd.DataFrame:
    """여러 종목 종가 다운로드 → DataFrame (columns=ticker)."""
    print(f"멀티 종목 다운로드: {tickers} ({start} ~) ...")
    data = yf.download(tickers, start=start, auto_adjust=True, progress=False)
    if isinstance(data.columns, pd.MultiIndex):
        closes = data["Close"].dropna(how="all")
    else:
        closes = data[["Close"]].dropna(how="all")
        closes.columns = tickers
    print(f"  -> {len(closes)}일 로드 ({closes.index[0].date()} ~ {closes.index[-1].date()})")
    return closes.astype(float)


def compute_portfolio_performance(
    indicators_df: pd.DataFrame,
    daily_states: list[str],
    start_date: str,
) -> dict | None:
    """실제 포트폴리오 종목(TQQQ/XLU/GLD/DBMF) 수익률 계산.

    On:  TQQQ 30% + XLU 15% + GLD 55%
    Off: DBMF 45% + GLD 55%  (DBMF 없는 기간은 GLD 100%)

    일일 리밸런싱(고정 비중) 가정.
    """
    tickers = ["TQQQ", "XLU", "GLD", "DBMF"]
    download_start = str(int(start_date[:4]) - 1) + start_date[4:]

    try:
        closes = download_multi(tickers, start=download_start)
    except Exception as e:
        print(f"  포트폴리오 데이터 다운로드 실패: {e}")
        return None

    # 시작일 필터 & 인디케이터와 날짜 정렬
    closes = closes[closes.index >= pd.Timestamp(start_date)]
    common_idx = indicators_df.index.intersection(closes.index)
    if len(common_idx) < 50:
        print(f"  공통 거래일 부족: {len(common_idx)}일")
        return None

    closes = closes.loc[common_idx]
    states = pd.Series(
        [daily_states[list(indicators_df.index).index(d)] for d in common_idx],
        index=common_idx,
    )

    # 일일 수익률
    rets = closes.pct_change().fillna(0)

    # 포트폴리오 일일 수익률 계산
    has_dbmf = closes["DBMF"].notna()
    port_returns = pd.Series(0.0, index=common_idx)

    for i in range(len(common_idx)):
        dt = common_idx[i]
        s = states.iloc[i]

        if s == "On":
            # TQQQ 30% + XLU 15% + GLD 55%
            r = (0.30 * rets["TQQQ"].iloc[i]
                 + 0.15 * rets["XLU"].iloc[i]
                 + 0.55 * rets["GLD"].iloc[i])
        else:
            # Off: DBMF 45% + GLD 55% (DBMF 없으면 GLD 100%)
            if has_dbmf.iloc[i] and pd.notna(rets["DBMF"].iloc[i]):
                r = (0.45 * rets["DBMF"].iloc[i]
                     + 0.55 * rets["GLD"].iloc[i])
            else:
                r = rets["GLD"].iloc[i]

        port_returns.iloc[i] = r

    # QQQ B&H (벤치마크)
    qqq_rets = indicators_df.loc[common_idx, "close"].pct_change().fillna(0)

    port_cum = (1 + port_returns).cumprod()
    qqq_cum = (1 + qqq_rets).cumprod()

    years = (common_idx[-1] - common_idx[0]).days / 365.25
    port_cagr = (port_cum.iloc[-1] ** (1 / years) - 1) * 100
    qqq_cagr = (qqq_cum.iloc[-1] ** (1 / years) - 1) * 100

    def calc_mdd(cum):
        peak = cum.cummax()
        dd = (cum - peak) / peak
        return dd.min() * 100

    def calc_sharpe(daily_rets, rf_annual=0.04):
        """연환산 Sharpe (무위험 4% 가정)."""
        rf_daily = (1 + rf_annual) ** (1/252) - 1
        excess = daily_rets - rf_daily
        if excess.std() == 0:
            return 0.0
        return float(excess.mean() / excess.std() * np.sqrt(252))

    def calc_sortino(daily_rets, rf_annual=0.04):
        """연환산 Sortino (하방 변동성만 사용)."""
        rf_daily = (1 + rf_annual) ** (1/252) - 1
        excess = daily_rets - rf_daily
        downside = excess[excess < 0]
        if len(downside) == 0 or downside.std() == 0:
            return 0.0
        return float(excess.mean() / downside.std() * np.sqrt(252))

    def calc_annual_vol(daily_rets):
        return float(daily_rets.std() * np.sqrt(252) * 100)

    return {
        "period": f"{common_idx[0].date()} ~ {common_idx[-1].date()}",
        "years": years,
        "days": len(common_idx),
        "port_total": (port_cum.iloc[-1] - 1) * 100,
        "qqq_total": (qqq_cum.iloc[-1] - 1) * 100,
        "port_cagr": port_cagr,
        "qqq_cagr": qqq_cagr,
        "port_mdd": calc_mdd(port_cum),
        "qqq_mdd": calc_mdd(qqq_cum),
        "port_sharpe": calc_sharpe(port_returns),
        "qqq_sharpe": calc_sharpe(qqq_rets),
        "port_sortino": calc_sortino(port_returns),
        "qqq_sortino": calc_sortino(qqq_rets),
        "port_vol": calc_annual_vol(port_returns),
        "qqq_vol": calc_annual_vol(qqq_rets),
        "has_dbmf_start": closes["DBMF"].first_valid_index(),
    }


def print_portfolio_results(result: dict) -> None:
    """실제 포트폴리오 백테스트 결과 출력."""
    print(f"\n{'='*60}")
    print(f"  실제 포트폴리오 백테스트 ({result['period']})")
    print(f"  기간: {result['years']:.1f}년 / 거래일: {result['days']}일")
    if result["has_dbmf_start"]:
        print(f"  DBMF 유효 시작: {result['has_dbmf_start'].date()}")
    print(f"{'='*60}\n")

    print(f"  On  = TQQQ 30% + XLU 15% + GLD 55%")
    print(f"  Off = DBMF 45% + GLD 55% (DBMF 없는 기간: GLD 100%)")
    print()

    print(f"  {'':20} {'전략':>12} {'QQQ B&H':>12}")
    print(f"  {'─'*44}")
    print(f"  {'총 수익률':20} {result['port_total']:>+11.1f}% {result['qqq_total']:>+11.1f}%")
    print(f"  {'CAGR':20} {result['port_cagr']:>+11.2f}% {result['qqq_cagr']:>+11.2f}%")
    print(f"  {'MDD':20} {result['port_mdd']:>+11.2f}% {result['qqq_mdd']:>+11.2f}%")
    print(f"  {'연 변동성':20} {result['port_vol']:>10.2f}% {result['qqq_vol']:>11.2f}%")
    print(f"  {'Sharpe (rf=4%)':20} {result['port_sharpe']:>11.3f} {result['qqq_sharpe']:>12.3f}")
    print(f"  {'Sortino (rf=4%)':20} {result['port_sortino']:>11.3f} {result['qqq_sortino']:>12.3f}")
    print()

    mdd_saved = result["port_mdd"] - result["qqq_mdd"]
    cagr_diff = result["port_cagr"] - result["qqq_cagr"]
    print(f"  CAGR 차이: {cagr_diff:+.2f}%p / MDD 방어: {mdd_saved:+.2f}%p")
    print(f"  Sharpe 차이: {result['port_sharpe'] - result['qqq_sharpe']:+.3f} / Sortino 차이: {result['port_sortino'] - result['qqq_sortino']:+.3f}")
    print()


def main():
    parser = argparse.ArgumentParser(description="H 전략 시그널 백테스트")
    parser.add_argument("--start", default="2012-01-01", help="백테스트 시작일 (기본: 2012-01-01)")
    parser.add_argument("--csv", default=None, help="결과 CSV 파일 경로")
    parser.add_argument("--trades", default=None, help="매매 로그 CSV 파일 경로")
    parser.add_argument("--portfolio", action="store_true", help="실제 포트폴리오 종목 백테스트 추가")
    args = parser.parse_args()

    # 데이터 다운로드 (SMA200 계산을 위해 시작일 2년 전부터)
    download_start = str(int(args.start[:4]) - 2) + args.start[4:]
    close = download_history(start=download_start)

    events, state, daily_states = run_backtest(close, start_date=args.start)

    # QQQ 기준 수익률 계산
    indicators_df = compute_all_indicators(close)
    indicators_df = indicators_df[indicators_df.index >= pd.Timestamp(args.start)]
    perf = compute_performance(indicators_df, daily_states)

    print_results(events, state, perf)

    # 포트폴리오 종목 수익률 데이터 (매매 로그용)
    port_rets = None
    if args.portfolio:
        try:
            tickers = ["TQQQ", "XLU", "GLD", "DBMF"]
            download_start_port = str(int(args.start[:4]) - 1) + args.start[4:]
            port_closes = download_multi(tickers, start=download_start_port)
            port_closes = port_closes[port_closes.index >= pd.Timestamp(args.start)]
            port_rets = port_closes.pct_change().fillna(0)
        except Exception as e:
            print(f"  포트폴리오 데이터 로드 실패 (QQQ만 표시): {e}")

    # 매매 로그
    trades = build_trade_log(events, indicators_df, port_rets)
    print_trade_log(trades)
    if args.trades:
        save_trade_log_csv(trades, args.trades)

    # 실제 포트폴리오 백테스트
    if args.portfolio:
        port_result = compute_portfolio_performance(indicators_df, daily_states, args.start)
        if port_result:
            print_portfolio_results(port_result)

        # DBMF 상장 이후 구간 (2019-06~)
        if args.start < "2019-06-01":
            print("── DBMF 상장 이후 구간 별도 테스트 ──")
            dbmf_start = "2019-06-01"
            close_dbmf = close[close.index >= pd.Timestamp("2017-06-01")]
            events_d, state_d, daily_states_d = run_backtest(close_dbmf, start_date=dbmf_start)
            indicators_dbmf = compute_all_indicators(close_dbmf)
            indicators_dbmf = indicators_dbmf[indicators_dbmf.index >= pd.Timestamp(dbmf_start)]
            port_dbmf = compute_portfolio_performance(indicators_dbmf, daily_states_d, dbmf_start)
            if port_dbmf:
                print_portfolio_results(port_dbmf)

    if args.csv:
        save_csv(events, args.csv)


if __name__ == "__main__":
    main()

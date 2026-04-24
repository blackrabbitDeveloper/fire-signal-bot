"""H 전략 시그널 체커 — F2D3 + 골든크로스 Entry."""

import json
import os
import sys
import time
import calendar
from datetime import datetime, date
from pathlib import Path

import yfinance as yf
import pandas as pd
import numpy as np

from config import (
    TICKER, VIX_TICKER, LOOKBACK_DAYS, SMA200_PERIOD, SMA50_PERIOD, RSI_PERIOD,
    EMERGENCY_EXIT_THRESHOLD, GOLDEN_CROSS_ENTRY_THRESHOLD,
    PRE_VIX_THRESHOLD, PRE_VIX_DROP_THRESHOLD, PRE_VIX_DROP_LOOKBACK,
    PRE_COOLDOWN, PRE_MONTHLY_COOLDOWN,
    MAX_RETRIES, RETRY_DELAY,
)
from notifiers.discord import (
    build_daily_status_embed, build_emergency_exit_embed,
    build_error_embed, build_golden_cross_entry_embed,
    build_monthly_change_embed, build_pre_entry_embed,
    build_pre_price_exit_embed, send_notification,
)

# ── 파일 경로 ──
BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "signal_state.json"
LOG_FILE = BASE_DIR / "signal_log.csv"


# ── 상태 관리 ──

DEFAULT_STATE = {
    "state": "On",
    "last_check": None,
    "last_action": None,
    "last_action_date": None,
    "exit_count": 0,
    "entry_count": 0,
    "current_entry": None,
    "in_pre": False,
    "pre_entry_day_idx": -1,
    "pre_entry_price": 0.0,
    "last_pre_trigger_idx": -10000,
    "day_idx": 0,
}

TRADE_LOG_FILE = BASE_DIR / "trade_log.csv"


def load_state() -> dict:
    """현재 On/Off 상태 로드."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, KeyError):
            pass
    return dict(DEFAULT_STATE)


def save_state(state: dict) -> None:
    """상태 파일 저장."""
    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def log_trade(entry: dict, exit_date: str, exit_type: str,
              exit_price: float, exit_deviation: float) -> None:
    """완료된 매매를 trade_log.csv에 기록."""
    header = not TRADE_LOG_FILE.exists()
    qqq_return = round((exit_price / entry["price"] - 1) * 100, 2)
    with open(TRADE_LOG_FILE, "a", encoding="utf-8") as f:
        if header:
            f.write("entry_date,entry_type,entry_price,entry_deviation,"
                    "exit_date,exit_type,exit_price,exit_deviation,qqq_return_pct\n")
        f.write(
            f"{entry['date']},{entry['type']},{entry['price']:.2f},{entry['deviation_pct']:+.2f},"
            f"{exit_date},{exit_type},{exit_price:.2f},{exit_deviation:+.2f},{qqq_return:+.2f}\n"
        )


def log_signal(check_date: str, signal_type: str, state_val: str,
               indicators: dict, action: str) -> None:
    """시그널 이력을 CSV에 기록."""
    header = not LOG_FILE.exists()
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        if header:
            f.write("date,signal_type,state,qqq_close,sma200,sma50,deviation,rsi,action\n")
        f.write(
            f"{check_date},{signal_type},{state_val},"
            f"{indicators['close']:.2f},{indicators['sma200']:.2f},"
            f"{indicators['sma50']:.2f},{indicators['deviation_pct']:+.2f},"
            f"{indicators['rsi']:.1f},{action}\n"
        )


# ── 데이터 수집 ──

def _download_ticker(ticker: str, lookback_days: int) -> pd.Series:
    """단일 종목 종가 시리즈 다운로드."""
    data = yf.download(
        ticker, period=f"{lookback_days}d",
        auto_adjust=True, progress=False,
    )
    if isinstance(data.columns, pd.MultiIndex):
        close = data[("Close", ticker)].dropna()
    else:
        close = data["Close"].dropna()
    return close.astype(float)


def get_market_data(lookback_days: int = LOOKBACK_DAYS) -> tuple[pd.Series, pd.Series]:
    """QQQ + VIX 종가 시리즈 반환. 실패 시 재시도."""
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            qqq_close = _download_ticker(TICKER, lookback_days)
            if len(qqq_close) < SMA200_PERIOD:
                raise ValueError(f"QQQ 데이터 부족: {len(qqq_close)}일 ({SMA200_PERIOD}일 필요)")
            vix_close = _download_ticker(VIX_TICKER, lookback_days)
            return qqq_close, vix_close
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                print(f"재시도 {attempt + 1}/{MAX_RETRIES}: {e}")
                time.sleep(RETRY_DELAY)

    raise RuntimeError(f"데이터 수집 실패 ({MAX_RETRIES}회 시도): {last_error}")


# ── 지표 계산 ──

def compute_indicators(close: pd.Series, vix_close: pd.Series | None = None) -> dict:
    """SMA200, SMA50, 편차, RSI, VIX 계산."""
    sma200 = close.rolling(SMA200_PERIOD).mean()
    sma50 = close.rolling(SMA50_PERIOD).mean()

    current_close = float(close.iloc[-1])
    current_sma200 = float(sma200.iloc[-1])
    current_sma50 = float(sma50.iloc[-1])
    deviation = (current_close - current_sma200) / current_sma200

    # RSI(14)
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(RSI_PERIOD).mean()
    loss = (-delta.clip(upper=0)).rolling(RSI_PERIOD).mean()
    rs = gain / loss
    rsi = float((100 - 100 / (1 + rs)).iloc[-1])

    result = {
        "close": current_close,
        "sma200": current_sma200,
        "sma50": current_sma50,
        "deviation": deviation,
        "deviation_pct": deviation * 100,
        "rsi": rsi,
        "above_sma200": current_close > current_sma200,
        "golden_cross": current_sma50 > current_sma200,
        "vix": 0.0,
        "vix_drop": 0.0,
    }

    if vix_close is not None and len(vix_close) > PRE_VIX_DROP_LOOKBACK:
        current_vix = float(vix_close.iloc[-1])
        vix_5d_ago = float(vix_close.iloc[-1 - PRE_VIX_DROP_LOOKBACK])
        result["vix"] = current_vix
        result["vix_drop"] = vix_5d_ago - current_vix

    return result


# ── 시그널 판단 ──

def check_signals(state: dict, indicators: dict, is_month_end: bool = False) -> list[dict]:
    """V16a_c20 시그널 체크 — 액션 리스트 반환."""
    actions = []
    current = state["state"]
    in_pre = state.get("in_pre", False)
    day_idx = state.get("day_idx", 0)
    days_held = day_idx - state.get("pre_entry_day_idx", -1) if in_pre else 0
    monthly_active = not (in_pre and days_held < PRE_MONTHLY_COOLDOWN)

    # 1. PRE 가격 Exit (최우선 — PRE 보유 중)
    if in_pre and indicators["close"] < state.get("pre_entry_price", 0):
        actions.append({
            "type": "PRE_PRICE_EXIT",
            "urgency": "CRITICAL",
            "message": (f"★ PRE 가격 Exit! QQQ {indicators['close']:.2f} "
                        f"< 진입가 {state['pre_entry_price']:.2f}"),
            "action": "TQQQ+XLU 전량 매도 → DBMF 매수",
            "new_state": "Off",
            "clear_pre": True,
        })
        return actions

    # 2. 긴급 탈출 (On 상태, PRE 아닌 경우)
    if current == "On" and not in_pre and indicators["deviation"] <= EMERGENCY_EXIT_THRESHOLD:
        actions.append({
            "type": "EMERGENCY_EXIT",
            "urgency": "CRITICAL",
            "message": f"★ 긴급 탈출! QQQ 편차 {indicators['deviation_pct']:+.2f}% (≤-10%)",
            "action": "TQQQ+XLU 전량 매도 → DBMF 매수",
            "new_state": "Off",
        })
        return actions

    # 3. PRE Entry (Off 상태)
    days_since_pre = day_idx - state.get("last_pre_trigger_idx", -10000)
    if (current == "Off"
        and days_since_pre >= PRE_COOLDOWN
        and indicators["deviation"] <= EMERGENCY_EXIT_THRESHOLD
        and indicators.get("vix", 0) > PRE_VIX_THRESHOLD
        and indicators.get("vix_drop", 0) >= PRE_VIX_DROP_THRESHOLD):
        actions.append({
            "type": "PRE_ENTRY",
            "urgency": "CRITICAL",
            "message": (f"★★ PRE Entry! 편차 {indicators['deviation_pct']:+.2f}%, "
                        f"VIX {indicators['vix']:.1f}, drop +{indicators['vix_drop']:.1f}"),
            "action": "DBMF 매도 → TQQQ+XLU+GLD 매수 (패닉 바닥 진입)",
            "new_state": "On",
            "set_pre": True,
            "pre_entry_price": indicators["close"],
        })
        return actions

    # 4. 골든크로스 Entry (Off 상태, PRE 아닌 경우)
    if (current == "Off" and not in_pre
        and indicators["deviation"] >= GOLDEN_CROSS_ENTRY_THRESHOLD
        and indicators["golden_cross"]):
        actions.append({
            "type": "GOLDEN_CROSS_ENTRY",
            "urgency": "HIGH",
            "message": f"★ 골든크로스 Entry! 편차 {indicators['deviation_pct']:+.2f}%, SMA50>SMA200",
            "action": "DBMF 전량 매도 → TQQQ+XLU 매수",
            "new_state": "On",
        })
        return actions

    # 5. PRE 자동 해제 (20일 + 편차 > 0, 월말 아님)
    if in_pre and days_held >= PRE_MONTHLY_COOLDOWN and not is_month_end:
        if indicators["deviation"] > 0:
            actions.append({
                "type": "PRE_AUTO_RELEASE",
                "urgency": "INFO",
                "message": (f"PRE 보호 해제 (On 유지, 일반 모드 복귀). "
                            f"편차 {indicators['deviation_pct']:+.2f}%, {days_held}일 보유"),
                "action": "포지션 변경 없음 (PRE 플래그만 해제)",
                "new_state": current,
                "clear_pre": True,
            })

    # 6. 월말 체크 (쿨타임 아닐 때)
    if is_month_end and monthly_active:
        if current == "On" and not indicators["above_sma200"]:
            actions.append({
                "type": "MONTHLY_OFF",
                "urgency": "NORMAL",
                "message": f"월말 Off 전환. QQQ={indicators['close']:.2f} < SMA200={indicators['sma200']:.2f}",
                "action": "TQQQ+XLU 전량 매도 → DBMF 매수",
                "new_state": "Off",
                "clear_pre": True,
            })
        elif current == "Off" and indicators["above_sma200"]:
            actions.append({
                "type": "MONTHLY_ON",
                "urgency": "NORMAL",
                "message": f"월말 On 전환. QQQ={indicators['close']:.2f} > SMA200={indicators['sma200']:.2f}",
                "action": "DBMF 전량 매도 → TQQQ+XLU+GLD 매수",
                "new_state": "On",
            })

    # 7. 일일 상태 (액션 없을 때)
    if not actions:
        gc_mark = "✓" if indicators["golden_cross"] else "✗"
        pre_tag = f" [PRE {days_held}일]" if in_pre else ""
        actions.append({
            "type": "DAILY_STATUS",
            "urgency": "INFO",
            "message": (
                f"[{current}{pre_tag}] QQQ={indicators['close']:.2f}, "
                f"편차={indicators['deviation_pct']:+.2f}%, "
                f"VIX={indicators.get('vix', 0):.1f} "
                f"(drop {indicators.get('vix_drop', 0):+.1f}), "
                f"RSI={indicators['rsi']:.1f}, GC={gc_mark}"
            ),
            "action": "유지",
            "new_state": current,
        })

    return actions


# ── 월말 판단 ──

def is_last_trading_day() -> bool:
    """오늘이 이번 달 마지막 거래일인지 판단."""
    today = date.today()
    _, last_day = calendar.monthrange(today.year, today.month)
    remaining_trading = sum(
        1 for d in range(today.day + 1, last_day + 1)
        if date(today.year, today.month, d).weekday() < 5
    )
    return remaining_trading == 0


# ── 거래일 판단 ──

def is_trading_day() -> bool:
    """오늘이 평일(거래일)인지 판단. 미국 공휴일은 미포함(근사)."""
    return date.today().weekday() < 5


# ── 알림 발송 ──

def send_action_alert(action: dict, state: dict, indicators: dict, check_date: str) -> None:
    """액션 유형에 따라 적절한 Discord embed 생성 및 발송."""
    if action["type"] == "PRE_PRICE_EXIT":
        embed = build_pre_price_exit_embed(indicators, state, check_date)
    elif action["type"] == "EMERGENCY_EXIT":
        embed = build_emergency_exit_embed(indicators, check_date)
    elif action["type"] == "PRE_ENTRY":
        embed = build_pre_entry_embed(indicators, check_date)
    elif action["type"] == "GOLDEN_CROSS_ENTRY":
        embed = build_golden_cross_entry_embed(indicators, check_date)
    elif action["type"] in ("MONTHLY_ON", "MONTHLY_OFF"):
        direction = "On" if action["type"] == "MONTHLY_ON" else "Off"
        embed = build_monthly_change_embed(direction, indicators, check_date)
    elif action["type"] == "DAILY_STATUS":
        if date.today().weekday() != 4:  # 금요일(4)만 발송
            return
        embed = build_daily_status_embed(state, indicators, check_date)
    else:
        return

    send_notification(embed)


# ── 메인 ──

def main() -> None:
    """메인 진입점: 데이터 수집 → 시그널 체크 → 알림 → 상태 저장."""
    today = date.today()
    check_date = today.strftime("%Y-%m-%d")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    print(f"=== H 전략 시그널 체크 ({now_str}) ===\n")

    # 1. 거래일 체크
    if not is_trading_day():
        print(f"{check_date}, SKIP: 주말/휴일")
        return

    # 2. 상태 로드
    state = load_state()

    # 3. 데이터 수집
    try:
        close, vix_close = get_market_data()
    except Exception as e:
        print(f"ERROR: {e}")
        send_notification(build_error_embed(str(e)))
        raise

    # 4. 지표 계산
    indicators = compute_indicators(close, vix_close)
    is_me = is_last_trading_day()

    # day_idx 증가
    state["day_idx"] = state.get("day_idx", 0) + 1

    in_pre = state.get("in_pre", False)
    pre_tag = " (PRE)" if in_pre else ""
    print(f"현재 상태: {state['state']}{pre_tag}")
    print(f"QQQ: {indicators['close']:.2f}")
    print(f"SMA200: {indicators['sma200']:.2f} / SMA50: {indicators['sma50']:.2f}")
    print(f"편차: {indicators['deviation_pct']:+.2f}%")
    print(f"VIX: {indicators['vix']:.2f} (5일 drop: {indicators['vix_drop']:+.2f})")
    print(f"RSI(14): {indicators['rsi']:.1f}")
    print(f"골든크로스: {'✓' if indicators['golden_cross'] else '✗'}")
    print(f"월말: {'✓' if is_me else '✗'}")
    print()

    # 5. 시그널 체크
    actions = check_signals(state, indicators, is_month_end=is_me)

    # 6. 처리
    for action in actions:
        urgency_marker = {
            "CRITICAL": "🚨🚨🚨",
            "HIGH": "⚡⚡",
            "NORMAL": "📋",
            "INFO": "ℹ️",
        }.get(action["urgency"], "")

        print(f"{urgency_marker} [{action['type']}] {action['message']}")
        print(f"  → {action['action']}")

        # 상태 업데이트
        state_changed = action["new_state"] != state["state"]
        pre_changed = action.get("set_pre") or action.get("clear_pre")

        if state_changed or pre_changed:
            old = state["state"]
            state["state"] = action["new_state"]
            state["last_action"] = action["type"]
            state["last_action_date"] = check_date
            state["last_check"] = check_date

            # PRE Entry
            if action.get("set_pre"):
                state["in_pre"] = True
                state["pre_entry_day_idx"] = state["day_idx"]
                state["pre_entry_price"] = action["pre_entry_price"]
                state["last_pre_trigger_idx"] = state["day_idx"]
                state["entry_count"] = state.get("entry_count", 0) + 1

            # PRE 해제 (가격 Exit, 월말 Off, 자동 해제)
            if action.get("clear_pre"):
                state["in_pre"] = False

            if action["type"] == "EMERGENCY_EXIT":
                state["exit_count"] = state.get("exit_count", 0) + 1
            elif action["type"] == "PRE_PRICE_EXIT":
                state["exit_count"] = state.get("exit_count", 0) + 1
            elif action["type"] == "GOLDEN_CROSS_ENTRY":
                state["entry_count"] = state.get("entry_count", 0) + 1

            # 매매 이력 기록
            if action["new_state"] == "On" and state_changed:
                state["current_entry"] = {
                    "date": check_date,
                    "type": action["type"],
                    "price": indicators["close"],
                    "deviation_pct": round(indicators["deviation_pct"], 2),
                }
            elif action["new_state"] == "Off" and state_changed and state.get("current_entry"):
                log_trade(
                    state["current_entry"], check_date, action["type"],
                    indicators["close"], indicators["deviation_pct"],
                )
                state["current_entry"] = None

            save_state(state)
            if state_changed:
                print(f"  -> 상태 변경: {old} -> {action['new_state']}")
            elif pre_changed:
                print(f"  -> PRE 플래그 변경")
        else:
            state["last_check"] = check_date
            save_state(state)

        # 로그 기록
        log_signal(check_date, action["type"], state["state"], indicators, action["action"])

        # 알림 발송
        send_action_alert(action, state, indicators, check_date)


if __name__ == "__main__":
    main()

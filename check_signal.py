"""FIRE Signal Bot — F전략: QQQ 200-day SMA crossover with Managed Futures."""

import json
import os
import time
from datetime import datetime, timezone
from urllib.request import urlopen, Request

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")

DEFAULT_STATE = {
    "signal": None,
    "last_check": None,
    "last_price": None,
    "last_sma": None,
    "diff_pct": None,
    "last_change": None,
}


def load_state(path: str = STATE_FILE) -> dict:
    """Load signal state from JSON file. Returns default state on any error."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(DEFAULT_STATE)


def save_state(path: str, state: dict) -> None:
    """Save signal state to JSON file."""
    with open(path, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds


def fetch_price_data(ticker: str = "QQQ", days: int = 300) -> list[float]:
    """Fetch adjusted close prices from Yahoo Finance. Retries up to 3 times."""
    now = int(time.time())
    period1 = now - days * 86400
    url = f"{YAHOO_URL.format(ticker=ticker)}?period1={period1}&period2={now}&interval=1d"
    headers = {"User-Agent": USER_AGENT}

    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            req = Request(url, headers=headers)
            with urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            closes = data["chart"]["result"][0]["indicators"]["adjclose"][0]["adjclose"]
            return [c for c in closes if c is not None]
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)

    raise Exception(f"Yahoo Finance API 요청 실패 — 3회 재시도 후 실패: {last_error}")


def calculate_sma(prices: list[float], period: int = 200) -> float:
    """Calculate Simple Moving Average for the given period."""
    if len(prices) < period:
        raise ValueError(f"가격 데이터 부족: {len(prices)}일 (최소 {period}일 필요, 200일 SMA 계산 불가)")
    recent = prices[-period:]
    return round(sum(recent) / period, 2)


def determine_signal(price: float, sma: float) -> str:
    """Determine RISK_ON or RISK_OFF signal."""
    return "RISK_ON" if price > sma else "RISK_OFF"


def calculate_diff_pct(price: float, sma: float) -> float:
    """Calculate divergence percentage between price and SMA."""
    return round((price - sma) / sma * 100, 2)


DAILY_ESCAPE_THRESHOLD = -0.10  # -10% deviation triggers emergency exit


def calculate_deviation(price: float, sma: float) -> float:
    """Calculate (price - sma) / sma as a ratio (e.g. -0.10 = -10%)."""
    return (price - sma) / sma


PORTFOLIO = {
    "RISK_ON": {
        "f1": "TQQQ 30% + XLU 15% + GLD 55%",
        "f2": "TQQQ 30% + XLU 15% + GLD 55%",
        "phase2": "SCHD 50% + DIVO 50%",
    },
    "RISK_OFF": {
        "f1": "DBMF 30% + XLU 15% + GLD 55%",
        "f2": "DBMF 45% + GLD 55%",
        "phase2": "GLD 50% + BIL 50%",
    },
}

COLORS = {
    "RISK_ON": 3066993,    # green
    "RISK_OFF": 15158332,  # red
    "REPORT": 3447003,     # blue
    "ERROR": 16776960,     # yellow
}


def build_signal_change_embed(signal: str, price: float, sma: float, diff_pct: float) -> dict:
    """Build Discord embed for signal change notification."""
    is_on = signal == "RISK_ON"
    emoji = "🟢" if is_on else "🔴"
    label = "RISK-ON" if is_on else "RISK-OFF"
    direction = "상향 돌파" if is_on else "하향 이탈"
    sign = "+" if diff_pct >= 0 else ""

    return {
        "title": f"{emoji} {label} 전환!",
        "description": f"QQQ가 200일 이동평균선을 {direction}했습니다.\n**포트폴리오 조정이 필요합니다.**",
        "color": COLORS[signal],
        "fields": [
            {"name": "QQQ 종가", "value": f"${price:,.2f}", "inline": True},
            {"name": "200일 SMA", "value": f"${sma:,.2f}", "inline": True},
            {"name": "이격도", "value": f"{sign}{diff_pct}%", "inline": True},
            {"name": "F1 (보수적)", "value": PORTFOLIO[signal]["f1"], "inline": False},
            {"name": "F2 (공격적)", "value": PORTFOLIO[signal]["f2"], "inline": False},
            {"name": "Phase 2 (배당추세 안정전략)", "value": PORTFOLIO[signal]["phase2"], "inline": False},
        ],
        "footer": {"text": "FIRE Signal Bot • F전략 (Off=MF)"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def build_monthly_report_embed(
    signal: str, price: float, sma: float,
    diff_pct: float, last_change: str | None, check_date: str
) -> dict:
    """Build Discord embed for monthly status report."""
    is_on = signal == "RISK_ON"
    emoji = "🟢" if is_on else "🔴"
    label = "RISK-ON" if is_on else "RISK-OFF"
    sign = "+" if diff_pct >= 0 else ""

    if last_change:
        days_held = (datetime.strptime(check_date, "%Y-%m-%d") -
                     datetime.strptime(last_change, "%Y-%m-%d")).days
        held_text = f"{days_held}일째"
    else:
        held_text = "N/A"

    year_month = check_date[:7].replace("-", "년 ") + "월"

    return {
        "title": "📊 월간 F전략 시그널 리포트",
        "description": f"{year_month} 정기 리포트",
        "color": COLORS["REPORT"],
        "fields": [
            {"name": "현재 시그널", "value": f"{emoji} {label}", "inline": True},
            {"name": "시그널 유지", "value": held_text, "inline": True},
            {"name": "마지막 전환", "value": last_change or "N/A", "inline": True},
            {"name": "QQQ", "value": f"${price:,.2f}", "inline": True},
            {"name": "200일 SMA", "value": f"${sma:,.2f}", "inline": True},
            {"name": "이격도", "value": f"{sign}{diff_pct}%", "inline": True},
            {"name": "현재 포트폴리오", "value": f"F1: {PORTFOLIO[signal]['f1']}\nF2: {PORTFOLIO[signal]['f2']}", "inline": False},
            {"name": "Phase 2 (배당추세 안정전략)", "value": PORTFOLIO[signal]["phase2"], "inline": False},
        ],
        "footer": {"text": "FIRE Signal Bot • F전략 (Off=MF) • 매월 1일 자동 발송"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


DAILY_ESCAPE_PORTFOLIO = "DBMF 45% + GLD 55%"


def build_daily_escape_embed(
    price: float, sma: float, deviation: float, check_date: str
) -> dict:
    """Build Discord embed for daily emergency escape notification."""
    return {
        "title": "🚨 긴급 탈출 (D3) 발동!",
        "description": (
            f"QQQ 이격도가 **{deviation*100:.1f}%** 로 -10% 임계치를 이탈했습니다.\n"
            "**다음 거래일 시가에 포트폴리오 조정이 필요합니다.**"
        ),
        "color": COLORS["RISK_OFF"],
        "fields": [
            {"name": "QQQ 종가", "value": f"${price:,.2f}", "inline": True},
            {"name": "200일 SMA", "value": f"${sma:,.2f}", "inline": True},
            {"name": "이격도", "value": f"{deviation*100:.2f}%", "inline": True},
            {"name": "매도", "value": "TQQQ 전량 + XLU 전량", "inline": False},
            {"name": "매수", "value": "매도 대금으로 DBMF 매수", "inline": False},
            {"name": "유지", "value": "GLD 유지", "inline": False},
            {"name": "최종 포트폴리오", "value": DAILY_ESCAPE_PORTFOLIO, "inline": False},
            {"name": "실행 시점", "value": "다음 거래일 시가", "inline": True},
        ],
        "footer": {"text": f"FIRE Signal Bot • D3 긴급 탈출 • {check_date}"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def build_error_embed(error_message: str) -> dict:
    """Build Discord embed for error notification."""
    return {
        "title": "⚠️ 시그널 체크 실패",
        "description": "Yahoo Finance API 요청에 실패했습니다. 수동으로 확인이 필요합니다.",
        "color": COLORS["ERROR"],
        "fields": [
            {"name": "에러 내용", "value": str(error_message), "inline": False},
            {"name": "재시도", "value": "3회 시도 후 실패", "inline": True},
        ],
        "footer": {"text": "FIRE Signal Bot"},
    }


def send_discord_notification(webhook_url: str, embed: dict) -> None:
    """Send an embed to Discord via webhook."""
    payload = json.dumps({
        "embeds": [embed],
        "username": "F 전략봇",
        "avatar_url": "https://em-content.zobj.net/source/twitter/376/chart-increasing_1f4c8.png",
    }).encode("utf-8")
    req = Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    with urlopen(req) as resp:
        pass  # 204 No Content = success


def check_daily_escape(state_path: str = STATE_FILE, dry_run: bool = False) -> dict:
    """Daily emergency escape check (D3).

    Triggers RISK_OFF when QQQ deviation from SMA200 <= -10%,
    only if currently RISK_ON and not already triggered this month.
    Recovery is handled solely by the monthly SMA check.

    Args:
        dry_run: If True, skip state save and Discord notification (console output only).
    """
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_ym = today_str[:7]  # "YYYY-MM"

    # 1. Load state
    state = load_state(state_path)

    # 2. Skip if already OFF (bypass in dry-run)
    if not dry_run and state.get("signal") != "RISK_ON":
        print(f"{today_str}, SKIP: already {state.get('signal')}")
        return state

    # 3. Skip if already triggered this month (bypass in dry-run)
    escape_date = state.get("daily_escape_date")
    if not dry_run and escape_date and escape_date[:7] == today_ym:
        print(f"{today_str}, SKIP: already triggered this month ({escape_date})")
        return state

    # 4. Fetch data and calculate
    try:
        prices = fetch_price_data("QQQ", days=300)
        if len(prices) < 200:
            print(f"{today_str}, SKIP: insufficient data ({len(prices)} days)")
            return state
        sma = calculate_sma(prices, period=200)
        current_price = round(prices[-1], 2)
        deviation = calculate_deviation(current_price, sma)
    except Exception as e:
        print(f"ERROR: {e}")
        if webhook_url:
            send_discord_notification(webhook_url, build_error_embed(str(e)))
        raise

    # 5. Check threshold
    if deviation > DAILY_ESCAPE_THRESHOLD:
        print(f"{today_str}, {current_price}, {sma}, {deviation:.4f}, NO_ACTION")
        return state

    # 6. Trigger emergency exit
    action = "EMERGENCY_OFF (dry-run)" if dry_run else "EMERGENCY_OFF"
    print(f"{today_str}, {current_price}, {sma}, {deviation:.4f}, {action}")

    new_state = {
        **state,
        "signal": "RISK_OFF",
        "last_check": today_str,
        "last_price": current_price,
        "last_sma": sma,
        "diff_pct": round(deviation * 100, 2),
        "last_change": today_str,
        "trigger": "daily_escape",
        "daily_escape_date": today_str,
    }

    if not dry_run:
        save_state(state_path, new_state)
        if webhook_url:
            embed = build_daily_escape_embed(current_price, sma, deviation, today_str)
            send_discord_notification(webhook_url, embed)

    return new_state


def main() -> dict:
    """Main orchestration: fetch data, check signal, notify if changed, save state."""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    today = datetime.now()
    today_str = today.strftime("%Y-%m-%d")

    # 1. Load previous state
    state = load_state(STATE_FILE)
    prev_signal = state["signal"]

    # 2. Fetch price data and calculate
    try:
        prices = fetch_price_data("QQQ", days=300)
        sma = calculate_sma(prices, period=200)
        current_price = round(prices[-1], 2)
        diff_pct = calculate_diff_pct(current_price, sma)
        new_signal = determine_signal(current_price, sma)
    except Exception as e:
        print(f"ERROR: {e}")
        if webhook_url:
            send_discord_notification(webhook_url, build_error_embed(str(e)))
        raise

    # 3. Determine if signal changed
    changed = prev_signal is not None and new_signal != prev_signal

    # 4. Send notification
    if changed and webhook_url:
        embed = build_signal_change_embed(new_signal, current_price, sma, diff_pct)
        send_discord_notification(webhook_url, embed)
        print(f"SIGNAL CHANGED: {prev_signal} → {new_signal}")
    elif prev_signal is not None and webhook_url:
        # 시그널 유지 — 월간 리포트 전송
        embed = build_monthly_report_embed(
            new_signal, current_price, sma, diff_pct,
            state.get("last_change"), today_str
        )
        send_discord_notification(webhook_url, embed)
        print(f"Monthly report sent: {new_signal} (price={current_price}, sma={sma}, diff={diff_pct}%)")
    else:
        print(f"First run: {new_signal} (price={current_price}, sma={sma})")

    # 5. Update state
    last_change = state.get("last_change")
    trigger = state.get("trigger")
    daily_escape_date = state.get("daily_escape_date")

    if changed:
        last_change = today_str
        if new_signal == "RISK_OFF":
            trigger = "monthly"
            # preserve daily_escape_date for history
        else:
            # Recovery to ON — reset escape fields
            trigger = None
            daily_escape_date = None
    elif prev_signal is None:
        last_change = None
        trigger = None
        daily_escape_date = None

    new_state = {
        "signal": new_signal,
        "last_check": today_str,
        "last_price": current_price,
        "last_sma": sma,
        "diff_pct": diff_pct,
        "last_change": last_change,
        "trigger": trigger,
        "daily_escape_date": daily_escape_date,
    }
    save_state(STATE_FILE, new_state)

    # 6. Set GitHub Actions outputs
    print(f"::set-output name=signal::{new_signal}")
    print(f"::set-output name=changed::{'true' if changed else 'false'}")
    print(f"::set-output name=price::{current_price}")
    print(f"::set-output name=sma::{sma}")

    return new_state


if __name__ == "__main__":
    import sys
    if "--daily" in sys.argv:
        check_daily_escape(dry_run="--dry-run" in sys.argv)
    else:
        main()

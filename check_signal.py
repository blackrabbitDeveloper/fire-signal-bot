"""FIRE Signal Bot — QQQ 200-day SMA crossover detector."""

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


PORTFOLIO = {
    "RISK_ON": {
        "phase1": "TQQQ 25% + QQQ 55% + GLD 20%",
        "phase2": "SCHD 100%",
    },
    "RISK_OFF": {
        "phase1": "GLD 50% + BIL 50%",
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
            {"name": "Phase 1 (LTF 성장전략)", "value": PORTFOLIO[signal]["phase1"], "inline": False},
            {"name": "Phase 2 (배당추세 안정전략)", "value": PORTFOLIO[signal]["phase2"], "inline": False},
        ],
        "footer": {"text": "FIRE Signal Bot"},
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
        "title": "📊 월간 FIRE 시그널 리포트",
        "description": f"{year_month} 정기 리포트",
        "color": COLORS["REPORT"],
        "fields": [
            {"name": "현재 시그널", "value": f"{emoji} {label}", "inline": True},
            {"name": "시그널 유지", "value": held_text, "inline": True},
            {"name": "마지막 전환", "value": last_change or "N/A", "inline": True},
            {"name": "QQQ", "value": f"${price:,.2f}", "inline": True},
            {"name": "200일 SMA", "value": f"${sma:,.2f}", "inline": True},
            {"name": "이격도", "value": f"{sign}{diff_pct}%", "inline": True},
            {"name": "이번 달 액션", "value": "없음 (시그널 유지 중)", "inline": False},
        ],
        "footer": {"text": "FIRE Signal Bot • 매월 1일 자동 발송"},
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
    payload = json.dumps({"embeds": [embed]}).encode("utf-8")
    req = Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    with urlopen(req) as resp:
        pass  # 204 No Content = success


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
    if changed:
        last_change = today_str
    elif prev_signal is None:
        last_change = None

    new_state = {
        "signal": new_signal,
        "last_check": today_str,
        "last_price": current_price,
        "last_sma": sma,
        "diff_pct": diff_pct,
        "last_change": last_change,
    }
    save_state(STATE_FILE, new_state)

    # 6. Set GitHub Actions outputs
    print(f"::set-output name=signal::{new_signal}")
    print(f"::set-output name=changed::{'true' if changed else 'false'}")
    print(f"::set-output name=price::{current_price}")
    print(f"::set-output name=sma::{sma}")

    return new_state


if __name__ == "__main__":
    main()

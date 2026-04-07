"""FIRE Signal Bot — QQQ 200-day SMA crossover detector."""

import json
import os
import time
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

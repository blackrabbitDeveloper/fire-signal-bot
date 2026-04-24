"""Discord 웹훅 알림 모듈."""

import json
import os
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from config import (
    COLOR_CRITICAL, COLOR_ERROR, COLOR_HIGH, COLOR_INFO,
    COLOR_NORMAL, COLOR_OFF, COLOR_PRE, PORTFOLIO_OFF, PORTFOLIO_ON,
)

USER_AGENT = "Mozilla/5.0 (FIRE-Signal-Bot)"

URGENCY_CONFIG = {
    "CRITICAL": {"color": COLOR_CRITICAL, "prefix": "🚨🚨🚨"},
    "HIGH":     {"color": COLOR_HIGH,     "prefix": "⚡⚡"},
    "NORMAL":   {"color": COLOR_NORMAL,   "prefix": "📋"},
    "INFO":     {"color": COLOR_INFO,     "prefix": "ℹ️"},
}


def _post_webhook(webhook_url: str, payload: dict) -> None:
    """Discord 웹훅으로 POST 요청."""
    data = json.dumps(payload).encode("utf-8")
    req = Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    with urlopen(req) as resp:
        pass  # 204 No Content = success


def build_emergency_exit_embed(indicators: dict, check_date: str) -> dict:
    """긴급 탈출 Discord embed."""
    return {
        "title": "🚨🚨🚨 긴급 탈출 (D3) 발동!",
        "description": (
            f"QQQ 편차 **{indicators['deviation_pct']:+.2f}%** ≤ -10% 임계치 이탈\n"
            "**다음 거래일 시가에 포트폴리오 조정 필요**"
        ),
        "color": COLOR_CRITICAL,
        "fields": [
            {"name": "QQQ 종가", "value": f"${indicators['close']:,.2f}", "inline": True},
            {"name": "SMA200", "value": f"${indicators['sma200']:,.2f}", "inline": True},
            {"name": "편차", "value": f"{indicators['deviation_pct']:+.2f}%", "inline": True},
            {"name": "매도", "value": "TQQQ + XLU 전량", "inline": True},
            {"name": "매수", "value": "DBMF (매도 대금)", "inline": True},
            {"name": "최종 포트폴리오", "value": PORTFOLIO_OFF, "inline": False},
        ],
        "footer": {"text": f"H 전략 시그널 봇 • D3 긴급 탈출 • {check_date}"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def build_golden_cross_entry_embed(indicators: dict, check_date: str) -> dict:
    """골든크로스 Entry Discord embed."""
    return {
        "title": "⚡⚡ 골든크로스 Entry!",
        "description": (
            f"편차 **{indicators['deviation_pct']:+.2f}%** ≥ +1% & SMA50 > SMA200\n"
            "**다음 거래일 시가에 포트폴리오 조정 필요**"
        ),
        "color": COLOR_HIGH,
        "fields": [
            {"name": "QQQ 종가", "value": f"${indicators['close']:,.2f}", "inline": True},
            {"name": "SMA200", "value": f"${indicators['sma200']:,.2f}", "inline": True},
            {"name": "SMA50", "value": f"${indicators['sma50']:,.2f}", "inline": True},
            {"name": "편차", "value": f"{indicators['deviation_pct']:+.2f}%", "inline": True},
            {"name": "골든크로스", "value": "✓ SMA50 > SMA200", "inline": True},
            {"name": "매도", "value": "DBMF 전량", "inline": True},
            {"name": "매수", "value": "TQQQ + XLU (매도 대금)", "inline": True},
            {"name": "최종 포트폴리오", "value": PORTFOLIO_ON, "inline": False},
        ],
        "footer": {"text": f"H 전략 시그널 봇 • GCE 진입 • {check_date}"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def build_pre_entry_embed(indicators: dict, check_date: str) -> dict:
    """PRE Entry Discord embed."""
    return {
        "title": "🚨🚨🚨 PRE Entry! 패닉 바닥 진입",
        "description": (
            f"편차 **{indicators['deviation_pct']:+.2f}%** ≤ -10% & "
            f"VIX **{indicators['vix']:.1f}** > 40 & "
            f"VIX drop **+{indicators['vix_drop']:.1f}**\n"
            "**다음 거래일 시가에 포트폴리오 조정 필요**\n"
            "20일간 월말 체크 비활성 / 진입가 하회 시 즉시 Exit"
        ),
        "color": COLOR_PRE,
        "fields": [
            {"name": "QQQ 종가", "value": f"${indicators['close']:,.2f}", "inline": True},
            {"name": "SMA200", "value": f"${indicators['sma200']:,.2f}", "inline": True},
            {"name": "편차", "value": f"{indicators['deviation_pct']:+.2f}%", "inline": True},
            {"name": "VIX", "value": f"{indicators['vix']:.1f}", "inline": True},
            {"name": "VIX 5일 drop", "value": f"+{indicators['vix_drop']:.1f}", "inline": True},
            {"name": "PRE 진입가", "value": f"${indicators['close']:,.2f}", "inline": True},
            {"name": "매도", "value": "DBMF 전량", "inline": True},
            {"name": "매수", "value": "TQQQ+XLU+GLD", "inline": True},
            {"name": "최종 포트폴리오", "value": PORTFOLIO_ON, "inline": False},
        ],
        "footer": {"text": f"H 전략 시그널 봇 • PRE Entry • {check_date}"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def build_pre_price_exit_embed(indicators: dict, state: dict, check_date: str) -> dict:
    """PRE 가격 Exit Discord embed."""
    pre_price = state.get("pre_entry_price", 0)
    return {
        "title": "🚨🚨🚨 PRE 가격 Exit! V자 실패",
        "description": (
            f"QQQ **{indicators['close']:,.2f}** < 진입가 **{pre_price:,.2f}**\n"
            "**다음 거래일 시가에 포트폴리오 조정 필요**"
        ),
        "color": COLOR_CRITICAL,
        "fields": [
            {"name": "QQQ 종가", "value": f"${indicators['close']:,.2f}", "inline": True},
            {"name": "PRE 진입가", "value": f"${pre_price:,.2f}", "inline": True},
            {"name": "편차", "value": f"{indicators['deviation_pct']:+.2f}%", "inline": True},
            {"name": "VIX", "value": f"{indicators.get('vix', 0):.1f}", "inline": True},
            {"name": "매도", "value": "TQQQ+XLU 전량", "inline": True},
            {"name": "매수", "value": "DBMF (매도 대금)", "inline": True},
            {"name": "최종 포트폴리오", "value": PORTFOLIO_OFF, "inline": False},
        ],
        "footer": {"text": f"H 전략 시그널 봇 • PRE 가격 Exit • {check_date}"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def build_monthly_change_embed(
    direction: str, indicators: dict, check_date: str
) -> dict:
    """월말 On/Off 전환 embed."""
    if direction == "On":
        title = "📋 월말 On 전환"
        desc = f"QQQ={indicators['close']:.2f} > SMA200={indicators['sma200']:.2f}"
        color = COLOR_NORMAL
        action = f"DBMF 전량 매도 → TQQQ+XLU+GLD 매수\n최종: {PORTFOLIO_ON}"
    else:
        title = "📋 월말 Off 전환"
        desc = f"QQQ={indicators['close']:.2f} ≤ SMA200={indicators['sma200']:.2f}"
        color = COLOR_OFF
        action = f"TQQQ+XLU 전량 매도 → DBMF 매수\n최종: {PORTFOLIO_OFF}"

    return {
        "title": title,
        "description": desc,
        "color": color,
        "fields": [
            {"name": "QQQ 종가", "value": f"${indicators['close']:,.2f}", "inline": True},
            {"name": "SMA200", "value": f"${indicators['sma200']:,.2f}", "inline": True},
            {"name": "편차", "value": f"{indicators['deviation_pct']:+.2f}%", "inline": True},
            {"name": "액션", "value": action, "inline": False},
        ],
        "footer": {"text": f"H 전략 시그널 봇 • 월말 정기 • {check_date}"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def build_daily_status_embed(
    state: dict, indicators: dict, check_date: str
) -> dict:
    """일일 상태 리포트 embed (가이드 v2 형식)."""
    current = state["state"]
    in_pre = state.get("in_pre", False)
    emoji = "🟢" if current == "On" else "🔴"
    pre_label = " [PRE]" if in_pre else ""

    # 임계치 거리 계산
    exit_price = indicators["sma200"] * 0.90
    exit_dist = (exit_price - indicators["close"]) / indicators["close"] * 100

    vix = indicators.get("vix", 0)
    vix_drop = indicators.get("vix_drop", 0)

    fields = [
        {"name": "상태", "value": f"{emoji} {current}{pre_label}", "inline": True},
        {"name": "QQQ", "value": f"${indicators['close']:,.2f}", "inline": True},
        {"name": "SMA200", "value": f"${indicators['sma200']:,.2f}", "inline": True},
        {"name": "편차", "value": f"{indicators['deviation_pct']:+.2f}%", "inline": True},
        {"name": "SMA50", "value": f"${indicators['sma50']:,.2f}", "inline": True},
        {"name": "RSI(14)", "value": f"{indicators['rsi']:.1f}", "inline": True},
        {"name": "골든크로스", "value": "✓" if indicators["golden_cross"] else "✗", "inline": True},
        {"name": "VIX", "value": f"{vix:.1f}", "inline": True},
        {"name": "VIX 5일 drop", "value": f"{vix_drop:+.1f}", "inline": True},
    ]

    if current == "On":
        fields.append({
            "name": "긴급 탈출 라인",
            "value": f"${exit_price:,.2f} ({exit_dist:+.1f}%)",
            "inline": True,
        })
    else:
        gce_price = indicators["sma200"] * 1.01
        gce_dist = (gce_price - indicators["close"]) / indicators["close"] * 100
        gc_status = "✓" if indicators["golden_cross"] else "✗ (대기)"
        fields.append({
            "name": "GCE 진입 라인",
            "value": f"${gce_price:,.2f} ({gce_dist:+.1f}%) / GC: {gc_status}",
            "inline": True,
        })

    if in_pre:
        pre_price = state.get("pre_entry_price", 0)
        fields.append({
            "name": "PRE 진입가",
            "value": f"${pre_price:,.2f}",
            "inline": True,
        })

    return {
        "title": f"H 전략 V16a_c20 일일 리포트 ({check_date})",
        "color": COLOR_INFO,
        "fields": fields,
        "footer": {"text": f"H 전략 시그널 봇 • Exit: {state.get('exit_count', 0)}회 / Entry: {state.get('entry_count', 0)}회"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def build_error_embed(error_message: str) -> dict:
    """에러 알림 embed."""
    return {
        "title": "⚠️ 시그널 체크 실패",
        "description": "데이터 수집에 실패했습니다. 수동 확인 필요.",
        "color": COLOR_ERROR,
        "fields": [
            {"name": "에러", "value": str(error_message)[:1024], "inline": False},
            {"name": "재시도", "value": "3회 시도 후 실패", "inline": True},
        ],
        "footer": {"text": "H 전략 시그널 봇"},
    }


def send_notification(embed: dict) -> None:
    """Discord 웹훅으로 embed 전송. DISCORD_WEBHOOK_URL 환경변수 필요."""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not webhook_url:
        print("[알림 건너뜀] DISCORD_WEBHOOK_URL 미설정")
        return

    payload = {
        "embeds": [embed],
        "username": "H 전략 시그널 봇",
        "avatar_url": "https://em-content.zobj.net/source/twitter/376/chart-increasing_1f4c8.png",
    }
    _post_webhook(webhook_url, payload)
    print("[알림 발송 완료]")

# H 전략 V16a_c20 시그널 알림 봇 가이드 v2

**BlackRabbit LAB · v2 · 2026-04-24**

**F2D3 + GCE + PRE 기준 · Phase 1 자동 알림 시스템**

---

## v1 → v2 핵심 변경

- **PRE (Panic Rebound Entry) 로직 추가**
  - 조건: Off + VIX > 40 + VIX 5일 drop ≥ 5 + 편차 ≤ -10%
  - 쿨다운 60 거래일, 월말 쿨타임 c20
  - PRE 가격 Exit (진입가 하회 시 즉시 Off)
- **VIX 데이터 소스 추가** (yfinance `^VIX`)
- **일일 리포트에 VIX 지표 포함**
- **SMA50 추가 (GCE 확인용)**

---

## 1. 개요

### 1.1 목적

H 전략 Phase 1 V16a_c20의 매매 시그널을 자동 감지하고 알림을 발송하는 봇.
직접 매매를 실행하지 않으며, **"알림만 보내고 사용자가 판단·실행"** 하는 구조.

### 1.2 체크 빈도

| 시그널 | 체크 빈도 | 긴급성 |
|--------|----------|--------|
| 월말 On/Off | 매월 마지막 거래일 16:00 EST | 정기 |
| 긴급 Exit (편차 ≤ -10%) | **매일 16:00 EST** (On 상태일 때만) | 긴급 |
| GCE Entry (골든크로스) | **매일 16:00 EST** (Off 상태일 때만) | 긴급 |
| **★ PRE Entry (패닉 바닥)** | **매일 16:00 EST** (Off 상태일 때만) | **CRITICAL** |
| PRE 가격 Exit | **매일** (PRE 보유 중일 때만) | 긴급 |
| 연 리밸런싱 | 매년 1월 첫 거래일 | 정기 |
| Phase 2 트리거 | 연말 (12월 말 자산 집계 시 확인) | 정기 |

---

## 2. 시그널 정의

### 2.1 Phase 1 V16a_c20 상태 체계

```
            ┌──────────────────────────────────────┐
            │                On 상태                │
            │   TQQQ 30% + XLU 15% + GLD 55%       │
            └────────┬───────────────┬──────────────┘
                     │               │
           월말 Off  │    긴급 Exit  │
        (QQQ<SMA200) │  (편차≤-10%)  │
                     ▼               ▼
            ┌──────────────────────────────────────┐
            │               Off 상태                │
            │      DBMF 45% + GLD 55%              │
            └────┬─────────────┬──────────────┬─────┘
                 │             │              │
       월말 On   │  GCE Entry  │  ★ PRE Entry │
    (QQQ>SMA200) │ (편차≥+1% &  │(VIX>40+drop5 │
                 │  SMA50>200) │ +편차≤-10%) │
                 ▼             ▼              ▼
            ┌──────────────────────────────────────┐
            │                On 상태                │
            │    (PRE 진입 시 20일 쿨타임 활성)     │
            └──────────────────────────────────────┘
```

### 2.2 시그널 조건 상세

#### 월말 On/Off (정기)

```python
if monthly_active:  # PRE 쿨타임 중이면 건너뛰기
    if qqq_close > sma200 and state == "Off":
        action = "Off → On 전환"
    elif qqq_close <= sma200 and state == "On":
        action = "On → Off 전환"
```

#### 긴급 Exit (On 상태)

```python
deviation = (qqq_close - sma200) / sma200
if state == "On" and deviation <= -0.10:
    action = "★ 긴급 Exit → Off 전환"
```

#### GCE Entry (Off 상태)

```python
if (state == "Off" and not in_pre
    and deviation >= 0.01 and sma50 > sma200):
    action = "★ GCE Entry → On 전환"
```

#### ★ PRE Entry (Off 상태, v2 신규)

```python
vix_drop = vix_5d_ago - vix_now

if (state == "Off"
    and deviation <= -0.10
    and vix_now > 40
    and vix_drop >= 5
    and (day_idx - last_pre_trigger_idx) >= 60):
    action = "★★ PRE Entry → On 전환 (패닉 바닥)"
    urgency = "CRITICAL"
    # 20일간 월말 체크 비활성
    # PRE 진입가 기록
```

#### PRE 가격 Exit (PRE 보유 중)

```python
if in_pre and qqq_close < pre_entry_price:
    action = "★ PRE 가격 Exit → Off (V자 실패)"
    urgency = "CRITICAL"
```

#### PRE 자동 해제 (20일 경과 + 편차 > 0)

```python
days_held = day_idx - pre_entry_day_idx
if in_pre and days_held >= 20 and deviation > 0 and not is_month_end:
    action = "PRE 보호 해제 (On 유지, 일반 모드)"
    # 포지션 변경 없음, 플래그만 해제
```

---

## 3. 구현 가이드

### 3.1 아키텍처

```
[데이터 소스]          [봇 서버]             [알림 채널]
 yfinance QQQ  ──────▶ signal_check.py ───▶  텔레그램
 yfinance ^VIX  ────▶  (상태 관리)           카카오톡
                      │                     이메일
                      ▼                     디스코드
              상태 저장 (JSON)
              로그 기록 (CSV)
```

### 3.2 핵심 코드 (v2 업데이트)

```python
"""H 전략 V16a_c20 시그널 체커 — F2D3 + GCE + PRE."""
import yfinance as yf
import pandas as pd
import numpy as np
import json
from datetime import datetime, date
from pathlib import Path

STATE_FILE = Path("signal_state.json")
LOG_FILE = Path("signal_log.csv")

# V16a_c20 파라미터
EMERGENCY_THRESHOLD = -0.10
GCE_DEVIATION = 0.01
PRE_VIX_THRESHOLD = 40.0
PRE_VIX_DROP_THRESHOLD = 5.0
PRE_VIX_DROP_LOOKBACK = 5
PRE_COOLDOWN = 60  # 거래일
PRE_MONTHLY_COOLDOWN = 20


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {
        "state": "On",
        "in_pre": False,
        "pre_entry_day_idx": -1,
        "pre_entry_price": 0.0,
        "last_pre_trigger_idx": -10000,
        "day_idx": 0,
        "last_check": None,
    }


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def get_market_data(lookback_days=250):
    """QQQ와 VIX 데이터 로드."""
    qqq = yf.download("QQQ", period=f"{lookback_days}d",
                      auto_adjust=True, progress=False)
    vix = yf.download("^VIX", period=f"{lookback_days}d",
                      auto_adjust=True, progress=False)
    # MultiIndex 처리
    if isinstance(qqq.columns, pd.MultiIndex):
        qqq_close = qqq[("Close", "QQQ")].dropna()
        vix_close = vix[("Close", "^VIX")].dropna()
    else:
        qqq_close = qqq["Close"].dropna()
        vix_close = vix["Close"].dropna()
    return qqq_close.astype(float), vix_close.astype(float)


def compute_indicators(qqq_close, vix_close):
    """필요한 모든 지표 계산."""
    sma200 = qqq_close.rolling(200).mean()
    sma50 = qqq_close.rolling(50).mean()
    
    current_qqq = float(qqq_close.iloc[-1])
    current_sma200 = float(sma200.iloc[-1])
    current_sma50 = float(sma50.iloc[-1])
    deviation = (current_qqq - current_sma200) / current_sma200
    
    # VIX drop (5일 전 대비)
    current_vix = float(vix_close.iloc[-1])
    vix_5d_ago = float(vix_close.iloc[-1 - PRE_VIX_DROP_LOOKBACK])
    vix_drop = vix_5d_ago - current_vix
    
    # RSI 계산 (참고용)
    delta = qqq_close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss
    rsi = float((100 - 100 / (1 + rs)).iloc[-1])
    
    return {
        "qqq": current_qqq,
        "sma200": current_sma200,
        "sma50": current_sma50,
        "deviation": deviation,
        "deviation_pct": deviation * 100,
        "vix": current_vix,
        "vix_drop": vix_drop,
        "rsi": rsi,
        "golden_cross": current_sma50 > current_sma200,
        "above_sma200": current_qqq > current_sma200,
    }


def check_signals(state, ind, is_month_end=False):
    """V16a_c20 시그널 체크."""
    actions = []
    current = state["state"]
    in_pre = state["in_pre"]
    day_idx = state["day_idx"]
    days_held = day_idx - state["pre_entry_day_idx"] if in_pre else 0
    monthly_active = not (in_pre and days_held < PRE_MONTHLY_COOLDOWN)
    
    # 1. PRE 가격 Exit (최우선)
    if in_pre and ind["qqq"] < state["pre_entry_price"]:
        actions.append({
            "type": "PRE_PRICE_EXIT",
            "urgency": "CRITICAL",
            "message": f"★ PRE 가격 Exit! QQQ {ind['qqq']:.2f} < 진입가 "
                       f"{state['pre_entry_price']:.2f}",
            "action": "TQQQ+XLU 전량 매도 → DBMF 매수",
            "new_state": "Off",
            "clear_pre": True,
        })
        return actions
    
    # 2. 긴급 Exit (On, PRE 아닌 상태)
    if current == "On" and not in_pre and ind["deviation"] <= EMERGENCY_THRESHOLD:
        actions.append({
            "type": "EMERGENCY_EXIT",
            "urgency": "CRITICAL",
            "message": f"★ 긴급 Exit! 편차 {ind['deviation_pct']:+.2f}%",
            "action": "TQQQ+XLU 전량 매도 → DBMF 매수",
            "new_state": "Off",
        })
        return actions
    
    # 3. ★ PRE Entry (Off 상태, v2 신규)
    days_since_pre = day_idx - state["last_pre_trigger_idx"]
    if (current == "Off"
        and days_since_pre >= PRE_COOLDOWN
        and ind["deviation"] <= EMERGENCY_THRESHOLD
        and ind["vix"] > PRE_VIX_THRESHOLD
        and ind["vix_drop"] >= PRE_VIX_DROP_THRESHOLD):
        actions.append({
            "type": "PRE_ENTRY",
            "urgency": "CRITICAL",
            "message": f"★★ PRE Entry! 편차 {ind['deviation_pct']:+.2f}%, "
                       f"VIX {ind['vix']:.1f}, drop +{ind['vix_drop']:.1f}",
            "action": "DBMF 매도 → TQQQ+XLU+GLD 매수 (패닉 바닥 진입)",
            "new_state": "On",
            "set_pre": True,
            "pre_entry_price": ind["qqq"],
        })
        return actions
    
    # 4. GCE Entry (Off 상태)
    if (current == "Off" and not in_pre
        and ind["deviation"] >= GCE_DEVIATION
        and ind["golden_cross"]):
        actions.append({
            "type": "GCE_ENTRY",
            "urgency": "HIGH",
            "message": f"★ GCE Entry! 편차 {ind['deviation_pct']:+.2f}%, "
                       f"SMA50>SMA200",
            "action": "DBMF 매도 → TQQQ+XLU+GLD 매수",
            "new_state": "On",
        })
        return actions
    
    # 5. PRE 자동 해제 (20일 + 편차 > 0, 월말 아님)
    if in_pre and days_held >= PRE_MONTHLY_COOLDOWN and not is_month_end:
        if ind["deviation"] > 0:
            actions.append({
                "type": "PRE_AUTO_RELEASE",
                "urgency": "INFO",
                "message": f"PRE 보호 해제 (On 유지, 일반 모드 복귀). "
                           f"편차 {ind['deviation_pct']:+.2f}%, {days_held}일 보유",
                "action": "포지션 변경 없음 (PRE 플래그만 해제)",
                "new_state": current,
                "clear_pre": True,
            })
    
    # 6. 월말 체크 (쿨타임 아닐 때)
    if is_month_end and monthly_active:
        if current == "On" and not ind["above_sma200"]:
            actions.append({
                "type": "MONTHLY_OFF",
                "urgency": "NORMAL",
                "message": f"월말 Off 전환",
                "action": "TQQQ+XLU 전량 매도 → DBMF 매수",
                "new_state": "Off",
                "clear_pre": True,
            })
        elif current == "Off" and ind["above_sma200"]:
            actions.append({
                "type": "MONTHLY_ON",
                "urgency": "NORMAL",
                "message": f"월말 On 전환",
                "action": "DBMF 매도 → TQQQ+XLU+GLD 매수",
                "new_state": "On",
            })
    
    # 7. 일일 리포트 (액션 없어도)
    if not actions:
        pre_tag = f" [PRE {days_held}일]" if in_pre else ""
        actions.append({
            "type": "DAILY_STATUS",
            "urgency": "INFO",
            "message": (f"[{current}{pre_tag}] QQQ={ind['qqq']:.2f}, "
                        f"편차={ind['deviation_pct']:+.2f}%, "
                        f"VIX={ind['vix']:.1f} (drop {ind['vix_drop']:+.1f}), "
                        f"RSI={ind['rsi']:.1f}, "
                        f"GC={'✓' if ind['golden_cross'] else '✗'}"),
            "action": "유지",
            "new_state": current,
        })
    
    return actions


def apply_state_changes(state, actions, day_idx, qqq_price):
    """액션에 따라 상태 업데이트."""
    for action in actions:
        if action["type"] == "PRE_ENTRY":
            state["state"] = "On"
            state["in_pre"] = True
            state["pre_entry_day_idx"] = day_idx
            state["pre_entry_price"] = action["pre_entry_price"]
            state["last_pre_trigger_idx"] = day_idx
        elif action.get("clear_pre"):
            state["in_pre"] = False
            if action["new_state"] != state["state"]:
                state["state"] = action["new_state"]
        elif action["new_state"] != state["state"]:
            state["state"] = action["new_state"]
    
    state["day_idx"] = day_idx
    state["last_check"] = datetime.now().isoformat()
    return state


def main():
    print(f"=== H 전략 V16a_c20 시그널 체크 ({datetime.now():%Y-%m-%d %H:%M}) ===\n")
    
    state = load_state()
    qqq_close, vix_close = get_market_data()
    ind = compute_indicators(qqq_close, vix_close)
    
    day_idx = state.get("day_idx", 0) + 1
    
    today = date.today()
    # 월말 여부 체크 (간단 구현)
    import calendar
    last_day = calendar.monthrange(today.year, today.month)[1]
    is_month_end = (today.day >= last_day - 3)  # 근사
    
    print(f"현재 상태: {state['state']} (PRE={state['in_pre']})")
    print(f"QQQ: {ind['qqq']:.2f} / SMA200: {ind['sma200']:.2f} / SMA50: {ind['sma50']:.2f}")
    print(f"편차: {ind['deviation_pct']:+.2f}%")
    print(f"VIX: {ind['vix']:.2f} (5일 drop: {ind['vix_drop']:+.2f})")
    print(f"RSI(14): {ind['rsi']:.1f}")
    print(f"골든크로스: {'✓' if ind['golden_cross'] else '✗'}")
    print()
    
    actions = check_signals(state, ind, is_month_end=is_month_end)
    
    for action in actions:
        marker = {
            "CRITICAL": "🚨🚨🚨",
            "HIGH": "⚡⚡",
            "NORMAL": "📋",
            "INFO": "ℹ️",
        }.get(action["urgency"], "")
        
        print(f"{marker} [{action['type']}] {action['message']}")
        print(f"  → {action['action']}")
    
    state = apply_state_changes(state, actions, day_idx, ind["qqq"])
    save_state(state)
    
    # CRITICAL/HIGH 알림만 전송
    for action in actions:
        if action["urgency"] in ("CRITICAL", "HIGH"):
            send_alert(action, ind)


def send_alert(action, indicators):
    """텔레그램/카카오톡/이메일 알림 발송 (구현 필요)."""
    # import os, requests
    # BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    # CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
    # text = f"{action['message']}\n\n행동: {action['action']}\n\nVIX: {indicators['vix']:.1f}"
    # requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
    #               json={"chat_id": CHAT_ID, "text": text})
    print(f"  [알림 발송 시뮬]")


if __name__ == "__main__":
    main()
```

### 3.3 스케줄링 (GitHub Actions 추천)

```yaml
# .github/workflows/signal-check.yml
name: H v5 Signal Check
on:
  schedule:
    - cron: '0 21 * * 1-5'  # UTC 21:00 = EST 16:00
  workflow_dispatch:

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install yfinance pandas numpy requests
      - run: python signal_checker.py
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
      - name: Commit state
        run: |
          git config user.email "bot@example.com"
          git config user.name "Signal Bot"
          git add signal_state.json signal_log.csv
          git commit -m "Update state $(date +%Y%m%d)" || echo "No changes"
          git push
```

---

## 4. 일일 리포트 형식 (v2 확장)

```
═══════════════════════════════════════════
  H 전략 V16a_c20 일일 리포트 (2026-04-24)
═══════════════════════════════════════════
  상태: 🟢 On [PRE 보유 아님]
  
  QQQ       : $485.32
  SMA200    : $465.10  (편차 +4.35%)
  SMA50     : $475.20  (GC: ✓)
  RSI(14)   : 52.3
  
  VIX       : 14.21
  VIX 5일전  : 13.87
  VIX drop  : -0.34 (상승 중, 패닉 아님)
  
  ── 임계치 거리 ──
  긴급 Exit:    $418.59 (-13.8%)  ← 안전
  GCE Entry:   N/A (On 상태)
  PRE Entry:   N/A (On 상태)
  
  ── PRE 상태 ──
  마지막 PRE 발동: 없음 (또는 YYYY-MM-DD, N일 전)
  PRE 쿨다운 남은 거래일: 0일
  
  ── 올해 ──
  Exit: 0회
  GCE Entry: 0회
  PRE Entry: 0회
═══════════════════════════════════════════
```

---

## 5. PRE 이벤트 기록 표준

PRE 발동 시 별도 JSON 파일에 기록:

```json
{
  "pre_events": [
    {
      "entry_date": "2030-03-15",
      "entry_price": 420.15,
      "entry_deviation": -0.152,
      "entry_vix": 52.3,
      "entry_vix_drop": 8.2,
      "exit_date": "2030-04-18",
      "exit_price": 478.92,
      "exit_reason": "auto_release",
      "holding_days": 24,
      "pnl_pct": 13.98
    }
  ]
}
```

이 기록은 **out-of-sample 검증**에 활용. 실전 배포 후 첫 PRE 이벤트는 V16a_c20의 real-world 검증 핵심 데이터.

---

## 6. 면책 고지

- 본 봇은 **알림 목적**이며 투자 조언이 아닙니다.
- 자동 매매 기능은 의도적으로 제외되었습니다.
- 시그널은 과거 검증 결과이며 미래 성과를 보장하지 않습니다.
- 최종 매매 판단은 사용자 본인의 책임입니다.
- yfinance 데이터는 지연될 수 있으며, 중요 판단 시 브로커 실시간 데이터로 확인하세요.

---

*BlackRabbit LAB · SIGNAL_ALERT_BOT_GUIDE v2 · 2026-04-24*
*H 전략 Phase 1 V16a_c20: F2D3 + GCE + PRE 기준*

# H 전략 시그널 알림 봇 개발 가이드

**BlackRabbit LAB · v1 · 2026-04-22**

**F2D3 + 골든크로스 Entry 기준 · Phase 1 자동 알림 시스템**

---

## 1. 개요

### 1.1 목적

H 전략 Phase 1(F2D3+GCE)의 매매 시그널을 자동 감지하고 알림을 발송하는 봇.
직접 매매를 실행하지 않으며, **"알림만 보내고 사용자가 판단·실행"** 하는 구조.

### 1.2 왜 봇이 아니라 알림인가

- Phase 1 B&H가 최선 (교훈 #6: 870+ 타이밍 전략 전부 B&H 미달)
- 자동매매 봇은 불필요 (2020 이전 검증 완료)
- 필요한 것은 "월 1회 체크 + 긴급 탈출/진입 알림"뿐

### 1.3 체크 빈도

| 시그널 | 체크 빈도 | 긴급성 |
|--------|----------|--------|
| 월말 On/Off | 매월 마지막 거래일 16:00 EST | 정기 |
| 긴급 탈출 (Exit) | **매일 16:00 EST** (On 상태일 때만) | 긴급 |
| 골든크로스 Entry | **매일 16:00 EST** (Off 상태일 때만) | 긴급 |
| 연 리밸런싱 | 매년 1월 첫 거래일 | 정기 |
| Phase 2 트리거 | 연말 (12월 말 자산 집계 시 확인) | 정기 |

---

## 2. 시그널 정의

### 2.1 Phase 1 상태 체계

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
         └────────┬───────────────┬──────────────┘
                  │               │
        월말 On   │   GCE Entry   │
     (QQQ>SMA200) │ (편차≥+1% &   │
                  │  SMA50>SMA200)│
                  ▼               ▼
         ┌──────────────────────────────────────┐
         │                On 상태                │
         └──────────────────────────────────────┘
```

### 2.2 시그널 조건 상세

#### 월말 On/Off (정기, 매월 마지막 거래일)

```python
# 조건
signal_on = qqq_close > sma200
signal_off = qqq_close <= sma200

# 상태 전환
if current_state == "Off" and signal_on:
    action = "Off → On 전환"
elif current_state == "On" and signal_off:
    action = "On → Off 전환"
else:
    action = "유지 (거래 없음)"
```

#### 긴급 탈출 — Exit (매일, On 상태에서만)

```python
# 조건: QQQ 종가 vs SMA200 편차 ≤ -10%
deviation = (qqq_close - sma200) / sma200

if current_state == "On" and deviation <= -0.10:
    action = "★ 긴급 탈출 → Off 전환"
    urgency = "CRITICAL"
```

**Bootstrap 근거**: 26Y 5회 발동, MDD -26.49% → -33.05% 방어 (6/8 위기 공통).

#### 골든크로스 Entry (매일, Off 상태에서만)

```python
# 조건: (편차 ≥ +1%) AND (SMA50 > SMA200)
deviation = (qqq_close - sma200) / sma200
golden_cross = sma50 > sma200

if current_state == "Off" and deviation >= 0.01 and golden_cross:
    action = "★ 골든크로스 Entry → On 전환"
    urgency = "HIGH"
```

**Bootstrap 근거**: 26Y Sharpe 1.015, 닷컴/2008 whipsaw 4건 전부 차단, 코로나 V자 통과.
FIRE 중위 14.27 → 14.10년 (Bootstrap 1000경로).

---

## 3. 구현 가이드

### 3.1 아키텍처

```
[데이터 소스]        [봇 서버]           [알림 채널]
 yfinance  ──────▶  signal_check.py  ──▶  텔레그램
 또는                    │                 카카오톡
 Investing.com          │                 이메일
                        ▼                 디스코드
                  상태 저장 (JSON)
                  로그 기록 (CSV)
```

### 3.2 핵심 코드

#### signal_checker.py

```python
"""H 전략 시그널 체커 — F2D3 + 골든크로스 Entry."""
import yfinance as yf
import pandas as pd
import numpy as np
import json
from datetime import datetime, date
from pathlib import Path

# ── 설정 ──
STATE_FILE = Path("signal_state.json")
LOG_FILE = Path("signal_log.csv")

def load_state():
    """현재 On/Off 상태 로드."""
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"state": "On", "last_check": None, "last_action": None}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))

def log_signal(date, signal_type, details):
    """시그널 이력 기록."""
    header = not LOG_FILE.exists()
    with open(LOG_FILE, "a") as f:
        if header:
            f.write("date,signal_type,state,qqq_close,sma200,sma50,deviation,rsi,action\n")
        f.write(f"{date},{signal_type},{details}\n")

def get_qqq_data(lookback_days=250):
    """QQQ 최근 데이터 로드."""
    qqq = yf.download("QQQ", period=f"{lookback_days}d", auto_adjust=True, progress=False)
    if isinstance(qqq.columns, pd.MultiIndex):
        close = qqq[("Close", "QQQ")].dropna()
    else:
        close = qqq["Close"].dropna()
    return close.astype(float)

def compute_indicators(close):
    """SMA200, SMA50, 편차, RSI 계산."""
    sma200 = close.rolling(200).mean()
    sma50 = close.rolling(50).mean()
    
    current_close = float(close.iloc[-1])
    current_sma200 = float(sma200.iloc[-1])
    current_sma50 = float(sma50.iloc[-1])
    deviation = (current_close - current_sma200) / current_sma200
    
    # RSI(14) — 참고용
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss
    rsi = float((100 - 100 / (1 + rs)).iloc[-1])
    
    return {
        "close": current_close,
        "sma200": current_sma200,
        "sma50": current_sma50,
        "deviation": deviation,
        "deviation_pct": deviation * 100,
        "rsi": rsi,
        "above_sma200": current_close > current_sma200,
        "golden_cross": current_sma50 > current_sma200,
    }

def check_signals(state, indicators, is_month_end=False):
    """시그널 체크 — 액션 리스트 반환."""
    actions = []
    current = state["state"]
    
    # 1. 긴급 탈출 (On 상태, 매일)
    if current == "On" and indicators["deviation"] <= -0.10:
        actions.append({
            "type": "EMERGENCY_EXIT",
            "urgency": "CRITICAL",
            "message": f"★ 긴급 탈출! QQQ 편차 {indicators['deviation_pct']:+.2f}% (≤-10%)",
            "action": "TQQQ+XLU 전량 매도 → DBMF 매수",
            "new_state": "Off",
        })
        return actions  # 긴급 탈출은 즉시 반환
    
    # 2. 골든크로스 Entry (Off 상태, 매일)
    if current == "Off" and indicators["deviation"] >= 0.01 and indicators["golden_cross"]:
        actions.append({
            "type": "GOLDEN_CROSS_ENTRY",
            "urgency": "HIGH",
            "message": f"★ 골든크로스 Entry! 편차 {indicators['deviation_pct']:+.2f}%, SMA50>SMA200",
            "action": "DBMF 전량 매도 → TQQQ+XLU 매수",
            "new_state": "On",
        })
        return actions
    
    # 3. 월말 체크 (매월 마지막 거래일)
    if is_month_end:
        if current == "On" and not indicators["above_sma200"]:
            actions.append({
                "type": "MONTHLY_OFF",
                "urgency": "NORMAL",
                "message": f"월말 Off 전환. QQQ={indicators['close']:.2f} < SMA200={indicators['sma200']:.2f}",
                "action": "TQQQ+XLU 전량 매도 → DBMF 매수",
                "new_state": "Off",
            })
        elif current == "Off" and indicators["above_sma200"]:
            actions.append({
                "type": "MONTHLY_ON",
                "urgency": "NORMAL",
                "message": f"월말 On 전환. QQQ={indicators['close']:.2f} > SMA200={indicators['sma200']:.2f}",
                "action": "DBMF 전량 매도 → TQQQ+XLU+GLD 매수",
                "new_state": "On",
            })
    
    # 4. 일일 리포트 (액션 없어도)
    if not actions:
        actions.append({
            "type": "DAILY_STATUS",
            "urgency": "INFO",
            "message": (f"[{current}] QQQ={indicators['close']:.2f}, "
                       f"SMA200={indicators['sma200']:.2f}, "
                       f"편차={indicators['deviation_pct']:+.2f}%, "
                       f"RSI={indicators['rsi']:.1f}, "
                       f"GC={'✓' if indicators['golden_cross'] else '✗'}"),
            "action": "유지",
            "new_state": current,
        })
    
    return actions

def is_last_trading_day():
    """오늘이 월말 마지막 거래일인지 판단 (근사)."""
    today = date.today()
    # 다음 거래일이 다음 달이면 오늘이 마지막
    import calendar
    _, last_day = calendar.monthrange(today.year, today.month)
    remaining = last_day - today.day
    # 주말 제외 남은 거래일 수 추정
    remaining_trading = sum(1 for d in range(today.day + 1, last_day + 1)
                          if date(today.year, today.month, d).weekday() < 5)
    return remaining_trading == 0

def main():
    print(f"=== H 전략 시그널 체크 ({datetime.now():%Y-%m-%d %H:%M}) ===\n")
    
    state = load_state()
    close = get_qqq_data()
    indicators = compute_indicators(close)
    is_me = is_last_trading_day()
    
    print(f"현재 상태: {state['state']}")
    print(f"QQQ: {indicators['close']:.2f}")
    print(f"SMA200: {indicators['sma200']:.2f}")
    print(f"SMA50: {indicators['sma50']:.2f}")
    print(f"편차: {indicators['deviation_pct']:+.2f}%")
    print(f"RSI(14): {indicators['rsi']:.1f}")
    print(f"골든크로스: {'✓' if indicators['golden_cross'] else '✗'}")
    print(f"월말: {'✓' if is_me else '✗'}")
    print()
    
    actions = check_signals(state, indicators, is_month_end=is_me)
    
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
        if action["new_state"] != state["state"]:
            old = state["state"]
            state["state"] = action["new_state"]
            state["last_action"] = action["type"]
            state["last_check"] = datetime.now().isoformat()
            save_state(state)
            print(f"  → 상태 변경: {old} → {action['new_state']}")
        
        # 로그 기록
        log_signal(
            datetime.now().isoformat(),
            action["type"],
            f"{state['state']},{indicators['close']:.2f},{indicators['sma200']:.2f},"
            f"{indicators['sma50']:.2f},{indicators['deviation_pct']:+.2f},"
            f"{indicators['rsi']:.1f},{action['action']}"
        )
    
    # 알림 발송 (CRITICAL/HIGH만)
    for action in actions:
        if action["urgency"] in ("CRITICAL", "HIGH"):
            send_alert(action)

def send_alert(action):
    """알림 발송 — 텔레그램/카카오톡/이메일 중 선택.
    
    아래는 텔레그램 예시. 실제 토큰/챗ID는 환경변수로 관리.
    """
    # import requests
    # BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    # CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
    # text = f"{action['message']}\n\n행동: {action['action']}"
    # requests.post(
    #     f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
    #     json={"chat_id": CHAT_ID, "text": text}
    # )
    print(f"  [알림 발송] {action['message']}")

if __name__ == "__main__":
    main()
```

### 3.3 스케줄링

#### cron (Linux/Mac)

```bash
# 매일 장 마감 후 (EST 16:00 = KST 06:00 다음날)
0 6 * * 1-5 cd /path/to/bot && python signal_checker.py >> signal.log 2>&1
```

#### Windows Task Scheduler

```
트리거: 매일 06:00 (KST)
동작: python C:\Projects\signal_bot\signal_checker.py
조건: 네트워크 연결 시에만
```

#### GitHub Actions (무료 서버리스)

```yaml
# .github/workflows/signal-check.yml
name: H Strategy Signal Check
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
      - run: pip install yfinance pandas numpy
      - run: python signal_checker.py
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
```

---

## 4. 알림 채널 설정

### 4.1 텔레그램 (추천)

```python
import os, requests

def send_telegram(message, urgency="INFO"):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    
    # 긴급도별 이모지
    prefix = {"CRITICAL": "🚨", "HIGH": "⚡", "NORMAL": "📋", "INFO": "ℹ️"}
    text = f"{prefix.get(urgency, '')} {message}"
    
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    )
```

**설정 방법:**
1. @BotFather에서 봇 생성 → 토큰 획득
2. 봇에 메시지 전송 후 `getUpdates`로 chat_id 확인
3. 환경변수 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` 설정

### 4.2 카카오톡 (한국 사용자)

카카오 비즈니스 API 또는 카카오톡 나에게 보내기 API 활용.
REST API Key + 리프레시 토큰 필요.

### 4.3 이메일 (가장 단순)

```python
import smtplib
from email.mime.text import MIMEText

def send_email(subject, body):
    msg = MIMEText(body)
    msg["Subject"] = f"[H전략] {subject}"
    msg["From"] = os.environ["EMAIL_FROM"]
    msg["To"] = os.environ["EMAIL_TO"]
    
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(os.environ["EMAIL_FROM"], os.environ["EMAIL_APP_PASSWORD"])
        s.send_message(msg)
```

---

## 5. 상태 관리

### 5.1 signal_state.json

```json
{
  "state": "On",
  "last_check": "2026-04-22T06:00:00",
  "last_action": "MONTHLY_ON",
  "last_action_date": "2026-04-01",
  "phase2_triggered": false,
  "phase2_trigger_date": null,
  "total_equity_estimate": 150000000,
  "exit_count": 2,
  "entry_count": 3
}
```

### 5.2 signal_log.csv

```csv
date,signal_type,state,qqq_close,sma200,sma50,deviation,rsi,action
2026-04-22T06:00:00,DAILY_STATUS,On,485.32,465.10,475.20,+4.35,52.3,유지
2026-04-10T06:00:00,GOLDEN_CROSS_ENTRY,On,472.15,460.80,462.30,+2.46,61.5,DBMF매도→TQQQ+XLU매수
```

---

## 6. 모니터링 대시보드 (선택)

### 6.1 일일 리포트 형식

```
══════════════════════════════════
  H 전략 일일 리포트 (2026-04-22)
══════════════════════════════════
  상태: 🟢 On
  
  QQQ     : $485.32
  SMA200  : $465.10  (편차 +4.35%)
  SMA50   : $475.20  (GC: ✓)
  RSI(14) : 52.3
  
  ── 임계치 거리 ──
  긴급 탈출: $418.59 (-13.8%)  ← 안전
  GCE 진입: N/A (On 상태)
  
  ── 이번 달 ──
  마지막 거래일: 4/30
  상태 변경 예상: 없음
  
  ── 올해 ──
  Exit: 1회 (2026-03-20)
  Entry: 1회 (2026-04-10 GCE)
══════════════════════════════════
```

### 6.2 주간 요약 (매주 금요일)

```python
def weekly_summary():
    """주간 요약 — 주요 지표 추이."""
    close = get_qqq_data(lookback_days=30)
    
    # 이번 주 수익률
    week_start = close.iloc[-5] if len(close) >= 5 else close.iloc[0]
    week_return = (close.iloc[-1] / week_start - 1) * 100
    
    # 편차 추이 (위험 접근 여부)
    sma200 = close.rolling(200).mean()
    dev_series = ((close - sma200) / sma200 * 100).dropna()
    
    return {
        "week_return": week_return,
        "current_deviation": float(dev_series.iloc[-1]),
        "min_deviation_week": float(dev_series.iloc[-5:].min()),
        "trend": "상승" if dev_series.iloc[-1] > dev_series.iloc[-5] else "하락",
    }
```

---

## 7. 연간 체크리스트 자동화

### 7.1 매년 1월 첫 거래일 — Phase 2 이전

```python
def check_annual_transfer(state):
    """매년 1월: Phase 2 이전 여부 체크."""
    if not state.get("phase2_triggered"):
        return None
    
    # 전년 Phase 1 수익 계산 (브로커 API 또는 수동 입력)
    last_year_profit = state.get("last_year_phase1_profit", 0)
    
    if last_year_profit > 0:
        transfer = last_year_profit * 0.50
        return {
            "type": "ANNUAL_TRANSFER",
            "message": f"매년 이전: Phase 1 수익 {last_year_profit:,.0f}원의 50% = {transfer:,.0f}원",
            "action": f"Phase 1에서 {transfer:,.0f}원 매도 → SCHD 50% + DIVO 50% 매수",
        }
    else:
        return {
            "type": "ANNUAL_SKIP",
            "message": f"전년 Phase 1 수익 없음 (손실). 이전 없음.",
            "action": "Phase 1 기준값만 갱신",
        }
```

### 7.2 DCA 알림

```python
def check_dca_reminder(state):
    """매월 첫 거래일: DCA 적립 알림."""
    today = date.today()
    months_invested = state.get("months_invested", 0)
    
    if months_invested < 40:
        amount = 3_000_000
        source = "월급 200만 + SGOV 100만"
    else:
        amount = 2_000_000
        source = "월급 200만"
    
    return {
        "type": "DCA_REMINDER",
        "message": f"DCA 적립: {amount:,.0f}원 ({source})",
        "month": months_invested + 1,
    }
```

---

## 8. 에러 처리 및 장애 대응

### 8.1 데이터 수집 실패

```python
import time

def get_qqq_data_safe(retries=3, delay=60):
    """재시도 로직 포함 데이터 수집."""
    for attempt in range(retries):
        try:
            close = get_qqq_data()
            if len(close) < 200:
                raise ValueError(f"데이터 부족: {len(close)}일 (200일 필요)")
            return close
        except Exception as e:
            if attempt < retries - 1:
                print(f"재시도 {attempt+1}/{retries}: {e}")
                time.sleep(delay)
            else:
                send_alert({
                    "urgency": "HIGH",
                    "message": f"⚠ 데이터 수집 실패 ({retries}회 시도): {e}. 수동 체크 필요.",
                })
                raise
```

### 8.2 핵심 안전 규칙

1. **알림 실패 시 수동 체크**: 알림이 안 오면 직접 QQQ 차트 확인
2. **상태 파일 백업**: 매일 signal_state.json을 클라우드에 백업
3. **이중 알림**: 긴급(CRITICAL/HIGH)은 텔레그램 + 이메일 동시 발송
4. **주말/휴일 무시**: 거래일에만 체크 (is_trading_day 함수 추가)
5. **수동 오버라이드**: 상태를 수동으로 변경할 수 있는 명령어 제공

---

## 9. 확장 — Phase 2 트리거 모니터링

### 9.1 총자산 추적

```python
def check_trigger(state, broker_api=None):
    """총자산 2억 도달 체크 — 연말(12월 말) 자산 집계 시 확인.
    매일 체크 불필요. 매년 1월 리밸런싱 시 함께 확인."""
    if state.get("phase2_triggered"):
        return None
    
    # 브로커 API로 총자산 조회 (또는 수동 입력)
    total_equity = state.get("total_equity_estimate", 0)
    
    trigger = 200_000_000
    progress = total_equity / trigger * 100
    
    if total_equity >= trigger:
        return {
            "type": "TRIGGER_REACHED",
            "urgency": "HIGH",
            "message": f"★ 2억 트리거 도달! 총자산 {total_equity/1e8:.2f}억",
            "action": "Phase 2 전환 시작 — 운용가이드 6장 참조",
        }
    
    # 90% 이상이면 근접 알림
    if progress >= 90:
        return {
            "type": "TRIGGER_APPROACHING",
            "urgency": "NORMAL",
            "message": f"트리거 근접: {total_equity/1e8:.2f}억 ({progress:.1f}%)",
        }
    
    return None
```

---

## 10. 시그널 검증 — 과거 정확도

### 10.1 14.4Y 실데이터 검증 결과

| 시그널 | 발동 횟수 | CAGR 기여 | 비고 |
|--------|----------|----------|------|
| 월말 On/Off | ~33회 | 기본 수익 | SMA200 시그널 |
| 긴급 탈출 (편차-10%) | 3회 | MDD 방어 | 2018, 2020, 2022 |
| 골든크로스 Entry | 4회 | +1.30%p | V자 캐치 |

### 10.2 Bootstrap 1000경로 결과

| 지표 | F2D3 (Exit만) | F2D3+GCE | Δ |
|------|-------------|----------|---|
| FIRE 중위 | 14.27년 | **14.10년** | **-0.17년** |
| 20년 총자산 | 42.66억 | **44.70억** | **+2.04억** |
| 성공률 | 96.6% | **96.9%** | +0.3%p |
| MDD ≤-40% | 0.1% | 0.5% | +0.4%p |

---

## 11. 파일 구조

```
signal_bot/
├── signal_checker.py      # 메인 시그널 체커
├── signal_state.json      # 현재 상태 (On/Off, 마지막 액션)
├── signal_log.csv         # 시그널 이력
├── config.py              # 설정 (알림 채널, 임계치)
├── notifiers/
│   ├── telegram.py        # 텔레그램 알림
│   ├── email_notify.py    # 이메일 알림
│   └── kakao.py           # 카카오톡 알림
├── requirements.txt       # yfinance, pandas, requests
└── .github/
    └── workflows/
        └── signal-check.yml  # GitHub Actions 스케줄
```

---

## 12. 면책 고지

- 본 봇은 **알림 목적**이며 투자 조언이 아닙니다.
- 자동 매매 기능은 의도적으로 제외되었습니다.
- 시그널은 과거 검증 결과이며 미래 성과를 보장하지 않습니다.
- 최종 매매 판단은 사용자 본인의 책임입니다.
- yfinance 데이터는 지연될 수 있으며, 중요 판단 시 브로커 실시간 데이터로 확인하세요.

---

*BlackRabbit LAB · SIGNAL_ALERT_BOT_GUIDE v1 · 2026-04-22*
*H 전략 Phase 1: F2D3 + 골든크로스 Entry 기준*

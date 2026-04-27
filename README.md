# BRIS-v1 시그널 알림 봇

F2D3 + GCE + PRE(VIX35) 기준 · Phase 1 자동 알림 시스템

## 개요

BRIS-v1의 매매 시그널을 자동 감지하고 Discord로 알림을 발송합니다.
직접 매매를 실행하지 않으며, **알림만 보내고 사용자가 판단·실행**하는 구조입니다.

## 시그널 체계

```
On 상태: TQQQ 30% + XLU 15% + GLD 55%
Off 상태: DBMF 45% + GLD 55%
```

| 시그널 | 조건 | 체크 빈도 | 긴급성 |
|--------|------|----------|--------|
| 긴급 탈출 (D3) | On + QQQ 편차 ≤ -10% | 매일 | CRITICAL |
| **PRE Entry** | **Off + 편차 ≤ -10% + VIX > 35 + VIX drop ≥ 5** | **매일** | **CRITICAL** |
| PRE 가격 Exit | PRE 보유 중 + QQQ < 진입가 | 매일 | CRITICAL |
| 골든크로스 Entry | Off + 편차 ≥ +1% + SMA50>SMA200 | 매일 | HIGH |
| PRE 자동 해제 | PRE 20일+ 보유 + 편차 > 0 + 비월말 | 매일 | INFO |
| 월말 Off | On + QQQ < SMA200 | 매월 마지막 거래일 | NORMAL |
| 월말 On | Off + QQQ > SMA200 | 매월 마지막 거래일 | NORMAL |

**우선순위**: PRE 가격 Exit > 긴급 탈출 > PRE Entry > GCE > PRE 자동 해제 > 월말 체크

## 설정

### 1. Discord Webhook

1. Discord 서버 → 채널 설정 → 연동 → 웹훅 → 새 웹훅 생성
2. 웹훅 URL 복사

### 2. GitHub Secret

Repository → Settings → Secrets → Actions → New repository secret:

| Secret | 값 |
|--------|---|
| `DISCORD_WEBHOOK_URL` | Discord 웹훅 URL |

### 3. 자동 실행

GitHub Actions가 매일 평일 UTC 21:00 (EST 16:00, KST 06:00)에 자동 실행됩니다.
수동 실행: Actions 탭 → "BRIS-v1 Signal Check" → Run workflow

## 파일 구조

```
├── signal_checker.py      # 메인 시그널 체커
├── config.py              # 설정 (임계치, 색상, 포트폴리오)
├── notifiers/
│   └── discord.py         # Discord 웹훅 알림
├── signal_state.json      # 현재 상태 (자동 업데이트)
├── requirements.txt       # 의존성
├── tests/
│   └── test_signal_checker.py
└── .github/workflows/
    └── signal-check.yml   # GitHub Actions
```

## 로컬 실행

```bash
pip install -r requirements.txt
python signal_checker.py
```

## 면책

본 봇은 알림 목적이며 투자 조언이 아닙니다.
최종 매매 판단은 사용자 본인의 책임입니다.

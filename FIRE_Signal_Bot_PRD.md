# FIRE Signal Bot — 프로젝트 지침서

## 1. 프로젝트 개요

QQQ ETF의 200일 단순이동평균선(SMA) 크로스오버를 자동으로 감지하고, 시그널 변경 시 사용자에게 알림을 보내는 봇이다. GitHub Actions를 활용하여 서버 비용 없이 운영한다.

### 배경

"2단계 FIRE 투자전략"은 매월 1회 QQQ의 200일 이동평균선만 확인하면 된다. 이 체크를 자동화하여 시그널 변경 시에만 알림을 받는 것이 이 프로젝트의 목표이다.

### 투자 전략 요약

| 시그널 | 조건 | Phase 1 (LTF 성장전략) | Phase 2 (배당추세 안정전략) |
|---|---|---|---|
| RISK-ON | QQQ 종가 > QQQ 200일 SMA | TQQQ 25% + QQQ 55% + GLD 20% | SCHD 100% |
| RISK-OFF | QQQ 종가 ≤ QQQ 200일 SMA | GLD 50% + BIL 50% | GLD 50% + BIL 50% |

---

## 2. 기능 요구사항

### 2.1 핵심 기능: 시그널 체크

- QQQ의 최근 종가와 200일 단순이동평균(SMA)을 비교한다
- 종가 > SMA → `RISK_ON`, 종가 ≤ SMA → `RISK_OFF`
- 이전 시그널과 비교하여 변경 여부를 판단한다
- 시그널 상태를 파일(state.json)에 저장하여 다음 실행 시 비교에 사용한다

### 2.2 알림

- 시그널이 변경될 때만 알림을 전송한다 (매일 보내지 않음)
- 알림에 포함할 정보:
  - 시그널 방향 (RISK_ON 또는 RISK_OFF)
  - QQQ 현재가, 200일 SMA 값, 이격도(%)
  - Phase 1, Phase 2 각각의 포트폴리오 액션
- 알림 채널: Discord Webhook (메인)
  - Discord Webhook URL 하나만 설정하면 됨
  - Embed 형태로 보기 좋게 전송
  - 시그널 변경 = 빨간/초록 Embed, 월간 리포트 = 파란 Embed

### 2.3 정기 리포트 (선택 기능)

- 매월 1일에 현재 상태 요약 리포트 전송
- 포함 내용: 현재 시그널, QQQ 가격, 200일선과의 이격도, 마지막 시그널 변경일, 해당 시그널 유지 기간

### 2.4 상태 관리

- `state.json` 파일에 마지막 시그널, 체크 일자, 가격, SMA 값 등을 저장
- GitHub repo에 자동 커밋하여 이력 추적 가능
- 커밋 메시지 형식: `Signal: RISK_ON (2025-04-07)` 또는 `Check: RISK_ON, no change (2025-04-07)`

---

## 3. 기술 스펙

### 3.1 실행 환경

- GitHub Actions (ubuntu-latest)
- Python 3.11+
- 외부 라이브러리 최소화 (가능하면 표준 라이브러리만 사용)

### 3.2 가격 데이터 소스

- Yahoo Finance 비공식 API 사용
- Endpoint: `https://query1.finance.yahoo.com/v8/finance/chart/{ticker}`
- 파라미터: `period1` (UNIX timestamp, 시작일), `period2` (종료일), `interval=1d`
- User-Agent 헤더 필수
- 대안: yfinance 라이브러리 (pip install 필요, 더 안정적)
- 최소 250일(약 1년) 데이터를 가져와서 200일 SMA 계산에 충분한 데이터 확보

### 3.3 SMA 계산

- 단순이동평균(Simple Moving Average) = 최근 200 거래일 종가의 산술평균
- 종가(Adjusted Close) 기준
- 소수점 둘째 자리까지 반올림

### 3.4 GitHub Actions 워크플로우

- 스케줄: 매일 평일(월~금) UTC 22:00 실행 (한국시간 오전 7:00, 미국 장 마감 후)
- cron 표현식: `0 22 * * 1-5`
- 수동 실행(workflow_dispatch) 지원
- 권한: contents write (state.json 커밋용)

### 3.5 Secrets (환경변수)

| Secret 이름 | 용도 | 필수 여부 |
|---|---|---|
| `DISCORD_WEBHOOK_URL` | Discord 채널 Webhook URL | 필수 |

Webhook URL 형식: `https://discord.com/api/webhooks/{webhook_id}/{webhook_token}`

### 3.6 Discord Webhook API

- Endpoint: Webhook URL로 POST 요청
- Content-Type: `application/json`
- Body: Discord Embed 객체를 포함한 JSON
- Rate Limit: 분당 30회 (충분)
- 인증 불필요 (URL 자체가 인증 역할)

Discord Embed 구조:
```json
{
  "embeds": [{
    "title": "제목",
    "description": "본문",
    "color": 3066993,
    "fields": [
      { "name": "필드명", "value": "값", "inline": true }
    ],
    "footer": { "text": "푸터" },
    "timestamp": "2025-04-07T00:00:00Z"
  }]
}
```

Embed 색상 코드:
- RISK-ON (초록): `3066993` (hex: `#2ECC71`)
- RISK-OFF (빨강): `15158332` (hex: `#E74C3C`)
- 월간 리포트 (파랑): `3447003` (hex: `#3498DB`)
- 에러 (노랑): `16776960` (hex: `#FFFF00`)

---

## 4. 데이터 모델

### state.json

```json
{
  "signal": "RISK_ON",
  "last_check": "2025-04-07",
  "last_price": 480.25,
  "last_sma": 455.30,
  "diff_pct": 5.5,
  "last_change": "2025-03-15"
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| signal | string | 현재 시그널: `RISK_ON` 또는 `RISK_OFF` 또는 `null`(최초) |
| last_check | string | 마지막 체크 날짜 (YYYY-MM-DD) |
| last_price | float | 마지막 체크 시 QQQ 종가 |
| last_sma | float | 마지막 체크 시 200일 SMA |
| diff_pct | float | 이격도 (%) |
| last_change | string | 마지막 시그널 변경 날짜 |

---

## 5. 알림 메시지 형식 (Discord Embed)

### 시그널 변경: RISK-ON 전환

```json
{
  "embeds": [{
    "title": "🟢 RISK-ON 전환!",
    "description": "QQQ가 200일 이동평균선을 상향 돌파했습니다.\n**포트폴리오 조정이 필요합니다.**",
    "color": 3066993,
    "fields": [
      { "name": "QQQ 종가", "value": "$480.25", "inline": true },
      { "name": "200일 SMA", "value": "$455.30", "inline": true },
      { "name": "이격도", "value": "+5.5%", "inline": true },
      { "name": "Phase 1 (LTF 성장전략)", "value": "TQQQ 25% + QQQ 55% + GLD 20%", "inline": false },
      { "name": "Phase 2 (배당추세 안정전략)", "value": "SCHD 100%", "inline": false }
    ],
    "footer": { "text": "FIRE Signal Bot" },
    "timestamp": "2025-04-07T22:00:00Z"
  }]
}
```

### 시그널 변경: RISK-OFF 전환

```json
{
  "embeds": [{
    "title": "🔴 RISK-OFF 전환!",
    "description": "QQQ가 200일 이동평균선을 하향 이탈했습니다.\n**포트폴리오 조정이 필요합니다.**",
    "color": 15158332,
    "fields": [
      { "name": "QQQ 종가", "value": "$420.10", "inline": true },
      { "name": "200일 SMA", "value": "$455.30", "inline": true },
      { "name": "이격도", "value": "-7.7%", "inline": true },
      { "name": "Phase 1 (LTF 성장전략)", "value": "GLD 50% + BIL 50%", "inline": false },
      { "name": "Phase 2 (배당추세 안정전략)", "value": "GLD 50% + BIL 50%", "inline": false }
    ],
    "footer": { "text": "FIRE Signal Bot" },
    "timestamp": "2025-04-07T22:00:00Z"
  }]
}
```

### 월간 리포트

```json
{
  "embeds": [{
    "title": "📊 월간 FIRE 시그널 리포트",
    "description": "2025년 4월 정기 리포트",
    "color": 3447003,
    "fields": [
      { "name": "현재 시그널", "value": "🟢 RISK-ON", "inline": true },
      { "name": "시그널 유지", "value": "23일째", "inline": true },
      { "name": "마지막 전환", "value": "2025-03-15", "inline": true },
      { "name": "QQQ", "value": "$480.25", "inline": true },
      { "name": "200일 SMA", "value": "$455.30", "inline": true },
      { "name": "이격도", "value": "+5.5%", "inline": true },
      { "name": "이번 달 액션", "value": "없음 (시그널 유지 중)", "inline": false }
    ],
    "footer": { "text": "FIRE Signal Bot • 매월 1일 자동 발송" },
    "timestamp": "2025-04-01T00:00:00Z"
  }]
}
```

### 에러 발생 시

```json
{
  "embeds": [{
    "title": "⚠️ 시그널 체크 실패",
    "description": "Yahoo Finance API 요청에 실패했습니다. 수동으로 확인이 필요합니다.",
    "color": 16776960,
    "fields": [
      { "name": "에러 내용", "value": "HTTP 503 Service Unavailable", "inline": false },
      { "name": "재시도", "value": "3회 시도 후 실패", "inline": true }
    ],
    "footer": { "text": "FIRE Signal Bot" }
  }]
}
```

---

## 6. 프로젝트 구조

```
fire-signal-bot/
├── check_signal.py          # 메인 시그널 체크 로직
├── state.json               # 시그널 상태 저장 (자동 업데이트)
├── README.md                # 프로젝트 설명 및 설정 가이드
├── .gitignore
└── .github/
    └── workflows/
        └── signal-check.yml # GitHub Actions 워크플로우
```

---

## 7. 처리 흐름

```
[GitHub Actions 스케줄 트리거 (매일 평일 22:00 UTC)]
    ↓
[check_signal.py 실행]
    ↓
[Yahoo Finance API로 QQQ 가격 데이터 250일분 가져오기]
    ↓  ← 실패 시 3회 재시도, 최종 실패 시 에러 Embed 전송
[200일 SMA 계산]
    ↓
[현재 종가 vs SMA 비교 → 시그널 판단]
    ↓
[state.json에서 이전 시그널 로드]
    ↓
[시그널 변경 여부 판단]
    ├── 변경됨 → Discord Webhook으로 Embed 전송 (초록 or 빨강)
    └── 변경 안됨 → 로그만 출력 (매월 1일이면 월간 리포트 Embed 전송)
    ↓
[state.json 업데이트]
    ↓
[state.json을 git commit & push]
```

### GitHub Actions 워크플로우 핵심 단계

```yaml
steps:
  - checkout
  - setup python
  - run check_signal.py (outputs: signal, changed, price, sma 등)
  - commit & push state.json
  - if changed == true → Discord webhook POST (시그널 변경 Embed)
  - if 매월 1일 → Discord webhook POST (월간 리포트 Embed)
```

Discord Webhook 호출은 curl로 충분하다:
```bash
curl -H "Content-Type: application/json" \
  -d '{"embeds":[{...}]}' \
  $DISCORD_WEBHOOK_URL
```

---

## 8. 에러 처리

- Yahoo Finance API 요청 실패 시: 3회 재시도 (5초 간격), 실패 시 에러 알림 전송
- 가격 데이터 부족 (200일 미만) 시: 에러 로그 출력, 알림 미전송
- 알림 전송 실패 시: GitHub Actions 로그에 에러 기록 (워크플로우 실패로 표시)
- state.json 파싱 실패 시: 초기 상태로 리셋 (signal = null)

---

## 9. 설정 가이드 (README에 포함)

### Discord Webhook 생성 방법
1. Discord 서버에서 알림 받을 채널 선택
2. 채널 설정(톱니바퀴) > 연동(Integrations) > 웹훅(Webhooks)
3. "새 웹훅" 클릭 → 이름을 "FIRE Signal Bot"으로 설정
4. "웹훅 URL 복사" 클릭
5. GitHub 저장소 > Settings > Secrets > Actions > New repository secret
6. Name: `DISCORD_WEBHOOK_URL`, Value: 복사한 URL 붙여넣기

### 전용 채널 추천 구성
- `#fire-signal` : 시그널 변경 알림 전용 (알림 ON)
- 선택: `#fire-monthly` : 월간 리포트용 (별도 webhook으로 분리 가능)

---

## 10. 테스트

- Actions 탭 > workflow_dispatch로 수동 실행하여 즉시 테스트 가능
- 최초 실행 시 state.json의 signal이 null이므로 "변경됨"으로 판단되지 않음 (첫 실행은 상태 저장만)
- 테스트용으로 시그널 변경을 시뮬레이션하려면 state.json의 signal을 수동으로 반대값으로 변경 후 실행

---

## 11. 확장 아이디어 (선택)

- VIX 지수 함께 표시 (공포 수준 참고용)
- 200일선 접근 경고: 이격도 2% 이내일 때 사전 알림
- 포트폴리오 가치 추적: 초기 투자금 입력 후 현재 가치 계산
- 웹 대시보드: GitHub Pages로 현재 상태 표시하는 정적 페이지 생성
- 다중 SMA: 50일, 100일, 200일선 동시 표시
- SCHD 배당 정보: 최근 배당금, 배당 성장률, 예상 연배당 수입 함께 표시

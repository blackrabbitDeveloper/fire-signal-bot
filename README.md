# FIRE Signal Bot

QQQ ETF의 200일 단순이동평균선(SMA) 크로스오버를 자동 감지하고, Discord로 알림을 보내는 봇입니다.

## 투자 전략

### F전략 (월말 SMA 체크)

| 시그널 | 조건 | F1 (보수적) | F2 (공격적) | Phase 2 |
|---|---|---|---|---|
| RISK-ON | QQQ 종가 > 200일 SMA | TQQQ 30% + XLU 15% + GLD 55% | TQQQ 30% + XLU 15% + GLD 55% | SCHD 50% + DIVO 50% |
| RISK-OFF | QQQ 종가 <= 200일 SMA | DBMF 30% + XLU 15% + GLD 55% | DBMF 45% + GLD 55% | GLD 50% + BIL 50% |

### D3 긴급 탈출 (일일 체크)

| 조건 | 행동 |
|---|---|
| QQQ 이격도 <= -10% (RISK-ON 상태일 때) | TQQQ/XLU 전량 매도 → DBMF 매수, GLD 유지 → **DBMF 45% + GLD 55%** |

- bktlib Bootstrap 1000경로 검증으로 MDD <= -40% 경험 확률 8.0% → 3.6%로 반감
- 월 내 1회만 발동, 복귀는 월말 SMA 체크에서만 처리
- 실행 시점: 다음 거래일 시가

## 작동 방식

1. **평일 매일** (KST 06:00) GitHub Actions가 자동 실행
2. 휴장일이면 자동 스킵 (Yahoo Finance 데이터 기반 판별)
3. 매 거래일: D3 긴급 탈출 체크 (QQQ 이격도 -10% 이하 시 발동)
4. 월말 마지막 거래일: 월간 SMA 크로스오버 체크 + 리포트 전송
5. Actions 탭에서 수동 실행으로 언제든 즉시 확인 가능

## 설정 방법

### 1. Discord Webhook 생성

1. Discord 서버에서 알림 받을 채널 선택
2. 채널 설정 > 연동(Integrations) > 웹훅(Webhooks)
3. "새 웹훅" 클릭 → 이름을 "FIRE Signal Bot"으로 설정
4. "웹훅 URL 복사"

### 2. GitHub Secret 등록

1. GitHub 저장소 > Settings > Secrets and variables > Actions
2. "New repository secret" 클릭
3. Name: `DISCORD_WEBHOOK_URL`, Value: 복사한 Webhook URL

### 3. 테스트 실행

Actions 탭 > "FIRE Signal Check" > "Run workflow" 클릭으로 수동 테스트

## 프로젝트 구조

```
fire-signal-bot/
├── check_signal.py              # 메인 로직 (F전략 + D3 긴급 탈출)
├── state.json                   # 시그널 상태 (자동 업데이트)
├── .github/workflows/
│   └── signal-check.yml         # 통합 워크플로우 (평일 매일)
└── tests/
    ├── test_check_signal.py     # 유닛 테스트 (41개)
    └── test_daily_escape_smoke.py # 과거 데이터 스모크 테스트
```

## 로컬 개발

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

### CLI 사용법

```bash
python check_signal.py              # 통합 실행 (거래일 체크 → D3 → 월말)
python check_signal.py --dry-run    # 콘솔 확인만 (상태 변경/알림 없음)
python check_signal.py --daily      # D3 긴급 탈출만 단독 실행
```

## 알림 예시

- **시그널 변경**: RISK-ON/OFF 전환 Embed (포트폴리오 액션 포함)
- **긴급 탈출**: D3 발동 Embed (매도/매수 지시, 최종 포트폴리오)
- **월간 리포트**: 파란 Embed (현재 상태 요약)
- **에러**: 노란 Embed (수동 확인 필요)

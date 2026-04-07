# 🔥 FIRE Signal Bot

QQQ ETF의 200일 단순이동평균선(SMA) 크로스오버를 자동 감지하고, Discord로 알림을 보내는 봇입니다.

## 투자 전략

| 시그널 | 조건 | Phase 1 (LTF 성장전략) | Phase 2 (배당추세 안정전략) |
|---|---|---|---|
| 🟢 RISK-ON | QQQ 종가 > 200일 SMA | TQQQ 25% + QQQ 55% + GLD 20% | SCHD 100% |
| 🔴 RISK-OFF | QQQ 종가 ≤ 200일 SMA | GLD 50% + BIL 50% | GLD 50% + BIL 50% |

## 작동 방식

1. 매월 1일(KST 07:00) GitHub Actions가 자동 실행
2. Yahoo Finance에서 QQQ 가격 데이터를 가져와 200일 SMA 계산
3. 시그널 변경 시 전환 알림, 유지 시 월간 리포트를 Discord로 전송
4. Actions 탭에서 수동 실행으로 언제든 즉시 확인 가능

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
├── check_signal.py          # 메인 시그널 체크 로직
├── state.json               # 시그널 상태 (자동 업데이트)
├── .github/workflows/
│   └── signal-check.yml     # GitHub Actions 워크플로우
└── tests/
    └── test_check_signal.py # 유닛 테스트
```

## 로컬 개발

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

## 알림 예시

- **시그널 변경**: 🟢/🔴 Embed (포트폴리오 액션 포함)
- **월간 리포트**: 📊 파란 Embed (현재 상태 요약)
- **에러**: ⚠️ 노란 Embed (수동 확인 필요)

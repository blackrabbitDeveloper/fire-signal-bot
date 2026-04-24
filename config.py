"""H 전략 시그널 봇 설정."""

# ── 임계치 (변경 금지 — Bootstrap 검증 완료) ──
EMERGENCY_EXIT_THRESHOLD = -0.10   # 편차 ≤ -10% → 긴급 탈출
GOLDEN_CROSS_ENTRY_THRESHOLD = 0.01  # 편차 ≥ +1% AND SMA50>SMA200 → GCE 진입

# ── PRE (Panic Rebound Entry) 임계치 ──
PRE_VIX_THRESHOLD = 40.0       # VIX > 40
PRE_VIX_DROP_THRESHOLD = 5.0   # VIX 5일 drop ≥ 5
PRE_VIX_DROP_LOOKBACK = 5      # VIX drop 계산 룩백 (거래일)
PRE_COOLDOWN = 60              # PRE 재발동 쿨다운 (거래일)
PRE_MONTHLY_COOLDOWN = 20      # PRE 진입 후 월말 체크 비활성 기간 (거래일)

# ── SMA 기간 ──
SMA200_PERIOD = 200
SMA50_PERIOD = 50
RSI_PERIOD = 14

# ── 데이터 ──
TICKER = "QQQ"
VIX_TICKER = "^VIX"
LOOKBACK_DAYS = 300  # 200일 SMA 계산에 충분한 여유

# ── 포트폴리오 ──
PORTFOLIO_ON = "TQQQ 30% + XLU 15% + GLD 55%"
PORTFOLIO_OFF = "DBMF 45% + GLD 55%"

# ── Discord Embed 색상 ──
COLOR_CRITICAL = 15158332  # red — 긴급 탈출
COLOR_HIGH = 15105570      # orange — GCE 진입
COLOR_NORMAL = 3066993     # green — 월말 On
COLOR_OFF = 10070709       # grey — 월말 Off
COLOR_INFO = 3447003       # blue — 일일 리포트
COLOR_ERROR = 16776960     # yellow — 에러
COLOR_PRE = 10181046       # purple — PRE 진입/퇴장

# ── 재시도 ──
MAX_RETRIES = 3
RETRY_DELAY = 60  # seconds

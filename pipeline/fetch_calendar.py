"""
fetch_calendar.py — "이번 주 일정+실적" 캘린더 (data/calendar.json 재료)

두 소스를 합쳐 오늘부터 +14일 이벤트만 반환:
  A. 경제지표/회의 — econ_calendar_*.json (정적 연간 일정, 연 1회 채록.
     출처/채록일은 각 파일 "sources" 참조. 실시간 스크래핑보다 유지보수 우위)
  B. 관심종목 실적 — yfinance get_earnings_dates (이선엽 체인 관심종목,
     실패/미제공 종목은 skip. yfinance 어닝일은 확정 전 추정치일 수 있음)

규격은 CONTRACT.md "calendar.json" 참조.
"""

import glob
import json
import logging
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

PIPELINE_DIR = Path(__file__).parent

# 캘린더 조회 범위: 오늘부터 +14일
CALENDAR_DAYS = 14

# 실적 관심종목 — 이선엽 체인 (framework §7) + 메모리/AI/전력·조선 바스켓.
# (ticker, 표시명, importance)
EARNINGS_WATCHLIST = [
    ("005930.KS", "삼성전자",       "high"),
    ("000660.KS", "SK하이닉스",     "high"),
    ("MU",        "마이크론",       "high"),
    ("NVDA",      "엔비디아",       "high"),
    ("TSM",       "TSMC",          "high"),
    ("MSFT",      "마이크로소프트", "mid"),
    ("AMZN",      "아마존",         "mid"),
    ("GOOGL",     "알파벳",         "mid"),
    ("META",      "메타",           "mid"),
    ("ORCL",      "오라클",         "mid"),
    ("034020.KS", "두산에너빌리티", "mid"),
    ("010120.KS", "LS일렉트릭",     "mid"),
    ("267260.KS", "HD현대일렉트릭", "mid"),
    ("009540.KS", "HD한국조선해양", "mid"),
    ("042660.KS", "한화오션",       "mid"),
]


def _load_econ_events() -> list[dict]:
    """정적 연간 일정 파일(econ_calendar_*.json) 전부 로드.
    이듬해 파일을 추가하면 자동 포함 (연말 +14일이 해를 넘겨도 안전)."""
    events: list[dict] = []
    for path in sorted(glob.glob(str(PIPELINE_DIR / "econ_calendar_*.json"))):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            events.extend(data.get("events", []))
        except Exception as e:
            logger.warning(f"[CALENDAR] {Path(path).name} 로드 실패 → skip: {e}")
    return events


def _next_earnings_date(ticker: str) -> date | None:
    """yfinance에서 다음 실적발표일(현지 거래소 기준 날짜) 1개.
    get_earnings_dates 우선, 비면 Ticker.calendar 폴백. 둘 다 없으면 None."""
    import pandas as pd
    import yfinance as yf

    tz = "Asia/Seoul" if ticker.endswith((".KS", ".KQ")) else "America/New_York"
    tk = yf.Ticker(ticker)
    today = date.today()

    # 1순위: get_earnings_dates — 미래 날짜 포함, tz-aware 타임스탬프
    try:
        ed = tk.get_earnings_dates(limit=8)
        if ed is not None and len(ed):
            future = sorted(
                ts.tz_convert(tz).date()
                for ts in ed.index
                if ts.tz_convert(tz).date() >= today
            )
            if future:
                return future[0]
    except Exception as e:
        logger.debug(f"[CALENDAR] {ticker} get_earnings_dates 실패: {e}")

    # 2순위: Ticker.calendar (과거 날짜가 남아있는 경우도 있어 미래만)
    try:
        cal = tk.calendar or {}
        future = sorted(d for d in (cal.get("Earnings Date") or []) if d >= today)
        if future:
            return future[0]
    except Exception as e:
        logger.debug(f"[CALENDAR] {ticker} calendar 실패: {e}")

    return None


def fetch_calendar_events() -> dict:
    """오늘~+14일 이벤트 목록. 반환: {"events": [...], "earnings_ok": [...], "earnings_skip": [...]}"""
    today = date.today()
    end = today + timedelta(days=CALENDAR_DAYS)
    events: list[dict] = []

    # A. 경제지표/회의 (정적 일정)
    for ev in _load_econ_events():
        try:
            d = date.fromisoformat(ev["date"])
        except (KeyError, ValueError):
            continue
        if today <= d <= end:
            events.append({
                "date": ev["date"],
                "type": ev.get("type", "지표"),
                "label": ev.get("label", ""),
                "importance": ev.get("importance", "mid"),
            })

    # B. 관심종목 실적 (yfinance — 종목별 실패는 skip, 전체는 계속)
    earnings_ok: list[str] = []
    earnings_skip: list[str] = []
    for ticker, name, importance in EARNINGS_WATCHLIST:
        try:
            d = _next_earnings_date(ticker)
        except Exception as e:
            logger.warning(f"[CALENDAR] {ticker} 실적일 조회 실패 → skip: {e}")
            earnings_skip.append(ticker)
            continue
        if d is None:
            earnings_skip.append(ticker)
            continue
        earnings_ok.append(f"{ticker}={d.isoformat()}")
        if today <= d <= end:
            events.append({
                "date": d.isoformat(),
                "type": "실적",
                "label": f"{name} 실적",
                "ticker": ticker,
                "importance": importance,
            })

    # 정렬: 날짜 → 중요도(high 먼저) → 타입(회의→지표→실적) → 라벨
    imp_order = {"high": 0, "mid": 1}
    type_order = {"회의": 0, "지표": 1, "실적": 2}
    events.sort(key=lambda e: (
        e["date"],
        imp_order.get(e.get("importance"), 2),
        type_order.get(e.get("type"), 3),
        e.get("label", ""),
    ))

    return {"events": events, "earnings_ok": earnings_ok, "earnings_skip": earnings_skip}

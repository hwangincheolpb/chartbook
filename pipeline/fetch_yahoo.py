"""
fetch_yahoo.py — Yahoo Finance 데이터 수집 모듈
yfinance를 사용해 S&P500, KOSPI, VIX, 섹터 ETF 데이터를 가져온다.
API 키 불필요.
"""

import logging
from datetime import datetime, timedelta, date
from typing import Any

import pandas as pd
import yfinance as yf
import pytz

logger = logging.getLogger(__name__)

KST = pytz.timezone("Asia/Seoul")


def _now_kst() -> str:
    """현재 시각을 KST ISO8601 문자열로 반환."""
    return datetime.now(KST).strftime("%Y-%m-%dT%H:%M:%S+09:00")


def _download(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    """
    yfinance로 가격 데이터를 다운로드한다.
    MultiIndex 컬럼을 안전하게 처리한다.
    """
    raw = yf.download(
        tickers,
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
        threads=True,
    )

    # MultiIndex 처리: (field, ticker) → ticker별 Close만 추출
    if isinstance(raw.columns, pd.MultiIndex):
        # 레벨0 = 필드명, 레벨1 = 티커
        close = raw["Close"].copy()
    else:
        # 단일 티커인 경우 Close 컬럼만
        close = raw[["Close"]].copy()
        if len(tickers) == 1:
            close.columns = tickers

    # 날짜 인덱스를 문자열로 정규화
    close.index = pd.to_datetime(close.index).normalize()
    close = close.sort_index()

    # NaN 행 제거
    close = close.dropna(how="all")

    return close


def _series_to_pairs(series: pd.Series) -> list[list]:
    """pandas Series → [[YYYY-MM-DD, value], ...] 리스트."""
    pairs = []
    for idx, val in series.items():
        if pd.isna(val):
            continue
        date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
        pairs.append([date_str, round(float(val), 4)])
    return pairs


def fetch_sp500(lookback_years: int = 6, eps_pairs: list[list] | None = None) -> dict[str, Any]:
    """
    S&P 500 밸류에이션 밴드 차트.

    eps_pairs(multpl EPS TTM, [["YYYY-MM-DD", eps], ...])가 주어지면:
      S&P 500 지수 + EPS×15/18/21 밴드 3선 (승격판).
    eps_pairs가 없으면(multpl 수집 실패):
      기존 S&P 500 + 200D MA로 폴백 — 차트가 죽지 않게 유지.
    """
    end = datetime.today()
    start = end - timedelta(days=lookback_years * 365 + 210)  # MA200 폴백 계산용 여유분

    logger.info("S&P 500 데이터 수집 중...")
    close_df = _download(["^GSPC"], start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))

    sp500 = close_df["^GSPC"] if "^GSPC" in close_df.columns else close_df.iloc[:, 0]
    sp500 = sp500.dropna()

    cutoff = (end - timedelta(days=lookback_years * 365)).strftime("%Y-%m-%d")
    sp500_trimmed = sp500[sp500.index >= cutoff]
    logger.info(f"  S&P 500: {len(sp500_trimmed)}개 데이터 포인트")

    if eps_pairs:
        # ─── 밸류에이션 밴드 (EPS×15/18/21) ───────────────────
        eps_window = [p for p in eps_pairs if p[0] >= cutoff]
        if eps_window:
            latest_index_date = sp500_trimmed.index[-1].strftime("%Y-%m-%d")
            last_eps_date, last_eps = eps_window[-1][0], eps_window[-1][1]
            # EPS는 발표 지연 → 마지막 값을 최신 지수 날짜까지 연장(밴드가 현재에 닿게)
            extended = list(eps_window)
            if latest_index_date > last_eps_date:
                extended.append([latest_index_date, last_eps])

            def band(mult: float) -> list[list]:
                return [[d, round(v * mult, 2)] for d, v in extended]

            logger.info(
                f"  EPS 밴드: {len(extended)}개 포인트 (마지막 EPS {last_eps} @ {last_eps_date})"
            )
            return {
                "id": "sp500",
                "type": "timeseries",
                "title": "S&P 500 밸류에이션 밴드",
                "subtitle": "지수 vs EPS(TTM)×15/18/21",
                "source": "Yahoo Finance + multpl.com",
                "unit": "index",
                "updated": _now_kst(),
                "note": (
                    "[C2 버블 판별] 지수 레벨이 아니라 무엇이 밀어올리는가를 본다. EPS 밴드(15/18/21x) "
                    "안의 상승 = 실적장, 21x 상단을 이탈한 멀티플 단독 확장 = 드림장 전환 — 탈출 신호가 "
                    "아니라 국면 전환 신호다. ±5% 안팎의 지수 등락 = 노이즈, 판정은 밴드 위치라는 구조로만. "
                    "→ 행동: 밴드 내 실적장에선 보유·변동 스킵, 상단 이탈 시 매도가 아니라 드림장 규칙"
                    "(심리 역지표 감시)으로 교체. "
                    "[출처] 이선엽 프레임워크 C2 (Bull vs Bubble 판별 체인) + multpl.com EPS(TTM). "
                    "[한계] EPS는 월별·약 1분기 지연 — 최근 구간 밴드는 마지막 EPS를 연장한 근사. "
                    "15/18/21배는 역사 평균대 고정 배수(포워드 아님)."
                ),
                "series": [
                    {"name": "S&P 500", "data": _series_to_pairs(sp500_trimmed)},
                    {"name": "밴드 하단 (15x)", "data": band(15)},
                    {"name": "밴드 중앙 (18x)", "data": band(18)},
                    {"name": "밴드 상단 (21x)", "data": band(21)},
                ],
            }
        logger.warning("  EPS 데이터가 조회 기간과 겹치지 않음 → 200D MA 폴백")
    else:
        logger.warning("  EPS 데이터 없음(multpl 실패) → 200D MA 폴백")

    # ─── 폴백: 기존 S&P 500 + 200D MA ─────────────────────────
    ma200 = sp500.rolling(window=200, min_periods=200).mean().dropna()
    ma200_trimmed = ma200[ma200.index >= cutoff]
    logger.info(f"  200D MA: {len(ma200_trimmed)}개 데이터 포인트")

    return {
        "id": "sp500",
        "type": "timeseries",
        "title": "S&P 500",
        "subtitle": "200일 이동평균 (EPS 밴드 수집 실패 → 폴백)",
        "source": "Yahoo Finance",
        "unit": "index",
        "updated": _now_kst(),
        "series": [
            {"name": "S&P 500", "data": _series_to_pairs(sp500_trimmed)},
            {"name": "200D MA", "data": _series_to_pairs(ma200_trimmed)},
        ],
    }


def fetch_kospi(lookback_years: int = 6) -> dict[str, Any]:
    """
    KOSPI (^KS11) + KOSDAQ (^KQ11) 일별 종가 수집.
    Returns timeseries JSON dict.
    """
    end = datetime.today()
    start = end - timedelta(days=lookback_years * 365 + 5)

    logger.info("KOSPI/KOSDAQ 데이터 수집 중...")
    close_df = _download(["^KS11", "^KQ11"], start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))

    series_list = []
    for ticker, name in [("^KS11", "KOSPI"), ("^KQ11", "KOSDAQ")]:
        if ticker in close_df.columns:
            s = close_df[ticker].dropna()
            logger.info(f"  {name}: {len(s)}개 데이터 포인트")
            series_list.append({"name": name, "data": _series_to_pairs(s)})
        else:
            logger.warning(f"  {ticker} 데이터 없음, 건너뜀")

    return {
        "id": "kospi",
        "type": "timeseries",
        "title": "KOSPI / KOSDAQ",
        "subtitle": "종합주가지수",
        "source": "Yahoo Finance",
        "unit": "index",
        "updated": _now_kst(),
        "series": series_list,
    }


def fetch_vix(lookback_years: int = 6) -> dict[str, Any]:
    """
    VIX (^VIX) 일별 종가 수집.
    Returns timeseries JSON dict.
    """
    end = datetime.today()
    start = end - timedelta(days=lookback_years * 365 + 5)

    logger.info("VIX 데이터 수집 중...")
    close_df = _download(["^VIX"], start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))

    vix = close_df["^VIX"] if "^VIX" in close_df.columns else close_df.iloc[:, 0]
    vix = vix.dropna()

    logger.info(f"  VIX: {len(vix)}개 데이터 포인트")

    return {
        "id": "vix",
        "type": "timeseries",
        "title": "VIX 공포지수",
        "subtitle": "CBOE Volatility Index",
        "source": "Yahoo Finance",
        "unit": "index",
        "updated": _now_kst(),
        "note": (
            "[C2 버블 판별] 불안감이 살아있는 동안엔 버블이 아니다 — 공포 게이지는 역지표. "
            "임계값: 15 미만 = 공포소멸 경계(버블 진입 감시), 30 이상 = 패닉 구간. 스파이크의 반복 "
            "자체는 강세장의 노이즈, 장기 저변동에 과열 심리가 겹칠 때가 구조 신호. "
            "→ 행동: 공포 잔존 시 보유 유지, 15 미만 장기화에 '무조건 사' 심리가 겹치면 단계적 매도 준비. "
            "[출처] 이선엽 프레임워크 §7-6 (공포 역설, C2 버블 판별 보조). "
            "[한계] VIX 단독 표시 — 원 스펙의 KOSPI 2축 오버레이는 미적용. 15/30 기준선은 chartbook "
            "운영 기준(프레임워크 원 수치 아님)."
        ),
        "series": [
            {"name": "VIX", "data": _series_to_pairs(vix)},
        ],
    }


def fetch_sectors() -> dict[str, Any]:
    """
    11개 SPDR 섹터 ETF의 기간별 퍼포먼스 수집.
    기간: 1D, 1W, 1M, 3M, YTD, 1Y
    Returns heatmap_perf JSON dict.
    """
    sector_map = [
        ("XLK", "Technology"),
        ("XLF", "Financials"),
        ("XLV", "Health Care"),
        ("XLE", "Energy"),
        ("XLI", "Industrials"),
        ("XLY", "Consumer Disc."),
        ("XLP", "Consumer Staples"),
        ("XLU", "Utilities"),
        ("XLB", "Materials"),
        ("XLRE", "Real Estate"),
        ("XLC", "Communication"),
    ]
    tickers = [t for t, _ in sector_map]

    # 1년치 + 여유 데이터 다운로드
    end = datetime.today()
    start = end - timedelta(days=400)

    logger.info("섹터 ETF 데이터 수집 중...")
    close_df = _download(tickers, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    logger.info(f"  다운로드 완료: {close_df.shape[0]}일 × {close_df.shape[1]}개 ETF")

    today = close_df.index[-1]  # 가장 최근 거래일
    today_dt = pd.Timestamp(today)

    def get_price_on_or_before(ticker: str, target_dt: pd.Timestamp) -> float | None:
        """특정 날짜 이전 가장 가까운 거래일 종가 반환."""
        if ticker not in close_df.columns:
            return None
        col = close_df[ticker].dropna()
        past = col[col.index <= target_dt]
        if past.empty:
            return None
        return float(past.iloc[-1])

    def calc_perf(ticker: str, ref_dt: pd.Timestamp) -> float | None:
        """ref_dt 시점 대비 현재 수익률 (%)."""
        current = get_price_on_or_before(ticker, today_dt)
        past = get_price_on_or_before(ticker, ref_dt)
        if current is None or past is None or past == 0:
            return None
        return round((current / past - 1) * 100, 2)

    # YTD 기준일: 직전 연도말 (12월 31일)
    ytd_ref = pd.Timestamp(f"{today_dt.year - 1}-12-31")

    items = []
    for ticker, name in sector_map:
        perf = {}

        # 1D: 전 거래일 대비
        col = close_df[ticker].dropna() if ticker in close_df.columns else pd.Series(dtype=float)
        if len(col) >= 2:
            perf["1D"] = round((float(col.iloc[-1]) / float(col.iloc[-2]) - 1) * 100, 2)
        else:
            perf["1D"] = None

        # 1W: 5 거래일 전
        ref_1w = today_dt - timedelta(days=7)
        perf["1W"] = calc_perf(ticker, ref_1w)

        # 1M: 1개월 전
        ref_1m = today_dt - pd.DateOffset(months=1)
        perf["1M"] = calc_perf(ticker, ref_1m)

        # 3M: 3개월 전
        ref_3m = today_dt - pd.DateOffset(months=3)
        perf["3M"] = calc_perf(ticker, ref_3m)

        # YTD: 전년도 12월 31일 대비
        perf["YTD"] = calc_perf(ticker, ytd_ref)

        # 1Y: 1년 전
        ref_1y = today_dt - pd.DateOffset(years=1)
        perf["1Y"] = calc_perf(ticker, ref_1y)

        # None 값 제거 (데이터 없는 기간)
        perf_clean = {k: v for k, v in perf.items() if v is not None}

        logger.info(f"  {ticker} ({name}): {perf_clean}")
        items.append({"name": name, "ticker": ticker, "perf": perf_clean})

    return {
        "id": "sectors",
        "type": "heatmap_perf",
        "title": "섹터 퍼포먼스",
        "source": "Yahoo Finance (SPDR ETFs)",
        "updated": _now_kst(),
        "periods": ["1D", "1W", "1M", "3M", "YTD", "1Y"],
        "items": items,
    }


# ─── 채권/금리 ─────────────────────────────────────────────────
# 주의: yahoo 금리 지수(^IRX/^FVX/^TNX/^TYX)는 값이 10배로 옴.
#       예) 10Y 4.25% → ^TNX = 42.5. 따라서 모두 ÷10 해서 % 단위로 저장.

# 만기 라벨 → yahoo 티커 매핑 (CONTRACT 채권/금리 표 기준)
_UST_TICKERS = {
    "3M": "^IRX",   # 13주 T-Bill
    "5Y": "^FVX",   # 5년 국채
    "10Y": "^TNX",  # 10년 국채
    "30Y": "^TYX",  # 30년 국채
}
_YIELD_SCALE = 10.0  # yahoo 금리 지수 → 실제 % 변환 계수


def _yield_divisor(series: pd.Series) -> float:
    """
    yahoo 금리 지수의 스케일을 감지해 ÷10 적용 여부를 결정한다.

    CONTRACT/요구사항: yahoo는 금리를 10배로 줌(^TNX 42.5 = 4.25%) → ÷10.
    그러나 yfinance 버전에 따라 이미 실제 %(^TNX 4.25)로 주는 경우가 있다.
    이 경우 무조건 ÷10 하면 0.42% 같은 비현실적 값이 나온다.

    → 최근 값의 크기로 판단: 중앙값이 20 이상이면 ×10 스케일로 보고 ÷10,
      그 미만(이미 % 단위)이면 그대로 사용. 결과는 항상 실제 % (~0-6%대).
    """
    recent = series.dropna()
    if recent.empty:
        return 1.0
    med = float(recent.tail(60).median())
    return _YIELD_SCALE if med >= 20 else 1.0


def _fetch_ust_close(lookback_years: int = 6) -> pd.DataFrame:
    """
    미국채 금리 4종(3M/5Y/10Y/30Y)을 다운로드해 실제 % 단위로 반환.
    yahoo가 ×10 스케일로 주면 ÷10, 이미 % 단위면 그대로 (자동 감지).
    컬럼명은 만기 라벨("3M","5Y","10Y","30Y").
    """
    end = datetime.today()
    start = end - timedelta(days=lookback_years * 365 + 10)

    tickers = list(_UST_TICKERS.values())
    close_df = _download(tickers, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))

    # 티커 컬럼 → 만기 라벨로 rename + 스케일 보정
    out = pd.DataFrame(index=close_df.index)
    for label, ticker in _UST_TICKERS.items():
        if ticker in close_df.columns:
            col = close_df[ticker]
            divisor = _yield_divisor(col)
            out[label] = col / divisor
        else:
            logger.warning(f"  국채 금리 {label}({ticker}) 데이터 없음")
    return out


def fetch_ust_yields(lookback_years: int = 6) -> dict[str, Any]:
    """
    미국채 금리 추이: 3M·5Y·10Y·30Y 4개 시리즈 (÷10 적용한 실제 %).
    Returns timeseries JSON dict.
    """
    logger.info("미국채 금리(3M/5Y/10Y/30Y) 데이터 수집 중...")
    df = _fetch_ust_close(lookback_years)

    series_list = []
    for label in ["3M", "5Y", "10Y", "30Y"]:
        if label in df.columns:
            s = df[label].dropna()
            logger.info(f"  {label}: {len(s)}개 데이터 포인트 (최신 {round(float(s.iloc[-1]), 2)}%)")
            series_list.append({"name": label, "data": _series_to_pairs(s)})

    return {
        "id": "ust_yields",
        "type": "timeseries",
        "title": "미국채 금리",
        "subtitle": "3M · 5Y · 10Y · 30Y",
        "source": "Yahoo Finance",
        "unit": "%",
        "updated": _now_kst(),
        "series": series_list,
    }


def fetch_yield_spread(lookback_years: int = 6) -> dict[str, Any]:
    """
    10Y-3M 스프레드 = (^TNX - ^IRX)/10. 같은 날짜로 정렬 후 계산.
    마이너스 = 장단기 역전(침체 신호).
    Returns timeseries JSON dict.
    """
    logger.info("10Y-3M 스프레드 데이터 수집 중...")
    df = _fetch_ust_close(lookback_years)

    # 10Y, 3M 둘 다 존재하는 날짜만 (inner join)
    pair_df = df[["10Y", "3M"]].dropna()
    spread = (pair_df["10Y"] - pair_df["3M"])

    logger.info(f"  10Y-3M: {len(spread)}개 데이터 포인트 (최신 {round(float(spread.iloc[-1]), 2)}%p)")

    return {
        "id": "yield_spread",
        "type": "timeseries",
        "title": "10Y-3M 스프레드",
        "subtitle": "장단기 금리차 (마이너스=역전)",
        "source": "Yahoo Finance",
        "unit": "%",
        "updated": _now_kst(),
        "note": (
            "[C1 금리 정점] 장단기 역전이 나타나기 전까지 금리로 걱정할 일은 없다. "
            "임계값: 0%p — 단기금리가 10Y를 넘어서는 역전 = 급격긴축 신호, 정상권(플러스) 유지 = "
            "금리 레벨 자체는 무시. "
            "→ 행동: 정상권에선 금리 뉴스에 반응하지 않기, 역전 발생 시 서서히 탈출 준비. "
            "[출처] 이선엽 프레임워크 §2-C1 금리 4조건 판별 중 역전 항목. "
            "[한계] 원 규격은 2Y-10Y(FRED T10Y2Y), 이 차트는 10Y-3M — 역전 판정 방향은 같으나 "
            "발생 시점이 다를 수 있음."
        ),
        "series": [
            {"name": "10Y-3M", "data": _series_to_pairs(spread)},
        ],
    }


def fetch_yield_curve(lookback_years: int = 6) -> dict[str, Any]:
    """
    수익률 곡선 스냅샷: "현재"(최신 영업일) vs "1년 전"(~365일 전 직전 영업일).
    만기 순서: 3M, 5Y, 10Y, 30Y. 모두 ÷10 적용된 실제 %.
    Returns curve_snapshot JSON dict.
    """
    logger.info("수익률 곡선 스냅샷 데이터 수집 중...")
    df = _fetch_ust_close(lookback_years)

    maturities = ["3M", "5Y", "10Y", "30Y"]

    def snapshot_on_or_before(target: pd.Timestamp) -> list[list]:
        """target 날짜 이하 가장 가까운 영업일의 만기별 yield 페어 리스트."""
        data = []
        for label in maturities:
            if label not in df.columns:
                continue
            col = df[label].dropna()
            past = col[col.index <= target]
            if past.empty:
                continue
            data.append([label, round(float(past.iloc[-1]), 4)])
        return data

    # "현재" = 가장 최근 영업일
    latest_dt = df.dropna(how="all").index[-1]
    current_snap = snapshot_on_or_before(latest_dt)

    # "1년 전" = 365일 전 직전 영업일
    one_year_ago = latest_dt - timedelta(days=365)
    past_snap = snapshot_on_or_before(one_year_ago)

    logger.info(f"  현재({latest_dt.date()}): {current_snap}")
    logger.info(f"  1년 전(~{one_year_ago.date()}): {past_snap}")

    return {
        "id": "yield_curve",
        "type": "curve_snapshot",
        "title": "미국 국채 수익률 곡선",
        "source": "Yahoo Finance",
        "unit": "%",
        "updated": _now_kst(),
        "note": "역전 여부 한눈에 (단기>장기면 침체 신호)",
        "maturities": maturities,
        "snapshots": [
            {"label": "현재", "data": current_snap},
            {"label": "1년 전", "data": past_snap},
        ],
    }


def fetch_credit_proxy(lookback_years: int = 6) -> dict[str, Any]:
    """
    크레딧 리스크 프록시 = HYG(하이일드 ETF) / LQD(투자등급 회사채 ETF) 비율.
    같은 날짜의 종가로 비율 계산. 키 불필요(yahoo).

    하락 = 하이일드가 IG 대비 언더퍼폼 = 크레딧 스트레스
    상승 = 위험선호(리스크온)
    Returns timeseries JSON dict.
    """
    end = datetime.today()
    start = end - timedelta(days=lookback_years * 365 + 10)

    logger.info("크레딧 프록시(HYG/LQD) 데이터 수집 중...")
    close_df = _download(["HYG", "LQD"], start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))

    # HYG, LQD 둘 다 존재하는 날짜만 (inner join)
    pair_df = close_df[["HYG", "LQD"]].dropna()
    ratio = (pair_df["HYG"] / pair_df["LQD"])

    logger.info(f"  HYG/LQD: {len(ratio)}개 데이터 포인트 (최신 {round(float(ratio.iloc[-1]), 4)})")

    return {
        "id": "credit_proxy",
        "type": "timeseries",
        "title": "크레딧 리스크 프록시",
        "subtitle": "HYG / LQD (하이일드 vs 투자등급)",
        "source": "Yahoo Finance",
        "unit": "ratio",
        "updated": _now_kst(),
        "note": "하락 = 하이일드 언더퍼폼 = 크레딧 스트레스 / 상승 = 위험선호",
        "series": [
            {"name": "HYG/LQD (크레딧 리스크 프록시)", "data": _series_to_pairs(ratio)},
        ],
    }


# ─── 단일 시계열 헬퍼 (환율·원자재 공용) ─────────────────────────
def _fetch_single_series(
    chart_id: str,
    tickers: list[str],
    series_name: str,
    title: str,
    subtitle: str,
    unit: str,
    note: str | None = None,
    lookback_years: int = 6,
) -> dict[str, Any]:
    """
    단일 티커의 일별 종가를 받아 단일 시리즈 timeseries JSON으로 반환.

    tickers는 폴백 리스트(순서대로 시도). 모두 빈 데이터면 ValueError를 던져
    호출부(run.py)가 graceful하게 ready:false 처리하도록 한다.
    """
    end = datetime.today()
    start = end - timedelta(days=lookback_years * 365 + 10)

    logger.info(f"{chart_id} ({'/'.join(tickers)}) 데이터 수집 중...")

    series = None
    used_ticker = None
    for ticker in tickers:
        try:
            close_df = _download([ticker], start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        except Exception as e:
            logger.warning(f"  {ticker} 다운로드 오류: {e}")
            continue
        if ticker in close_df.columns:
            col = close_df[ticker].dropna()
        elif close_df.shape[1] >= 1:
            col = close_df.iloc[:, 0].dropna()
        else:
            col = pd.Series(dtype=float)
        if not col.empty:
            series = col
            used_ticker = ticker
            break
        logger.warning(f"  {ticker} 빈 데이터 → 다음 폴백 시도")

    if series is None or series.empty:
        raise ValueError(f"{chart_id}: 모든 티커 실패 ({tickers})")

    logger.info(f"  {chart_id}: {len(series)}개 데이터 포인트 [{used_ticker}] (최신 {round(float(series.iloc[-1]), 2)})")

    out: dict[str, Any] = {
        "id": chart_id,
        "type": "timeseries",
        "title": title,
        "subtitle": subtitle,
        "source": "Yahoo Finance",
        "unit": unit,
        "updated": _now_kst(),
        "series": [
            {"name": series_name, "data": _series_to_pairs(series)},
        ],
    }
    if note:
        out["note"] = note
    return out


# ─── 환율 ─────────────────────────────────────────────────────
def fetch_usdkrw(lookback_years: int = 6) -> dict[str, Any]:
    """원/달러 환율 (KRW=X)."""
    return _fetch_single_series(
        chart_id="usdkrw",
        tickers=["KRW=X"],
        series_name="원/달러",
        title="원/달러 환율",
        subtitle="USD/KRW",
        unit="원",
        lookback_years=lookback_years,
    )


def fetch_dxy(lookback_years: int = 6) -> dict[str, Any]:
    """달러 인덱스 (DX-Y.NYB, 실패 시 ^DX-Y.NYB / DXY 폴백)."""
    return _fetch_single_series(
        chart_id="dxy",
        tickers=["DX-Y.NYB", "^DX-Y.NYB", "DXY"],
        series_name="달러 인덱스",
        title="달러 인덱스 (DXY)",
        subtitle="US Dollar Index",
        unit="index",
        lookback_years=lookback_years,
    )


# ─── 원자재 ───────────────────────────────────────────────────
def fetch_gold(lookback_years: int = 6) -> dict[str, Any]:
    """금 선물 (GC=F)."""
    return _fetch_single_series(
        chart_id="gold",
        tickers=["GC=F"],
        series_name="금 (Gold)",
        title="금 선물",
        subtitle="Gold Futures (GC=F)",
        unit="USD",
        lookback_years=lookback_years,
    )


def fetch_wti(lookback_years: int = 6) -> dict[str, Any]:
    """WTI 원유 선물 (CL=F)."""
    return _fetch_single_series(
        chart_id="wti",
        tickers=["CL=F"],
        series_name="WTI 원유",
        title="WTI 원유 선물",
        subtitle="Crude Oil Futures (CL=F)",
        unit="USD",
        note=(
            "[C1 금리 정점] 물가의 실체는 유가다. 호르무즈 프리미엄 해소(분쟁 전 레벨 복귀) = "
            "물가 정점 판정 성립, 급등 지속 = C1 반증 조건. "
            "→ 행동: 유가 안정 확인 시 금리 정점 콜 유지, 재급등 고착 시 콜 재검토. "
            "[출처] 이선엽 프레임워크 §3-C1 (호르무즈 프리미엄 규칙). "
            "[한계] WTI 근월물 선물 — 현물과 스프레드·롤오버 노이즈 존재."
        ),
        lookback_years=lookback_years,
    )


def fetch_copper(lookback_years: int = 6) -> dict[str, Any]:
    """
    구리/금 비율 (HG=F ÷ GC=F, ×1000) + 미국채 10Y(^TNX) 이중축 — 건들락 비율.
    비율 상승 = 성장 기대 → 금리 상방 압력. 승격판(기존 구리 단독 차트 대체).
    """
    end = datetime.today()
    start = end - timedelta(days=lookback_years * 365 + 10)

    logger.info("구리/금 비율 + 10Y (HG=F/GC=F, ^TNX) 데이터 수집 중...")
    close_df = _download(["HG=F", "GC=F", "^TNX"], start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))

    for t in ("HG=F", "GC=F"):
        if t not in close_df.columns:
            raise ValueError(f"copper: {t} 데이터 없음")
    pair_df = close_df[["HG=F", "GC=F"]].dropna()
    if pair_df.empty:
        raise ValueError("copper: 구리/금 공통 거래일 없음")
    ratio = pair_df["HG=F"] / pair_df["GC=F"] * 1000.0  # 가독성 위해 ×1000

    if "^TNX" not in close_df.columns:
        raise ValueError("copper: ^TNX 데이터 없음")
    tnx = close_df["^TNX"].dropna()
    tnx = tnx / _yield_divisor(tnx)

    logger.info(
        f"  구리/금(×1000): {len(ratio)}개 (최신 {round(float(ratio.iloc[-1]), 3)}) / "
        f"10Y: {len(tnx)}개 (최신 {round(float(tnx.iloc[-1]), 2)}%)"
    )

    return {
        "id": "copper",
        "type": "timeseries",
        "title": "구리/금 비율 × 미국채 10Y",
        "subtitle": "HG=F ÷ GC=F (×1000) + 10Y(%, 우축) — 건들락 비율",
        "source": "Yahoo Finance",
        "unit": "ratio(×1000)",
        "unit2": "%",
        "updated": _now_kst(),
        "note": (
            "구리/금 비율은 채권시장보다 정직한 성장 온도계다(건들락). 비율이 꺾이는데 금리만 오르면 "
            "그 금리는 실체 없는 수급 노이즈 — 금리 정점 논거가 강해진다. "
            "[출처] Jeffrey Gundlach 구리/금→10Y 프레임 + 이선엽 프레임워크 C1(금리 정점 체인) 보조. "
            "[한계] 근월물 선물 비율(HG=F÷GC=F, ×1000 스케일) — 롤오버 노이즈 존재. "
            "좌우 축 스케일이 달라 교차 시점 자체는 참고용."
        ),
        "series": [
            {"name": "구리/금 비율 (×1000)", "data": _series_to_pairs(ratio), "yAxis": 0},
            {"name": "미국채 10Y", "data": _series_to_pairs(tnx), "yAxis": 1},
        ],
    }



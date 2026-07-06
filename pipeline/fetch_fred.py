"""
fetch_fred.py — FRED (Federal Reserve Economic Data) 데이터 수집 모듈

환경변수 FRED_API_KEY 필요. 없으면 모든 FRED 차트를 건너뛴다.
이 모듈은 credit_hy_oas 차트를 담당한다.
(valuation_pe / sp500_eps는 fetch_multpl.py에서 multpl.com을 스크래핑해 처리.
 FRED에는 Shiller CAPE / S&P 500 EPS 직접 시리즈가 없기 때문.)

buffett 차트는 Valley AI 링크 카드(run.py LINK_CARDS의 valley_buffett_link)로
대체되어 비활성 (2026-07-06). fetch_buffett 함수는 재활성화 대비로 남겨둠 —
살리려면 fetch_all_fred의 fred_fetchers에 ("buffett", fetch_buffett) 복귀
+ run.py chart_meta/RETIRED_IDS 되돌리기.
"""

import logging
import os
from typing import Any

import pandas as pd
import requests
import pytz
from datetime import datetime

logger = logging.getLogger(__name__)

KST = pytz.timezone("Asia/Seoul")
FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"


def _now_kst() -> str:
    """현재 시각을 KST ISO8601 문자열로 반환."""
    return datetime.now(KST).strftime("%Y-%m-%dT%H:%M:%S+09:00")


def _get_api_key() -> str | None:
    """FRED API 키를 환경변수에서 읽는다."""
    return os.environ.get("FRED_API_KEY", "").strip() or None


def _fetch_series(series_id: str, api_key: str, observation_start: str = "1990-01-01") -> pd.Series:
    """
    FRED에서 단일 시리즈를 가져온다.
    Returns pd.Series with DatetimeIndex.
    """
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": observation_start,
        "sort_order": "asc",
    }
    resp = requests.get(FRED_BASE_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    observations = data.get("observations", [])
    if not observations:
        raise ValueError(f"FRED 시리즈 {series_id}: 데이터 없음")

    records = {}
    for obs in observations:
        val_str = obs.get("value", ".")
        if val_str == ".":  # FRED 결측치 표기
            continue
        try:
            records[obs["date"]] = float(val_str)
        except (ValueError, KeyError):
            continue

    series = pd.Series(records)
    series.index = pd.to_datetime(series.index)
    series = series.sort_index()
    return series


def _series_to_pairs(series: pd.Series) -> list[list]:
    """pandas Series → [[YYYY-MM-DD, value], ...] 리스트."""
    pairs = []
    for idx, val in series.items():
        if pd.isna(val):
            continue
        date_str = idx.strftime("%Y-%m-%d")
        pairs.append([date_str, round(float(val), 4)])
    return pairs


def _fetch_series_keyless(series_id: str, observation_start: str = "1990-01-01") -> pd.Series:
    """
    FRED 공개 CSV 엔드포인트(fredgraph.csv) — API 키 불필요.
    버블 체크리스트 차트(fed_funds, capex_margin) 전용 폴백.
    (credit_hy_oas 등 기존 FRED 차트의 '키 없으면 ready:false' 규칙은 유지 — CONTRACT 참조)
    """
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()

    records = {}
    lines = resp.text.strip().splitlines()
    for line in lines[1:]:  # 헤더: observation_date,<SERIES_ID>
        parts = line.split(",")
        if len(parts) != 2:
            continue
        date_str, val_str = parts[0].strip(), parts[1].strip()
        if val_str in (".", ""):
            continue
        if date_str < observation_start:
            continue
        try:
            records[date_str] = float(val_str)
        except ValueError:
            continue

    if not records:
        raise ValueError(f"FRED 키리스 CSV {series_id}: 데이터 없음")
    series = pd.Series(records)
    series.index = pd.to_datetime(series.index)
    return series.sort_index()


def _fetch_series_any(series_id: str, api_key: str | None,
                      observation_start: str = "1990-01-01") -> pd.Series:
    """API 키 있으면 정식 API, 없으면 fredgraph.csv 공개 CSV 폴백."""
    if api_key:
        return _fetch_series(series_id, api_key, observation_start)
    return _fetch_series_keyless(series_id, observation_start)


def fetch_buffett(api_key: str) -> dict[str, Any]:
    """
    [비활성 2026-07-06] Valley AI 링크 카드로 대체 — fetch_all_fred에서 제외됨.
    Buffett Indicator = Wilshire 5000 (WILL5000PRFC) / GDP × 100.
    두 시리즈 모두 분기별 데이터. 날짜 기준으로 inner join 후 비율 계산.
    """
    logger.info("Buffett Indicator 데이터 수집 중...")

    wilshire = _fetch_series("WILL5000PRFC", api_key, "1970-01-01")
    gdp = _fetch_series("GDP", api_key, "1970-01-01")

    logger.info(f"  WILL5000PRFC: {len(wilshire)}개 관측치")
    logger.info(f"  GDP: {len(gdp)}개 관측치")

    # 두 시리즈를 날짜 기준으로 정렬 후 inner merge
    df = pd.DataFrame({"wilshire": wilshire, "gdp": gdp}).dropna()

    # Buffett Indicator = 시총 지수 / GDP(십억달러) × 100
    # 참고: WILL5000PRFC는 1971.12.31=1411.70을 기준으로 하는 가격 인덱스.
    #       따라서 절대적인 "시총 비율"이 아닌 상대적 트렌드 지표로 해석.
    df["indicator"] = (df["wilshire"] / df["gdp"]) * 100

    ratio = df["indicator"].dropna()
    logger.info(f"  Buffett Indicator: {len(ratio)}개 데이터 포인트")

    return {
        "id": "buffett",
        "type": "timeseries",
        "title": "Buffett Indicator",
        "subtitle": "시가총액 / GDP (%)",
        "source": "FRED (WILL5000PRFC / GDP)",
        "unit": "%",
        "updated": _now_kst(),
        "note": "Wilshire 5000 Full Cap Index / Nominal GDP × 100. 분기별 데이터.",
        "series": [
            {"name": "Mkt Cap / GDP", "data": _series_to_pairs(ratio)},
        ],
    }


def fetch_credit_hy_oas(api_key: str) -> dict[str, Any]:
    """
    ICE BofA US High Yield OAS = FRED series BAMLH0A0HYM2 (일별, %).
    하이일드 크레딧 스프레드. 값이 벌어질수록 크레딧 리스크 확대.
    """
    logger.info("하이일드 OAS(BAMLH0A0HYM2) 데이터 수집 중...")

    oas = _fetch_series("BAMLH0A0HYM2", api_key, "1996-12-31")
    logger.info(f"  BAMLH0A0HYM2: {len(oas)}개 데이터 포인트")

    return {
        "id": "credit_hy_oas",
        "type": "timeseries",
        "title": "하이일드 OAS 스프레드",
        "subtitle": "ICE BofA US High Yield OAS",
        "source": "FRED (BAMLH0A0HYM2)",
        "unit": "%",
        "updated": _now_kst(),
        "note": "옵션조정 스프레드. 확대 시 크레딧 리스크·스트레스 신호.",
        "series": [
            {"name": "HY OAS", "data": _series_to_pairs(oas)},
        ],
    }


# ─── 버블 체크리스트 (김성환 "버블 템플릿" 2025-08-19) ───────────
# ④ 연준 긴축 전환 = FEDFUNDS  ⑤ 공급과잉/마진 하락 = NEWORDER YoY + CP/GDP
# 두 차트는 키 없으면 fredgraph.csv(공개 CSV, 키 불필요)로 폴백 — 상시 ready.
# 판정 배지는 run.py build_bubble()이 data/*.json에서 계산.

def fetch_fed_funds(api_key: str | None = None) -> dict[str, Any]:
    """버블 체크리스트 ④ 연준 긴축 전환 — 실효 연방기금금리(FEDFUNDS, 월간)."""
    logger.info("연방기금금리(FEDFUNDS) 수집 중...")
    ff = _fetch_series_any("FEDFUNDS", api_key, "1995-01-01")
    logger.info(f"  FEDFUNDS: {len(ff)}개 (최신 {round(float(ff.iloc[-1]), 2)}%)")

    return {
        "id": "fed_funds",
        "type": "timeseries",
        "title": "연준 기준금리 (Fed Funds)",
        "subtitle": "인하/동결=🟢 · 3개월 바닥 대비 +25bp=🟡 · 인하 사이클 후 인상 전환=🔴",
        "source": "FRED (FEDFUNDS)" + ("" if api_key else " — 공개 CSV(키리스)"),
        "unit": "%",
        "updated": _now_kst(),
        "note": (
            "[버블④ 긴축 전환] 버블을 끝내는 건 밸류에이션이 아니라 연준이다 — 1929, 2000, "
            "2022 전부 인하 사이클이 인상으로 재전환된 뒤 정점이 왔다. 인하/동결이 이어지는 동안 "
            "버블은 계속 자랄 수 있다. "
            "[출처] 김성환(신한투자증권) '버블 템플릿' 2025-08-19 "
            "[한계] FEDFUNDS는 실효금리 월평균 — 목표범위 변경(FOMC 결정)보다 표시가 완만·지연"
        ),
        "series": [
            {"name": "실효 연방기금금리", "data": _series_to_pairs(ff)},
        ],
    }


def fetch_capex_margin(api_key: str | None = None) -> dict[str, Any]:
    """
    버블 체크리스트 ⑤ 공급과잉/마진 하락 프록시.
    Capex 프록시 = 비국방자본재(항공기 제외) 신규수주 NEWORDER YoY% (월간)
    마진 프록시 = 세후 기업이익/명목GDP = CP/GDP % (분기)
    논리: '투자는 느는데 마진이 꺾인다' = 공급과잉 진입 신호.
    """
    logger.info("Capex YoY(NEWORDER) + 마진 프록시(CP/GDP) 수집 중...")
    neworder = _fetch_series_any("NEWORDER", api_key, "1995-01-01")
    cp = _fetch_series_any("CP", api_key, "1995-01-01")
    gdp = _fetch_series_any("GDP", api_key, "1995-01-01")

    capex_yoy = (neworder.pct_change(12) * 100).dropna()

    margin_df = pd.DataFrame({"cp": cp, "gdp": gdp}).dropna()
    margin = (margin_df["cp"] / margin_df["gdp"] * 100).dropna()

    cutoff = "2000-01-01"
    capex_yoy = capex_yoy[capex_yoy.index >= cutoff]
    margin = margin[margin.index >= cutoff]
    logger.info(
        f"  Capex YoY: {len(capex_yoy)}개 (최신 {round(float(capex_yoy.iloc[-1]), 1)}%) / "
        f"CP/GDP: {len(margin)}개 (최신 {round(float(margin.iloc[-1]), 2)}%)"
    )

    return {
        "id": "capex_margin",
        "type": "timeseries",
        "title": "공급과잉 프록시 (Capex vs 마진)",
        "subtitle": "Capex YoY+ 인데 마진(CP/GDP) 2분기 연속 하락=🔴 / 1분기 하락=🟡",
        "source": "FRED (NEWORDER, CP, GDP)" + ("" if api_key else " — 공개 CSV(키리스)"),
        "unit": "%",
        "unit2": "%",
        "updated": _now_kst(),
        "note": (
            "[버블⑤ 공급과잉] 버블 후반부의 공통 구조: 호황을 믿고 투자(Capex)는 계속 느는데 "
            "경쟁 심화로 마진이 먼저 꺾인다. 비국방자본재 수주 YoY가 플러스인 채로 기업이익마진 "
            "프록시(CP/GDP)가 2분기 연속 하락하면 정점 근접. "
            "[출처] 김성환(신한투자증권) '버블 템플릿' 2025-08-19 "
            "[한계] CP/GDP는 전 산업 세후이익 기준 분기·발표 지연 ~2개월. S&P500 마진과 괴리 가능"
        ),
        "markLines": [
            {"value": 0, "label": "Capex YoY 0선", "axis": 0},
        ],
        "series": [
            {"name": "비국방자본재 수주 YoY", "yAxis": 0, "data": _series_to_pairs(capex_yoy)},
            {"name": "기업이익마진 프록시 (CP/GDP)", "yAxis": 1, "data": _series_to_pairs(margin)},
        ],
    }


def fetch_all_fred() -> dict[str, dict[str, Any]]:
    """
    FRED 차트 전체를 수집한다. (credit_hy_oas 담당)
    Returns: {chart_id: result_dict or {"_skip": True, "_reason": ...}}

    FRED_API_KEY가 없거나 오류 발생 시 해당 차트를 skip 처리한다.

    참고: valuation_pe / sp500_eps는 FRED에 직접 시리즈가 없어
          fetch_multpl.py (multpl.com 스크래핑)에서 담당한다.
          buffett은 Valley AI 링크로 대체 → 비활성 (모듈 docstring 참조).
    """
    api_key = _get_api_key()
    results: dict[str, dict[str, Any]] = {}

    # FRED API 키 없으면 키 필수 차트(credit_hy_oas)는 skip (기존 규칙 유지)
    if not api_key:
        logger.warning("FRED_API_KEY 미설정 → 키 필수 FRED 차트 건너뜀 "
                       "(버블 체크리스트 fed_funds/capex_margin은 공개 CSV 폴백)")
        for cid in ("credit_hy_oas",):
            results[cid] = {
                "_skip": True,
                "_reason": "FRED_API_KEY 환경변수 미설정",
            }
        fred_fetchers = []
    else:
        # buffett은 Valley 링크 대체로 제외 (재활성화 방법은 모듈 docstring)
        fred_fetchers = [
            ("credit_hy_oas", fetch_credit_hy_oas),
        ]

    # 버블 체크리스트 FRED 차트 — 키 없어도 fredgraph.csv(공개 CSV)로 수집
    fred_fetchers += [
        ("fed_funds", fetch_fed_funds),
        ("capex_margin", fetch_capex_margin),
    ]

    for cid, fetcher in fred_fetchers:
        try:
            results[cid] = fetcher(api_key)
            logger.info(f"{cid}: 수집 완료")
        except Exception as e:
            logger.error(f"{cid} 수집 실패: {e}")
            results[cid] = {
                "_skip": True,
                "_reason": f"수집 오류: {e}",
            }

    return results

"""
fetch_fred.py — FRED (Federal Reserve Economic Data) 데이터 수집 모듈

환경변수 FRED_API_KEY 필요. 없으면 모든 FRED 차트를 건너뛴다.
이 모듈은 buffett 차트만 담당한다.
(valuation_pe / sp500_eps는 fetch_multpl.py에서 multpl.com을 스크래핑해 처리.
 FRED에는 Shiller CAPE / S&P 500 EPS 직접 시리즈가 없기 때문.)

FRED 시리즈 선택 근거:
  - buffett:      실제 FRED 시리즈 사용:
                  - WILL5000PRFC (Wilshire 5000 Full Cap Index, 분기별)
                  - GDP (Nominal GDP, 십억달러, 분기별)
                  Buffett Indicator ≈ WILL5000PRFC / GDP × 100
                  (순수 시총 달러값인 WILL5000IND 대신 PRFC 인덱스 사용.
                   절대값보다 트렌드·방향성 파악이 목적이므로 실용적으로 충분.)
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


def fetch_buffett(api_key: str) -> dict[str, Any]:
    """
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


def fetch_all_fred() -> dict[str, dict[str, Any]]:
    """
    FRED 차트 전체를 수집한다. (buffett, credit_hy_oas 담당)
    Returns: {chart_id: result_dict or {"_skip": True, "_reason": ...}}

    FRED_API_KEY가 없거나 오류 발생 시 해당 차트를 skip 처리한다.

    참고: valuation_pe / sp500_eps는 FRED에 직접 시리즈가 없어
          fetch_multpl.py (multpl.com 스크래핑)에서 담당한다.
    """
    api_key = _get_api_key()
    results: dict[str, dict[str, Any]] = {}

    # FRED API 키 없으면 모든 FRED 차트 skip
    if not api_key:
        logger.warning("FRED_API_KEY 미설정 → 모든 FRED 차트 건너뜀")
        for cid in ("buffett", "credit_hy_oas"):
            results[cid] = {
                "_skip": True,
                "_reason": "FRED_API_KEY 환경변수 미설정",
            }
        return results

    # 키가 있으면 각 차트 수집 시도 (개별 실패는 graceful skip)
    fred_fetchers = [
        ("buffett", fetch_buffett),
        ("credit_hy_oas", fetch_credit_hy_oas),
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

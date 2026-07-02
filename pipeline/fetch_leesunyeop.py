"""
fetch_leesunyeop.py — "이선엽 체인" 섹션 차트 수집 모듈

leesunyeop-framework §7(차트북 연동 스펙)의 논지 체인을 yfinance 데이터로 구현.
API 키 불필요. fetch_yahoo의 헬퍼(_download, _series_to_pairs, _yield_divisor) 재사용.

차트 목록 (id 고정):
  - ls_rate_peak     : 미10Y(^TNX) + WTI(CL=F) 이중축, markLines 4.85(CTA)/5.5(구조 경보)
  - ls_semi_vs_power : SOX vs 한국 전력기기 3사 균등 바스켓 (index100 상대강도)
  - ls_memory_cycle  : 삼성전자·SK하이닉스·마이크론 index100 3선
  - ls_taiwan_hedge  : 삼성전자 ÷ TSM 비율
  - ls_ship_defense  : 조선 바스켓(HD한국조선해양·한화오션) vs KOSPI index100
  - move_index       : ^MOVE 채권 변동성 지수

개별 fetcher는 실패 시 예외를 던진다 → run.py가 차트 단위로 격리해 ready:false 처리.
"""

import logging
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from fetch_yahoo import _download, _series_to_pairs, _yield_divisor, _now_kst

logger = logging.getLogger(__name__)

# 상대강도/지수화 차트는 최근 사이클 가독성을 위해 3년, 매크로 레벨 차트는 6년.
_REL_LOOKBACK_YEARS = 3
_MACRO_LOOKBACK_YEARS = 6


def _start_str(lookback_years: int) -> tuple[str, str]:
    end = datetime.today()
    start = end - timedelta(days=lookback_years * 365 + 10)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _index100(series: pd.Series) -> pd.Series:
    """첫 유효값=100으로 지수화."""
    s = series.dropna()
    if s.empty:
        return s
    return s / float(s.iloc[0]) * 100.0


def _basket_index100(close_df: pd.DataFrame, tickers: list[str]) -> pd.Series:
    """
    바스켓 = 각 종목 index100의 균등 평균.
    전 종목이 존재하는 첫 날짜부터 시작 (ffill로 결측 보간 후 공통 구간만).
    """
    cols = [t for t in tickers if t in close_df.columns]
    if not cols:
        raise ValueError(f"바스켓 티커 전부 실패: {tickers}")
    if len(cols) < len(tickers):
        missing = set(tickers) - set(cols)
        logger.warning(f"  바스켓 일부 티커 누락(제외하고 진행): {missing}")
    df = close_df[cols].ffill().dropna()
    if df.empty:
        raise ValueError(f"바스켓 공통 구간 없음: {tickers}")
    idx = df.apply(lambda c: c / float(c.iloc[0]) * 100.0)
    return idx.mean(axis=1)


# ─── 1. 금리 정점 체인: 10Y + WTI ────────────────────────────────
def fetch_ls_rate_peak(lookback_years: int = _MACRO_LOOKBACK_YEARS) -> dict[str, Any]:
    """미국채 10Y(^TNX, %) + WTI(CL=F, USD) 이중축. CTA 손절선 4.85% markLine."""
    start, end = _start_str(lookback_years)
    logger.info("ls_rate_peak (^TNX + CL=F) 데이터 수집 중...")
    close_df = _download(["^TNX", "CL=F"], start, end)

    if "^TNX" not in close_df.columns:
        raise ValueError("ls_rate_peak: ^TNX 데이터 없음")
    tnx = close_df["^TNX"].dropna()
    tnx = tnx / _yield_divisor(tnx)

    if "CL=F" not in close_df.columns:
        raise ValueError("ls_rate_peak: CL=F 데이터 없음")
    wti = close_df["CL=F"].dropna()

    logger.info(f"  10Y: {len(tnx)}개 (최신 {round(float(tnx.iloc[-1]), 2)}%) / WTI: {len(wti)}개")

    return {
        "id": "ls_rate_peak",
        "type": "timeseries",
        "title": "금리 정점 체인 — 10Y × 유가",
        "subtitle": "미국채 10Y(%) + WTI($, 우축) · 4.85% = CTA 손절선",
        "source": "Yahoo Finance",
        "unit": "%",
        "unit2": "USD",
        "updated": _now_kst(),
        "markLines": [
            {"value": 4.85, "label": "CTA 손절선", "axis": 0},
            {"value": 5.5, "label": "구조 경보", "axis": 0},
        ],
        "note": (
            "물가의 실체는 유가, 유가의 실체는 호르무즈. 유가가 꺾이면 지난달 물가가 고점이 되고 "
            "금리는 정점이 된다. 4.85는 CTA 손절선 — 넘으면 조정 빌미, 그 조정은 노이즈니 매수. "
            "[출처] 이선엽 프레임워크 §7-1 (금리 정점 체인 C1) — 임계선 4.85%(CTA 손절선)·5.5%(구조 경보). "
            "[한계] 10Y는 야후 ^TNX(원 스펙 FRED DGS10 대체), 유가는 WTI 근월물 선물 — 현물과 스프레드 존재."
        ),
        "series": [
            {"name": "미국채 10Y", "data": _series_to_pairs(tnx), "yAxis": 0},
            {"name": "WTI 유가", "data": _series_to_pairs(wti), "yAxis": 1},
        ],
    }


# ─── 2. 로테이션 체인: 반도체 vs 전력기기 ────────────────────────
_POWER_BASKET = ["010120.KS", "267260.KS", "034020.KS"]  # LS일렉트릭·HD현대일렉트릭·두산에너빌리티


def fetch_ls_semi_vs_power(lookback_years: int = _REL_LOOKBACK_YEARS) -> dict[str, Any]:
    """SOX(^SOX) vs 한국 전력기기 3사 균등 바스켓 — 둘 다 index100 상대강도."""
    start, end = _start_str(lookback_years)
    logger.info("ls_semi_vs_power (^SOX vs 전력기기 바스켓) 데이터 수집 중...")
    close_df = _download(["^SOX"] + _POWER_BASKET, start, end)

    if "^SOX" not in close_df.columns:
        raise ValueError("ls_semi_vs_power: ^SOX 데이터 없음")
    sox = _index100(close_df["^SOX"])
    power = _basket_index100(close_df, _POWER_BASKET)

    logger.info(f"  SOX: {len(sox)}개 / 전력기기 바스켓: {len(power)}개")

    return {
        "id": "ls_semi_vs_power",
        "type": "timeseries",
        "title": "로테이션 체인 — 반도체 vs 전력기기",
        "subtitle": f"SOX vs 한국 전력기기 3사 균등 바스켓 (기준일=100, {lookback_years}년)",
        "source": "Yahoo Finance",
        "unit": "index(=100)",
        "updated": _now_kst(),
        "note": (
            "삼성전자·하이닉스에 큰 조정이 오면 주도주는 전력·원자력으로 바뀐다. 전기가 없으면 "
            "반도체를 사도 7년간 못 돌린다. 이 선이 꺾이는 날이 로테이션 개시일. "
            "[출처] 이선엽 프레임워크 §7-4 (로테이션 체인) — 반도체 고점 대비 −20%가 트리거. "
            "[한계] 원 스펙(SOXX vs URA+GEV) 대신 SOX vs 한국 전력기기 3사(LS일렉트릭·HD현대일렉트릭·"
            "두산에너빌리티) 균등 바스켓으로 구성. 지수화 상대 비교라 환율 미조정."
        ),
        "series": [
            {"name": "SOX (필라델피아 반도체)", "data": _series_to_pairs(sox)},
            {"name": "한국 전력기기 바스켓 (3사 균등)", "data": _series_to_pairs(power)},
        ],
    }


# ─── 3. 메모리 사이클: 삼성전자·하이닉스·마이크론 ────────────────
def fetch_ls_memory_cycle(lookback_years: int = _REL_LOOKBACK_YEARS) -> dict[str, Any]:
    """005930.KS / 000660.KS / MU index100 3선."""
    start, end = _start_str(lookback_years)
    logger.info("ls_memory_cycle (삼성전자/하이닉스/마이크론) 데이터 수집 중...")
    tickers = [("005930.KS", "삼성전자"), ("000660.KS", "SK하이닉스"), ("MU", "마이크론")]
    close_df = _download([t for t, _ in tickers], start, end)

    series_list = []
    for ticker, name in tickers:
        if ticker not in close_df.columns:
            logger.warning(f"  {name}({ticker}) 데이터 없음, 건너뜀")
            continue
        s = _index100(close_df[ticker])
        if s.empty:
            continue
        logger.info(f"  {name}: {len(s)}개 (최신 {round(float(s.iloc[-1]), 1)})")
        series_list.append({"name": name, "data": _series_to_pairs(s)})

    if not series_list:
        raise ValueError("ls_memory_cycle: 모든 티커 실패")

    return {
        "id": "ls_memory_cycle",
        "type": "timeseries",
        "title": "메모리 사이클 — 삼성전자·하이닉스·마이크론",
        "subtitle": f"정규화 주가 (기준일=100, {lookback_years}년)",
        "source": "Yahoo Finance",
        "unit": "index(=100)",
        "updated": _now_kst(),
        "note": (
            "메모리는 에이전트의 기억이고 다음은 동영상이다. 마이크론이 밤에 오르면 한국 메모리는 "
            "다음날 오른다 — 이제 겨우 1회 초. "
            "[출처] 이선엽 프레임워크 §7-5 (메모리 사이클 체인). "
            "[한계] 분기 실적일 마커는 수동 주입 예정(미구현). 지수화 기준일 선택에 따라 상대 격차 착시 가능."
        ),
        "series": series_list,
    }


# ─── 4. 대만 헤지: 삼성전자/TSM 비율 ─────────────────────────────
def fetch_ls_taiwan_hedge(lookback_years: int = _REL_LOOKBACK_YEARS) -> dict[str, Any]:
    """005930.KS ÷ TSM 상대주가 비율 1선."""
    start, end = _start_str(lookback_years)
    logger.info("ls_taiwan_hedge (삼성전자/TSM) 데이터 수집 중...")
    close_df = _download(["005930.KS", "TSM"], start, end)

    for t in ("005930.KS", "TSM"):
        if t not in close_df.columns:
            raise ValueError(f"ls_taiwan_hedge: {t} 데이터 없음")

    pair = close_df[["005930.KS", "TSM"]].dropna()  # 공통 거래일만
    if pair.empty:
        raise ValueError("ls_taiwan_hedge: 공통 거래일 없음")
    ratio = pair["005930.KS"] / pair["TSM"]

    logger.info(f"  삼성전자/TSM: {len(ratio)}개 (최신 {round(float(ratio.iloc[-1]), 2)})")

    return {
        "id": "ls_taiwan_hedge",
        "type": "timeseries",
        "title": "대만 헤지 — 삼성전자 / TSM",
        "subtitle": "상대주가 비율 (지정학 프리미엄 온도계)",
        "source": "Yahoo Finance",
        "unit": "ratio",
        "updated": _now_kst(),
        "note": (
            "대만 무기판매 5년 지연 = 5년 시나리오. 대만 리스크가 커질수록 삼성전자가 반사익 — "
            "이 비율의 추세 전환이 지정학 프리미엄의 온도계. "
            "[출처] 이선엽 프레임워크 §7-7 (대만 헤지 체인). "
            "[한계] 원화/달러 표시 통화가 달라 비율의 절대 수준은 무의미 — 추세 방향만 유효. "
            "대만 이벤트 마커는 수동 주입 예정(미구현)."
        ),
        "series": [
            {"name": "삼성전자 / TSM", "data": _series_to_pairs(ratio)},
        ],
    }


# ─── 5. 조선·방산: 조선 바스켓 vs KOSPI ──────────────────────────
_SHIP_BASKET = ["009540.KS", "042660.KS"]  # HD한국조선해양·한화오션


def fetch_ls_ship_defense(lookback_years: int = _REL_LOOKBACK_YEARS) -> dict[str, Any]:
    """조선 바스켓(균등 index100) vs KOSPI(index100) 상대강도."""
    start, end = _start_str(lookback_years)
    logger.info("ls_ship_defense (조선 바스켓 vs KOSPI) 데이터 수집 중...")
    close_df = _download(_SHIP_BASKET + ["^KS11"], start, end)

    ship = _basket_index100(close_df, _SHIP_BASKET)
    if "^KS11" not in close_df.columns:
        raise ValueError("ls_ship_defense: ^KS11 데이터 없음")
    kospi = _index100(close_df["^KS11"])

    logger.info(f"  조선 바스켓: {len(ship)}개 / KOSPI: {len(kospi)}개")

    return {
        "id": "ls_ship_defense",
        "type": "timeseries",
        "title": "미 해군 재건 — 조선 바스켓 vs KOSPI",
        "subtitle": f"HD한국조선해양·한화오션 균등 vs KOSPI (기준일=100, {lookback_years}년)",
        "source": "Yahoo Finance",
        "unit": "index(=100)",
        "updated": _now_kst(),
        "note": (
            "미국은 1년에 군함 한 척, 항모 12척 중 6척이 시동 불능. 미 해군 재건의 조선소는 "
            "한국이다 — 대만이 시끄러울수록 이 선은 오른다. "
            "[출처] 이선엽 프레임워크 §7-10 (조선·방산 체인). "
            "[한계] 바스켓은 HD한국조선해양(009540)+한화오션(042660) 균등 — 원 스펙의 HD현대중공업 "
            "대신 상장 지주(한국조선해양) 사용. 美 MRO 수주 이벤트 마커는 수동 주입 예정(미구현)."
        ),
        "series": [
            {"name": "조선 바스켓 (2사 균등)", "data": _series_to_pairs(ship)},
            {"name": "KOSPI", "data": _series_to_pairs(kospi)},
        ],
    }


# ─── 6. MOVE 채권 변동성 ─────────────────────────────────────────
def fetch_move_index(lookback_years: int = _MACRO_LOOKBACK_YEARS) -> dict[str, Any]:
    """^MOVE (ICE BofA MOVE Index) 단일 시계열."""
    start, end = _start_str(lookback_years)
    logger.info("move_index (^MOVE) 데이터 수집 중...")
    close_df = _download(["^MOVE"], start, end)

    if "^MOVE" in close_df.columns:
        move = close_df["^MOVE"].dropna()
    elif close_df.shape[1] >= 1:
        move = close_df.iloc[:, 0].dropna()
    else:
        move = pd.Series(dtype=float)

    if move.empty:
        raise ValueError("move_index: ^MOVE 데이터 없음")

    logger.info(f"  MOVE: {len(move)}개 (최신 {round(float(move.iloc[-1]), 2)})")

    return {
        "id": "move_index",
        "type": "timeseries",
        "title": "MOVE 채권 변동성",
        "subtitle": "ICE BofA MOVE Index",
        "source": "Yahoo Finance",
        "unit": "index",
        "updated": _now_kst(),
        "note": (
            "금리發 주가 조정의 진원지는 채권 변동성이다. MOVE가 튀며 만든 하락은 밸류에이션 문제가 "
            "아니라 국채 수급 노이즈 — 이선엽 문법에선 매수 타이밍이다. "
            "[출처] 이선엽 프레임워크 C1 보조지표 (§7 표 외 — CTA 손절 연쇄 논리에서 유도). "
            "[한계] 야후 ^MOVE는 결측일이 있을 수 있음. ICE 원 데이터 대비 지연 가능."
        ),
        "series": [
            {"name": "MOVE", "data": _series_to_pairs(move)},
        ],
    }

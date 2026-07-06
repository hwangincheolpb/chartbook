"""
fetch_kr_flow.py — 한국 수급 데이터 수집 모듈 (섹션 "수급")

로테이션(한국 주도주 장세) 끝 판정 재료:
  - kr_foreign_flow    : 외국인/기관 KOSPI 순매수 (일별 + 외국인 20일 누적) — Naver Finance
  - kr_rotation_check  : KOSPI 지수 + 50일선 + 거래량 — Yahoo Finance (^KS11)

소스 선정 경위 (2026-07-06):
  - pykrx(1.2.x)는 KRX_ID/KRX_PW 로그인 필수화, 구버전(1.0.x)도 KRX가 익명 접근을
    차단해 빈 데이터 반환 ("LOGOUT"). data.krx.co.kr 직접 POST도 동일.
  - VKOSPI는 KRX 외 무키 소스가 없음(Naver/Daum/Yahoo 미제공) → 차트 스킵.
  - 외국인/기관 순매수는 Naver Finance 일별 표(investorDealTrendDay)로 대체.
    무키·무로그인, 단위 억원. 비공식 엔드포인트라 구조 변경 리스크 있음.

주의: KRX 영업일 기준. launchd 06:30 실행 시 당일 데이터가 아직 없으므로
      "가장 최근 영업일까지"가 자연스럽게 내려온다 (별도 처리 불필요 —
      Naver 표 자체가 영업일만 담고 있음).
"""

import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import pytz
import requests
import yfinance as yf

logger = logging.getLogger(__name__)

KST = pytz.timezone("Asia/Seoul")

# Naver Finance 투자자별 매매동향 (일별) — KOSPI(sosok=01). 페이지당 10영업일.
_NAVER_FLOW_URL = "https://finance.naver.com/sise/investorDealTrendDay.naver"
_NAVER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Referer": "https://finance.naver.com/sise/",
}

# 행 패턴: <td class="date2">26.07.06</td> 뒤로 개인/외국인/기관계(+기관 세부) td 나열
_ROW_RE = re.compile(
    r'<td class="date2">(\d{2}\.\d{2}\.\d{2})</td>((?:\s*<td[^>]*>[^<]*</td>){3})',
    re.S,
)
_NUM_RE = re.compile(r"<td[^>]*>\s*([+\-]?[\d,]+)\s*</td>")


def _now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%dT%H:%M:%S+09:00")


def _series_to_pairs(series: pd.Series) -> list[list]:
    pairs = []
    for idx, val in series.items():
        if pd.isna(val):
            continue
        date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
        pairs.append([date_str, round(float(val), 4)])
    return pairs


def _fetch_naver_investor_flow(pages: int = 16) -> pd.DataFrame:
    """
    Naver 일별 투자자 매매동향(KOSPI)을 pages장 수집 (페이지당 10영업일).
    Returns: DataFrame(index=date asc, columns=[개인, 외국인, 기관], 단위 억원)
    """
    bizdate = datetime.now(KST).strftime("%Y%m%d")  # 미래/휴일이면 Naver가 최근 영업일로 앵커
    rows: dict[str, tuple[float, float, float]] = {}

    for page in range(1, pages + 1):
        resp = requests.get(
            _NAVER_FLOW_URL,
            params={"bizdate": bizdate, "sosok": "01", "page": page},
            headers=_NAVER_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        html = resp.content.decode("euc-kr", errors="ignore")

        page_rows = _ROW_RE.findall(html)
        if not page_rows:
            logger.warning(f"  Naver 수급 p{page}: 행 없음 → 중단 (구조 변경?)")
            break
        for date_raw, tds in page_rows:
            nums = _NUM_RE.findall(tds)
            if len(nums) < 3:
                continue
            date = "20" + date_raw.replace(".", "-")  # 26.07.06 → 2026-07-06
            indiv, foreign, inst = (float(n.replace(",", "").replace("+", "")) for n in nums[:3])
            rows[date] = (indiv, foreign, inst)
        time.sleep(0.25)  # 비공식 엔드포인트 예의

    if not rows:
        raise ValueError("kr_foreign_flow: Naver 수급 표 파싱 실패 (0행)")

    df = pd.DataFrame.from_dict(rows, orient="index", columns=["개인", "외국인", "기관"])
    df.index = pd.to_datetime(df.index)
    return df.sort_index()


def fetch_kr_foreign_flow() -> dict[str, Any]:
    """
    외국인/기관 KOSPI 순매수 (일별, 억원) + 외국인 20일 누적(우축).
    로테이션 끝 1번 신호(외국인 순매도 전환 + 4주 이상 지속) 판정 재료.
    """
    logger.info("한국 수급(외국인/기관 순매수, Naver) 데이터 수집 중...")
    df = _fetch_naver_investor_flow(pages=16)  # ~160영업일 ≈ 7.5개월

    foreign_cum20 = df["외국인"].rolling(window=20, min_periods=20).sum().dropna()
    logger.info(
        f"  일별 {len(df)}개 영업일 (최신 {df.index[-1].date()} 외국인 {df['외국인'].iloc[-1]:+,.0f}억) / "
        f"20일 누적 {len(foreign_cum20)}개 (최신 {foreign_cum20.iloc[-1]:+,.0f}억)"
    )

    return {
        "id": "kr_foreign_flow",
        "type": "timeseries",
        "title": "외국인/기관 KOSPI 순매수",
        "subtitle": "일별 순매수(억원) + 외국인 20일 누적(우축)",
        "source": "Naver Finance (KRX 집계)",
        "unit": "억원",
        "unit2": "억원(20일 누적)",
        "updated": _now_kst(),
        "note": (
            "[수급] 로테이션(주도주 장세)의 연료는 외국인 순매수다. 임계값: 외국인 순매도 전환 후 "
            "4주 이상 지속 = 로테이션 끝 경보 — 하루 이틀 순매도는 노이즈, 판정은 주 단위 연속성으로만. "
            "20일 누적선(우축)이 0 아래로 내려가 머무는지 함께 본다. "
            "→ 행동: 4주 연속 순매도 확인 시 주도주 비중 축소 검토, 그 전까지 단주 매도는 노이즈. "
            "[출처] 로테이션 종료 체크리스트 (수급 3신호 중 ①) — 스냅샷 '로테이션 신호' 카드와 연동. "
            "[한계] Naver 집계(억원) 기준 — KRX 확정치와 미세 차이 가능. KRX 정보데이터시스템이 "
            "로그인 필수화되어(2026) 무키 대안으로 채택. 비공식 엔드포인트라 구조 변경 리스크."
        ),
        "markLines": [
            {"value": 0, "label": "매수/매도 분기", "axis": 0},
        ],
        "series": [
            {"name": "외국인 일별 순매수", "data": _series_to_pairs(df["외국인"]), "yAxis": 0},
            {"name": "기관 일별 순매수", "data": _series_to_pairs(df["기관"]), "yAxis": 0},
            {"name": "외국인 20일 누적", "data": _series_to_pairs(foreign_cum20), "yAxis": 1},
        ],
    }


def fetch_kr_rotation_check(lookback_years: int = 3) -> dict[str, Any]:
    """
    KOSPI 지수 + 50일선 + 거래량(우축, 백만주) — "50일선 거래량 동반 붕괴" 판정용.
    로테이션 끝 2번 신호 재료. 소스: Yahoo ^KS11 (Close+Volume).
    """
    end = datetime.today()
    start = end - timedelta(days=lookback_years * 365 + 100)  # MA50 계산 여유분

    logger.info("KOSPI 로테이션 체크(지수+50일선+거래량, ^KS11) 데이터 수집 중...")
    raw = yf.download("^KS11", start=start.strftime("%Y-%m-%d"), end=None,
                      auto_adjust=True, progress=False)
    if raw.empty:
        raise ValueError("kr_rotation_check: ^KS11 데이터 없음")
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"].iloc[:, 0]
        volume = raw["Volume"].iloc[:, 0]
    else:
        close = raw["Close"]
        volume = raw["Volume"]

    close = close.dropna()
    close.index = pd.to_datetime(close.index).normalize()
    volume = volume.dropna()
    volume.index = pd.to_datetime(volume.index).normalize()
    volume = volume[volume > 0]  # 휴일/미집계 0 방어

    ma50 = close.rolling(window=50, min_periods=50).mean().dropna()

    # yahoo ^KS11 Volume 스케일 자동 감지 → 백만주 통일
    # (천주 단위로 오면 중앙값 ~수십만, 주 단위로 오면 ~수억)
    med = float(volume.tail(60).median()) if not volume.empty else 0.0
    divisor = 1e6 if med > 5e6 else 1e3
    volume_m = volume / divisor

    cutoff = (end - timedelta(days=lookback_years * 365)).strftime("%Y-%m-%d")
    close_t = close[close.index >= cutoff]
    ma50_t = ma50[ma50.index >= cutoff]
    vol_t = volume_m[volume_m.index >= cutoff]

    logger.info(
        f"  KOSPI {len(close_t)}개 (최신 {round(float(close_t.iloc[-1]), 1)}) / 50일선 {len(ma50_t)}개 / "
        f"거래량 {len(vol_t)}개 (최신 {round(float(vol_t.iloc[-1]), 0)}백만주)"
    )

    return {
        "id": "kr_rotation_check",
        "type": "timeseries",
        "title": "KOSPI 50일선 × 거래량",
        "subtitle": "지수 + 50D MA + 거래량(백만주, 우축)",
        "source": "Yahoo Finance (^KS11)",
        "unit": "index",
        "unit2": "백만주",
        "updated": _now_kst(),
        "note": (
            "[수급] 50일선 이탈 자체가 아니라 거래량이 실리는가가 판정 기준이다. 임계값: 종가가 "
            "50일선을 하회 + 거래량 급증 동반 = 기관 이탈(디스트리뷰션) 구조 신호, 거래량 없는 이탈 = "
            "수급 공백 노이즈(복귀 관찰). "
            "→ 행동: 거래량 동반 붕괴 시 주도주 비중 축소, 무거래 이탈은 관망·낙폭 매수 후보 점검. "
            "[출처] 로테이션 종료 체크리스트 (수급 3신호 중 ②) — 오닐(W. O'Neil) 디스트리뷰션 데이 "
            "원칙 응용. [한계] ^KS11 거래량은 Yahoo 집계 — KRX 확정치와 차이 가능, 당일 장중 값은 "
            "부분 집계일 수 있음."
        ),
        "series": [
            {"name": "KOSPI", "data": _series_to_pairs(close_t), "yAxis": 0},
            {"name": "50일선", "data": _series_to_pairs(ma50_t), "yAxis": 0},
            {"name": "거래량(백만주)", "data": _series_to_pairs(vol_t), "yAxis": 1},
        ],
    }

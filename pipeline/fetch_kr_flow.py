"""
fetch_kr_flow.py — 한국 수급 데이터 수집 모듈 (섹션 "수급")

로테이션(한국 주도주 장세) 끝 판정 재료:
  - kr_foreign_flow    : 외국인/기관 KOSPI 순매수 (일별 + 외국인 20일 누적) — Naver Finance
  - kr_rotation_check  : KOSPI 지수 + 50일선 + 거래량 — Yahoo Finance (^KS11)
  - kr_fear_greed      : KOSPI 공포·탐욕 지수 (수급 가중 자체 산식, 0~100) — 위 두 소스 재사용

네트워크 절약: Naver 수급 표와 ^KS11 다운로드는 모듈 캐시(_get_flow_df/_get_ks11)로
1회만 수행하고 세 fetcher가 공유한다 (파이프라인 1회 실행 = 프로세스 1개 전제).

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


# ─── 모듈 캐시 (파이프라인 1회 실행 내 fetcher 간 데이터 공유, 이중 fetch 방지) ───
_FLOW_DF_CACHE: pd.DataFrame | None = None       # Naver 수급 (~280영업일)
_KS11_CACHE: tuple[pd.Series, pd.Series] | None = None  # (close, volume) ~3y


def _get_flow_df() -> pd.DataFrame:
    """Naver 수급 표를 1회만 수집해 캐시. 28페이지 ≈ 280영업일 ≈ 13개월
    (fear_greed 백분위 분포용 최근 1년 확보. kr_foreign_flow는 뒤 160일만 사용)."""
    global _FLOW_DF_CACHE
    if _FLOW_DF_CACHE is None:
        _FLOW_DF_CACHE = _fetch_naver_investor_flow(pages=28)
    return _FLOW_DF_CACHE


def _get_ks11(lookback_years: int = 3) -> tuple[pd.Series, pd.Series]:
    """^KS11 (close, volume)를 1회만 다운로드해 캐시 (rotation_check + fear_greed 공유)."""
    global _KS11_CACHE
    if _KS11_CACHE is None:
        end = datetime.today()
        start = end - timedelta(days=lookback_years * 365 + 100)  # MA 계산 여유분
        raw = yf.download("^KS11", start=start.strftime("%Y-%m-%d"), end=None,
                          auto_adjust=True, progress=False)
        if raw.empty:
            raise ValueError("^KS11 데이터 없음")
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
        _KS11_CACHE = (close, volume)
    return _KS11_CACHE


def fetch_kr_foreign_flow() -> dict[str, Any]:
    """
    외국인/기관 KOSPI 순매수 (일별, 억원) + 외국인 20일 누적(우축).
    로테이션 끝 1번 신호(외국인 순매도 전환 + 4주 이상 지속) 판정 재료.
    """
    logger.info("한국 수급(외국인/기관 순매수, Naver) 데이터 수집 중...")
    df = _get_flow_df().tail(160)  # ~160영업일 ≈ 7.5개월 (기존 표시 범위 유지)

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

    logger.info("KOSPI 로테이션 체크(지수+50일선+거래량, ^KS11) 데이터 수집 중...")
    close, volume = _get_ks11(lookback_years)

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


# ─────────────────────────────────────────────────────────────
# KOSPI 공포·탐욕 지수 (0~100) — 수급 가중 자체 산식
#
# 설계 원칙 (2026-03 X Research 설계 재개): 한국 시장은 외국인/기관 수급이
# 가장 중요한 요인인데 해외 F&G 구현체(CNN 등)는 이를 과소 반영한다
# → 수급 요인에 합산 55% 가중. 산식은 CONTRACT.md "수급 차트" 절에 문서화.
#
# 요인 5개 (각각 최근 1년 표본 내 백분위 0~100으로 정규화 후 가중평균):
#   ① 외국인 20일 누적 순매수 (Naver)          w=0.35  ← 최대 가중
#   ② 기관 20일 누적 순매수 (Naver)            w=0.20
#   ③ KOSPI 50일선 이격도 (^KS11)              w=0.20
#   ④ 20일 실현변동성 (^KS11, 역방향)          w=0.15  — VKOSPI 무키 부재 프록시
#   ⑤ 52주 신고가 대비 위치 (^KS11)            w=0.10
# 구간: <25 극공포 / 25~45 공포 / 45~55 중립 / 55~75 탐욕 / >75 극탐욕
# ─────────────────────────────────────────────────────────────

_FG_WEIGHTS = {"외국인": 0.35, "기관": 0.20, "모멘텀": 0.20, "변동성": 0.15, "52주": 0.10}


def fg_zone(value: float) -> str:
    """공포·탐욕 지수 구간 라벨 (snapshot 카드와 공유)."""
    if value < 25:
        return "극공포"
    if value < 45:
        return "공포"
    if value <= 55:
        return "중립"
    if value <= 75:
        return "탐욕"
    return "극탐욕"


def fetch_kr_fear_greed() -> dict[str, Any]:
    """
    KOSPI 공포·탐욕 지수 (0~100). 캐시된 Naver 수급 + ^KS11만 사용 (추가 fetch 없음).
    각 요인을 최근 1년(수급 데이터 가용 범위) 표본 내 백분위로 정규화 후 가중평균.
    """
    logger.info("KOSPI 공포·탐욕 지수(수급 가중 산식) 계산 중...")
    flow = _get_flow_df()          # ~280영업일 (Naver, 억원)
    close, _ = _get_ks11()         # ~3y (^KS11 Close)

    # ①② 수급: 20일 누적 순매수 (억원)
    frn20 = flow["외국인"].rolling(window=20, min_periods=20).sum().dropna()
    inst20 = flow["기관"].rolling(window=20, min_periods=20).sum().dropna()

    # ③ 모멘텀: 50일선 이격도 (%)
    ma50 = close.rolling(window=50, min_periods=50).mean()
    momentum = (close / ma50 - 1) * 100

    # ④ 변동성: 20일 실현변동성 (연율화 %, 역방향 — 급등 = 공포)
    rvol = close.pct_change().rolling(window=20, min_periods=20).std() * (252 ** 0.5) * 100

    # ⑤ 52주 신고가 대비 위치 (%)
    pos52 = (close / close.rolling(window=252, min_periods=200).max()) * 100

    # 정렬: 수급 20일 누적의 날짜(KRX 영업일, ~1년)를 기준 창으로 통일
    base_idx = frn20.index
    factors = pd.DataFrame({
        "외국인": frn20,
        "기관": inst20.reindex(base_idx),
        "모멘텀": momentum.reindex(base_idx, method="ffill"),
        "변동성": rvol.reindex(base_idx, method="ffill"),
        "52주": pos52.reindex(base_idx, method="ffill"),
    }).dropna()
    if len(factors) < 120:
        raise ValueError(f"kr_fear_greed: 표본 부족 ({len(factors)}일 < 120일)")

    # 백분위 정규화 (표본 = 위 창 ≈ 최근 1년) → 가중평균
    pct = factors.rank(pct=True) * 100
    pct["변동성"] = 100 - pct["변동성"]  # 변동성 급등 = 공포 쪽
    fg = sum(pct[name] * w for name, w in _FG_WEIGHTS.items()).round(1)

    last_val = float(fg.iloc[-1])
    logger.info(
        f"  {len(fg)}영업일 (최신 {fg.index[-1].date()} = {last_val:.1f} [{fg_zone(last_val)}] / "
        f"요인 백분위: " + ", ".join(f"{k} {pct[k].iloc[-1]:.0f}" for k in _FG_WEIGHTS)
    )

    return {
        "id": "kr_fear_greed",
        "type": "timeseries",
        "title": "KOSPI 공포·탐욕 지수",
        "subtitle": "수급 가중 자체 산식 (0~100) · 최근 1년",
        "source": "Naver Finance + Yahoo Finance (^KS11) 자체 계산",
        "unit": "pt",
        "updated": _now_kst(),
        "note": (
            "[수급·심리] 한국 시장은 외국인/기관 수급이 제일 중요한데 해외 공포·탐욕 지수는 이를 "
            "과소 반영한다 — 그래서 수급에 55%를 얹은 자체 산식: 외국인 20일 누적 순매수 35% + "
            "기관 20일 누적 20% + KOSPI 50일선 이격도 20% + 20일 실현변동성(역방향) 15% + "
            "52주 고점 대비 위치 10%, 각 요인을 최근 1년 분포 백분위로 정규화 후 가중평균. "
            "구간: <25 극공포 / 25~45 공포 / 45~55 중립 / 55~75 탐욕 / >75 극탐욕. "
            "[C2 버블 판별] 불안감이 살아있는 동안엔 버블이 아니다 — 극탐욕 구간 진입+지속이 "
            "심리 역지표다. VIX 카드가 미국 심리라면 이 지수는 한국 수급 심리 — 둘은 상보 관계. "
            "→ 행동: 극공포 진입 = 매수 후보 점검, 극탐욕 장기화 = 단계적 매도 준비, "
            "중간 구간은 신호 아님(관망). "
            "[한계] VKOSPI 무키 소스 부재로 변동성은 20일 실현변동성 프록시(내재변동성 아님). "
            "수급은 Naver 비공식 집계(억원). 백분위 기준 분포가 최근 1년이라 표본 내 상대 위치 — "
            "장기 사이클 극단과는 다를 수 있고, 과최적화를 피해 요인·가중치는 단순 고정."
        ),
        "markLines": [
            {"value": 25, "label": "극공포", "axis": 0},
            {"value": 75, "label": "극탐욕", "axis": 0},
        ],
        "series": [
            {"name": "공포·탐욕 지수", "data": _series_to_pairs(fg)},
        ],
    }

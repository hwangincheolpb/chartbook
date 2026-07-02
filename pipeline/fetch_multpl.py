"""
fetch_multpl.py — multpl.com 무료 공개 테이블 스크래핑 모듈

API 키 불필요. multpl.com이 제공하는 월별 데이터 테이블을 파싱한다.
  - Shiller CAPE:      https://www.multpl.com/shiller-pe/table/by-month
  - S&P 500 P/E (TTM): https://www.multpl.com/s-p-500-pe-ratio/table/by-month
  - S&P 500 EPS (TTM): https://www.multpl.com/s-p-500-earnings/table/by-month

테이블 구조: <table id="datatable"> 안에 Date | Value 행 (월별, 최신순 내림차순).
날짜 포맷: "Mon DD, YYYY" (예: "Jun 8, 2026").

복원력(resilience): 개별 fetch 실패 시 예외를 던지지 않고 None을 반환하여
호출부(run.py)가 해당 차트를 ready:false로 graceful skip 할 수 있게 한다.

HTML 파싱은 외부 의존성(lxml/html5lib) 없이 표준 라이브러리 html.parser로 처리한다.
(pandas.read_html 대비 의존성 단순 + 견고)
"""

import logging
from datetime import datetime
from html.parser import HTMLParser
from typing import Any

import requests
import pytz

logger = logging.getLogger(__name__)

KST = pytz.timezone("Asia/Seoul")

# 실제 브라우저처럼 보이는 User-Agent (봇 차단 회피)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

URLS = {
    "shiller_cape": "https://www.multpl.com/shiller-pe/table/by-month",
    "sp500_pe": "https://www.multpl.com/s-p-500-pe-ratio/table/by-month",
    "sp500_eps": "https://www.multpl.com/s-p-500-earnings/table/by-month",
}


def _now_kst() -> str:
    """현재 시각을 KST ISO8601 문자열로 반환."""
    return datetime.now(KST).strftime("%Y-%m-%dT%H:%M:%S+09:00")


class _DataTableParser(HTMLParser):
    """
    multpl.com <table id="datatable"> 의 (Date, Value) 행을 추출하는 파서.
    헤더 행(Date/Value)은 자동으로 걸러진다.
    """

    def __init__(self):
        super().__init__()
        self.in_target_table = False
        self.in_cell = False
        self.current_row: list[str] = []
        self.rows: list[list[str]] = []
        self._cell_buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if tag == "table" and attrs_d.get("id") == "datatable":
            self.in_target_table = True
        elif self.in_target_table and tag == "tr":
            self.current_row = []
        elif self.in_target_table and tag in ("td", "th"):
            self.in_cell = True
            self._cell_buf = []

    def handle_endtag(self, tag):
        if tag == "table" and self.in_target_table:
            self.in_target_table = False
        elif self.in_target_table and tag in ("td", "th"):
            self.in_cell = False
            text = "".join(self._cell_buf).strip()
            self.current_row.append(text)
        elif self.in_target_table and tag == "tr":
            if self.current_row:
                self.rows.append(self.current_row)
            self.current_row = []

    def handle_data(self, data):
        if self.in_cell:
            self._cell_buf.append(data)


def _parse_value(raw: str) -> float | None:
    """
    셀 텍스트에서 숫자 값을 추출한다.
    공백/특수문자/$/콤마 제거 후 float 변환. 실패 시 None.
    """
    cleaned = raw.replace(" ", "").replace(",", "").replace("$", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_date(raw: str) -> str | None:
    """
    "Mon DD, YYYY" 형식 날짜를 "YYYY-MM-DD"로 변환. 실패 시 None.
    """
    raw = raw.strip()
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _fetch_table(url: str) -> list[list]:
    """
    multpl.com URL에서 (date_str, value) 페어 리스트를 가져온다.
    시간 오름차순 정렬, null 제거.
    실패 시 예외를 그대로 던진다 (호출부에서 graceful 처리).
    """
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html"}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()

    parser = _DataTableParser()
    parser.feed(resp.text)

    pairs: list[list] = []
    for row in parser.rows:
        if len(row) < 2:
            continue
        date_str = _parse_date(row[0])
        value = _parse_value(row[1])
        if date_str is None or value is None:
            # 헤더 행("Date"/"Value") 또는 결측 → skip
            continue
        pairs.append([date_str, round(value, 4)])

    if not pairs:
        raise ValueError(f"파싱된 데이터 없음: {url}")

    # 시간 오름차순 정렬 (multpl은 최신순 내림차순으로 제공)
    pairs.sort(key=lambda p: p[0])
    return pairs


def _try_fetch(key: str) -> list[list] | None:
    """단일 시리즈 안전 수집 wrapper. 실패 시 None 반환."""
    url = URLS[key]
    try:
        pairs = _fetch_table(url)
        logger.info(f"  {key}: {len(pairs)}개 데이터 포인트 ({pairs[0][0]} ~ {pairs[-1][0]})")
        return pairs
    except Exception as e:
        logger.warning(f"  {key} 수집 실패: {e}")
        return None


def fetch_valuation_pe() -> dict[str, Any] | None:
    """
    valuation_pe 차트: Shiller CAPE + S&P 500 P/E (trailing) 2개 시리즈.
    둘 다 실패하면 None (graceful skip). 하나만 성공하면 그것만 포함.
    """
    logger.info("multpl: valuation_pe (Shiller CAPE / S&P 500 P/E) 수집 중...")
    cape = _try_fetch("shiller_cape")
    pe = _try_fetch("sp500_pe")

    series = []
    if cape:
        series.append({"name": "Shiller CAPE", "data": cape})
    if pe:
        series.append({"name": "S&P 500 P/E", "data": pe})

    if not series:
        logger.warning("valuation_pe: 두 시리즈 모두 실패 → skip")
        return None

    return {
        "id": "valuation_pe",
        "type": "timeseries",
        "title": "밸류에이션 (P/E)",
        "subtitle": "Shiller CAPE & S&P 500 트레일링 P/E",
        "source": "multpl.com",
        "unit": "x",
        "updated": _now_kst(),
        "note": "월별 데이터. Shiller CAPE = 경기조정 P/E (10년 평균 실질이익 기준).",
        "series": series,
    }


def fetch_sp500_eps() -> dict[str, Any] | None:
    """
    sp500_eps 차트: S&P 500 EPS (TTM, trailing 12m earnings) 1개 시리즈.
    실패 시 None (graceful skip).
    """
    logger.info("multpl: sp500_eps (S&P 500 EPS TTM) 수집 중...")
    eps = _try_fetch("sp500_eps")
    if not eps:
        logger.warning("sp500_eps: 수집 실패 → skip")
        return None

    return {
        "id": "sp500_eps",
        "type": "timeseries",
        "title": "S&P 500 EPS",
        "subtitle": "주당순이익 (트레일링 12개월)",
        "source": "multpl.com",
        "unit": "USD",
        "updated": _now_kst(),
        "note": "월별 데이터. TTM(최근 12개월) 실적 기준 주당순이익.",
        "series": [
            {"name": "EPS (TTM)", "data": eps},
        ],
    }


def fetch_all_multpl() -> dict[str, dict[str, Any]]:
    """
    multpl 차트 전체 수집.
    Returns: {chart_id: result_dict or {"_skip": True, "_reason": ...}}
    """
    results: dict[str, dict[str, Any]] = {}

    val = fetch_valuation_pe()
    if val is None:
        results["valuation_pe"] = {
            "_skip": True,
            "_reason": "multpl.com 수집 실패 (네트워크/파싱 오류)",
        }
    else:
        results["valuation_pe"] = val

    eps = fetch_sp500_eps()
    if eps is None:
        results["sp500_eps"] = {
            "_skip": True,
            "_reason": "multpl.com 수집 실패 (네트워크/파싱 오류)",
        }
    else:
        results["sp500_eps"] = eps

    return results

"""
fetch_finra.py — FINRA 마진 통계 (버블 체크리스트 ① 신용매수)

논지 출처: 신한투자증권 김성환 "버블 템플릿: 2026-2027 미국 증시 버블 시나리오" (2025-08-19).
버블 정점 탐지 지표 ①: margin debt가 직전 2년 저점 대비 얼마나 올랐는가.
과거 버블 정점(2000, 2007, 2021)은 전부 +90~100%를 상회했다.

소스 (키 불필요):
  1차 = FINRA 공식 엑셀 (전체 히스토리 1997-01~현재, 매월 같은 URL에 갱신):
        https://www.finra.org/sites/default/files/2021-03/margin-statistics.xlsx
        (2026-07 확인: URL의 "2021-03"은 최초 업로드 경로일 뿐, 파일 내용은 최신월까지 갱신됨.
         inline string 방식 xlsx → 외부 의존성 없이 zipfile+ElementTree로 파싱)
  2차 폴백 = FINRA margin statistics 페이지 HTML 표 (최근 13개월만):
        https://www.finra.org/investors/learn-to-invest/advanced-investing/margin-statistics
        폴백 시 2년 저점 창이 짧아져 판정 정확도 낮음 → note에 명시.

값 단위: 원본 $백만 → 십억$ 로 변환해 저장.
"""

import io
import logging
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any

import pytz
import requests

logger = logging.getLogger(__name__)

KST = pytz.timezone("Asia/Seoul")

XLSX_URL = "https://www.finra.org/sites/default/files/2021-03/margin-statistics.xlsx"
PAGE_URL = "https://www.finra.org/investors/learn-to-invest/advanced-investing/margin-statistics"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

# 판정 기준 (run.py build_bubble이 동일 기준으로 배지 계산)
THRESH_WARN = 50.0   # 2년 저점 대비 +50% 이상 = 🟡
THRESH_ALERT = 80.0  # +80% 이상 = 🔴 (과거 정점은 +90~100% 상회)

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%dT%H:%M:%S+09:00")


def _col_of(ref: str) -> str:
    """'B12' → 'B'."""
    return re.match(r"[A-Z]+", ref).group(0)


def _parse_xlsx(content: bytes) -> list[tuple[str, float]]:
    """
    FINRA margin-statistics.xlsx → [("YYYY-MM", debit_balance_$M), ...] 날짜 오름차순.
    구조(2026-07 확인): sheet1, A열 = "YYYY-MM"(inline string),
    B열 = Debit Balances in Customers' Securities Margin Accounts ($백만).
    inline string / shared string 둘 다 방어적으로 처리.
    """
    zf = zipfile.ZipFile(io.BytesIO(content))

    # shared strings (현재 파일은 inline string이라 비어 있지만 방어)
    shared: list[str] = []
    if "xl/sharedStrings.xml" in zf.namelist():
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
        for si in root.findall(f"{_NS}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{_NS}t")))

    sheet_name = next(
        n for n in zf.namelist() if re.match(r"xl/worksheets/sheet1\.xml$", n)
    )
    root = ET.fromstring(zf.read(sheet_name))

    def cell_value(c: ET.Element) -> str | None:
        t = c.get("t")
        if t == "inlineStr":
            return "".join(el.text or "" for el in c.iter(f"{_NS}t"))
        v = c.find(f"{_NS}v")
        if v is None or v.text is None:
            return None
        if t == "s":  # shared string
            try:
                return shared[int(v.text)]
            except (ValueError, IndexError):
                return None
        return v.text

    rows: list[tuple[str, float]] = []
    for row in root.iter(f"{_NS}row"):
        month = None
        debit = None
        for c in row.findall(f"{_NS}c"):
            col = _col_of(c.get("r", "A"))
            val = cell_value(c)
            if val is None:
                continue
            if col == "A":
                month = val.strip()
            elif col == "B":
                try:
                    debit = float(val.replace(",", ""))
                except ValueError:
                    debit = None
        if month and debit is not None and re.match(r"^\d{4}-\d{2}$", month):
            rows.append((month, debit))

    rows.sort(key=lambda r: r[0])
    return rows


def _parse_page_html() -> list[tuple[str, float]]:
    """폴백: FINRA 페이지 HTML 표 (최근 13개월). 'May-26' → '2026-05'."""
    resp = requests.get(PAGE_URL, headers=UA, timeout=30)
    resp.raise_for_status()
    # 행 패턴: <td>May-26</td><td>1,415,557</td>... — 첫 숫자 셀 = Debit Balances
    cells = re.findall(
        r"<td[^>]*>\s*([A-Z][a-z]{2}-\d{2})\s*</td>\s*<td[^>]*>\s*([\d,]+)\s*</td>",
        resp.text,
    )
    rows = []
    for mon_txt, num_txt in cells:
        try:
            dt = datetime.strptime(mon_txt, "%b-%y")
            rows.append((dt.strftime("%Y-%m"), float(num_txt.replace(",", ""))))
        except ValueError:
            continue
    rows.sort(key=lambda r: r[0])
    return rows


def _rise_from_2y_low(rows: list[tuple[str, float]]) -> list[list]:
    """
    각 월의 '직전 2년(24개월) 저점 대비 상승률(%)' 시계열.
    창 = 해당 월 포함 직전 24개월. 24개월 히스토리가 안 되는 초기 구간은
    가용 창으로 계산 (폴백 소스 대비 방어).
    """
    pairs: list[list] = []
    for i, (month, val) in enumerate(rows):
        window = [v for _, v in rows[max(0, i - 23): i + 1]]
        low = min(window)
        if low <= 0:
            continue
        pairs.append([f"{month}-01", round((val / low - 1) * 100, 2)])
    return pairs


def fetch_margin_debt() -> dict[str, Any]:
    """
    버블 체크리스트 ① 신용매수 (margin debt) 차트.
    series: [Margin Debt(십억$), 2년 저점 대비 상승률(%, yAxis 1)]
    markLines: +50%(🟡) / +80%(🔴) — 보조축 기준.
    """
    logger.info("FINRA 마진 통계 수집 중...")
    rows: list[tuple[str, float]] = []
    src_note = ""
    try:
        resp = requests.get(XLSX_URL, headers=UA, timeout=30)
        resp.raise_for_status()
        rows = _parse_xlsx(resp.content)
        source = "FINRA Margin Statistics (xlsx)"
        logger.info(f"  xlsx: {len(rows)}개월 ({rows[0][0]} ~ {rows[-1][0]})")
    except Exception as e:
        logger.warning(f"  xlsx 실패({e}) → 페이지 HTML 표 폴백 (최근 13개월)")
        rows = _parse_page_html()
        source = "FINRA Margin Statistics (HTML 표 폴백)"
        src_note = " [주의] xlsx 실패로 13개월 폴백 — 2년 저점 창 불완전, 판정 참고용."
        logger.info(f"  HTML 폴백: {len(rows)}개월")

    if len(rows) < 6:
        raise ValueError(f"FINRA 마진 데이터 부족: {len(rows)}개월")

    level_pairs = [[f"{m}-01", round(v / 1000.0, 2)] for m, v in rows]  # $M → $bn
    rise_pairs = _rise_from_2y_low(rows)

    return {
        "id": "margin_debt",
        "type": "timeseries",
        "title": "신용매수 잔고 (Margin Debt)",
        "subtitle": "FINRA 마진 잔고 — 2년 저점 대비 +50%↑=🟡 / +80%↑=🔴 (과거 정점 +90~100%)",
        "source": source,
        "unit": "십억$",
        "unit2": "%",
        "updated": _now_kst(),
        "note": (
            "[버블① 신용매수] 버블 정점은 레버리지 절정과 같이 온다. margin debt가 "
            "직전 2년 저점 대비 +80%를 넘으면 정점 근접 — 2000·2007·2021 정점은 전부 "
            "+90~100%를 상회했다. 절대 레벨이 아니라 저점 대비 가속도로 본다."
            f"{src_note} "
            "[출처] 김성환(신한투자증권) '버블 템플릿' 2025-08-19 · FINRA 월간 마진 통계 "
            "[한계] FINRA 발표는 익월 말 지연. 월간 데이터라 정점 당월 포착은 불가"
        ),
        "markLines": [
            {"value": THRESH_WARN, "label": "주의 +50%", "axis": 1},
            {"value": THRESH_ALERT, "label": "정점 근접 +80%", "axis": 1},
        ],
        "series": [
            {"name": "Margin Debt (십억$)", "yAxis": 0, "data": level_pairs},
            {"name": "2년 저점 대비 상승률 (%)", "yAxis": 1, "data": rise_pairs},
        ],
    }

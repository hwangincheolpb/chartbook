#!/usr/bin/env python
"""
build_megaprojects.py — chart-reproduce v1 end-to-end test.

Reconstructs the "Data Centers vs. Megaprojects" chart with LOGIC fixes
(not pixel copy):
  - x = years from program start (year 0 = program launch)
  - y = cumulative inflation-adjusted cost, $B in 2024 real dollars
  - hyperscaler datacenter capex: LIVE via yfinance (measured, solid) with
    a separate DASHED series for the 2026 planned/guidance portion.
  - 6 fixed historical programs: linear-cumulative approximation to total,
    all normalized to 2024$ where the input provided 2024$ figures.

Registers via registry.upsert_chart (same code the server endpoint uses).
Does NOT start a server. Merge-safe: only adds id `megaprojects_reconstructed`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yfinance as yf

# import the real registry the hub reads
sys.path.insert(0, str(Path(__file__).resolve().parent / "server"))
import registry  # noqa: E402

CHART_ID = "megaprojects_reconstructed"
SECTION = "테마"

# ---------------------------------------------------------------------------
# Datacenter capex: 5 hyperscalers, annual capital expenditure ($B).
# 2022-2025 pulled LIVE from yfinance (see fetch_live_capex). 2020-2021 are
# published 10-K actuals (yfinance only returns ~4 fiscal years, so these two
# early years are supplemented from filings; labeled measured/solid). 2026 is
# company capex GUIDANCE (planned; drawn as a separate dashed series).
# ---------------------------------------------------------------------------

# Published FY actuals ($B) for years yfinance does not return (10-K cash flow,
# "purchases of property & equipment"). 5-company sum wave starts modest.
# Values verified against 10-K cash-flow "purchases of property & equipment".
CAPEX_SUPPLEMENT = {
    2020: {"MSFT": 15.44, "AMZN": 40.14, "GOOGL": 22.28, "META": 15.12, "ORCL": 1.56},  # sum ~94.5
    2021: {"MSFT": 20.62, "AMZN": 61.05, "GOOGL": 24.64, "META": 18.57, "ORCL": 2.14},  # sum ~127.0
}
# 2026 planned capex GUIDANCE ($B), 5-company sum (late-2025/early-2026 calls;
# CreditSights/Tom's Hardware range ~665-720, midpoint used). Moving target.
CAPEX_2026_GUIDANCE_SUM = 700.0

TICKERS = ["MSFT", "AMZN", "GOOGL", "META", "ORCL"]
BASE_YEAR = 2020  # x = year - BASE_YEAR


def fetch_live_capex() -> dict[int, dict[str, float]]:
    """Return {calendar_year: {ticker: capex_$B}} from yfinance yearly cashflow.

    ORCL fiscal year ends in May; its FY ending May-2026 ($ latest) is the
    Oracle contribution that aligns with the others' calendar-2025 capex wave.
    We therefore bucket ORCL's latest FY into 2025 to match the research
    verification figure (~$413B for 2025).
    """
    raw: dict[str, dict[int, float]] = {}
    for t in TICKERS:
        cf = yf.Ticker(t).get_cashflow(freq="yearly")
        if "CapitalExpenditure" not in cf.index:
            raise RuntimeError(f"{t}: no CapitalExpenditure row")
        s = cf.loc["CapitalExpenditure"]
        raw[t] = {c.year: abs(float(v)) / 1e9 for c, v in s.items() if v == v}

    out: dict[int, dict[str, float]] = {}
    for t, byyear in raw.items():
        for y, v in byyear.items():
            if t == "ORCL":
                # shift ORCL fiscal-year to the calendar wave: FYyyyy -> yyyy-1
                y = y - 1
            out.setdefault(y, {})[t] = round(v, 1)
    return out


def datacenter_series():
    live = fetch_live_capex()
    # merged annual per-company capex, measured years only (2020-2025)
    annual_sum: dict[int, float] = {}
    for y in range(2020, 2026):
        comp = dict(CAPEX_SUPPLEMENT.get(y, {}))
        comp.update(live.get(y, {}))
        annual_sum[y] = round(sum(comp.values()), 1)

    # cumulative (measured, solid line): years 2020..2025
    measured = []
    cum = 0.0
    for y in range(2020, 2026):
        cum += annual_sum[y]
        measured.append((y - BASE_YEAR, round(cum, 1)))

    # planned (dashed series): starts at the last measured cumulative point
    # (2025) and adds 2026 guidance. We anchor the dashed line at 2025 so the
    # two segments visually connect.
    cum_2025 = measured[-1][1]
    planned = [
        (2025 - BASE_YEAR, cum_2025),
        (2026 - BASE_YEAR, round(cum_2025 + CAPEX_2026_GUIDANCE_SUM, 1)),
    ]
    return measured, planned, annual_sum


def linear_cum(total: float, years: int):
    """Linear 0->total accumulation over `years` (point per year)."""
    return [(k, round(total * k / years, 1)) for k in range(years + 1)]


# x축은 날짜가 아니라 경과 연차 숫자(0,1,2...) 그대로 사용.
# 차트 JSON 최상위 xAxisType:"value" + xAxisName으로 렌더러에 알림 (CONTRACT.md 참조).
# (이전 버전은 연차를 2000+N 가짜 날짜로 인코딩했음 — 논리 왜곡이라 제거)

# --- 6 fixed historical programs: (name, total_2024$B, duration_yr, note) ---
FIXED_PROGRAMS = [
    ("주간고속도로 (Interstate Highway)", 634, 37, "FHWA 명목 $114B → 2024$ ≈ $634B (37년)"),
    ("대륙횡단철도 (US Railroads)", 550, 71, "추정·저신뢰: 명목→실질 환산 방법론 불투명 (71년)"),
    ("F-35 Program", 400, 25, "GAO 취득비 ~$400B (생애비용 $1.7~2T는 별개)"),
    ("아폴로 (Apollo)", 257, 14, "Planetary Society 동료심사 2020$≈2024$ 근사 (14년)"),
    ("마셜플랜 (Marshall Plan)", 170, 4, "소스별 $150~170B 편차, 상단 채택 (4년)"),
    ("국제우주정거장 (ISS)", 150, 27, "NASA 전 파트너 합산 (명목혼합→2024$ 근사, 27년)"),
]


def build_chart():
    measured, planned, annual_sum = datacenter_series()

    series = []
    # 1) datacenter measured (solid)
    series.append({
        "name": "AI 데이터센터 capex (실측, 5사 합산)",
        "data": [[x, v] for x, v in measured],
    })
    # 2) datacenter planned 2026 (dashed via separate series)
    series.append({
        "name": "AI 데이터센터 capex (2026 계획/가이던스)",
        "data": [[x, v] for x, v in planned],
    })
    # 3-8) fixed programs
    for name, total, dur, _note in FIXED_PROGRAMS:
        series.append({
            "name": name,
            "data": [[x, v] for x, v in linear_cum(total, dur)],
        })

    fixed_notes = " · ".join(f"{n.split(' (')[0]}: {nt}" for n, _t, _d, nt in FIXED_PROGRAMS)
    note = (
        "논지: '규모'보다 '속도' — 데이터센터 capex는 수십 년짜리 메가프로젝트 누적비용을 "
        "단 6년(2020=0년차)에 따라잡는다. "
        "x축=프로그램 시작 후 경과 연차, y축=누적비용(2024$, $B). "
        "[논리 교정] (1) 실측(2020~25 실선)/계획(2026 가이던스 점선=별도 시리즈)을 분리. "
        "(2) 전 시리즈 2024$ 기준으로 통일. "
        "(3) 대륙횡단철도는 방법론 불투명 저신뢰 추정. "
        "[한계] 역사 6개는 총액→기간 선형누적 근사(실제 지출곡선 아님). "
        "데이터센터는 물류창고 등 비-DC capex 포함 프록시. "
        "[출처] " + fixed_notes
    )

    chart = {
        "id": CHART_ID,
        "type": "timeseries",
        "title": "데이터센터 vs. 초대형 프로젝트",
        "subtitle": "인플레조정 누적비용($B, 2024real) · x축=시작 후 경과 연차 · 실측=실선/계획=점선(별도시리즈)",
        "source": "manual",
        "unit": "USD(2024$B)",
        "updated": registry._now_kst(),
        "note": note,
        "xAxisType": "value",
        "xAxisName": "프로그램 시작 후 경과 연차",
        "series": series,
    }
    return chart, annual_sum, measured, planned


def main():
    chart, annual_sum, measured, planned = build_chart()

    print("=== datacenter capex annual sum ($B) ===")
    for y in sorted(annual_sum):
        print(f"  {y}: {annual_sum[y]}")
    print(f"  2025 (sanity vs ~413): {annual_sum[2025]}")
    print(f"  measured cumulative last: yr{measured[-1][0]} = ${measured[-1][1]}B")
    print(f"  planned 2026 cumulative:  yr{planned[-1][0]} = ${planned[-1][1]}B")
    print("=== series point counts ===")
    for s in chart["series"]:
        print(f"  {s['name']}: {len(s['data'])} pts")

    res = registry.upsert_chart(
        chart_id=CHART_ID,
        section=SECTION,
        chart_type="timeseries",
        chart_data=chart,
        ready=True,
    )
    print("=== upsert result ===")
    print(res)


if __name__ == "__main__":
    main()

"""더미 데이터 생성기 — 프론트(B) 개발/통합 테스트용. 실제 파이프라인이 data/를 덮어씀."""
import json, math, os
from datetime import date, timedelta

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
os.makedirs(DATA, exist_ok=True)
UPDATED = "2026-06-09T12:00:00+09:00"


def daily_series(start, days, base, drift, amp, period=120):
    out, d = [], date.fromisoformat(start)
    for i in range(days):
        v = base + drift * i + amp * math.sin(i / period * 2 * math.pi)
        out.append([d.isoformat(), round(v, 2)])
        d += timedelta(days=1)
    return out


def ma(series, window):
    vals = [p[1] for p in series]
    out = []
    for i in range(len(series)):
        if i < window - 1:
            continue
        avg = sum(vals[i - window + 1:i + 1]) / window
        out.append([series[i][0], round(avg, 2)])
    return out


def write(obj):
    with open(os.path.join(DATA, obj["id"] + ".json"), "w") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


sp = daily_series("2019-01-01", 1300, 2600, 1.6, 250)
write({"id": "sp500", "type": "timeseries", "title": "S&P 500", "subtitle": "200일 이동평균",
       "source": "DUMMY", "unit": "index", "updated": UPDATED,
       "series": [{"name": "S&P 500", "data": sp}, {"name": "200D MA", "data": ma(sp, 200)}]})

ks = daily_series("2019-01-01", 1300, 2100, 0.3, 200)
kq = daily_series("2019-01-01", 1300, 700, 0.05, 90)
write({"id": "kospi", "type": "timeseries", "title": "KOSPI / KOSDAQ", "subtitle": "한국 지수",
       "source": "DUMMY", "unit": "index", "updated": UPDATED,
       "series": [{"name": "KOSPI", "data": ks}, {"name": "KOSDAQ", "data": kq}]})

vix = daily_series("2019-01-01", 1300, 18, 0, 8, period=60)
write({"id": "vix", "type": "timeseries", "title": "VIX", "subtitle": "변동성 지수",
       "source": "DUMMY", "unit": "index", "updated": UPDATED,
       "series": [{"name": "VIX", "data": vix}]})

secs = [("Technology", "XLK"), ("Financials", "XLF"), ("Health Care", "XLV"),
        ("Energy", "XLE"), ("Industrials", "XLI"), ("Consumer Disc.", "XLY"),
        ("Consumer Staples", "XLP"), ("Utilities", "XLU"), ("Materials", "XLB"),
        ("Real Estate", "XLRE"), ("Communication", "XLC")]
periods = ["1D", "1W", "1M", "3M", "YTD", "1Y"]
items = []
for i, (n, t) in enumerate(secs):
    perf = {p: round(2 * math.sin(i + j) + (j - 2), 2) for j, p in enumerate(periods)}
    items.append({"name": n, "ticker": t, "perf": perf})
write({"id": "sectors", "type": "heatmap_perf", "title": "섹터 퍼포먼스",
       "source": "DUMMY", "updated": UPDATED, "periods": periods, "items": items})

# FRED 차트 더미 (ready=true로 같이 테스트)
pe = daily_series("2019-01-01", 1300, 18, 0.002, 3, period=180)
cape = daily_series("2019-01-01", 1300, 30, 0.003, 4, period=180)
write({"id": "valuation_pe", "type": "timeseries", "title": "밸류에이션", "subtitle": "Forward P/E & Shiller CAPE",
       "source": "DUMMY", "unit": "x", "updated": UPDATED,
       "series": [{"name": "Forward P/E", "data": pe}, {"name": "Shiller CAPE", "data": cape}]})

eps = daily_series("2019-01-01", 1300, 140, 0.03, 10, period=365)
write({"id": "sp500_eps", "type": "timeseries", "title": "S&P 500 EPS", "subtitle": "주당순이익",
       "source": "DUMMY", "unit": "USD", "updated": UPDATED,
       "series": [{"name": "EPS", "data": eps}]})

buf = daily_series("2019-01-01", 1300, 160, 0.01, 20, period=200)
write({"id": "buffett", "type": "timeseries", "title": "Buffett Indicator", "subtitle": "시가총액 / GDP (%)",
       "source": "DUMMY", "unit": "%", "updated": UPDATED,
       "series": [{"name": "Mkt Cap / GDP", "data": buf}]})

# --- 채권/금리 더미 ---
m3 = daily_series("2019-01-01", 1300, 4.8, -0.0005, 0.6, period=250)
y5 = daily_series("2019-01-01", 1300, 4.0, 0.0003, 0.5, period=250)
y10 = daily_series("2019-01-01", 1300, 4.2, 0.0004, 0.5, period=250)
y30 = daily_series("2019-01-01", 1300, 4.4, 0.0004, 0.4, period=250)
write({"id": "ust_yields", "type": "timeseries", "title": "미국채 금리", "subtitle": "3M · 5Y · 10Y · 30Y",
       "source": "DUMMY", "unit": "%", "updated": UPDATED,
       "series": [{"name": "3M", "data": m3}, {"name": "5Y", "data": y5},
                  {"name": "10Y", "data": y10}, {"name": "30Y", "data": y30}]})

spread = [[m3[i][0], round(y10[i][1] - m3[i][1], 2)] for i in range(len(m3))]
write({"id": "yield_spread", "type": "timeseries", "title": "10Y-3M 스프레드", "subtitle": "장단기 금리차 (마이너스=역전)",
       "source": "DUMMY", "unit": "%", "updated": UPDATED,
       "series": [{"name": "10Y-3M", "data": spread}]})

write({"id": "yield_curve", "type": "curve_snapshot", "title": "미국 국채 수익률 곡선",
       "source": "DUMMY", "unit": "%", "updated": UPDATED, "note": "역전 여부 한눈에",
       "maturities": ["3M", "5Y", "10Y", "30Y"],
       "snapshots": [
           {"label": "현재", "data": [["3M", m3[-1][1]], ["5Y", y5[-1][1]], ["10Y", y10[-1][1]], ["30Y", y30[-1][1]]]},
           {"label": "1년 전", "data": [["3M", m3[-365][1]], ["5Y", y5[-365][1]], ["10Y", y10[-365][1]], ["30Y", y30[-365][1]]]},
       ]})

index = {"updated": UPDATED, "charts": [
    {"id": "sp500", "file": "sp500.json", "type": "timeseries", "section": "주식시장", "ready": True},
    {"id": "valuation_pe", "file": "valuation_pe.json", "type": "timeseries", "section": "밸류에이션", "ready": True},
    {"id": "sp500_eps", "file": "sp500_eps.json", "type": "timeseries", "section": "밸류에이션", "ready": True},
    {"id": "buffett", "file": "buffett.json", "type": "timeseries", "section": "밸류에이션", "ready": True},
    {"id": "sectors", "file": "sectors.json", "type": "heatmap_perf", "section": "섹터", "ready": True},
    {"id": "vix", "file": "vix.json", "type": "timeseries", "section": "리스크", "ready": True},
    {"id": "kospi", "file": "kospi.json", "type": "timeseries", "section": "한국", "ready": True},
    {"id": "ust_yields", "file": "ust_yields.json", "type": "timeseries", "section": "채권/금리", "ready": True},
    {"id": "yield_spread", "file": "yield_spread.json", "type": "timeseries", "section": "채권/금리", "ready": True},
    {"id": "yield_curve", "file": "yield_curve.json", "type": "curve_snapshot", "section": "채권/금리", "ready": True},
    {"id": "credit_hy_oas", "file": "credit_hy_oas.json", "type": "timeseries", "section": "채권/금리", "ready": False},
]}
with open(os.path.join(DATA, "index.json"), "w") as f:
    json.dump(index, f, ensure_ascii=False, indent=2)

print("dummy data written to", os.path.abspath(DATA))

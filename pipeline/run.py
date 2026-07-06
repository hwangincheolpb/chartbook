"""
run.py — Chartbook 데이터 파이프라인 오케스트레이터

실행 방법:
    python pipeline/run.py

동작:
    1. Yahoo Finance 차트 수집 (SP500, KOSPI, VIX, 섹터)
    2. FRED 차트 수집 (하이일드 OAS; FRED_API_KEY 있을 때만)
    3. data/<id>.json 파일 저장
    4. data/index.json 업데이트 (ready 플래그 포함)
    5. 수집 결과 요약 출력
"""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pytz

# 파이프라인 루트를 sys.path에 추가
PIPELINE_DIR = Path(__file__).parent
REPO_ROOT = PIPELINE_DIR.parent
DATA_DIR = REPO_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

KST = pytz.timezone("Asia/Seoul")


def _now_kst() -> str:
    """현재 시각을 KST ISO8601 문자열로 반환."""
    return datetime.now(KST).strftime("%Y-%m-%dT%H:%M:%S+09:00")


def write_json(path: Path, data: dict[str, Any]) -> None:
    """JSON 파일 저장 (compact, 한글 유지)."""
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# 외부 라이브 대시보드 링크 카드 (type:"link"). 파이프라인이 index.json을 매번
# 새로 쓰므로 여기 두어 매 실행마다 보존되게 한다(이전엔 누락돼 daily 실행 때 사라짐).
# 포트는 serve.sh와 일치(8770). 8765는 jarvis-voice 데몬이 점유 → 충돌 회피.
SERVE_PORT = 8770
LINK_CARDS = [
    {"id": "peer_valuation_link", "type": "link", "section": "밸류에이션",
     "title": "피어 밸류에이션 모니터", "subtitle": "190종목·48카테고리 일별 스냅샷·변동률·시계열",
     "url": f"http://localhost:{SERVE_PORT}/peer-valuation-monitor/", "live": True,
     "preview": "embed", "source": "GitHub Pages", "note": "로컬 서버(serve.sh) 필요"},
    {"id": "active_etf_link", "type": "link", "section": "자금흐름",
     "title": "액티브 ETF 트래커", "subtitle": "액티브 ETF 자금/구성 모니터",
     "url": f"http://localhost:{SERVE_PORT}/active-etf-tracker/web/", "live": True,
     "source": "로컬 전용", "note": "로컬 경로 ~/workspace/dev/active-etf-tracker | serve.sh 필요"},
    {"id": "money_flow_link", "type": "link", "section": "자금흐름",
     "title": "머니 플로우", "subtitle": "자금흐름 대시보드",
     "url": f"http://localhost:{SERVE_PORT}/money-flow/money-flow-2026.html", "live": True,
     "source": "로컬 전용", "note": "로컬 경로 ~/workspace/dev/money-flow | serve.sh 필요"},
    {"id": "structural_shortage_link", "type": "link", "section": "테마",
     "title": "구조적 쇼티지 대시보드", "subtitle": "구조적 공급부족 테마 모니터",
     "url": f"http://localhost:{SERVE_PORT}/structural-shortage-dashboard/", "live": True,
     "source": "Netlify", "note": "serve.sh 필요"},
    {"id": "financial_products_link", "type": "link", "section": "상품/포트폴리오",
     "title": "금융상품 / 포트폴리오 제안", "subtitle": "2026 자산배분 전략·상품 제안",
     "url": f"http://localhost:{SERVE_PORT}/financial-products/", "live": True,
     "source": "GitHub Pages", "note": "serve.sh 필요"},
    {"id": "brazil_bond_link", "type": "link", "section": "상품/포트폴리오",
     "title": "브라질 국채 교체매매", "subtitle": "27Y/29Y → 37Y 교체매매 전략",
     "url": f"http://localhost:{SERVE_PORT}/financial-products/brazil-bond/", "live": True,
     "source": "GitHub Pages", "note": "serve.sh 필요"},
    # ─── Valley AI (valley.town) — 평생무료 계정 보유. 원칙(2026-07-06):
    # Valley에 있는 기능은 재개발하지 않고 링크로 단다. 로그인 필요.
    {"id": "valley_buffett_link", "type": "link", "section": "밸류에이션",
     "title": "버핏지수·자산군 밸류에이션", "subtitle": "시총/GDP 버핏지수 + 자산군별 밸류에이션 대시보드",
     "url": "https://www.valley.town/economy/asset-valuation/stock/buffett", "live": True,
     "source": "Valley AI (로그인 필요)"},
    {"id": "valley_cycle_heatmap_link", "type": "link", "section": "매크로",
     "title": "사이클 히트맵", "subtitle": "경기 사이클 국면 히트맵",
     "url": "https://www.valley.town/economy/business-cycles/heatmap", "live": True,
     "source": "Valley AI (로그인 필요)"},
    {"id": "valley_econ_calendar_link", "type": "link", "section": "매크로",
     "title": "경제지표 캘린더", "subtitle": "경제지표·실적 발표 실시간 캘린더",
     "url": "https://www.valley.town/economy/economic-calendar", "live": True,
     "source": "Valley AI (로그인 필요)"},
    {"id": "valley_indicators_link", "type": "link", "section": "매크로",
     "title": "경제지표 열람", "subtitle": "FRED류 경제지표 커스텀 차트 시트",
     "url": "https://www.valley.town/economy/indicators", "live": True,
     "source": "Valley AI (로그인 필요)"},
    {"id": "valley_guru_13f_link", "type": "link", "section": "자금흐름",
     "title": "거장 매매 (13F)", "subtitle": "거장 포트폴리오·13F 매매 내역 추적",
     "url": "https://www.valley.town/guru/transactions", "live": True,
     "source": "Valley AI (로그인 필요)"},
    {"id": "valley_wsaj_column_link", "type": "link", "section": "주식시장",
     "title": "월가아재 시황칼럼", "subtitle": "출근길·퇴근길 시황 + 월가소식 기관뷰 요약",
     "url": "https://www.valley.town/premium/wsaj-column", "live": True,
     "source": "Valley AI (로그인 필요)"},
]

# 은퇴한 차트 id — index 재생성 시 기존 index.json에서 넘어와도 버린다.
# buffett: FRED 키 대기 placeholder였으나 Valley AI 링크 카드(valley_buffett_link)로
# 대체 (2026-07-06). 재활성화하려면 여기서 빼고 chart_meta + fetch_fred 복귀.
RETIRED_IDS = {"buffett"}


def build_index(chart_results: list[dict[str, Any]], now: str) -> dict[str, Any]:
    """
    index.json 구조를 생성한다.
    CONTRACT.md 정의 순서: 주식시장 → 밸류에이션 → 섹터 → 리스크 → 한국
    """
    # 차트 메타 정의 (배열 순서 = 전체 뷰 섹션 렌더 순서, 고정)
    # daily: True → 사이트 "데일리" 뷰 기본 포함.
    # daily_order → 데일리 뷰 표시 순서 = 매일 판단하는 논리체인 순서:
    #   C1 금리 정점(ls_rate_peak, yield_spread) → C2 버블 판별(sp500 밸류밴드, vix)
    #   → C3 메모리(ls_memory_cycle: MU 선행 포함) → C4 로테이션(ls_semi_vs_power)
    #   → C5 대만(ls_taiwan_hedge) → 기타(ls_ship_defense, move_index, wti)
    # 사용자가 사이트 ⭐로 localStorage 오버라이드 가능 — 여긴 시드만.
    chart_meta = [
        {"id": "sp500",        "file": "sp500.json",        "type": "timeseries",   "section": "주식시장", "daily": True, "daily_order": 3},
        {"id": "kospi",        "file": "kospi.json",        "type": "timeseries",   "section": "한국"},
        # ─── 수급 (로테이션 끝 판정 재료 — 스냅샷 '로테이션 신호' 카드 연동) ─
        # vkospi는 무키 소스 없음(KRX 로그인 필수화, Naver/Daum/Yahoo 미제공) → 미구현 (fetch_kr_flow.py 주석 참조)
        {"id": "kr_foreign_flow",   "file": "kr_foreign_flow.json",   "type": "timeseries", "section": "수급", "daily": True, "daily_order": 11},
        {"id": "kr_rotation_check", "file": "kr_rotation_check.json", "type": "timeseries", "section": "수급"},
        # kr_fear_greed: 수급 가중 공포·탐욕 지수 — 데일리 시드 제외(스냅샷 카드로 충분, 차트는 전체 탭)
        {"id": "kr_fear_greed",     "file": "kr_fear_greed.json",     "type": "timeseries", "section": "수급"},
        {"id": "vix",          "file": "vix.json",          "type": "timeseries",   "section": "리스크", "daily": True, "daily_order": 4},
        {"id": "sectors",      "file": "sectors.json",      "type": "heatmap_perf", "section": "섹터"},
        {"id": "valuation_pe", "file": "valuation_pe.json", "type": "timeseries",   "section": "밸류에이션"},
        {"id": "sp500_eps",    "file": "sp500_eps.json",    "type": "timeseries",   "section": "밸류에이션"},
        # buffett: Valley AI 링크(valley_buffett_link)로 대체 — RETIRED_IDS 참조.
        # ─── 버블 체크리스트 (김성환 '버블 템플릿' 2025-08-19 — 정점 5지표) ─
        # 판정 배지·종합(n/5)은 build_bubble() → data/bubble_checklist.json (CONTRACT 참조)
        {"id": "margin_debt",  "file": "margin_debt.json",  "type": "timeseries", "section": "버블 체크리스트"},
        {"id": "ipo_rs",       "file": "ipo_rs.json",       "type": "timeseries", "section": "버블 체크리스트"},
        {"id": "arkk_rs",      "file": "arkk_rs.json",      "type": "timeseries", "section": "버블 체크리스트"},
        {"id": "fed_funds",    "file": "fed_funds.json",    "type": "timeseries", "section": "버블 체크리스트"},
        {"id": "capex_margin", "file": "capex_margin.json", "type": "timeseries", "section": "버블 체크리스트"},
        # ─── 이선엽 체인 (framework §7 논지 체인, 채권/금리 앞 배치) ─
        {"id": "ls_rate_peak",     "file": "ls_rate_peak.json",     "type": "timeseries", "section": "이선엽 체인", "daily": True, "daily_order": 1},
        {"id": "ls_semi_vs_power", "file": "ls_semi_vs_power.json", "type": "timeseries", "section": "이선엽 체인", "daily": True, "daily_order": 6},
        {"id": "ls_memory_cycle",  "file": "ls_memory_cycle.json",  "type": "timeseries", "section": "이선엽 체인", "daily": True, "daily_order": 5},
        {"id": "ls_taiwan_hedge",  "file": "ls_taiwan_hedge.json",  "type": "timeseries", "section": "이선엽 체인", "daily": True, "daily_order": 7},
        {"id": "ls_ship_defense",  "file": "ls_ship_defense.json",  "type": "timeseries", "section": "이선엽 체인", "daily": True, "daily_order": 8},
        {"id": "move_index",       "file": "move_index.json",       "type": "timeseries", "section": "이선엽 체인", "daily": True, "daily_order": 9},
        # ─── 채권/금리 (기존 차트 뒤에 추가) ───────────────────
        {"id": "ust_yields",   "file": "ust_yields.json",   "type": "timeseries",     "section": "채권/금리"},
        {"id": "yield_spread", "file": "yield_spread.json", "type": "timeseries",     "section": "채권/금리", "daily": True, "daily_order": 2},
        {"id": "yield_curve",  "file": "yield_curve.json",  "type": "curve_snapshot", "section": "채권/금리"},
        {"id": "credit_proxy", "file": "credit_proxy.json", "type": "timeseries",     "section": "채권/금리"},
        {"id": "credit_hy_oas","file": "credit_hy_oas.json","type": "timeseries",     "section": "채권/금리"},
        # ─── 환율 ───────────────────────────────────────────────
        {"id": "usdkrw",       "file": "usdkrw.json",       "type": "timeseries",     "section": "환율"},
        {"id": "dxy",          "file": "dxy.json",          "type": "timeseries",     "section": "환율"},
        # ─── 원자재 ─────────────────────────────────────────────
        {"id": "gold",         "file": "gold.json",         "type": "timeseries",     "section": "원자재"},
        {"id": "wti",          "file": "wti.json",          "type": "timeseries",     "section": "원자재", "daily": True, "daily_order": 10},
        {"id": "copper",       "file": "copper.json",       "type": "timeseries",     "section": "원자재"},
    ]

    # 수집 결과 id → 성공 여부 맵
    ready_map = {r["id"]: r["ready"] for r in chart_results}

    charts = []
    for meta in chart_meta:
        chart_id = meta["id"]
        ready = ready_map.get(chart_id, False)
        entry = {
            "id": chart_id,
            "file": meta["file"],
            "type": meta["type"],
            "section": meta["section"],
            "ready": ready,
            "daily": bool(meta.get("daily", False)),
        }
        if "daily_order" in meta:
            entry["dailyOrder"] = meta["daily_order"]  # 데일리 뷰 표시 순서 (CONTRACT 참조)
        charts.append(entry)

    # 파이프라인 소유가 아닌 기존 차트 전부 보존(매 실행 유지).
    # - 링크 카드(LINK_CARDS 기본값 + 사용자가 추가한 link 항목)
    # - 도구/스킬(chart-reproduce, 관리툴)로 등록된 차트 — 이걸 안 보존하면
    #   매일 아침 파이프라인이 index 재생성하면서 지워버림 (2026-07-02 버그 수정)
    pipeline_ids = {m["id"] for m in chart_meta}
    link_by_id = {c["id"]: c for c in LINK_CARDS}
    extra_charts = []
    try:
        existing = json.loads((DATA_DIR / "index.json").read_text(encoding="utf-8"))
        for c in existing.get("charts", []):
            cid = c.get("id")
            if cid in pipeline_ids or cid in link_by_id or cid in RETIRED_IDS:
                continue  # 파이프라인 소유 or 기본 링크 카드 or 은퇴 차트 → 보존 안 함
            if c.get("type") == "link":
                link_by_id[cid] = c
            else:
                extra_charts.append(c)  # 도구/스킬 등록 차트 그대로 보존 (daily 필드 포함)
    except Exception:
        pass
    charts.extend(extra_charts)
    charts.extend(link_by_id.values())

    return {"updated": now, "charts": charts}


# ─────────────────────────────────────────────────────────────
# 스냅샷 보드 (data/snapshot.json) — "아침 10초 확인"용 카드 11개.
# 모든 차트 fetch가 끝난 뒤, 생성된 data/*.json에서만 계산한다
# (추가 네트워크 호출 없음). 재료 없으면 해당 카드 skip.
# 규격은 CONTRACT.md "snapshot.json" 참조.
# ─────────────────────────────────────────────────────────────

def _load_chart(chart_id: str) -> dict | None:
    path = DATA_DIR / f"{chart_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _series_pairs(chart: dict | None, name_contains: str | None = None) -> list:
    """chart의 series에서 이름에 name_contains가 포함된 첫 시리즈 data 반환.
    name_contains=None이면 첫 시리즈."""
    if not chart:
        return []
    for s in chart.get("series") or []:
        if name_contains is None or name_contains in (s.get("name") or ""):
            return s.get("data") or []
    return []


def _latest(pairs: list) -> tuple[str, float] | None:
    """마지막 유효 (date, value)."""
    for d, v in reversed(pairs):
        if v is not None:
            return d, float(v)
    return None


def _prev(pairs: list) -> float | None:
    """마지막 직전 유효값 (전일비 계산용)."""
    vals = [v for _, v in pairs if v is not None]
    return float(vals[-2]) if len(vals) >= 2 else None


def _d1_pct(pairs: list) -> float | None:
    """전일비 % (마지막 vs 직전 데이터 포인트)."""
    last = _latest(pairs)
    prev = _prev(pairs)
    if last is None or prev in (None, 0):
        return None
    return round((last[1] / prev - 1) * 100, 2)


def _chg_3m_pct(pairs: list) -> float | None:
    """3개월 변화율 % (마지막 날짜 기준 ~90일 전과 비교)."""
    last = _latest(pairs)
    if last is None:
        return None
    from datetime import timedelta
    last_dt = datetime.strptime(last[0], "%Y-%m-%d")
    target = last_dt - timedelta(days=90)
    base = None
    for d, v in pairs:
        if v is None:
            continue
        if datetime.strptime(d, "%Y-%m-%d") <= target:
            base = float(v)
        else:
            break
    if base in (None, 0):
        return None
    return round((last[1] / base - 1) * 100, 2)


def _arrow(chg: float | None) -> str:
    if chg is None:
        return "→"
    return "↑" if chg > 1 else ("↓" if chg < -1 else "→")


def build_snapshot(now: str) -> dict[str, Any]:
    """생성된 data/*.json에서 아침 스냅샷 카드 11개를 계산."""
    cards: list[dict[str, Any]] = []

    def add(card: dict[str, Any] | None) -> None:
        if card is not None:
            cards.append(card)

    # 1. 미국채 10Y — CTA 손절선(4.85)까지 거리
    def card_us10y():
        pairs = _series_pairs(_load_chart("ls_rate_peak"), "10Y") \
            or _series_pairs(_load_chart("ust_yields"), "10Y")
        last = _latest(pairs)
        if last is None:
            return None
        val = last[1]
        dist = 4.85 - val
        if val >= 4.85:
            state, badge = "alert", "돌파"
        elif dist <= 0.2:
            state, badge = "warn", "근접"
        else:
            state, badge = "good", "여유"
        return {
            "id": "us10y", "label": "미국채 10Y", "value": round(val, 3), "unit": "%",
            "d1": _d1_pct(pairs), "state": state, "badge": badge,
            "caption": f"CTA 손절선 4.85%까지 {dist:+.2f}%p",
            "link": "#card-ls_rate_peak",
        }

    # 1-b. 금리 시나리오 A/B — 트레이드 플랜 트리거 (규격/정의는 CONTRACT "rate_scenario" 행 참조)
    #   A=매파 재프라이싱: 10Y 4.40% 상향 안착(안착 = 종가 3영업일 연속 ≥4.40)
    #   B=되돌림 지속: 10Y 4.30% 하향 이탈. 사이 = 중립(관망).
    #   보조신호(베어플래트닝): 2Y 무키 소스 없음 → 10Y-3M 스프레드(yield_spread)로 근사.
    #   "10Y 5영업일 상승 + 스프레드 5영업일 축소 동시"면 플래트닝 주의 문구. 2Y 정식판은 FRED 키 이후.
    def card_rate_scenario():
        pairs = _series_pairs(_load_chart("ls_rate_peak"), "10Y") \
            or _series_pairs(_load_chart("ust_yields"), "10Y")
        last = _latest(pairs)
        if last is None:
            return None
        val = last[1]
        vals = [float(v) for _, v in pairs if v is not None]

        if len(vals) >= 3 and all(v >= 4.40 for v in vals[-3:]):
            state, badge = "alert", "A 매파 재프라이싱"
            judge = "4.40 상향 안착(종가 3영업일 연속)"
        elif val >= 4.40:
            state, badge = "warn", "A 안착 대기"
            judge = "4.40 상회 — 안착(종가 3영업일 연속) 확인 중"
        elif val <= 4.30:
            state, badge = "alert", "B 되돌림"
            judge = "4.30 하향 이탈"
        else:
            state, badge = "neutral", "중립(관망)"
            judge = "4.30~4.40 사이"

        # 베어플래트닝 근사: 10Y 5영업일 상승 + 10Y-3M 스프레드 5영업일 축소 동시
        flat_txt = ""
        sp_vals = [float(v) for _, v in _series_pairs(_load_chart("yield_spread"), "10Y-3M")
                   if v is not None]
        if len(vals) >= 6 and len(sp_vals) >= 6 and vals[-1] > vals[-6] and sp_vals[-1] < sp_vals[-6]:
            flat_txt = " · 10Y 상승+10Y-3M 축소 = 플래트닝 주의(2Y 근사)"

        dist_a = (4.40 - val) * 100  # A선까지 bp (음수 = 이미 상회)
        dist_b = (4.30 - val) * 100  # B선까지 bp (음수 = 하향 이탈까지 남은 폭)
        caption = (
            f"{judge} · A선 4.40까지 {dist_a:+.0f}bp·B선 4.30까지 {dist_b:+.0f}bp{flat_txt}"
            " → A 확정 시 분할 진입·전제 깨지면 기계적 손절, B 확정 시 되돌림 포지션 유지"
        )
        return {
            "id": "rate_scenario", "label": "금리 시나리오 A/B", "value": round(val, 3), "unit": "%",
            "d1": _d1_pct(pairs), "state": state, "badge": badge,
            "caption": caption, "link": "#card-ls_rate_peak",
        }

    # 2. S&P500 vs 21x 밴드 상단 — >1.0 = 드림장
    def card_spx_band():
        chart = _load_chart("sp500")
        spx = _series_pairs(chart, "S&P 500")
        band = _series_pairs(chart, "21x")
        spx_last, band_last = _latest(spx), _latest(band)
        if spx_last is None or band_last is None or band_last[1] == 0:
            return None
        ratio = spx_last[1] / band_last[1]
        state = "warn" if ratio > 1.0 else "good"
        badge = "드림장" if ratio > 1.0 else "밴드 내"
        return {
            "id": "spx_band", "label": "S&P500 / 21x 밴드", "value": round(ratio, 2), "unit": "x",
            "d1": _d1_pct(spx), "state": state, "badge": badge,
            "caption": f"지수 {spx_last[1]:,.0f} = 21x 밴드 상단({band_last[1]:,.0f})의 {ratio:.2f}배 — 1.0 초과=드림장",
            "link": "#card-sp500",
        }

    # 3. VIX — <15 = 공포소멸 경계 (공포역설)
    def card_vix():
        pairs = _series_pairs(_load_chart("vix"))
        last = _latest(pairs)
        if last is None:
            return None
        val = last[1]
        if val < 15:
            state, badge, cap = "warn", "공포소멸", "15 미만 = 공포소멸 경계 (공포역설: 모두가 안심할 때가 위험)"
        elif val >= 30:
            state, badge, cap = "alert", "공포", "30 이상 = 패닉 구간"
        else:
            state, badge, cap = "neutral", "보통", "15~30 정상 범위 (15 미만이 공포역설 경계)"
        return {
            "id": "vix", "label": "VIX", "value": round(val, 2), "unit": "",
            "d1": _d1_pct(pairs), "state": state, "badge": badge,
            "caption": cap, "link": "#card-vix",
        }

    # 4. MOVE — 낮음 = 채권시장 정온
    def card_move():
        pairs = _series_pairs(_load_chart("move_index"))
        last = _latest(pairs)
        if last is None:
            return None
        val = last[1]
        if val < 80:
            state, badge = "good", "정온"
        elif val < 110:
            state, badge = "neutral", "보통"
        else:
            state, badge = "alert", "불안"
        return {
            "id": "move", "label": "MOVE", "value": round(val, 1), "unit": "",
            "d1": _d1_pct(pairs), "state": state, "badge": badge,
            "caption": "낮음 = 채권시장 정온 (금리 변동성)", "link": "#card-move_index",
        }

    # 5. 달러 인덱스
    def card_dxy():
        pairs = _series_pairs(_load_chart("dxy"))
        last = _latest(pairs)
        if last is None:
            return None
        return {
            "id": "dxy", "label": "달러 인덱스", "value": round(last[1], 2), "unit": "",
            "d1": _d1_pct(pairs), "state": "neutral", "badge": "",
            "caption": "DXY — 달러 강세=신흥국·원자재 역풍", "link": "#card-dxy",
        }

    # 6. USD/KRW
    def card_usdkrw():
        pairs = _series_pairs(_load_chart("usdkrw"))
        last = _latest(pairs)
        if last is None:
            return None
        return {
            "id": "usdkrw", "label": "USD/KRW", "value": round(last[1], 1), "unit": "원",
            "d1": _d1_pct(pairs), "state": "neutral", "badge": "",
            "caption": "원/달러 환율", "link": "#card-usdkrw",
        }

    # 7. 구리/금 비율 — 3개월 방향 (건들락)
    def card_copper_gold():
        pairs = _series_pairs(_load_chart("copper"), "구리/금")
        last = _latest(pairs)
        if last is None:
            return None
        chg3m = _chg_3m_pct(pairs)
        chg_txt = f"{chg3m:+.1f}%" if chg3m is not None else "n/a"
        return {
            "id": "copper_gold", "label": "구리/금 비율", "value": round(last[1], 3), "unit": "",
            "d1": _d1_pct(pairs), "state": "neutral", "badge": _arrow(chg3m),
            "caption": f"3개월 {_arrow(chg3m)} {chg_txt} — 상승=성장·금리 상방 (건들락)",
            "link": "#card-copper",
        }

    # 8. 크레딧 (HYG/LQD) — 하락 = 크레딧 스트레스
    def card_credit():
        pairs = _series_pairs(_load_chart("credit_proxy"))
        last = _latest(pairs)
        if last is None:
            return None
        chg3m = _chg_3m_pct(pairs)
        chg_txt = f"{chg3m:+.1f}%" if chg3m is not None else "n/a"
        if chg3m is not None and chg3m <= -2:
            state, badge = "warn", "스트레스"
        else:
            state, badge = "good", "정온"
        return {
            "id": "credit", "label": "크레딧 HYG/LQD", "value": round(last[1], 4), "unit": "",
            "d1": _d1_pct(pairs), "state": state, "badge": badge,
            "caption": f"3개월 {_arrow(chg3m)} {chg_txt} — 하락=크레딧 스트레스",
            "link": "#card-credit_proxy",
        }

    # 9. 로테이션 신호 — 로테이션(한국 주도주 장세) 끝 판정 종합 배지.
    #    체크리스트(단순 규칙): ①외국인 주간 순매도 4주 이상 연속 ②KOSPI 50일선
    #    거래량 동반 붕괴 ③VKOSPI 급등. 충족 0개=🟢유지 / 1개=🟡주의 / 2개 이상=🔴끝.
    #    ③은 vkospi.json이 있을 때만 평가 (현재 무키 소스 없음 → 2개 조건으로 판정).
    def card_rotation():
        frn = _series_pairs(_load_chart("kr_foreign_flow"), "외국인 일별")
        rot = _load_chart("kr_rotation_check")
        kospi = _series_pairs(rot, "KOSPI")
        ma50 = _series_pairs(rot, "50일선")
        vol = _series_pairs(rot, "거래량")
        if not frn or not kospi or not ma50:
            return None

        # ① 외국인 주간(ISO주) 순매수 합계 → 최신 주부터 거꾸로 연속 순매도 주 수
        weekly: dict[tuple[int, int], float] = {}
        for d, v in frn:
            if v is None:
                continue
            iso = datetime.strptime(d, "%Y-%m-%d").isocalendar()
            weekly[(iso[0], iso[1])] = weekly.get((iso[0], iso[1]), 0.0) + float(v)
        neg_weeks = 0
        for _, wsum in sorted(weekly.items(), reverse=True):
            if wsum < 0:
                neg_weeks += 1
            else:
                break
        cond_foreign = neg_weeks >= 4

        # ② 50일선 하회 + 거래량 동반 (최근 5일 평균 거래량 > 20일 평균)
        k_last, m_last = _latest(kospi), _latest(ma50)
        below_ma = k_last[1] < m_last[1] if (k_last and m_last) else False
        vols = [v for _, v in vol if v is not None]
        vol_up = (len(vols) >= 20 and
                  sum(vols[-5:]) / 5 > sum(vols[-20:]) / 20)
        cond_break = below_ma and vol_up

        conds = [cond_foreign, cond_break]

        # ③ VKOSPI 급등 (데이터 있을 때만): 최신값이 60일 평균 대비 +30% 이상
        vk = _series_pairs(_load_chart("vkospi"))
        vk_txt = ""
        if vk:
            vk_vals = [v for _, v in vk if v is not None]
            if len(vk_vals) >= 60:
                vk_avg = sum(vk_vals[-60:]) / 60
                cond_vk = vk_avg > 0 and vk_vals[-1] / vk_avg >= 1.3
                conds.append(cond_vk)
                vk_txt = f" · VKOSPI {'급등' if cond_vk else '안정'}"

        n_hit = sum(conds)
        if n_hit == 0:
            state, badge = "good", "유지"
        elif n_hit == 1:
            state, badge = "warn", "주의"
        else:
            state, badge = "alert", "끝 경보"

        caption = (
            f"외인 순매도 {neg_weeks}주 연속(기준 4주)"
            f" · 50일선 {'하회' if below_ma else '상회'}"
            f"·거래량 {'급증' if vol_up else '보통'}{vk_txt}"
            f" — 충족 {n_hit}개 (1개=주의/2개+=끝)"
        )
        return {
            "id": "rotation", "label": "로테이션 신호", "value": neg_weeks, "unit": "주",
            "d1": None, "state": state, "badge": badge,
            "caption": caption, "link": "#card-kr_foreign_flow",
        }

    # 10. 공포·탐욕 (KOSPI) — 수급 가중 자체 산식 (kr_fear_greed.json, 산식은 CONTRACT 참조).
    #     역지표 판정: 극탐욕 진입+지속=alert(C2 버블 심리), 극공포=warn(매수 후보 점검),
    #     공포=good(불안 생존=버블 아님), 중립/탐욕=neutral/warn. VIX 카드(미국 심리)와 상보.
    def card_kr_fear_greed():
        pairs = _series_pairs(_load_chart("kr_fear_greed"))
        last = _latest(pairs)
        if last is None:
            return None
        val = last[1]
        if val < 25:
            state, badge, action = "warn", "극공포", "매수 후보 점검"
        elif val < 45:
            state, badge, action = "good", "공포", "불안 생존=버블 아님"
        elif val <= 55:
            state, badge, action = "neutral", "중립", "관망"
        elif val <= 75:
            state, badge, action = "warn", "탐욕", "극탐욕 진입 감시"
        else:
            state, badge, action = "alert", "극탐욕", "장기화 시 단계적 매도 준비"
        return {
            "id": "kr_fear_greed", "label": "공포·탐욕", "value": round(val, 1), "unit": "pt",
            "d1": _d1_pct(pairs), "state": state, "badge": badge,
            "caption": (
                f"{badge}({val:.0f}) — 수급 가중 KOSPI 심리(외인35%·기관20%) · "
                f"극공포<25/극탐욕>75 · {action} · VIX(미국 심리)와 상보"
            ),
            "link": "#card-kr_fear_greed",
        }

    # 11. 버블 체크리스트 종합 — build_bubble()이 먼저 만든 bubble_checklist.json 재료.
    #     value = 🔴 개수. 🔴 2개+=alert / 🔴 1개 or 🟡 2개+=warn / 그 외=good.
    def card_bubble():
        bb = _load_chart("bubble_checklist")
        if not bb or not bb.get("overall"):
            return None
        o = bb["overall"]
        n_red, n_warn = o.get("red", 0), o.get("warn", 0)
        if n_red >= 2:
            state = "alert"
        elif n_red == 1 or n_warn >= 2:
            state = "warn"
        else:
            state = "good"
        parts = " ".join(f"{it['emoji']}{it['label']}" for it in bb.get("items", []))
        judged = o.get("judged", 0)
        na_txt = "" if judged >= o.get("total", 5) else f" · 판정가능 {judged}/{o.get('total', 5)}"
        return {
            "id": "bubble", "label": "버블 체크리스트", "value": n_red, "unit": "/5",
            "d1": None, "state": state, "badge": o.get("label", f"정점 근접도 {n_red}/5"),
            "caption": f"{parts} — 🔴 2개 이상=정점 경보{na_txt} (김성환 버블 템플릿)",
            "link": "#card-margin_debt",
        }

    for builder in (card_us10y, card_rate_scenario, card_spx_band, card_vix, card_move,
                    card_dxy, card_usdkrw, card_copper_gold, card_credit,
                    card_rotation, card_kr_fear_greed, card_bubble):
        try:
            add(builder())
        except Exception as e:
            logger.warning(f"[SNAPSHOT] {builder.__name__} 계산 실패 → skip: {e}")

    return {"updated": now, "cards": cards}


# ─────────────────────────────────────────────────────────────
# 버블 체크리스트 (data/bubble_checklist.json) — 미국 증시 버블 정점 5지표 자동판정.
# 논지: 신한투자증권 김성환 "버블 템플릿: 2026-2027 미국 증시 버블 시나리오" (2025-08-19).
# snapshot과 동일 원칙: 모든 차트 fetch 후 data/*.json에서만 계산 (추가 네트워크 없음).
# 재료 없는 지표는 state:"na"(⚪ 판정 불가) — 배열에서 빼지 않는다 (5지표 고정 표시).
# 규격은 CONTRACT.md "bubble_checklist.json" 참조.
# ─────────────────────────────────────────────────────────────

BUBBLE_STATE_EMOJI = {"good": "🟢", "warn": "🟡", "alert": "🔴", "na": "⚪"}


def _month_end_values(pairs: list) -> list[float]:
    """일별 pairs → 월말(각 월 마지막 데이터) 값 리스트, 월 오름차순."""
    by_month: dict[str, float] = {}
    for d, v in pairs:
        if v is not None:
            by_month[d[:7]] = float(v)
    return [by_month[m] for m in sorted(by_month)]


def build_bubble(now: str) -> dict[str, Any]:
    """생성된 data/*.json에서 버블 체크리스트 5지표 판정을 계산."""
    items: list[dict[str, Any]] = []

    # ① 신용매수 — margin_debt의 '2년 저점 대비 상승률' 최신값. +50%↑🟡 / +80%↑🔴
    def judge_margin():
        pairs = _series_pairs(_load_chart("margin_debt"), "2년 저점")
        last = _latest(pairs)
        if last is None:
            return None
        rise = last[1]
        state = "alert" if rise >= 80 else ("warn" if rise >= 50 else "good")
        return {
            "state": state, "value": round(rise, 1), "unit": "%",
            "caption": f"margin debt 2년 저점 대비 {rise:+.1f}% (기준 +50/+80 · 과거 정점 +90~100%)",
        }

    # ② IPO 붐 — ipo_rs의 '6개월 변화율' 최신값. +20%↑🟡 / +40%↑🔴
    def judge_ipo():
        pairs = _series_pairs(_load_chart("ipo_rs"), "6개월")
        last = _latest(pairs)
        if last is None:
            return None
        chg = last[1]
        state = "alert" if chg >= 40 else ("warn" if chg >= 20 else "good")
        return {
            "state": state, "value": round(chg, 1), "unit": "%",
            "caption": f"IPO/S&P500 상대강도 6개월 {chg:+.1f}% (기준 +20/+40)",
        }

    # ③ 투기 강세 — arkk_rs 상대강도의 월간 연속 아웃퍼폼 개월 수.
    #    6개월↑ 연속=🟡 / 10개월↑(≈12개월 가까이) 연속 + 6개월 +40%↑ 급등=🔴
    def judge_arkk():
        pairs = _series_pairs(_load_chart("arkk_rs"), "상대강도")
        if not pairs:
            return None
        monthly = _month_end_values(pairs)
        if len(monthly) < 2:
            return None
        streak = 0
        for i in range(len(monthly) - 1, 0, -1):
            if monthly[i] > monthly[i - 1]:
                streak += 1
            else:
                break
        # 급등 판정: 상대강도 6개월(~183일) 변화율
        from datetime import timedelta
        last_d, last_v = pairs[-1][0], float(pairs[-1][1])
        base_dt = datetime.strptime(last_d, "%Y-%m-%d") - timedelta(days=183)
        base = None
        for d, v in pairs:
            if v is None:
                continue
            if datetime.strptime(d, "%Y-%m-%d") <= base_dt:
                base = float(v)
            else:
                break
        chg6m = (last_v / base - 1) * 100 if base else None
        surge = chg6m is not None and chg6m >= 40
        if streak >= 10 and surge:
            state = "alert"
        elif streak >= 6:
            state = "warn"
        else:
            state = "good"
        chg_txt = f"{chg6m:+.1f}%" if chg6m is not None else "n/a"
        return {
            "state": state, "value": streak, "unit": "개월",
            "caption": (
                f"ARKK/S&P500 월간 연속 아웃퍼폼 {streak}개월 · 6개월 {chg_txt} "
                "(6개월↑=🟡 / 10개월↑+급등 40%↑=🔴)"
            ),
        }

    # ④ 연준 긴축 전환 — FEDFUNDS 월간. 인하/동결=🟢 /
    #    최근 3개월 바닥 대비 +25bp=🟡 / 인하 사이클(-50bp↑) 후 인상 전환(+25bp↑) 확정=🔴
    def judge_fed():
        pairs = _series_pairs(_load_chart("fed_funds"))
        vals = [float(v) for _, v in pairs if v is not None]
        if len(vals) < 4:
            return None
        latest = vals[-1]
        win24 = vals[-24:] if len(vals) >= 24 else vals
        trough = min(win24)
        trough_pos = len(vals) - len(win24) + win24.index(trough)
        pre = vals[max(0, trough_pos - 36):trough_pos + 1]
        cut_cycle = pre and (max(pre) - trough) >= 0.5      # 정점→바닥 -50bp 이상 = 인하 사이클
        hike_confirmed = (latest - trough) >= 0.25          # 바닥 대비 +25bp = 인상 전환
        low3 = min(vals[-3:])
        if cut_cycle and hike_confirmed:
            state, txt = "alert", "인하 사이클 후 인상 전환 확정"
        elif (latest - low3) >= 0.25:
            state, txt = "warn", "3개월 바닥 대비 +25bp — 인상 논의 국면"
        else:
            state, txt = "good", "인하/동결 지속"
        return {
            "state": state, "value": round(latest, 2), "unit": "%",
            "caption": f"FEDFUNDS {latest:.2f}% · 24개월 바닥 {trough:.2f}% — {txt}",
        }

    # ⑤ 공급과잉/마진 하락 — Capex YoY 플러스인데 마진 프록시(CP/GDP)가
    #    2분기 연속 하락=🔴 / 최근 1분기 하락=🟡 / 그 외=🟢
    def judge_capex():
        chart = _load_chart("capex_margin")
        capex = _series_pairs(chart, "YoY")   # "비국방자본재 수주 YoY"
        margin = _series_pairs(chart, "마진")  # "기업이익마진 프록시 (CP/GDP)"
        capex_last = _latest(capex)
        m_vals = [float(v) for _, v in margin if v is not None]
        if capex_last is None or len(m_vals) < 3:
            return None
        capex_pos = capex_last[1] > 0
        d1 = m_vals[-1] < m_vals[-2]
        d2 = m_vals[-2] < m_vals[-3]
        if capex_pos and d1 and d2:
            state, txt = "alert", "투자 확장 중 마진 2분기 연속 하락 — 공급과잉 신호"
        elif d1:
            state, txt = "warn", "마진 프록시 1분기 하락"
        else:
            state, txt = "good", "마진 유지"
        return {
            "state": state, "value": round(m_vals[-1], 2), "unit": "%",
            "caption": (
                f"Capex YoY {capex_last[1]:+.1f}% · CP/GDP {m_vals[-1]:.2f}% — {txt}"
            ),
        }

    judges = [
        ("margin_debt",  "신용매수",   judge_margin),
        ("ipo_rs",       "IPO 붐",     judge_ipo),
        ("arkk_rs",      "투기 강세",  judge_arkk),
        ("fed_funds",    "긴축 전환",  judge_fed),
        ("capex_margin", "공급과잉",   judge_capex),
    ]
    for chart_id, label, fn in judges:
        result = None
        try:
            result = fn()
        except Exception as e:
            logger.warning(f"[BUBBLE] {chart_id} 판정 실패 → 판정 불가: {e}")
        if result is None:
            result = {"state": "na", "value": None, "unit": "",
                      "caption": "데이터 없음 — 판정 불가"}
        items.append({
            "chart": chart_id,
            "label": label,
            "state": result["state"],
            "emoji": BUBBLE_STATE_EMOJI[result["state"]],
            "value": result.get("value"),
            "unit": result.get("unit", ""),
            "caption": result["caption"],
        })

    n_red = sum(1 for it in items if it["state"] == "alert")
    n_warn = sum(1 for it in items if it["state"] == "warn")
    judged = sum(1 for it in items if it["state"] != "na")
    overall = {
        "red": n_red,
        "warn": n_warn,
        "judged": judged,
        "total": len(items),
        "label": f"정점 근접도 {n_red}/{len(items)}",
    }
    return {"updated": now, "overall": overall, "items": items}


# ─────────────────────────────────────────────────────────────
# 캘린더 (data/calendar.json) — "이번 주 일정+실적" 카드 (아침 검증 ⑥).
# A. 경제지표/회의 = pipeline/econ_calendar_*.json (정적 연간 일정, 연 1회 채록)
# B. 관심종목 실적 = yfinance (실패 종목 skip)
# 오늘부터 +14일 이벤트만. 규격은 CONTRACT.md "calendar.json" 참조.
# ─────────────────────────────────────────────────────────────

def build_calendar(now: str) -> dict[str, Any]:
    try:
        from fetch_calendar import fetch_calendar_events
    except ImportError:
        sys.path.insert(0, str(PIPELINE_DIR))
        from fetch_calendar import fetch_calendar_events

    result = fetch_calendar_events()
    if result["earnings_skip"]:
        logger.info(f"[CALENDAR] 실적일 미확보 skip: {', '.join(result['earnings_skip'])}")
    return {"updated": now, "events": result["events"]}


def run() -> None:
    now = _now_kst()
    logger.info(f"=== Chartbook 파이프라인 시작 ({now}) ===")

    chart_results: list[dict[str, Any]] = []  # {"id": ..., "ready": bool, "reason": ...}
    written: list[str] = []
    skipped: list[str] = []

    # ─── Yahoo Finance 차트 수집 ─────────────────────────────────
    try:
        from fetch_yahoo import (
            fetch_sp500, fetch_kospi, fetch_vix, fetch_sectors,
            fetch_ust_yields, fetch_yield_spread, fetch_yield_curve,
            fetch_credit_proxy,
            fetch_usdkrw, fetch_dxy, fetch_gold, fetch_wti, fetch_copper,
            fetch_ipo_rs, fetch_arkk_rs,
        )
        from fetch_leesunyeop import (
            fetch_ls_rate_peak, fetch_ls_semi_vs_power, fetch_ls_memory_cycle,
            fetch_ls_taiwan_hedge, fetch_ls_ship_defense, fetch_move_index,
        )
        from fetch_kr_flow import (
            fetch_kr_foreign_flow, fetch_kr_rotation_check, fetch_kr_fear_greed,
        )
        from fetch_multpl import fetch_all_multpl
        from fetch_finra import fetch_margin_debt
    except ImportError:
        # run.py가 다른 디렉토리에서 실행될 때를 대비
        sys.path.insert(0, str(PIPELINE_DIR))
        from fetch_yahoo import (
            fetch_sp500, fetch_kospi, fetch_vix, fetch_sectors,
            fetch_ust_yields, fetch_yield_spread, fetch_yield_curve,
            fetch_credit_proxy,
            fetch_usdkrw, fetch_dxy, fetch_gold, fetch_wti, fetch_copper,
            fetch_ipo_rs, fetch_arkk_rs,
        )
        from fetch_leesunyeop import (
            fetch_ls_rate_peak, fetch_ls_semi_vs_power, fetch_ls_memory_cycle,
            fetch_ls_taiwan_hedge, fetch_ls_ship_defense, fetch_move_index,
        )
        from fetch_kr_flow import (
            fetch_kr_foreign_flow, fetch_kr_rotation_check, fetch_kr_fear_greed,
        )
        from fetch_multpl import fetch_all_multpl
        from fetch_finra import fetch_margin_debt

    # ─── multpl.com 먼저 수집 (sp500 밸류밴드 재료 = EPS TTM) ───
    # sp500 승격판이 EPS×15/18/21 밴드를 그리므로 yahoo 루프보다 앞서 실행.
    # multpl 실패 시 eps_pairs=None → fetch_sp500이 200D MA로 폴백 (파이프라인 무사).
    multpl_results = fetch_all_multpl()
    eps_pairs = None
    eps_result = multpl_results.get("sp500_eps") or {}
    if not eps_result.get("_skip"):
        eps_series = eps_result.get("series") or []
        if eps_series:
            eps_pairs = eps_series[0].get("data")

    yahoo_fetchers = [
        ("sp500",         lambda: fetch_sp500(eps_pairs=eps_pairs)),
        ("kospi",         fetch_kospi),
        ("vix",           fetch_vix),
        ("sectors",       fetch_sectors),
        ("ust_yields",    fetch_ust_yields),
        ("yield_spread",  fetch_yield_spread),
        ("yield_curve",   fetch_yield_curve),
        ("credit_proxy",  fetch_credit_proxy),
        # 환율
        ("usdkrw",        fetch_usdkrw),
        ("dxy",           fetch_dxy),
        # 원자재
        ("gold",          fetch_gold),
        ("wti",           fetch_wti),
        ("copper",        fetch_copper),
        # 이선엽 체인 (framework §7)
        ("ls_rate_peak",     fetch_ls_rate_peak),
        ("ls_semi_vs_power", fetch_ls_semi_vs_power),
        ("ls_memory_cycle",  fetch_ls_memory_cycle),
        ("ls_taiwan_hedge",  fetch_ls_taiwan_hedge),
        ("ls_ship_defense",  fetch_ls_ship_defense),
        ("move_index",       fetch_move_index),
        # 수급 (kr_foreign_flow=Naver, kr_rotation_check=Yahoo — fetch_kr_flow.py)
        # kr_fear_greed는 앞 둘의 모듈 캐시(Naver 표+^KS11)를 재사용 — 추가 네트워크 없음
        ("kr_foreign_flow",   fetch_kr_foreign_flow),
        ("kr_rotation_check", fetch_kr_rotation_check),
        ("kr_fear_greed",     fetch_kr_fear_greed),
        # 버블 체크리스트 ②③ (yahoo) + ① (FINRA — fetch_finra.py, 키 불필요)
        ("ipo_rs",            fetch_ipo_rs),
        ("arkk_rs",           fetch_arkk_rs),
        ("margin_debt",       fetch_margin_debt),
    ]

    for chart_id, fetcher in yahoo_fetchers:
        try:
            data = fetcher()
            out_path = DATA_DIR / f"{chart_id}.json"
            write_json(out_path, data)
            chart_results.append({"id": chart_id, "ready": True})
            written.append(chart_id)
            logger.info(f"[OK] {chart_id} → {out_path}")
        except Exception as e:
            logger.error(f"[FAIL] {chart_id}: {e}")
            chart_results.append({"id": chart_id, "ready": False, "reason": str(e)})
            skipped.append(f"{chart_id} (수집 오류: {e})")

    # ─── 수집 결과 처리 헬퍼 ────────────────────────────────────
    def process_results(source_results: dict) -> None:
        """{chart_id: result|skip} 딕셔너리를 받아 파일 저장 + 상태 기록."""
        for chart_id, result in source_results.items():
            if result.get("_skip"):
                reason = result.get("_reason", "알 수 없는 이유")
                logger.info(f"[SKIP] {chart_id}: {reason}")
                chart_results.append({"id": chart_id, "ready": False, "reason": reason})
                skipped.append(f"{chart_id} ({reason})")
            else:
                out_path = DATA_DIR / f"{chart_id}.json"
                write_json(out_path, result)
                chart_results.append({"id": chart_id, "ready": True})
                written.append(chart_id)
                logger.info(f"[OK] {chart_id} → {out_path}")

    # ─── multpl.com 차트 결과 반영 (valuation_pe, sp500_eps) ───
    # 실제 수집은 위(yahoo 루프 전)에서 완료 — sp500 밸류밴드 재료 공유.
    process_results(multpl_results)

    # ─── FRED 차트 수집 (credit_hy_oas) ─────────────────────────
    try:
        from fetch_fred import fetch_all_fred
    except ImportError:
        sys.path.insert(0, str(PIPELINE_DIR))
        from fetch_fred import fetch_all_fred

    process_results(fetch_all_fred())

    # ─── index.json 생성 ────────────────────────────────────────
    index_data = build_index(chart_results, now)
    index_path = DATA_DIR / "index.json"
    write_json(index_path, index_data)
    logger.info(f"[OK] index.json → {index_path}")

    # ─── bubble_checklist.json 생성 (버블 정점 5지표 자동판정) ──
    # snapshot보다 먼저 — snapshot의 '버블 체크리스트' 카드가 이 파일을 재료로 쓴다.
    try:
        bubble = build_bubble(now)
        bubble_path = DATA_DIR / "bubble_checklist.json"
        write_json(bubble_path, bubble)
        logger.info(f"[OK] bubble_checklist.json ({bubble['overall']['label']}) → {bubble_path}")
    except Exception as e:
        logger.error(f"[FAIL] bubble_checklist.json: {e}")

    # ─── snapshot.json 생성 (아침 스냅샷 보드) ──────────────────
    try:
        snapshot = build_snapshot(now)
        snapshot_path = DATA_DIR / "snapshot.json"
        write_json(snapshot_path, snapshot)
        logger.info(f"[OK] snapshot.json ({len(snapshot['cards'])}카드) → {snapshot_path}")
    except Exception as e:
        logger.error(f"[FAIL] snapshot.json: {e}")

    # ─── calendar.json 생성 (이번 주 일정+실적 카드) ────────────
    try:
        calendar = build_calendar(now)
        calendar_path = DATA_DIR / "calendar.json"
        write_json(calendar_path, calendar)
        logger.info(f"[OK] calendar.json ({len(calendar['events'])}이벤트) → {calendar_path}")
    except Exception as e:
        logger.error(f"[FAIL] calendar.json: {e}")

    # ─── 결과 요약 출력 ──────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"Chartbook 파이프라인 완료  {now}")
    print("=" * 60)
    print(f"\n✔ 성공 ({len(written)}개): {', '.join(written) if written else '없음'}")
    print(f"\n✗ 건너뜀 ({len(skipped)}개):")
    for s in skipped:
        print(f"   - {s}")
    print(f"\n데이터 경로: {DATA_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    run()

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
        {"id": "vix",          "file": "vix.json",          "type": "timeseries",   "section": "리스크", "daily": True, "daily_order": 4},
        {"id": "sectors",      "file": "sectors.json",      "type": "heatmap_perf", "section": "섹터"},
        {"id": "valuation_pe", "file": "valuation_pe.json", "type": "timeseries",   "section": "밸류에이션"},
        {"id": "sp500_eps",    "file": "sp500_eps.json",    "type": "timeseries",   "section": "밸류에이션"},
        # buffett: Valley AI 링크(valley_buffett_link)로 대체 — RETIRED_IDS 참조.
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
# 스냅샷 보드 (data/snapshot.json) — "아침 10초 확인"용 카드 8개.
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
    """생성된 data/*.json에서 아침 스냅샷 카드 8개를 계산."""
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

    for builder in (card_us10y, card_spx_band, card_vix, card_move,
                    card_dxy, card_usdkrw, card_copper_gold, card_credit):
        try:
            add(builder())
        except Exception as e:
            logger.warning(f"[SNAPSHOT] {builder.__name__} 계산 실패 → skip: {e}")

    return {"updated": now, "cards": cards}


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
        )
        from fetch_leesunyeop import (
            fetch_ls_rate_peak, fetch_ls_semi_vs_power, fetch_ls_memory_cycle,
            fetch_ls_taiwan_hedge, fetch_ls_ship_defense, fetch_move_index,
        )
        from fetch_multpl import fetch_all_multpl
    except ImportError:
        # run.py가 다른 디렉토리에서 실행될 때를 대비
        sys.path.insert(0, str(PIPELINE_DIR))
        from fetch_yahoo import (
            fetch_sp500, fetch_kospi, fetch_vix, fetch_sectors,
            fetch_ust_yields, fetch_yield_spread, fetch_yield_curve,
            fetch_credit_proxy,
            fetch_usdkrw, fetch_dxy, fetch_gold, fetch_wti, fetch_copper,
        )
        from fetch_leesunyeop import (
            fetch_ls_rate_peak, fetch_ls_semi_vs_power, fetch_ls_memory_cycle,
            fetch_ls_taiwan_hedge, fetch_ls_ship_defense, fetch_move_index,
        )
        from fetch_multpl import fetch_all_multpl

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
            skipped.append(f"{chart_id} (Yahoo 오류: {e})")

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

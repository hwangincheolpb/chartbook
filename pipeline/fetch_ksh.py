"""
fetch_ksh.py — 김성환 프레임워크 파생 데이터 수집 모듈

김성환(신한투자증권) 버블 템플릿의 시그니처 차트 2종을 실데이터로 재구성한다.
산출물은 chartbook 프론트가 렌더하는 차트가 아니라 **김성환 대시보드
(~/workspace/dev/kimsunghwan-framework/build_dashboard.py) 전용 피드**다.
→ index.json에 등록하지 않는다 (CONTRACT.md "ksh_* 파생 데이터" 절 참조).

1) ksh_ai_dotcom  — 사이클 오버레이 4선 (2026 PB교육 p3 원본 구성):
   광란의 20년대(다우 1924.7~1932.6) / 닷컴(나스닥 1995.1~2001.6) /
   클라우드·FANG(나스닥 2016.7~2021.12) / AI(나스닥 2023.1~현재).
   각 시작=100 리베이스, x=시작 후 개월수.
2) ksh_ratecut_traj — 사이클 마지막 금리인하일(T)=100 리베이스, x=T 후 개월수(0~30)
   ①1927-08-05(대공황 — 뉴욕연은 재할인율 3.5→3.0%, 버블템플릿 p45) ②1998-10-15(닷컴)
   ③2020-03-16(팬데믹) ④현재 사이클(FRED에서 최근 인하일 자동 탐지 — "잠정 T")

서버 예의: ^IXIC 다운로드는 3회(1995-2001 / 2016-2022 / 2020-현재)로 묶고 모듈 캐시 공유.
DJIA 역사(1920년대)는 stooq CSV 시도 → 실패 시 FRED NBER 매크로히스토리
(M1109BUSM293NNBR, 월평균, 키리스) 폴백 → 둘 다 실패하면 해당 시리즈/케이스만 생략(방어적).
FRED는 fredgraph.csv(키 불필요) — DFEDTARU 1회(폴백 FEDFUNDS 1회 추가) + DJIA 1회.
"""

import logging
from datetime import datetime
from typing import Any

import pandas as pd
import pytz

from fetch_yahoo import _download
from fetch_fred import _fetch_series_keyless

logger = logging.getLogger(__name__)

KST = pytz.timezone("Asia/Seoul")

# 1개월 = 30.4375일 (365.25/12) — x축 "개월수" 환산 계수
_MONTH_DAYS = 30.4375

# 과거 케이스의 마지막 인하 → 지수 정점까지 평균 개월수.
# 대공황: 1927-08-05 → 1929-09 정점 ≈ 25개월(월평균 기준) / 닷컴: 1998-10-15 → 2000-03-10 ≈ 17개월
# / 팬데믹: 2020-03-16 → 2021-11-19 ≈ 20개월.
# 김성환 리포트(버블 템플릿 p45, 3Q26 전략)는 "평균 21개월"을 수직 기준선으로 사용 → 그대로 채택.
AVG_PEAK_MONTHS = 21

# ^IXIC 다운로드 모듈 캐시 — 두 fetcher가 같은 구간을 공유 (요청 3회로 억제)
_IXIC_CACHE: dict[tuple[str, str], pd.Series] = {}


def _now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%dT%H:%M:%S+09:00")


def _ixic(start: str, end: str) -> pd.Series:
    """나스닥종합(^IXIC) 일별 종가. 같은 구간은 모듈 캐시 재사용."""
    key = (start, end)
    if key not in _IXIC_CACHE:
        logger.info(f"  ^IXIC 다운로드: {start} ~ {end}")
        df = _download(["^IXIC"], start, end)
        col = df["^IXIC"] if "^IXIC" in df.columns else df.iloc[:, 0]
        _IXIC_CACHE[key] = col.dropna()
    return _IXIC_CACHE[key]


def _ixic_window(t0: str, t1: str) -> pd.Series:
    """캐시된 세 구간(1995-2001 / 2016-2022 / 2020-현재)에서 [t0, t1] 창을 잘라 반환."""
    today = datetime.today().strftime("%Y-%m-%d")
    if t0 < "2002-01-01":
        base = _ixic("1995-01-01", "2001-07-01")
    elif t0 < "2020-01-01":
        base = _ixic("2016-07-01", "2022-01-10")
    else:
        base = _ixic("2020-03-01", today)
    return base[(base.index >= t0) & (base.index <= t1)]


# ─── DJIA 역사 데이터 (광란의 20년대 / 1927 케이스) ──────────────
_DJIA_CACHE: dict[str, Any] = {}


def _djia_early() -> tuple[pd.Series | None, str]:
    """
    1920~30년대 DJIA. 반환 (Series|None, 소스 설명).
    1순위 stooq 무료 CSV(^dji 일별, 1896~) — 단 stooq는 JS 안티봇 챌린지를
    켤 때가 있어 실패 가능(2026-07 확인). 2순위 FRED NBER 매크로히스토리
    M1109BUSM293NNBR(다우 월평균, 1914-1968, 키리스). 둘 다 실패하면 None
    — 호출부는 해당 시리즈/케이스만 생략하고 파이프라인은 계속.
    """
    if "djia" in _DJIA_CACHE:
        return _DJIA_CACHE["djia"], _DJIA_CACHE["src"]
    out: pd.Series | None = None
    src = ""
    # 1) stooq 일별 CSV
    try:
        import requests
        resp = requests.get(
            "https://stooq.com/q/d/l/?s=^dji&i=d",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=30,
        )
        resp.raise_for_status()
        lines = resp.text.strip().splitlines()
        if lines and lines[0].lower().startswith("date"):
            records = {}
            for line in lines[1:]:
                parts = line.split(",")
                if len(parts) >= 5:
                    try:
                        records[parts[0]] = float(parts[4])  # Close
                    except ValueError:
                        continue
            if records:
                s = pd.Series(records)
                s.index = pd.to_datetime(s.index)
                out, src = s.sort_index(), "Stooq (DJIA 일별)"
                logger.info(f"  DJIA(stooq): {len(out)}개 포인트")
        if out is None:
            raise ValueError("stooq CSV 형식 아님 (안티봇 챌린지 추정)")
    except Exception as e:
        logger.warning(f"  DJIA stooq 실패 → FRED NBER 폴백: {e}")
        # 2) FRED NBER 매크로히스토리 (월평균, 키리스)
        try:
            out = _fetch_series_keyless("M1109BUSM293NNBR",
                                        observation_start="1914-01-01")
            src = "FRED NBER (DJIA 월평균, M1109BUSM293NNBR)"
            logger.info(f"  DJIA(FRED NBER, 월간): {len(out)}개 포인트")
        except Exception as e2:
            logger.warning(f"  DJIA FRED 폴백도 실패 → 1920년대 시리즈 생략: {e2}")
            out, src = None, "없음 (stooq·FRED 모두 실패)"
    _DJIA_CACHE["djia"], _DJIA_CACHE["src"] = out, src
    return out, src


def _rebase_weekly_pairs(daily: pd.Series, t0: pd.Timestamp,
                         max_months: float | None = None) -> list[list]:
    """
    t0 이후 첫 값=100으로 리베이스한 뒤 주간(금요일 마지막 값)으로 리샘플.
    월간 데이터(FRED NBER)가 들어와도 동작 — 리샘플 후 결측 주는 드롭되어 월간 간격 유지.
    반환: [[t0 이후 개월수(float), 리베이스값], ...] — x=0(첫 값) 포함.
    """
    s = daily[daily.index >= t0]
    if s.empty:
        raise ValueError(f"리베이스 구간에 데이터 없음 (t0={t0.date()})")
    base = float(s.iloc[0])
    rebased = s / base * 100.0
    weekly = rebased.resample("W-FRI").last().dropna()
    # x=0 기준점(첫 값)이 주간 리샘플에 묻히지 않게 선두에 보장
    if weekly.index[0] != s.index[0]:
        weekly = pd.concat([rebased.iloc[[0]], weekly])
    pairs = []
    for ts, v in weekly.items():
        m = (ts - t0).days / _MONTH_DAYS
        if max_months is not None and m > max_months:
            break
        pairs.append([round(m, 2), round(float(v), 2)])
    return pairs


# ─────────────────────────────────────────────────────────────
# 1) 사이클 궤적 오버레이 (광란의 20년대 · 닷컴 · 클라우드 · AI)
# ─────────────────────────────────────────────────────────────

def fetch_ksh_ai_dotcom() -> dict[str, Any]:
    """
    사이클 오버레이 4선 — AI(나스닥 2023.1~현재) vs 닷컴(나스닥 1995.1~2001.6)
    vs 클라우드·FANG(나스닥 2016.7~2021.12) vs 광란의 20년대(다우 1924.7~1932.6).
    각 시리즈 시작=100 리베이스, x=시작 후 개월수. 대시보드 전용 자유 스키마.
    광란의 20년대는 stooq/FRED 실패 시 생략(방어적).
    """
    logger.info("[KSH] 사이클 궤적 오버레이 수집 중...")
    today = datetime.today().strftime("%Y-%m-%d")

    specs = [
        # (name, t0, t1, kind) — kind: "ixic" | "djia"
        ("AI 사이클 (나스닥, 2023.1=100)", "2023-01-01", today, "ixic"),
        ("닷컴 사이클 (나스닥, 1995.1=100)", "1995-01-01", "2001-06-30", "ixic"),
        ("클라우드·FANG (나스닥, 2016.7=100)", "2016-07-01", "2021-12-31", "ixic"),
        ("광란의 20년대 (다우, 1924.7=100)", "1924-07-01", "1932-06-30", "djia"),
    ]

    djia, djia_src = _djia_early()

    series_out = []
    for name, t0_str, t1_str, kind in specs:
        try:
            if kind == "djia":
                if djia is None:
                    logger.warning(f"  {name}: DJIA 소스 없음 → 생략")
                    continue
                daily = djia[(djia.index >= t0_str) & (djia.index <= t1_str)]
            else:
                daily = _ixic_window(t0_str, t1_str)
            t0 = daily.index[0]  # 구간 첫 데이터일 = T0 (x=0)
            pairs = _rebase_weekly_pairs(daily, t0)
            last_ts = daily.index[-1]
            series_out.append({
                "name": name,
                "start": t0.strftime("%Y-%m-%d"),
                "end": last_ts.strftime("%Y-%m-%d"),
                "last": {
                    "months": round((last_ts - t0).days / _MONTH_DAYS, 1),
                    "value": round(float(daily.iloc[-1] / daily.iloc[0] * 100.0), 1),
                    "date": last_ts.strftime("%Y-%m-%d"),
                },
                "data": pairs,
            })
            logger.info(f"  {name}: {len(pairs)}포인트 (last={series_out[-1]['last']})")
        except Exception as e:
            logger.warning(f"  {name} 실패 → 생략: {e}")

    if not series_out:
        raise ValueError("ksh_ai_dotcom: 모든 시리즈 실패")

    return {
        "id": "ksh_ai_dotcom",
        "kind": "ksh_derived",          # chartbook 프론트 렌더 대상 아님 (CONTRACT 참조)
        "title": "기술혁신 사이클 궤적 오버레이 — AI vs 닷컴 vs 클라우드 vs 광란의 20년대",
        "subtitle": "각 사이클 시작=100 리베이스 · 주간 · x=시작 후 개월수 (2026 PB교육 p3 구성)",
        "source": f"Yahoo Finance (^IXIC) + {djia_src}",
        "x_unit": "개월 (사이클 시작 후)",
        "updated": _now_kst(),
        "meta": {
            # 닷컴 사이클에서 "본격 버블 국면" 참조 구간: T+4.5Y~5.2Y (=54~62.4개월,
            # 1999.7~2000.3 수직 상승기). AI 사이클 환산 시 2027년 중반~2028년 초.
            "bubble_ref_window_months": [54.0, 62.4],
            "bubble_ref_label": "본격 버블 국면(2027) — 닷컴 T+4.5~5.2Y 참조",
            "djia_source": djia_src,
        },
        "series": series_out,
    }


# ─────────────────────────────────────────────────────────────
# 2) 마지막 금리인하 → 정점 궤적
# ─────────────────────────────────────────────────────────────

def _detect_last_cut() -> tuple[str, str]:
    """
    현재 사이클의 최근 금리인하일 탐지. 반환 (YYYY-MM-DD, 탐지 소스 설명).
    1순위: FRED DFEDTARU(목표 상단, 일별) — 값이 내려간 마지막 날짜 = 인하 발효일.
    폴백: FRED FEDFUNDS(실효, 월평균) — 마지막으로 -5bp 이상 내린 달의 1일 (근사).
    """
    try:
        s = _fetch_series_keyless("DFEDTARU", observation_start="2024-01-01")
        drops = s.diff()
        cut_dates = drops[drops < -0.01].index
        if len(cut_dates) > 0:
            d = cut_dates[-1].strftime("%Y-%m-%d")
            return d, "FRED DFEDTARU(연방기금 목표 상단) 하향일"
        raise ValueError("DFEDTARU: 2024년 이후 인하 없음")
    except Exception as e:
        logger.warning(f"  DFEDTARU 탐지 실패 → FEDFUNDS 폴백: {e}")
    s = _fetch_series_keyless("FEDFUNDS", observation_start="2024-01-01")
    drops = s.diff()
    cut_months = drops[drops < -0.05].index
    if len(cut_months) == 0:
        raise ValueError("FEDFUNDS: 2024년 이후 인하 탐지 실패")
    d = cut_months[-1].strftime("%Y-%m-%d")
    return d, "FRED FEDFUNDS(월평균) 하락월 근사"


def fetch_ksh_ratecut_traj(max_months: int = 30) -> dict[str, Any]:
    """
    시리즈별 T=사이클 마지막(해당 국면) 금리인하일에 100 리베이스, x=T 후 개월수(0~30).
    ①1927-08-05(대공황, 다우 — 뉴욕연은 재할인율 3.5→3.0%) ②1998-10-15(닷컴, 나스닥)
    ③2020-03-16(팬데믹, 나스닥) ④현재 사이클(나스닥, 잠정 T — FRED 자동 탐지).
    버블 템플릿 p45 시그니처 차트: 과거 케이스 평균 정점 = T+21개월 (meta.avg_peak_months).
    1927 케이스는 DJIA 소스 실패 시 생략(방어적).
    """
    logger.info("[KSH] 마지막 금리인하 → 정점 궤적 수집 중...")
    today = datetime.today()
    today_str = today.strftime("%Y-%m-%d")

    cur_t, cur_src = _detect_last_cut()
    logger.info(f"  현재 사이클 잠정 T = {cur_t} ({cur_src})")

    cases = [
        {"name": "대공황 케이스 (다우, T=1927-08-05)", "T": "1927-08-05",
         "provisional": False, "kind": "djia"},
        {"name": "닷컴 케이스 (T=1998-10-15)", "T": "1998-10-15",
         "provisional": False, "kind": "ixic"},
        {"name": "팬데믹 케이스 (T=2020-03-16)", "T": "2020-03-16",
         "provisional": False, "kind": "ixic"},
        {"name": f"현재 사이클 (잠정 T={cur_t})", "T": cur_t,
         "provisional": True, "kind": "ixic"},
    ]

    djia, djia_src = _djia_early()

    series_out = []
    for case in cases:
        try:
            t0 = pd.Timestamp(case["T"])
            t1 = min(t0 + pd.Timedelta(days=int(max_months * _MONTH_DAYS) + 35),
                     pd.Timestamp(today_str))
            if case["kind"] == "djia":
                if djia is None:
                    logger.warning(f"  {case['name']}: DJIA 소스 없음 → 생략")
                    continue
                daily = djia[(djia.index >= case["T"])
                             & (djia.index <= t1.strftime("%Y-%m-%d"))]
            else:
                daily = _ixic_window(case["T"], t1.strftime("%Y-%m-%d"))
            pairs = _rebase_weekly_pairs(daily, t0, max_months=float(max_months))
            # 정점(구간 내 최대값) 메타 — 캡션·마커용
            peak_m, peak_v = max(pairs, key=lambda p: p[1])
            series_out.append({
                "name": case["name"],
                "T": case["T"],
                "provisional": case["provisional"],
                "peak": {"months": peak_m, "value": peak_v},
                "last": {"months": pairs[-1][0], "value": pairs[-1][1]},
                "data": pairs,
            })
            logger.info(
                f"  {case['name']}: {len(pairs)}포인트, 정점 T+{peak_m}M={peak_v}"
            )
        except Exception as e:
            logger.warning(f"  {case['name']} 실패 → 생략: {e}")

    if not series_out:
        raise ValueError("ksh_ratecut_traj: 모든 케이스 실패")

    return {
        "id": "ksh_ratecut_traj",
        "kind": "ksh_derived",          # chartbook 프론트 렌더 대상 아님 (CONTRACT 참조)
        "title": "마지막 금리인하 → 지수 정점 궤적",
        "subtitle": "T=국면 마지막 인하일=100 리베이스 · x=T 후 개월수(0~30) · 주간",
        "source": f"Yahoo Finance (^IXIC) + {djia_src} + FRED (DFEDTARU/FEDFUNDS, 키리스)",
        "x_unit": "개월 (마지막 인하 후)",
        "updated": _now_kst(),
        "meta": {
            "avg_peak_months": AVG_PEAK_MONTHS,   # 수직 기준선: 과거 평균 정점 T+21개월
            "avg_peak_label": f"평균 정점 {AVG_PEAK_MONTHS}M",
            "current_T": cur_t,
            "current_T_source": cur_src,
            "current_T_note": (
                "연준 인하 사이클 진행 중 — 추가 인하 시 T가 뒤로 이동하는 잠정값"
            ),
            "djia_source": djia_src,
        },
        "series": series_out,
    }

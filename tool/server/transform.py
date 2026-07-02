"""
transform.py — 어댑터 원시 응답 → 허브 차트 스키마 변환 + transform 적용

어댑터는 {dates[],values[],meta} 를 준다.
허브(CONTRACT.md)의 timeseries 스키마는:
  {id,type,title,subtitle?,source,unit,updated,note?,series:[{name,data:[[date,val],...]}]}

transform 옵션 (series별):
  none     : 그대로
  yoy      : 전년 대비 변화율(%). 같은 달/분기 비교가 이상적이나 v1은 ~365일 전 값 대비.
  index100 : 첫 값=100으로 정규화.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def _now_kst() -> str:
    from datetime import timezone, timedelta

    kst = timezone(timedelta(hours=9))
    return datetime.now(kst).strftime("%Y-%m-%dT%H:%M:%S+09:00")


def _to_pairs(dates: list[str], values: list[float]) -> list[list]:
    return [[d, v] for d, v in zip(dates, values)]


def apply_transform(
    dates: list[str], values: list[float], transform: str
) -> tuple[list[str], list[float]]:
    transform = (transform or "none").lower()
    if not values:
        return dates, values
    if transform == "index100":
        base = next((v for v in values if v not in (0, None)), None)
        if not base:
            return dates, values
        return dates, [round(v / base * 100, 4) for v in values]
    if transform == "yoy":
        # date 문자열 → datetime. 각 점에 대해 ~365일 전 직전 값과 비교.
        parsed = []
        for d in dates:
            try:
                parsed.append(datetime.fromisoformat(d[:10]))
            except ValueError:
                parsed.append(None)
        out_dates: list[str] = []
        out_vals: list[float] = []
        for i, (d, v) in enumerate(zip(dates, values)):
            if parsed[i] is None:
                continue
            target = parsed[i].replace(year=parsed[i].year - 1)
            # target 이하 가장 가까운 과거 값
            base_val = None
            for j in range(i, -1, -1):
                if parsed[j] is not None and parsed[j] <= target:
                    base_val = values[j]
                    break
            if base_val and base_val != 0:
                out_dates.append(d)
                out_vals.append(round((v / base_val - 1) * 100, 4))
        return out_dates, out_vals
    return dates, values


def build_timeseries(
    chart_id: str,
    title: str,
    summary: str,
    unit: str,
    source_label: str,
    series_defs: list[dict[str, Any]],
    fetched: dict[str, dict[str, Any]],
    note: str = "",
) -> dict[str, Any]:
    """
    series_defs: [{sourceId,label,transform}]
    fetched: {sourceId: {dates,values,meta}}  (어댑터 결과)
    → 허브 timeseries 차트 dict 반환.
    """
    series = []
    for sd in series_defs:
        sid = sd.get("sourceId")
        raw = fetched.get(sid) or {}
        dates = raw.get("dates") or []
        values = raw.get("values") or []
        dates, values = apply_transform(dates, values, sd.get("transform", "none"))
        series.append(
            {"name": sd.get("label") or sid, "data": _to_pairs(dates, values)}
        )

    out: dict[str, Any] = {
        "id": chart_id,
        "type": "timeseries",
        "title": title,
        "source": source_label,
        "unit": unit or "",
        "updated": _now_kst(),
        "series": series,
    }
    if summary:
        out["subtitle"] = summary
    if note:
        out["note"] = note
    return out

"""
registry.py — 차트북 레지스트리 읽기/쓰기 (머지 안전)

★ 중요: 이 도구는 허브가 실제로 읽는 레지스트리를 CRUD 한다.
   허브의 실제 계약(CONTRACT.md)은 `chartbook.json`(topics/tiles)이 아니라:
     - data/index.json        : {updated, charts:[{id,file,type,section,ready}]}
     - data/<id>.json         : 차트별 데이터 (timeseries|heatmap_perf|curve_snapshot)
   따라서 여기서는 그 실제 스키마를 대상으로 한다. 새 chartbook.json을 만들지 않는다
   (만들면 허브가 안 읽어 무용지물).

머지 안전 원칙:
  - index.json은 항상 읽어서 기존 charts 배열을 보존하고, 추가/삭제만 한다.
  - 절대 통째로 덮어쓰지 않는다 (파이프라인이 만든 ready 플래그/순서 보존).
  - 차트 추가 시 data/<id>.json을 새로 쓰고 index.json에 항목을 append.
  - 차트 삭제 시 index.json 항목 제거 + data/<id>.json 삭제.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

# tool/server/registry.py → 상위 chartbook/data
DATA_DIR = (Path(__file__).resolve().parent.parent.parent / "data").resolve()


def _now_kst() -> str:
    # pytz가 venv에 있으나, 의존 줄이려 고정 오프셋 사용
    from datetime import timezone, timedelta

    kst = timezone(timedelta(hours=9))
    return datetime.now(kst).strftime("%Y-%m-%dT%H:%M:%S+09:00")


def index_path() -> Path:
    return DATA_DIR / "index.json"


def read_index() -> dict[str, Any]:
    """index.json을 읽는다. 없으면 빈 스켈레톤(머지 안전: 빈 charts)."""
    p = index_path()
    if not p.exists():
        return {"updated": _now_kst(), "charts": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"updated": _now_kst(), "charts": []}
    if "charts" not in data or not isinstance(data.get("charts"), list):
        data["charts"] = []
    return data


def write_index(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    index_path().write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def read_chart(chart_id: str) -> dict[str, Any] | None:
    p = DATA_DIR / f"{chart_id}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_chart(chart_id: str, data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / f"{chart_id}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def list_sections() -> list[str]:
    """현재 등록된 섹션(=주제) 목록을 순서 보존해 반환."""
    seen: list[str] = []
    for c in read_index().get("charts", []):
        s = c.get("section")
        if s and s not in seen:
            seen.append(s)
    return seen


def chart_exists(chart_id: str) -> bool:
    return any(c.get("id") == chart_id for c in read_index().get("charts", []))


def upsert_chart(
    chart_id: str,
    section: str,
    chart_type: str,
    chart_data: dict[str, Any],
    ready: bool = True,
) -> dict[str, Any]:
    """
    차트를 추가(또는 같은 id면 갱신)한다. 머지 안전:
      - 기존 index의 다른 차트들은 그대로 둔다.
      - data/<id>.json 작성 후 index 항목 upsert + meta.updated 갱신.
    """
    write_chart(chart_id, chart_data)

    idx = read_index()
    entry = {
        "id": chart_id,
        "file": f"{chart_id}.json",
        "type": chart_type,
        "section": section,
        "ready": ready,
    }
    charts = idx["charts"]
    replaced = False
    for i, c in enumerate(charts):
        if c.get("id") == chart_id:
            charts[i] = entry
            replaced = True
            break
    if not replaced:
        charts.append(entry)
    idx["updated"] = _now_kst()
    write_index(idx)
    return {"action": "updated" if replaced else "added", "entry": entry}


def delete_chart(chart_id: str) -> dict[str, Any]:
    """차트를 index에서 제거하고 data/<id>.json 삭제. 머지 안전(나머지 보존)."""
    idx = read_index()
    before = len(idx["charts"])
    idx["charts"] = [c for c in idx["charts"] if c.get("id") != chart_id]
    removed = before - len(idx["charts"])
    if removed:
        idx["updated"] = _now_kst()
        write_index(idx)
    # data 파일 삭제
    p = DATA_DIR / f"{chart_id}.json"
    file_removed = False
    if p.exists():
        p.unlink()
        file_removed = True
    return {"removed_from_index": bool(removed), "file_removed": file_removed}

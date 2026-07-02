"""
cache.py — 원시 fetch 결과 캐시 (../../data/cache/<chartId>.json)

refresh 시 어댑터 원시 응답({dates,values,meta})을 캐시에 저장해 디버깅/재사용.
허브가 읽는 data/<id>.json(차트 스키마)과는 별개 — cache는 진단용 원본.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .registry import DATA_DIR

CACHE_DIR = (DATA_DIR / "cache").resolve()


def save(chart_id: str, payload: dict[str, Any]) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = CACHE_DIR / f"{chart_id}.json"
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def load(chart_id: str) -> dict[str, Any] | None:
    p = CACHE_DIR / f"{chart_id}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None

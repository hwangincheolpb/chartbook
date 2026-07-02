"""
fred.py — FRED 어댑터 (🔑 FRED_API_KEY 필요)

키 없으면 search는 [] , fetch는 {error:"key needed"} 반환. 절대 죽지 않음.
키가 있으면 실제로 동작한다(스텁 아님).

API:
  검색: https://api.stlouisfed.org/fred/series/search?search_text=...
  조회: https://api.stlouisfed.org/fred/series/observations?series_id=...
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

from .base import Adapter, key_needed_result

logger = logging.getLogger(__name__)

SEARCH_URL = "https://api.stlouisfed.org/fred/series/search"
OBS_URL = "https://api.stlouisfed.org/fred/series/observations"
TIMEOUT = 25


class FredAdapter(Adapter):
    name = "fred"
    needs_key = True

    def _key(self) -> str | None:
        return (os.environ.get("FRED_API_KEY", "") or "").strip() or None

    def available(self) -> bool:
        return self._key() is not None

    def search(self, q: str) -> list[dict[str, Any]]:
        key = self._key()
        if not key:
            return []
        if not q or not q.strip():
            return []
        try:
            resp = requests.get(
                SEARCH_URL,
                params={
                    "search_text": q.strip(),
                    "api_key": key,
                    "file_type": "json",
                    "limit": 20,
                    "order_by": "popularity",
                    "sort_order": "desc",
                },
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            items = resp.json().get("seriess") or []
        except Exception as e:  # noqa: BLE001
            logger.warning("FRED 검색 오류: %s", e)
            return []

        out: list[dict[str, Any]] = []
        for it in items:
            sid = it.get("id")
            if not sid:
                continue
            out.append(
                {
                    "source": self.name,
                    "id": sid,
                    "label": f"{sid} — {it.get('title', '')}",
                    "meta": {
                        "title": it.get("title"),
                        "units": it.get("units_short") or it.get("units"),
                        "frequency": it.get("frequency_short"),
                        "seasonal": it.get("seasonal_adjustment_short"),
                    },
                }
            )
        return out

    def fetch(self, series_id: str) -> dict[str, Any]:
        key = self._key()
        if not key:
            return key_needed_result()
        try:
            resp = requests.get(
                OBS_URL,
                params={
                    "series_id": series_id,
                    "api_key": key,
                    "file_type": "json",
                    "sort_order": "asc",
                },
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            obs = resp.json().get("observations") or []
        except Exception as e:  # noqa: BLE001
            logger.warning("FRED 조회 오류: %s", e)
            return {"dates": [], "values": [], "meta": {}, "error": str(e)}

        dates: list[str] = []
        values: list[float] = []
        for o in obs:
            v = o.get("value", ".")
            if v == ".":
                continue
            try:
                values.append(round(float(v), 6))
                dates.append(o["date"])
            except (ValueError, KeyError):
                continue
        return {"dates": dates, "values": values, "meta": {"series_id": series_id}}

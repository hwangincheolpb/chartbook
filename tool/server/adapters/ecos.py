"""
ecos.py — 한국은행 ECOS 어댑터 (🔑 ECOS_API_KEY 필요)

키 없으면 search는 [], fetch는 {error:"key needed"} 반환. 절대 죽지 않음.
키가 있으면 실제로 동작한다.

ECOS OpenAPI (XML/JSON):
  통계표 검색: StatisticTableList / StatisticItemList
  데이터 조회: StatisticSearch

ECOS는 통계코드(STAT_CODE)+항목코드(ITEM_CODE) 조합이 필요해 일반 키워드 검색이
까다롭다. v1에서는:
  - search(q): 통계표 목록(StatisticTableList)에서 표 이름 매칭 → 표 단위 후보.
               id = "STAT_CODE" (표 단위). fetch 시 첫 항목을 자동 선택.
  - fetch(id): 표의 첫 항목을 골라 월간(또는 가용 주기) 시계열 조회.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

from .base import Adapter, key_needed_result

logger = logging.getLogger(__name__)

BASE = "https://ecos.bok.or.kr/api"
TIMEOUT = 25


class EcosAdapter(Adapter):
    name = "ecos"
    needs_key = True

    def _key(self) -> str | None:
        return (os.environ.get("ECOS_API_KEY", "") or "").strip() or None

    def available(self) -> bool:
        return self._key() is not None

    def search(self, q: str) -> list[dict[str, Any]]:
        key = self._key()
        if not key or not q or not q.strip():
            return []
        # StatisticTableList: 전체 통계표 목록 → 이름 매칭(결정적)
        url = f"{BASE}/StatisticTableList/{key}/json/kr/1/1000"
        try:
            resp = requests.get(url, timeout=TIMEOUT)
            resp.raise_for_status()
            body = resp.json()
            rows = (body.get("StatisticTableList") or {}).get("row") or []
        except Exception as e:  # noqa: BLE001
            logger.warning("ECOS 검색 오류: %s", e)
            return []

        ql = q.strip().lower()
        out: list[dict[str, Any]] = []
        for r in rows:
            name = r.get("STAT_NAME") or ""
            code = r.get("STAT_CODE") or ""
            if not code:
                continue
            if ql in name.lower() or q.strip() == code:
                out.append(
                    {
                        "source": self.name,
                        "id": code,
                        "label": f"{name} ({code})",
                        "meta": {"stat_name": name, "cycle": r.get("CYCLE")},
                    }
                )
            if len(out) >= 20:
                break
        return out

    def fetch(self, series_id: str) -> dict[str, Any]:
        key = self._key()
        if not key:
            return key_needed_result()
        stat_code = series_id.strip()

        # 1) 표의 항목 목록에서 첫 항목 코드 + 주기 파악
        try:
            il = requests.get(
                f"{BASE}/StatisticItemList/{key}/json/kr/1/1/{stat_code}",
                timeout=TIMEOUT,
            )
            il.raise_for_status()
            items = (il.json().get("StatisticItemList") or {}).get("row") or []
        except Exception as e:  # noqa: BLE001
            logger.warning("ECOS 항목 조회 오류: %s", e)
            return {"dates": [], "values": [], "meta": {}, "error": str(e)}

        if not items:
            return {"dates": [], "values": [], "meta": {}, "error": "no items"}

        first = items[0]
        item_code = first.get("ITEM_CODE") or ""
        cycle = (first.get("CYCLE") or "M").upper()  # M/Q/A/D
        # 주기별 조회 기간 포맷
        if cycle == "A":
            start, end = "1990", "2099"
        elif cycle == "Q":
            start, end = "1990Q1", "2099Q4"
        elif cycle == "D":
            start, end = "19900101", "20991231"
        else:  # 월간 기본
            cycle = "M"
            start, end = "199001", "209912"

        # 2) StatisticSearch 로 시계열 조회
        url = (
            f"{BASE}/StatisticSearch/{key}/json/kr/1/100000/"
            f"{stat_code}/{cycle}/{start}/{end}/{item_code}"
        )
        try:
            resp = requests.get(url, timeout=TIMEOUT)
            resp.raise_for_status()
            rows = (resp.json().get("StatisticSearch") or {}).get("row") or []
        except Exception as e:  # noqa: BLE001
            logger.warning("ECOS 데이터 조회 오류: %s", e)
            return {"dates": [], "values": [], "meta": {}, "error": str(e)}

        dates: list[str] = []
        values: list[float] = []
        for r in rows:
            t = r.get("TIME", "")
            v = r.get("DATA_VALUE", "")
            if v in (None, "", "-"):
                continue
            try:
                values.append(round(float(v), 6))
                dates.append(_fmt_ecos_time(t, cycle))
            except (ValueError, TypeError):
                continue

        return {
            "dates": dates,
            "values": values,
            "meta": {
                "stat_code": stat_code,
                "item_code": item_code,
                "item_name": first.get("ITEM_NAME"),
                "cycle": cycle,
            },
        }


def _fmt_ecos_time(t: str, cycle: str) -> str:
    """ECOS TIME(예: 202401, 2024Q1, 20240115, 2024)을 YYYY-MM-DD로 정규화."""
    t = str(t)
    if cycle == "A" and len(t) == 4:
        return f"{t}-12-31"
    if cycle == "Q":
        # 2024Q1 / 20241 형태
        if "Q" in t:
            y, q = t.split("Q")
        else:
            y, q = t[:4], t[4:]
        month = {"1": "03", "2": "06", "3": "09", "4": "12"}.get(q, "12")
        return f"{y}-{month}-28"
    if cycle == "M" and len(t) == 6:
        return f"{t[:4]}-{t[4:6]}-01"
    if cycle == "D" and len(t) == 8:
        return f"{t[:4]}-{t[4:6]}-{t[6:8]}"
    return t

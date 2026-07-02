"""
dbnomics.py — DBnomics 어댑터 (API 키 불필요)

DBnomics(https://db.nomics.world)는 전 세계 공공 경제 데이터를 무료 공개 API로 제공.
키 불필요. 결정적 키워드 검색 + 시리즈 조회.

API:
  검색: https://api.db.nomics.world/v22/search?q=...&limit=...
  조회: https://api.db.nomics.world/v22/series/{provider}/{dataset}/{series}?observations=1

series id 포맷은 "PROVIDER/DATASET/SERIES" (DBnomics 표준 series_code 전체 경로).
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from .base import Adapter

logger = logging.getLogger(__name__)

BASE = "https://api.db.nomics.world/v22"
TIMEOUT = 20


class DBnomicsAdapter(Adapter):
    name = "dbnomics"
    needs_key = False

    def search(self, q: str) -> list[dict[str, Any]]:
        if not q or not q.strip():
            return []
        try:
            resp = requests.get(
                f"{BASE}/search",
                params={"q": q.strip(), "limit": 20},
                timeout=TIMEOUT,
                headers={"User-Agent": "chartbook-tool/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            logger.warning("DBnomics 검색 오류: %s", e)
            return []

        # /search 는 dataset 단위로 결과를 준다. 각 dataset을 후보로 노출하되,
        # fetch가 가능하도록 대표 시리즈를 함께 조회한다(있으면).
        out: list[dict[str, Any]] = []
        docs = (data.get("results") or {}).get("docs") or []
        for d in docs[:20]:
            provider = d.get("provider_code") or ""
            dataset = d.get("code") or d.get("dataset_code") or ""
            if not provider or not dataset:
                continue
            label = d.get("name") or f"{provider}/{dataset}"
            out.append(
                {
                    "source": self.name,
                    # dataset 경로. fetch 시 dataset이면 첫 시리즈를 자동 선택.
                    "id": f"{provider}/{dataset}",
                    "label": f"{label} [{provider}]",
                    "meta": {
                        "provider": provider,
                        "dataset": dataset,
                        "nb_series": d.get("nb_series"),
                        "kind": "dataset",
                    },
                }
            )
        return out

    def _resolve_series_path(self, series_id: str) -> str | None:
        """
        series_id 가 PROVIDER/DATASET/SERIES 면 그대로,
        PROVIDER/DATASET 면 그 dataset의 첫 시리즈 코드를 찾아 완성한다.
        """
        parts = series_id.strip("/").split("/")
        if len(parts) >= 3:
            return series_id.strip("/")
        if len(parts) == 2:
            provider, dataset = parts
            try:
                resp = requests.get(
                    f"{BASE}/series/{provider}/{dataset}",
                    params={"limit": 1},
                    timeout=TIMEOUT,
                    headers={"User-Agent": "chartbook-tool/1.0"},
                )
                resp.raise_for_status()
                docs = (resp.json().get("series") or {}).get("docs") or []
                if docs:
                    code = docs[0].get("series_code")
                    if code:
                        return f"{provider}/{dataset}/{code}"
            except Exception as e:  # noqa: BLE001
                logger.warning("DBnomics 시리즈 해석 오류: %s", e)
        return None

    def fetch(self, series_id: str) -> dict[str, Any]:
        path = self._resolve_series_path(series_id)
        if not path:
            return {"dates": [], "values": [], "meta": {}, "error": "series not found"}
        try:
            resp = requests.get(
                f"{BASE}/series/{path}",
                params={"observations": 1},
                timeout=TIMEOUT,
                headers={"User-Agent": "chartbook-tool/1.0"},
            )
            resp.raise_for_status()
            docs = (resp.json().get("series") or {}).get("docs") or []
        except Exception as e:  # noqa: BLE001
            logger.warning("DBnomics 조회 오류: %s", e)
            return {"dates": [], "values": [], "meta": {}, "error": str(e)}

        if not docs:
            return {"dates": [], "values": [], "meta": {}, "error": "no data"}

        doc = docs[0]
        periods = doc.get("period") or []
        raw_values = doc.get("value") or []
        dates: list[str] = []
        values: list[float] = []
        for p, v in zip(periods, raw_values):
            if v is None or v == "NA":
                continue
            try:
                values.append(round(float(v), 6))
                dates.append(str(p))
            except (TypeError, ValueError):
                continue

        meta = {
            "series_code": doc.get("series_code"),
            "series_name": doc.get("series_name"),
            "provider": doc.get("provider_code"),
            "dataset": doc.get("dataset_code"),
            "unit": doc.get("@frequency") or "",
            "path": path,
        }
        return {"dates": dates, "values": values, "meta": meta}

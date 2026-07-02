"""
krx.py — KRX 어댑터 (API 키 불필요, best-effort)

KRX(data.krx.co.kr)는 공식 공개 API가 없고 내부 AJAX 엔드포인트라 종종 막힌다.
요구사항: 가능하면 종목 시세 위주, 막히면 graceful degrade(빈 결과 + 메모).

전략:
  - search(q): KRX 상장종목 목록을 조회해 종목명/코드로 매칭(결정적).
               차단되면 빈 리스트 + 메모.
  - fetch(id): yfinance 폴백(국내 종목은 {코드}.KS / {코드}.KQ)로 일별 종가.
               KRX 직접 시세가 막히는 경우가 많아 yfinance 폴백이 가장 안정적.

id 포맷: 6자리 종목코드(예: "005930") 또는 "005930.KS".
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from .base import Adapter

logger = logging.getLogger(__name__)

# KRX 상장종목 목록 (best-effort; 종종 차단됨)
KRX_LIST_URL = "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
KRX_OTP_REFERER = "http://data.krx.co.kr/contents/MDC/MDI/mdiLoader"
TIMEOUT = 12


class KRXAdapter(Adapter):
    name = "krx"
    needs_key = False

    def __init__(self) -> None:
        self._cache: list[dict[str, str]] | None = None  # [{code,name,market}]

    def _load_listing(self) -> list[dict[str, str]]:
        """KRX 전종목 목록을 1회 로드해 캐시. 실패 시 빈 리스트."""
        if self._cache is not None:
            return self._cache
        try:
            resp = requests.post(
                KRX_LIST_URL,
                data={
                    # 전종목 기본정보 (KOSPI+KOSDAQ+KONEX)
                    "bld": "dbms/MDC/STAT/standard/MDCSTAT01901",
                    "mktId": "ALL",
                    "share": "1",
                    "csvxls_isNo": "false",
                },
                headers={
                    "Referer": KRX_OTP_REFERER,
                    "User-Agent": "Mozilla/5.0 (chartbook-tool)",
                },
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            rows = resp.json().get("OutBlock_1") or resp.json().get("output") or []
            out = []
            for r in rows:
                code = r.get("ISU_SRT_CD") or r.get("short_code") or ""
                name = r.get("ISU_ABBRV") or r.get("ISU_NM") or r.get("codeName") or ""
                market = r.get("MKT_TP_NM") or r.get("marketName") or ""
                if code and name:
                    out.append({"code": code, "name": name, "market": market})
            self._cache = out
            logger.info("KRX 종목 목록 로드: %d개", len(out))
        except Exception as e:  # noqa: BLE001
            logger.warning("KRX 종목 목록 로드 실패(차단 가능): %s", e)
            self._cache = []
        return self._cache

    def search(self, q: str) -> list[dict[str, Any]]:
        if not q or not q.strip():
            return []
        q = q.strip()
        listing = self._load_listing()
        if not listing:
            # graceful degrade: 빈 결과 + 메모. 6자리 코드면 직접 후보로 노출.
            if q.isdigit() and len(q) == 6:
                return [
                    {
                        "source": self.name,
                        "id": q,
                        "label": f"{q} (KRX 직접 코드)",
                        "meta": {"note": "KRX 목록 차단 — yfinance 폴백으로 조회"},
                    }
                ]
            return []

        ql = q.lower()
        out: list[dict[str, Any]] = []
        for item in listing:
            if ql in item["name"].lower() or q == item["code"]:
                out.append(
                    {
                        "source": self.name,
                        "id": item["code"],
                        "label": f"{item['name']} ({item['code']}) [{item['market']}]",
                        "meta": {"name": item["name"], "market": item["market"]},
                    }
                )
            if len(out) >= 20:
                break
        return out

    def fetch(self, series_id: str) -> dict[str, Any]:
        """
        KRX 종목 일별 종가. yfinance 폴백(.KS → .KQ)으로 조회한다.
        KRX 직접 시세 AJAX는 차단이 잦아 yfinance가 가장 안정적.
        """
        code = series_id.strip().upper()
        from .yfinance_adapter import YFinanceAdapter

        yf_ad = YFinanceAdapter()

        # 이미 접미사가 있으면 그대로, 없으면 .KS → .KQ 순으로 시도
        candidates = [code] if "." in code else [f"{code}.KS", f"{code}.KQ"]
        last_err = "no data"
        for cand in candidates:
            res = yf_ad.fetch(cand)
            if res.get("values"):
                res["meta"] = {**res.get("meta", {}), "krx_code": code, "via": "yfinance"}
                return res
            last_err = res.get("error", last_err)
        return {
            "dates": [],
            "values": [],
            "meta": {"krx_code": code},
            "error": f"KRX/yfinance 조회 실패: {last_err}",
        }

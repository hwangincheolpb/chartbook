"""
yfinance_adapter.py — Yahoo Finance 어댑터 (API 키 불필요)

티커 결정적 검색 + 가격 시계열 조회.
yfinance가 느리거나 막힐 수 있으므로 모든 호출에 예외 핸들링.

검색 전략 (결정적):
  1. Yahoo 공개 search 엔드포인트(quote/v1/finance/search)로 심볼 후보를 가져온다.
  2. 실패하면 입력값을 그대로 단일 티커 후보로 노출(사용자가 정확한 티커 입력 가정).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import requests

from .base import Adapter

logger = logging.getLogger(__name__)

SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"
TIMEOUT = 15
HEADERS = {"User-Agent": "Mozilla/5.0 (chartbook-tool)"}


class YFinanceAdapter(Adapter):
    name = "yfinance"
    needs_key = False

    def search(self, q: str) -> list[dict[str, Any]]:
        if not q or not q.strip():
            return []
        q = q.strip()
        out: list[dict[str, Any]] = []
        try:
            resp = requests.get(
                SEARCH_URL,
                params={"q": q, "quotesCount": 15, "newsCount": 0},
                timeout=TIMEOUT,
                headers=HEADERS,
            )
            resp.raise_for_status()
            quotes = resp.json().get("quotes") or []
            for item in quotes:
                symbol = item.get("symbol")
                if not symbol:
                    continue
                name = item.get("shortname") or item.get("longname") or symbol
                qtype = item.get("quoteType") or ""
                exch = item.get("exchDisp") or item.get("exchange") or ""
                out.append(
                    {
                        "source": self.name,
                        "id": symbol,
                        "label": f"{symbol} — {name}",
                        "meta": {"type": qtype, "exchange": exch, "name": name},
                    }
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("Yahoo 검색 오류: %s", e)

        # 검색 결과가 없으면 입력값을 직접 티커 후보로 (예: 정확한 티커 입력)
        if not out:
            out.append(
                {
                    "source": self.name,
                    "id": q.upper(),
                    "label": f"{q.upper()} (직접 티커)",
                    "meta": {"type": "ticker", "note": "검색 결과 없음 — 직접 티커로 시도"},
                }
            )
        return out

    def fetch(self, series_id: str, lookback_years: int = 6) -> dict[str, Any]:
        try:
            import yfinance as yf  # 지연 import (느린 라이브러리)
            import pandas as pd
        except Exception as e:  # noqa: BLE001
            return {"dates": [], "values": [], "meta": {}, "error": f"yfinance import 실패: {e}"}

        end = datetime.today()
        start = end - timedelta(days=lookback_years * 365 + 10)
        try:
            raw = yf.download(
                series_id,
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                auto_adjust=True,
                progress=False,
                threads=False,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("Yahoo 조회 오류 (%s): %s", series_id, e)
            return {"dates": [], "values": [], "meta": {}, "error": str(e)}

        if raw is None or raw.empty:
            return {"dates": [], "values": [], "meta": {}, "error": "no data"}

        # MultiIndex / 단일 컬럼 모두 안전 처리
        if isinstance(raw.columns, pd.MultiIndex):
            try:
                close = raw["Close"]
                col = close.iloc[:, 0] if close.shape[1] >= 1 else close
            except Exception:  # noqa: BLE001
                col = raw.iloc[:, 0]
        else:
            col = raw["Close"] if "Close" in raw.columns else raw.iloc[:, 0]

        col = col.dropna()
        dates: list[str] = []
        values: list[float] = []
        for idx, val in col.items():
            if pd.isna(val):
                continue
            ds = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
            dates.append(ds)
            values.append(round(float(val), 4))

        return {
            "dates": dates,
            "values": values,
            "meta": {"ticker": series_id, "field": "Close (adjusted)"},
        }

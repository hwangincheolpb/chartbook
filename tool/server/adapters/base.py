"""
base.py — Adapter 인터페이스

모든 데이터 소스 어댑터는 이 인터페이스를 따른다.

  search(q)  -> [{"source","id","label","meta"}]   결정적 키워드 검색
  fetch(id)  -> {"dates":[...], "values":[...], "meta":{...}}  시계열 조회

키가 필요한 어댑터(FRED/ECOS)는 키가 없으면 fetch/search에서
{"error": "key needed", ...} 를 반환하고, 절대 예외로 죽지 않는다.
"""

from __future__ import annotations

from typing import Any


class Adapter:
    """데이터 소스 어댑터 베이스. 하위 클래스가 search/fetch 구현."""

    # 소스 식별자 (registry source 값과 일치). 하위 클래스가 override.
    name: str = "base"
    # API 키 필요 여부
    needs_key: bool = False

    def available(self) -> bool:
        """이 어댑터가 현재 사용 가능한지 (키 필요 시 키 존재 여부)."""
        return True

    def search(self, q: str) -> list[dict[str, Any]]:
        """키워드로 후보 시리즈 검색. [{source,id,label,meta}] 반환."""
        raise NotImplementedError

    def fetch(self, series_id: str) -> dict[str, Any]:
        """단일 시리즈 시계열 조회. {dates[],values[],meta} 반환."""
        raise NotImplementedError


def key_needed_result() -> dict[str, Any]:
    """키 미발급 시 fetch가 반환하는 표준 응답."""
    return {"dates": [], "values": [], "meta": {}, "error": "key needed"}

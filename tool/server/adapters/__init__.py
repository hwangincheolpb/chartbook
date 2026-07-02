"""어댑터 레지스트리.

요구사항의 'source' 값(manual|dbnomics|yfinance|krx|fred|ecos)과
어댑터를 매핑한다. 키 필요 소스는 키 없으면 search [] / fetch error 처리.
"""

from __future__ import annotations

from .base import Adapter
from .dbnomics import DBnomicsAdapter
from .ecos import EcosAdapter
from .fred import FredAdapter
from .krx import KRXAdapter
from .yfinance_adapter import YFinanceAdapter

# 싱글톤 인스턴스 (krx는 종목목록 캐시 보존을 위해 인스턴스 재사용)
_ADAPTERS: dict[str, Adapter] = {
    "dbnomics": DBnomicsAdapter(),
    "yfinance": YFinanceAdapter(),
    "krx": KRXAdapter(),
    "fred": FredAdapter(),
    "ecos": EcosAdapter(),
}

# 검색 가능한(=결정적 검색 지원) 소스 순서. all 검색 시 이 순서로 합친다.
SEARCHABLE = ["dbnomics", "yfinance", "krx", "fred", "ecos"]


def get_adapter(source: str) -> Adapter | None:
    return _ADAPTERS.get(source)


def all_adapters() -> dict[str, Adapter]:
    return dict(_ADAPTERS)

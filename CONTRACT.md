# Chartbook Data Contract

파이프라인(A)과 프론트엔드(B)가 공유하는 데이터 규격. **이 규격을 깨면 안 됨.**

## 파일 레이아웃

```
data/
├── index.json          # 차트 목록 + 순서 + 메타 (프론트가 제일 먼저 읽음)
├── sp500.json          # 차트별 1파일
├── valuation_pe.json
├── ...
```

## index.json

```json
{
  "updated": "2026-06-09T12:00:00+09:00",   // ISO8601, KST
  "charts": [
    {
      "id": "sp500",
      "file": "sp500.json",
      "type": "timeseries",       // "timeseries" | "heatmap_perf"
      "section": "주식시장",        // 섹션 그룹핑 라벨 (탭/소제목)
      "ready": true,               // false면 데이터 없음(예: FRED 키 미발급) → 프론트는 placeholder 표시
      "daily": true,               // (선택) true면 "데일리" 뷰 기본 포함 시드. 사용자 ⭐(localStorage)로 오버라이드 가능
      "dailyOrder": 3              // (선택) 데일리 뷰 표시 순서 (오름차순). 논리체인 순서: C1→C2→C3→C4→C5→기타
    }
  ]
}
```

차트는 index.json의 배열 순서대로 화면에 위→아래 렌더(전체 뷰). `ready:false`면 회색 placeholder 카드.
데일리 뷰는 `daily:true` 시드 + ⭐ 오버라이드 병합 후 `dailyOrder` 오름차순 정렬(없는 차트는 뒤에 index 순서).

## type: "timeseries"

```json
{
  "id": "sp500",
  "type": "timeseries",
  "title": "S&P 500",
  "subtitle": "200일 이동평균",
  "source": "Yahoo Finance",
  "unit": "index",                 // "index" | "%" | "x" | "USD" 등 (y축 라벨)
  "updated": "2026-06-09T12:00:00+09:00",
  "note": "차트 아래 캡션 (선택)",
  "series": [
    { "name": "S&P 500", "data": [["2020-01-02", 3257.85], ["2020-01-03", 3234.85]] },
    { "name": "200D MA", "data": [["2020-01-02", 3100.10]] }
  ]
}
```

- `data`는 `[ "YYYY-MM-DD", number ]` 페어 배열. 시간 오름차순.
- `series`는 1개 이상. 여러 개면 라인 겹쳐 그림 + 범례.
- 결측은 그냥 해당 날짜를 빼면 됨(null 넣지 말 것).

### timeseries 확장 필드 (선택 — 없으면 기존 동작. 규격 확장이며 파괴 아님)

```json
{
  "unit": "%",                        // 왼쪽(기본) y축 라벨 — 기존과 동일
  "unit2": "USD",                     // (선택) 오른쪽 보조 y축 라벨. 이중축 차트에서만
  "markLines": [                      // (선택) 수평 기준선 목록
    { "value": 4.85, "label": "CTA 손절선", "axis": 0 }
  ],
  "xAxisType": "value",               // (선택) "time"(기본) | "value"
  "xAxisName": "프로그램 시작 후 경과 연차",  // (선택) x축 이름 라벨
  "series": [
    { "name": "미국채 10Y", "yAxis": 0, "data": [["2024-01-02", 4.02]] },
    { "name": "WTI 유가",  "yAxis": 1, "data": [["2024-01-02", 72.7]] }
  ]
}
```

- **시리즈별 `yAxis`**: `0`=왼쪽 축(기본, 생략 가능) / `1`=오른쪽 보조축. `yAxis:1`이 하나라도 있으면 이중축 렌더, 보조축 라벨은 `unit2`.
- **`markLines`**: 각 항목 `{value, label, axis}`. `value`=수평선 y값, `label`=선 위 라벨, `axis`=기준 y축 인덱스(0=왼쪽/1=오른쪽, 생략 시 0).
- **`xAxisType`**: 생략 또는 `"time"`이면 기존처럼 x=날짜 문자열. `"value"`면 x축은 숫자 축이고 `data` 페어의 x가 숫자(예: `[0, 94.5]`, `[1, 221.5]` — 경과 연차 등). 현재 사용처: `megaprojects_reconstructed`.
- **`xAxisName`**: x축에 표시할 이름. 주로 `xAxisType:"value"`와 함께 사용.

## snapshot.json (아침 스냅샷 보드) — 규격 확장(파괴 아님)

"아침 10초 확인"용 상단 보드. 파이프라인이 **모든 차트 fetch 후, 생성된 data/*.json에서만 계산**해
`data/snapshot.json`으로 저장한다 (추가 네트워크 호출 없음, `run.py build_snapshot()`).
재료 파일이 없거나 계산 실패하면 해당 카드는 **skip** (배열에서 빠짐). 파일 자체가 없으면 프론트는 보드를 숨긴다.

```json
{
  "updated": "2026-07-02T10:16:09+09:00",
  "cards": [
    {
      "id": "us10y",                        // 카드 고유 id
      "label": "미국채 10Y",                 // 카드 제목
      "value": 4.475,                       // 최신값 (숫자)
      "unit": "%",                          // 값 단위 ("" 가능)
      "d1": 2.36,                           // 전일비 % (직전 데이터 포인트 대비, null 가능)
      "state": "good",                      // "good" | "warn" | "alert" | "neutral" → 배지 색
      "badge": "여유",                       // (선택) 배지 텍스트. 없으면 state 기본 라벨(양호/주의/경보)
      "caption": "CTA 손절선 4.85%까지 +0.38%p",  // 근거 한 줄
      "link": "#card-ls_rate_peak"          // 클릭 시 스크롤할 차트 카드 앵커 (#card-<chart_id>)
    }
  ]
}
```

- 프론트(`charts.js`)는 각 차트 카드에 `id="card-<chart_id>"` 앵커를 부여한다. `link`는 이 앵커를 가리킨다.
- 카드 클릭 시: 대상 차트가 접힌 섹션 안이면 섹션을 펼친 뒤 스크롤 + 하이라이트.
- 카드 10종 (재료 차트 → 판정 로직):

| id          | 재료(data/*.json)      | 값 | 판정 |
|-------------|------------------------|----|------|
| us10y       | ls_rate_peak (폴백 ust_yields) | 10Y 최신 % | 4.85 미만 여유=good / 0.2%p 이내 근접=warn / 돌파=alert. caption에 CTA까지 거리 |
| rate_scenario | ls_rate_peak (폴백 ust_yields) + yield_spread(보조) | 10Y 최신 % | 금리 시나리오 A/B 트리거 (6/29 트레이드 플랜). **A=매파 재프라이싱**: 10Y 4.40% 상향 **안착** 시 — 안착 정의 = **종가 3영업일 연속 ≥4.40** → alert / 4.40 상회했으나 3영업일 미충족 = "A 안착 대기"=warn / **B=되돌림 지속**: 4.30% 하향 이탈(≤4.30) → alert / 사이 = 중립(관망)=neutral. caption에 4.40·4.30까지 거리(bp) + 행동(A 확정 시 분할 진입·전제 깨지면 기계적 손절, B 확정 시 되돌림 포지션 유지). **베어플래트닝 보조신호**: 2Y가 yfinance 무키 소스에 없음(^TNX/^FVX/^TYX/^IRX만) → 10Y-3M 스프레드(yield_spread)로 근사 — "10Y 5영업일 상승 + 스프레드 5영업일 축소 동시"면 caption에 플래트닝 주의 표기. **2Y 정식판(2s10s 베어플래트닝)은 FRED 키(DGS2) 확보 이후 교체 예정** |
| spx_band    | sp500                  | 지수 ÷ 21x 밴드 상단 | >1.0 드림장=warn / 이하 밴드 내=good |
| vix         | vix                    | 최신값 | <15 공포소멸=warn(공포역설) / ≥30 공포=alert / 그 외 neutral |
| move        | move_index             | 최신값 | <80 정온=good / <110 보통=neutral / ≥110 불안=alert |
| dxy         | dxy                    | 최신값 | neutral |
| usdkrw      | usdkrw                 | 최신값 | neutral |
| copper_gold | copper (구리/금 시리즈) | 최신값 | neutral, badge=3개월 방향 화살표(↑/→/↓), caption에 3개월 % |
| credit      | credit_proxy           | HYG/LQD 최신값 | 3개월 −2% 이하 스트레스=warn / 그 외 정온=good |
| rotation    | kr_foreign_flow + kr_rotation_check (+ vkospi 있으면) | 외인 연속 순매도 주 수 | 로테이션 끝 체크리스트: ①외인 주간(ISO주) 순매도 4주+ 연속 ②KOSPI 50일선 하회+거래량 급증(5일평균>20일평균) 동반 ③VKOSPI 60일 평균 대비 +30% 급등(데이터 있을 때만). 충족 0=🟢유지(good) / 1=🟡주의(warn) / 2+=🔴끝 경보(alert) |

## calendar.json (이번 주 일정+실적 카드) — 규격 확장(파괴 아님)

아침 검증 ⑥ "오늘/이번 주 촉매" 카드. 파이프라인(`run.py build_calendar()` → `pipeline/fetch_calendar.py`)이
**오늘부터 +14일** 이벤트만 `data/calendar.json`으로 저장. 프론트는 스냅샷 보드 바로 아래
`#calendar-card`에 렌더 (데일리/전체 뷰 공통 노출). 파일 없으면 카드 숨김, `events`가 비면 "이번 주 주요 촉매 없음".

```json
{
  "updated": "2026-07-02T13:54:29+09:00",
  "events": [
    { "date": "2026-07-14", "type": "지표", "label": "미 CPI (6월분)", "importance": "high" },
    { "date": "2026-07-16", "type": "회의", "label": "한은 금통위 (기준금리)", "importance": "high" },
    { "date": "2026-07-16", "type": "실적", "label": "TSMC 실적", "ticker": "TSM", "importance": "high" }
  ]
}
```

- `date`: `YYYY-MM-DD` (발표 주체의 현지일. FOMC는 이틀 회의 중 결정 발표일=2일차).
- `type`: `"지표"`(📊) | `"실적"`(💰) | `"회의"`(🏛️) — 프론트 아이콘 구분.
- `ticker`: 실적 이벤트에만 존재.
- `importance`: `"high"` | `"mid"` — high는 굵게 강조.
- 정렬: 날짜 → 중요도 → 타입(회의→지표→실적). 프론트는 날짜별 그룹 + D-day 배지(오늘=🔴, 내일=🟡).

### 소스 (키 불필요)

| 종류 | 소스 | 방식 |
|------|------|------|
| 경제지표/회의 (FOMC·CPI·NFP·PCE·GDP·금통위) | `pipeline/econ_calendar_2026.json` | **정적 연간 일정, 연 1회 채록** (매년 12월 이듬해 파일 추가 — `econ_calendar_*.json` 전부 자동 로드). 출처/채록일은 파일 내 `sources` 필드 |
| 관심종목 실적 | yfinance `get_earnings_dates` (폴백 `Ticker.calendar`) | 매 실행 조회. 워치리스트 = `fetch_calendar.py EARNINGS_WATCHLIST` (이선엽 체인 15종목). 실패/미제공 종목은 skip. **yfinance 어닝일은 확정 전 추정치일 수 있음** |

## type: "heatmap_perf" (섹터 퍼포먼스)

```json
{
  "id": "sectors",
  "type": "heatmap_perf",
  "title": "섹터 퍼포먼스",
  "source": "Yahoo Finance (SPDR ETFs)",
  "updated": "2026-06-09T12:00:00+09:00",
  "periods": ["1D", "1W", "1M", "3M", "YTD", "1Y"],   // 컬럼 순서
  "items": [
    { "name": "Technology", "ticker": "XLK", "perf": { "1D": 0.52, "1W": 2.1, "1M": -1.2, "3M": 5.0, "YTD": 12.3, "1Y": 20.1 } }
  ]
}
```

- `perf` 값은 퍼센트 숫자(%, 부호 포함). 빨강(-)/초록(+) 색칠.

## type: "curve_snapshot" (수익률 곡선 — 만기별 스냅샷)

x축 = 만기(범주, 주어진 순서대로), 선 = 시점별 스냅샷. 시계열이 아니라 "오늘 vs 과거" 곡선 비교용.

```json
{
  "id": "yield_curve",
  "type": "curve_snapshot",
  "title": "미국 국채 수익률 곡선",
  "source": "Yahoo Finance",
  "unit": "%",
  "updated": "2026-06-09T12:00:00+09:00",
  "note": "역전 여부 한눈에 (단기>장기면 침체 신호)",
  "maturities": ["3M", "5Y", "10Y", "30Y"],   // x축 순서 (왼→오)
  "snapshots": [
    { "label": "현재",    "data": [["3M", 5.21], ["5Y", 4.10], ["10Y", 4.25], ["30Y", 4.40]] },
    { "label": "1년 전",  "data": [["3M", 5.45], ["5Y", 4.60], ["10Y", 4.55], ["30Y", 4.70]] }
  ]
}
```

- 각 snapshot의 `data`는 `["만기라벨", yield%]` 페어. 만기 라벨은 상위 `maturities`와 일치.
- 프론트: x=category(만기), 여러 snapshot을 라인으로 겹쳐 그림 + 범례. 툴팁에 만기/수익률.

## type: "link" (외부 라이브 대시보드 링크)  — 규격 확장(파괴 아님)

기존 라이브 대시보드를 차트북 안에서 재발명하지 않고, **클릭 가능한 카드**로 묶기 위한 타입.
data 파일을 만들지 않는다. **`index.json` 항목 자체에 모든 필드를 인라인**으로 넣는다(별도 `<id>.json` 없음, `file` 불필요).

```json
{
  "id": "peer_valuation_link",
  "type": "link",
  "section": "밸류에이션",
  "title": "피어 밸류에이션 모니터",
  "subtitle": "190종목·48카테고리 일별 스냅샷·변동률",
  "url": "https://hwangincheolpb.github.io/peer-valuation-monitor/",
  "live": true,                 // true=배포중(LIVE↗ 배지), false=로컬전용/미배포(흐린 "로컬" 배지)
  "source": "GitHub Pages",     // 선택
  "note": "클릭 시 새 탭으로 열림"  // 선택
}
```

- `type:"link"` 항목은 `ready`/`file` 필드 없이도 유효(`index.json`에 인라인). `ready`를 넣어도 무시 가능.
- 프론트: 카드 전체가 클릭 영역 → `window.open(url, '_blank')`. `live:true`면 "LIVE ↗", `live:false`면 흐린 "로컬" 배지. `url`이 비면 클릭 비활성.
- 기존 timeseries / heatmap_perf / curve_snapshot 규격은 **변경 없음**. link는 순수 추가 타입.

## 1차 차트 목록 (id 고정)

| id            | type          | source   | 키필요 | 설명 |
|---------------|---------------|----------|--------|------|
| sp500         | timeseries    | yahoo+multpl | N  | **밸류에이션 밴드 (승격)**: S&P500 지수 + multpl EPS(TTM)×15/18/21 밴드 3선. multpl EPS 실패 시 기존 200D MA로 폴백 |
| kospi         | timeseries    | yahoo    | N      | KOSPI + KOSDAQ (series 2개) |
| vix           | timeseries    | yahoo    | N      | VIX (note=이선엽 §7-6 공포역설 캡션) |
| sectors       | heatmap_perf  | yahoo    | N      | 11개 SPDR 섹터 |
| valuation_pe  | timeseries    | fred     | Y      | Forward P/E + Shiller CAPE |
| sp500_eps     | timeseries    | fred     | Y      | S&P500 EPS |

- ~~buffett~~ (Buffett Indicator, fred): **은퇴 2026-07-06** — Valley AI 링크 카드(`valley_buffett_link`)로 대체. `run.py RETIRED_IDS`에 등록되어 index 재생성 시 부활하지 않음.

키필요=Y인데 FRED 키 없으면 → index.json에서 `ready:false`로 내보내고 data 파일은 만들지 않음.

## 채권/금리 차트 (id 고정) — section "채권/금리"

| id            | type           | source   | 키필요 | 설명 |
|---------------|----------------|----------|--------|------|
| ust_yields    | timeseries     | yahoo    | N      | 미국채 금리 추이: 3M(^IRX)·5Y(^FVX)·10Y(^TNX)·30Y(^TYX), series 4개 |
| yield_spread  | timeseries     | yahoo    | N      | 10Y-3M 스프레드(=^TNX-^IRX). 0선 기준, 마이너스=장단기 역전(침체 신호) |
| yield_curve   | curve_snapshot | yahoo    | N      | 수익률 곡선: "현재" vs "1년 전" 만기별 스냅샷 |
| credit_proxy  | timeseries     | yahoo    | N      | 크레딧 리스크 프록시 = HYG/LQD 가격비율. 하락=HY 언더퍼폼=크레딧 스트레스. 키 불필요 |
| credit_hy_oas | timeseries     | fred     | Y      | 하이일드 OAS 스프레드(BAMLH0A0HYM2). 크레딧 리스크 (FRED 키 있으면 정밀판) |

- yahoo 금리 지수는 값이 10배로 옴(예: 10Y 4.25% → ^TNX 42.5). **÷10 해서 % 단위로 저장**할 것.
- `yield_spread`는 같은 날짜의 ^TNX-^IRX를 계산해 ÷10. 단위 "%".
- `yield_curve`의 "1년 전"은 ~365일 전 영업일 값.
- `credit_hy_oas`는 FRED 키 없으면 ready:false.

## 환율 차트 (id 고정) — section "환율"

| id      | type       | source | 키필요 | 설명 |
|---------|------------|--------|--------|------|
| usdkrw  | timeseries | yahoo  | N      | 원/달러 환율 (KRW=X). unit "원" |
| dxy     | timeseries | yahoo  | N      | 달러 인덱스 (DX-Y.NYB, 실패 시 "^DX-Y.NYB"/"DXY" 폴백). unit "index" |

## 원자재 차트 (id 고정) — section "원자재"

| id     | type       | source | 키필요 | 설명 |
|--------|------------|--------|--------|------|
| gold   | timeseries | yahoo  | N      | 금 선물 (GC=F). unit "USD" |
| wti    | timeseries | yahoo  | N      | WTI 원유 선물 (CL=F). unit "USD" |
| copper | timeseries | yahoo  | N      | **구리/금 비율 (승격)**: HG=F÷GC=F(×1000) + 미10Y(^TNX, yAxis:1) 이중축 — 건들락 비율. unit "ratio(×1000)", unit2 "%" |

- gold/wti는 yfinance 단일 시계열(~6y daily close), 키 불필요. 각각 series 1개.
- index.json 순서: 채권/금리 다음에 환율(usdkrw, dxy) → 원자재(gold, wti, copper).

## 수급 차트 (id 고정) — section "수급"

로테이션(한국 주도주 장세) 끝 판정 재료. 스냅샷 `rotation` 카드와 연동. index.json 순서상 **한국(kospi) 바로 다음**.
수집: `pipeline/fetch_kr_flow.py`. 캡션은 fetcher 원천에 하드코딩(수급 체크리스트 톤).

| id                | type       | source | 키필요 | 설명 |
|-------------------|------------|--------|--------|------|
| kr_foreign_flow   | timeseries | naver  | N      | 외국인/기관 KOSPI 일별 순매수(억원) 2선 + 외국인 20일 누적(yAxis:1). markLine 0선. 소스=Naver Finance 투자자별 매매동향(비공식, 무키). daily 시드(dailyOrder 11) |
| kr_rotation_check | timeseries | yahoo  | N      | KOSPI(^KS11 Close) + 50일선 + 거래량(백만주, yAxis:1). 거래량 스케일 자동 감지(천주/주 → 백만주) |
| ~~vkospi~~        | —          | —      | —      | **미구현**: KRX 정보데이터시스템 로그인 필수화(2026, pykrx 포함)로 무키 소스 없음(Naver/Daum/Yahoo 미제공). 소스 생기면 추가 — rotation 카드는 vkospi.json 존재 시 자동으로 ③ 조건 평가 |

- pykrx는 사용하지 않음: 1.2.x는 KRX_ID/PW 로그인 필수, 구버전도 KRX 익명 차단으로 빈 데이터 (2026-07 확인).
- kr_foreign_flow는 Naver 페이지네이션(페이지당 10영업일)으로 ~160영업일 수집. 영업일만 내려오므로 휴일 방어 별도 불필요.

## 이선엽 체인 차트 (id 고정) — section "이선엽 체인"

leesunyeop-framework `§7 차트북 연동 스펙`의 논지 체인. index.json 순서상 **밸류에이션 다음, 채권/금리 앞**.
전부 yfinance(키 불필요), note에 §7 논지 캡션(리드문 + [출처]/[한계]) 포함. 수집: `pipeline/fetch_leesunyeop.py`.

| id               | type       | source | 키필요 | 설명 |
|------------------|------------|--------|--------|------|
| ls_rate_peak     | timeseries | yahoo  | N      | 미10Y(^TNX ÷10 자동감지, %) + WTI(CL=F, yAxis:1 USD) 이중축. markLines: 4.85%(CTA 손절선)·5.5%(구조 경보)·4.40%(시나리오 A선)·4.30%(시나리오 B선), 전부 axis 0. 시나리오 A/B 정의는 snapshot `rate_scenario` 카드 행 참조 |
| ls_semi_vs_power | timeseries | yahoo  | N      | SOX(^SOX) vs 한국 전력기기 바스켓(010120.KS·267260.KS·034020.KS 균등, 각 index100 평균) — 둘 다 index100 상대강도, 3y |
| ls_memory_cycle  | timeseries | yahoo  | N      | 삼성전자(005930.KS)·SK하이닉스(000660.KS)·마이크론(MU) index100 3선 + MU/한국 메모리 선행 스프레드(MU index100 ÷ 한국 2사 index100 균등평균 ×100, yAxis:1), 2y — C3 마이크론 선행 규칙 |
| ls_taiwan_hedge  | timeseries | yahoo  | N      | 삼성전자 ÷ TSM 비율 1선 (공통 거래일 inner join), 3y |
| ls_ship_defense  | timeseries | yahoo  | N      | 조선 바스켓(009540.KS·042660.KS 균등 index100) vs KOSPI(^KS11 index100), 3y |
| move_index       | timeseries | yahoo  | N      | ^MOVE 채권 변동성 지수, 6y |

- index100 = 조회 구간 첫 유효값을 100으로 지수화. 바스켓 = 각 종목 index100의 균등 평균(전 종목 존재 구간만).
- 개별 티커/차트 실패 시 해당 차트만 ready:false (파이프라인 전체는 계속).

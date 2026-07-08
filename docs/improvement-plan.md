# Chartbook 개선안 (Improvement Plan)

> 작성: 2026-07-08 (조사 세션, 서브에이전트 6개 병렬 리서치 + 코드 검증)
> **범위: 조사·설계만. 코드 수정 없음.** 각 이슈 = 현황 / 원인 / 해결책 / 난이도 / 우선순위.
> 관련: `CONTRACT.md`, `pipeline/config.yaml`, `pipeline/run.py`, `pipeline/fetch_fred.py`, `pipeline/fetch_kr_flow.py`,
> `~/workspace/dev/jarvis-brief/`, [[project-chartbook]], [[valley-ai-platform-base]], [[investment-decision-framework]]

---

## 0. 우선순위 요약 (먼저 볼 것)

| 우선 | 이슈 | 한 줄 | 난이도 | 근거 |
|------|------|-------|--------|------|
| **P1** | #1 HY OAS 키리스 | `BAMLH0A0HYM2`를 fredgraph.csv로 → 상시 ready (실시간 크레딧 스트레스 정밀판) | **low** | curl 검증: 키리스 200, 최신 2.72%(07-06) |
| **P1** | #2 jarvis-brief Fwd P/E·10Y 버그 | `_ts_last`가 `series[0]` 하드코딩 → CAPE를 "Fwd P/E"로, 3M을 "美10년"으로 오표기. 매일 틀린 숫자 발송 중 | **low** | 코드 확인, 한 함수 수정으로 2버그 동시 해결 |
| **P1** | #4 마진 프록시 교체 | CP/GDP(가짜 마진) → `A466RD3Q052SBEA`(진짜 단위이익마진). 키리스, 나눗셈 제거 | **low** | curl 검증: Q1'26까지, 개념 정확 |
| **P2** | #5 EWY/KOSPI 카드 | 단일 티커 스냅샷 카드 2개 (기존 카드 스키마 재사용, 신규 fetch 0) | **low** | kospi.json 재사용 가능 |
| **P2** | #5 US 마켓맵 treemap | 기존 sectors.json 재사용 + `marketmap` 렌더러 신설 | low~med | ECharts5 treemap 확인 |
| **P2** | #7 한미금리차 (ECOS) | 국고채10Y(ECOS 060Y001) − 美10Y(FRED DGS10 키리스). 채권 PB 핵심 | med | 통계표코드 교차확인 |
| **P2** | #6 CONTRACT lineStyle | 시리즈별 점선(dashed) 필드 추가 — 하위호환 확장 | low | 설계안 아래 |
| **P3** | #3 수급 소스 | 네이버가 여전히 최선(실측 확인). 하드닝 + 파싱실패 알림만 | low | KRX 사망 확정, 대안 없음 |
| **P3** | #1 버핏지수 키리스 | Wilshire는 FRED에서 영구 삭제(2024-06-03). `NCBEILQ027S/GDP`로 재건 가능하나 Valley가 이미 커버 → 저순위 | med | curl 검증: WILL5000 404 |
| **P3** | #2 EWY 이상치 | 소스 버그 아님 — 시황 크론 **LLM 환각**(등락률 변조). 지수 박스를 파이썬 계산으로 이관 | med | 크론 산출물 대조 확인 |

**한 세션에 묶을 수 있는 P1 3건**: #1(HY OAS)·#4(마진)는 `fetch_fred.py` 한 파일 / #2는 `jarvis-brief/brief.py` 한 함수. 각각 독립적이라 병렬 가능.

---

## 이슈 #1 — FRED 키 없이 버핏지수 + HY OAS 활성화

### 현황
- `fetch_fred.py`에 **키리스 폴백(`_fetch_series_keyless`, fredgraph.csv)**이 이미 존재하나 `fed_funds`/`capex_margin`에만 적용.
- `credit_hy_oas`(HY OAS)와 `buffett`(비활성)은 여전히 `_fetch_series`(키 필수) 경로 → 키 없으면 `ready:false` placeholder.

### 원인
- HY OAS: `fetch_credit_hy_oas()`가 `_fetch_series_any`(키리스 폴백 지원)가 아니라 `_fetch_series`(키 강제)를 호출. 단순 미적용.
- 버핏: 원본 `WILL5000PRFC / GDP` 방식이 키 유무와 무관하게 **불가능** (아래).

### 해결책 (검증 완료 — curl 실측)

**A) HY OAS `BAMLH0A0HYM2` → 키리스 전환 (P1, 즉시)**
- 키리스 fredgraph.csv **정상 작동 확인**: HTTP 200, 793행, 최신 **2.72% (2026-07-06)**. 일별·영업일만(휴일은 행 자체가 빠짐, `.` 결측 아님 → 날짜 갭 처리).
- 조치: `fetch_credit_hy_oas`를 `_fetch_series_any(series_id, api_key)` 사용으로 바꾸고 `fetch_all_fred`에서 키 없어도 수집하도록 이동(fed_funds/capex_margin과 동일 패턴). CONTRACT의 "키 없으면 ready:false" 규칙은 이 차트에 한해 해제.
- 값: 가장 고가치. HYG/LQD 프록시(이미 있음)를 폴백으로 강등, OAS를 정밀 1차 소스로.

**B) 버핏지수 (P3, 저순위)**
- **원본 방식 사망**: FRED가 **2024-06-03에 Wilshire 인덱스 전 시리즈 삭제**(라이선스 종료). `WILL5000PRFC`/`WILL5000IND` 전부 **404** — 키가 있어도 복구 불가.
- 키리스 대체(검증됨): 분자 `NCBEILQ027S`(비금융법인 주식 시가총액 레벨, Z.1, $백만, 최신 $69.5T @2026-01-01) ÷ 분모 `GDP`($십억). 비율 = `NCBEILQ027S / (GDP*1000) * 100` ≈ 218% (스케일 주의). 분기·발표지연 ~10주.
- **하지만 저순위**: [[valley-ai-platform-base]] 원칙상 버핏지수는 "Valley가 커버 → 재개발 금지" 목록. 이미 `valley_buffett_link` 카드로 대체됨. 살릴 거면 `NCBEILQ027S/GDP`로, 아니면 Valley 링크 유지.

### 난이도 / 우선순위
- HY OAS: **low / P1** — 즉시.
- 버핏: **med / P3** — Valley 중복이라 굳이 안 해도 됨.

---

## 이슈 #2 — jarvis-brief "Fwd EPS 41.7배" 버그 (+ 10Y 이중값, EWY 이상치)

> 소스: `~/workspace/dev/jarvis-brief/`. jarvis-brief는 자체 시세 계산이 아니라 (A) chartbook 캐시 JSON, (B) 시황 크론 LLM 텍스트, (C) prices.py(Yahoo)를 조합해 렌더.

### 버그 1 — "Fwd P/E 41.7배" (실제 렌더 42.0)
- **위치**: `brief.py:64-73` `_ts_last()` (읽기) → `brief.py:141` `_ts_last("valuation_pe")` → `brief.py:162` `f"S&P500 Fwd P/E {...:.1f}배"`.
- **원인**: `_ts_last`가 무조건 `series[0]`을 집는데 `valuation_pe.json`의 `series[0]`은 **Shiller CAPE(41.97)**, `series[1]`이 실제 "S&P 500 P/E(28.13)". → CAPE를 P/E로 오선택 + 둘 다 forward가 아닌데 "Fwd" 라벨.
- **해결책**: `_ts_last`에 `series_name` 인자 추가 → `_ts_last("valuation_pe", series_name="S&P 500 P/E")`. 근본적으로 chartbook에 **진짜 forward P/E 시리즈가 없으므로** 라벨을 "트레일링 P/E" 또는 "Shiller CAPE"로 정정(정확한 데이터에 맞춤). 진짜 Fwd가 필요하면 별도 소스 필요(yfinance `^GSPC`는 forwardPE 미제공).
- **난이도**: low (라벨/인덱스 정정) / 진짜 Fwd 확보까지면 med.

### 버그 2 — 10Y 이중값 (같은 브리핑에 4.53% vs 3.73%)
- **위치**: `brief.py:142` `_ts_last("ust_yields")` → `brief.py:164` `f"美10년 {...:.2f}%"`. `publish_view.py`의 국채표(`ops/heatmap.py:bond_board`, 만기명 dict 조회)와 충돌.
- **원인**: 버그1과 **동일한 `series[0]` 결함**. `ust_yields.json` 순서 `['3M','5Y','10Y','30Y']` → `series[0]`=**3M(3.725%)**을 "美10년"으로 오표기. 정상 국채표는 10Y=4.53%로 맞게 나옴 → 한 브리핑에 두 값.
- **주의**: 스케일(×10/÷10) 문제 **아님**. chartbook `^TNX÷10`과 겹치지 않음(jarvis-brief는 이미 %정규화된 `ust_yields.json` 사용).
- **해결책**: `_ts_last("ust_yields", series_name="10Y")`. **버그1과 동일 수정(`_ts_last`에 series_name 인자)으로 한 번에 해결.**
- **난이도**: low.

### 버그 3 — EWY 이상치 (-8.21% vs 실제 -4.51%)
- **위치**: 소스 코드 버그 아님. `brief.py:93-105` `load_sihwang()`이 시황 크론 LLM 텍스트(`~/.hermes/cron/output/.../*.md`)를 **무검증 통째 반영**.
- **원인**: **LLM 환각**. 크론 산출물 대조 결과 입력 데이터블록엔 `EWY -4.51%`인데 LLM `## Response` 출력에서 `-8.21%`로 변조. EWY만이 아니라 **다우(-0.25%→+1.42% 부호반전), VIX(+3.60%→-8.61%)** 등 지수 박스 등락률 전반이 LLM에 오염됨.
- **해결책**: 결정론적 수치를 LLM에 맡기지 말 것. (권장) jarvis-brief가 지수 박스를 `prices.py`(소스 C, Yahoo)로 **직접 재계산**해 렌더하고 LLM 텍스트는 정성 코멘트에만 사용. jarvis-brief 원칙("③④ 숫자는 순수 파이썬")과 정확히 부합. (임시) 크론 프롬프트에 "지수 숫자는 원문 그대로 전사, 재계산 금지" 강제 — 단 재발 위험.
- **난이도**: med.

### 종합
- 버그 1·2는 **한 결함(`_ts_last` series[0] 하드코딩)** → `series_name` 인자 추가 + 호출부 2줄 명시 + "Fwd" 라벨 정정으로 동시 해결. **P1 (매일 틀린 숫자가 브리핑으로 나감).**
- 버그 3만 성격 다름(LLM). 세 버그 모두 스케일링 이슈 아님.

---

## 이슈 #3 — 외인/기관 수급 데이터 소스 (pykrx 사망 후)

### 현황 / 결론
- **pykrx 사망 확정**: KRX 정보데이터시스템이 2025-12-27 회원제(로그인 필수) 전환 → pykrx/FinanceDataReader 익명 경로 차단.
- **네이버 금융이 여전히 유일한 무키·무로그인·일별 외인/기관 순매수 소스** (실측 검증). 현행 유지가 정답.

### 조사 결과 (실측)
- **네이버 지수 투자자별 매매동향** — 검증된 엔드포인트:
  `https://finance.naver.com/sise/investorDealTrendDay.naver?bizdate={YYYYMMDD}&sosok={01=KOSPI,02=KOSDAQ}&page={n}`
  - 정적 HTML 표(JS 아님), 인코딩 **euc-kr**(반드시 지정), `pd.read_html`로 파싱. 단위 **억원**.
  - 컬럼: 날짜/개인/외국인/기관계/(세부 기관)/기타법인. **page당 유효 5영업일** (빈 행 제외).
  - 실측: 2026-07-07 KOSPI 외국인 −29,172 / 기관계 −3,108 정상.
  - **주의**: 현재 `fetch_kr_flow.py`가 쓰는 URL/페이지 가정(문서상 "페이지당 10영업일")과 **실측(5영업일)이 다름** → 현 구현이 어느 엔드포인트를 쓰는지 확인하고, 4주(20영업일) 판정엔 page 1~4까지 수집 필요.
  - **종목별 수급도 가능**: `https://finance.naver.com/item/frgn.naver?code={종목코드}` (기관/외국인 순매매량 + 보유율).
- **KRX 신규 공식 OPEN API** (`openapi.krx.co.kr`, 무료 키): OHLCV·지수·채권은 있으나 **투자자별 수급 미제공** → 로테이션 체크리스트엔 무용. 단 OHLCV 백본 백업으론 가치.
- **공공데이터포털/FinanceDataReader/pykrx/다음 금융**: 전부 수급 미제공 또는 불안정(다음 JSON은 HTTP 500).

### 해결책 (하드닝)
- 네이버 스크래핑 유지 + 보강: ① `encoding='euc-kr'` 명시 ② UA 헤더 필수 ③ 요청간 sleep(1~2s) ④ **파싱 실패 시 텔레그램 알림**(URL/스키마 변경으로 조용히 끊기는 사고 방지 — 이게 유일한 구조적 리스크) ⑤ 빈행 NaN 필터 + sanity check.
- (선택) KRX OPEN API 무료 키를 미리 발급해 시세 백본 이원화(수급=네이버, OHLCV=KRX 공식) 대비.

### 난이도 / 우선순위
- **low / P3** — 이미 작동 중. 하드닝(특히 실패 알림)만 추가. VKOSPI는 여전히 무키 소스 없음(미구현 유지).

---

## 이슈 #4 — Capex vs 마진 프록시 개선

### 현황
- ⑤ 공급과잉 지표: Capex=`NEWORDER` YoY, 마진=`CP/GDP`(세후 기업이익 ÷ 명목GDP). 문제: CP/GDP는 (a) 전 산업 세후이익이라 S&P500과 괴리, (b) 개념상 "이익÷GDP"라 분모가 마진의 분모(매출·부가가치)가 아님, (c) 분기·발표지연 ~2개월.

### 해결책 (검증 완료 — curl 실측)

**1순위 (즉시·무비용): CP/GDP → `A466RD3Q052SBEA`**
- = 비금융법인 실질부가가치 **단위당 세후이익 = 진짜 단위 마진**. 키리스 CSV로 Q1'26(값 0.186)까지 확인. GFC 때 0.065까지 급락 → **사이클 정점/저점을 CP/GDP보다 선명하게 표현**.
- 이점: 나눗셈 제거(2콜→1콜), 개념 정확, **판정 룰 무변경**(여전히 분기·2개월 지연이라 "2분기 연속 하락=🔴" 로직 그대로). 논리 고정("투자는 느는데 마진이 꺾인다") 유지.
- 코드: `fetch_fred.py` L233-247 `cp`/`gdp` 나눗셈 → 단일 시리즈(×100 %표기). `CONTRACT.md` L170·L183 "CP/GDP" 문구 동반 갱신.

**보완 (여유 시):**
- `ULCNFB`(비금융기업 단위노동비용, 키리스, 분기·~1개월): "비용 오르는데 가격 못 올림 = 마진 꺾임" **선행** 보조라인.
- multpl EPS(이미 스크래핑) ÷ SPS(sales 페이지 파서 추가, med) = **S&P500 실물 순이익률** 참고선. 단 sales도 실질 분기 갱신이라 실시간 이득 제한적.

**주의 (지연은 못 줄임)**: 진짜 실시간 선행지표는 Yardeni fwd margin / I·B·E·S NERI지만 **무료 자동수집 불가(차트 이미지뿐)** → 채택 비권장, 필요 시 수동 주석. 빅테크 AI capex 집중($700~900B, +77% YoY)도 무료 시계열 없음 → 서사 주석만.

### 난이도 / 우선순위
- 1순위 교체: **low / P1**. ULCNFB 보완: low / P2. multpl margin: med / P3.

---

## 이슈 #5 — 마켓맵 treemap + EWY/KOSPI 카드

### 현황
- 없음. 신설. ECharts5 CDN 확인됨(`site/index.html:76`). treemap `series` 타입 지원 확인.

### 해결책 (설계)

**A) EWY + KOSPI 요약 카드 (P2, 최우선·최저난이도)**
- EWY(iShares MSCI South Korea)·`^KS11`은 단일 티커. 최신가 + 1D%만. **KOSPI는 기존 `kospi.json`에서 계산 → 신규 fetch 0**(snapshot 스타일 후처리). EWY만 2행 다운로드.
- 기존 `snapshot.json`의 `cards[]` 스키마(`value/unit/d1/state/caption`) 그대로 재사용 → **프론트 렌더러 신설 불필요**.

**B) US 마켓맵 treemap (P2)**
- **데이터 소스**: 기존 `sectors.json`(SPDR 11섹터, 매일 `perf.1D` 이미 수집) 재사용. `build_snapshot()` 스타일 후처리로 marketmap JSON 생성(추가 네트워크 0). 타일 크기=섹터 ETF 시총(`yf.Ticker.fast_info`) 또는 **고정/균등(색이 신호 담당)**.
- **색상**: 파이프라인에서 1D%→hex 계산(Finviz 스타일 발산: red `#c0392b`→gray `#6b7280`(0)→green `#27ae60`, ±3% 클램프) 후 `itemStyle.color`로 JSON에 실어보냄. snapshot이 이미 `state` 색을 계산해 보내는 방식과 일관. (visualMap 연속색도 v5 지원되나 소형 카드엔 과함 — 폴백.)
- **신규 chart type `"marketmap"`** 스키마(하위호환 추가):
  ```json
  {
    "id": "us_marketmap", "type": "marketmap", "title": "US 마켓맵",
    "subtitle": "SPDR 섹터 ETF · 타일=시총, 색=1D%", "source": "Yahoo Finance",
    "updated": "...", "colorScale": {"min": -3, "max": 3, "unit": "%"},
    "tree": [
      {"name": "Technology", "children": [
        {"name": "AAPL", "value": 3.2e12, "d1": -1.24, "itemStyle": {"color": "#c0392b"}}
      ]}
    ]
  }
  ```
  - `tree` → `series[0].data`로 매핑. `value`=시총(면적), `d1`=툴팁용 커스텀 필드(ECharts 무시), 섹터 부모 value는 children 자동합산.
  - 섹터-only 변형: `children` 없이 11 SPDR 타일만(가장 단순).
- **프론트**: `site/js`에 `renderMarketmap()` 분기 신설(기존 timeseries/heatmap_perf 옆). treemap 옵션: `roam:false, nodeClick:false, breadcrumb.show:false, leafDepth:2, upperLabel`(섹터명 밴드).

**C) KR/KOSPI treemap (선택)**
- **KOSPI 섹터 비중 무료 소스 없음**(KRX/FnGuide 게이트). 개별종목 비중 받지 말 것.
- 대안: **KODEX/TIGER 섹터 ETF treemap**(반도체 091160.KS, 은행 091170.KS 등) — 각 단일 티커 1D%. US SPDR과 동일 코드 경로, 무키. 또는 KR treemap 생략하고 A) 카드 + 기존 수급 차트로 갈음.

### 난이도 / 우선순위
- EWY/KOSPI 카드: **low / P2**(먼저). US SPDR treemap: **low~med / P2**. KR ETF treemap: med / P3. US 개별종목 드릴다운(~50-110티커 배치, `market_cap` null 캐시 필요): med~high / P3(비주얼 최고).

---

## 이슈 #6 — CONTRACT.md 개선 (시리즈별 lineStyle/dashed)

### 현황
- `timeseries`는 시리즈별 `name`/`yAxis`/`data`만. 실선 단일 스타일. 프록시·보조선(예: MA, 스프레드 참고선)을 시각적으로 구분 못 함.

### 설계 (하위호환 확장 — 파괴 아님)
- **시리즈에 선택적 `lineStyle` 객체 추가**. 없으면 기존 실선 동작 그대로:
  ```json
  {
    "name": "MU/한국 메모리 선행 스프레드", "yAxis": 1,
    "lineStyle": { "type": "dashed", "width": 2, "color": "#888" },
    "data": [["2024-01-02", 101.2]]
  }
  ```
  - `type`: `"solid"`(기본, 생략 시) | `"dashed"` | `"dotted"` — ECharts `series.lineStyle.type` 그대로 통과.
  - `width`(선택, px), `color`(선택, hex) — 생략 시 테마 기본.
  - 대안 최소안: `"dashed": true` boolean 하나만. 하지만 width/color 확장성 위해 **객체 형태 권장**.
- **하위호환 원칙** (기존 `markLines`/`unit2`/`xAxisType` 확장과 동일 패턴):
  - 필드 부재 → 프론트는 기존대로 실선 렌더. 파이프라인 미출력 시 무영향.
  - 프론트 `renderTimeseries()`에서 `s.lineStyle`가 있으면 ECharts series 옵션에 spread, 없으면 생략.
- **CONTRACT.md 반영 위치**: "timeseries 확장 필드" 절(현 markLines/unit2 아래)에 `lineStyle` 항목 추가 + "규격 확장이며 파괴 아님" 명시. 실제 첫 사용처 예: `capex_margin`의 마진 프록시선, `ls_memory_cycle`의 선행 스프레드선 등을 점선 처리.

### 난이도 / 우선순위
- **low / P2** — 스키마 1필드 + 프론트 렌더러 한 줄 분기. 리스크 없음.

---

## 이슈 #7 — ECOS(한국은행) 키 활용

### 현황
- ECOS 미사용. 키 발급 가능(무료). 채권/금리 섹션을 한국 국고채·한미금리차로 확장할 여지.

### 조사 결과 (통계표코드 교차확인)
- **키 발급**: ecos.bok.or.kr/api 회원가입 → 인증키 신청, 무료·자동, 통상 1일 내.
- **엔드포인트**: `https://ecos.bok.or.kr/api/StatisticSearch/{KEY}/json/kr/{시작}/{끝}/{통계표}/{주기}/{검색시작}/{검색종료}/{항목1}...`
  - 응답 `StatisticSearch.row[]` → `TIME`(YYYYMMDD), `DATA_VALUE`(문자열). 에러 `RESULT.CODE`(INFO-200=데이터없음/INFO-100=인증오류).
  - **결측·공휴일 갭 처리 필수**(`DATA_VALUE` 빈 문자열/누락 row → `float()` 전 필터).
- **정정**: 요청 가정 `817Y002`는 근거 못 찾음 → 시장금리(일별)는 **`060Y001`**. 환율은 731Y001 아니라 **731Y003**.

**확인된 코드 (일부 재확인 권장)**:
| 지표 | 통계표 | 항목 | 주기 | 확인도 |
|------|--------|------|------|--------|
| 국고채 3년 | 060Y001 | 010200000 | D | 교차확인 |
| 국고채 5년 | 060Y001 | 010200001 | D | 확인 |
| 국고채 10년 | 060Y001 | 010210000 | D | 확인 |
| 국고채 30년 | 060Y001 | 010230000 | D | **재확인 권장** |
| 회사채 3년 AA- | 060Y001 | 010310000 | D | **재확인 권장** |
| CD 91일 | 060Y001 | 010502000 | D | **재확인 권장** |
| 한은 기준금리 | 722Y001 | 0101000 | M | 교차확인 |
| 원/달러 | 731Y003 | 0000002 | D | 확인(단 yfinance KRW=X와 **중복** → 제외) |

### 해결책 (추천 차트)

**추천 1 — 한미 장기금리차 (P2, 최우선)**
- 한국 국고채 10Y(ECOS `060Y001/D/010210000`) − 미국 10Y(**FRED `DGS10`, 기존 키리스 CSV 폴백 재사용**). 날짜 정렬 후 차감, 라인 + 0선. 정책금리차(ECOS 722Y001/0101000 − FRED FEDFUNDS)를 보조선. **채권 로테이션·환율 방향 판단에 직결** ([[investment-decision-framework]] 채권 A/B 트리거와 연결).
- 수집: ECOS 1콜 + FRED 1콜. 난이도 med.

**추천 2 — 국고채 수익률 곡선 (P2)**
- ECOS `060Y001/D` 항목 4개(3·5·10·30년). 표현: (a) 멀티라인 시계열 또는 (b) 최신일 스냅샷 곡선(`curve_snapshot` 타입 재사용!) + 3·10년 스프레드. 난이도 하~중.

- 미국 금리는 ECOS 말고 **FRED 키리스 재사용이 압도적으로 간단**(항목코드 확인 부담 없음).
- 원/달러(중복), 외환보유액·경상수지(통계표코드 미확정 → 키 발급 후 `StatisticTableList`/`StatisticItemList`로 정본 확정) 는 후순위.

### 난이도 / 우선순위
- 한미금리차: **med / P2**. 국고채 곡선: 하~중 / P2. 키 발급 후 5분 검증(항목 목록조회로 30년/회사채/CD 코드 확정)이 선행.

---

## 부록 — 실행 묶음 제안 (한 세션 1목표 원칙)

- **세션 A (FRED, low, 즉효)**: #1 HY OAS 키리스 + #4 마진 프록시 교체. 둘 다 `fetch_fred.py` 한 파일. → 버블 체크리스트 정밀도↑, HY OAS 상시 ready.
- **세션 B (jarvis-brief 버그, low)**: #2 `_ts_last` series_name 인자 + Fwd/10Y 라벨 정정. 독립. → 매일 틀린 숫자 제거.
- **세션 C (마켓맵, low~med)**: #5 EWY/KOSPI 카드 먼저 → US SPDR treemap(`marketmap` 타입 + 렌더러).
- **세션 D (ECOS 확장, med)**: 키 발급·검증 → #7 한미금리차 + 국고채 곡선. #6 lineStyle을 여기서 같이(점선 보조선 필요).
- **상시 (P3)**: #3 네이버 파싱실패 텔레 알림, 버핏지수는 Valley 링크 유지.

> 코드 수정은 각 세션에서 **워크플로우 제시 → 컨펌 → 서브에이전트 백그라운드** 순서로 (WORKSPACE CLAUDE.md HARD RULE).

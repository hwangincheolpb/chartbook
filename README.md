# Chartbook

글로벌 주요 시장 지표를 매일 자동으로 수집·시각화하는 개인 차트북.
S&P 500, KOSPI, VIX, 섹터 퍼포먼스, 채권/금리 등 핵심 차트를
로컬 정적 사이트(HTML+JS)로 제공한다. Valley AI(valley.town)에 있는 기능
(버핏지수·사이클 히트맵·13F 등)은 재개발하지 않고 링크 카드로 연결한다.

---

## 구조

```
chartbook/
├── pipeline/           # 데이터 수집 파이프라인
│   ├── run.py          # 오케스트레이터 (진입점)
│   ├── fetch_yahoo.py  # Yahoo Finance 수집
│   ├── fetch_fred.py   # FRED 수집 (API 키 필요)
│   ├── config.yaml     # 차트 설정 (여기만 편집)
│   └── requirements.txt
├── site/               # 정적 사이트 (index.html, js, css)
├── data/               # 수집된 JSON 파일 (자동 생성)
├── logs/               # 실행 로그 (자동 생성)
├── scripts/
│   ├── update.sh       # 파이프라인 실행 스크립트
│   └── serve.sh        # 로컬 HTTP 서버
├── launchd/
│   └── com.user.chartbook.plist   # macOS LaunchAgent
└── .env.example        # 환경변수 샘플
```

---

## 설치

### 1. 의존성 설치

```bash
cd ~/workspace/dev/chartbook
python3 -m venv .venv
source .venv/bin/activate
pip install -r pipeline/requirements.txt
```

### 2. FRED API 키 설정 (선택)

FRED 키가 없으면 Yahoo Finance 차트(S&P 500, KOSPI, VIX, 섹터)는 정상 수집되고,
FRED 기반 차트(하이일드 OAS)만 `ready: false`로 처리된다.

```bash
cp .env.example .env
# .env 를 열어 FRED_API_KEY= 에 키 입력
# 발급: https://fredaccount.stlouisfed.org/apikeys
```

---

## 파이프라인 수동 실행

```bash
cd ~/workspace/dev/chartbook
scripts/update.sh
```

또는 직접:

```bash
source .venv/bin/activate
python pipeline/run.py
```

결과는 `data/*.json`에 저장되고, `logs/update.log`에 기록된다.

---

## 차트북 열람

```bash
scripts/serve.sh
# → http://localhost:8765/site/ 를 브라우저에서 열기
```

---

## 매일 자동 업데이트 설정 (macOS launchd)

### 1. LaunchAgent 설치

```bash
# 복사 방식
cp ~/workspace/dev/chartbook/launchd/com.user.chartbook.plist \
   ~/Library/LaunchAgents/com.user.chartbook.plist

# 또는 심볼릭 링크 방식 (plist 수정 시 재설치 불필요)
ln -sf ~/workspace/dev/chartbook/launchd/com.user.chartbook.plist \
       ~/Library/LaunchAgents/com.user.chartbook.plist
```

### 2. 등록 및 즉시 실행

```bash
launchctl load ~/Library/LaunchAgents/com.user.chartbook.plist
```

등록하면 즉시 1회 실행(`RunAtLoad true`)되고, 이후 매일 **06:30**에 자동 실행된다.

### 3. 상태 확인

```bash
launchctl list | grep chartbook
# 결과 예: -  0  com.user.chartbook   (마지막 종료 코드 0 = 정상)
```

### 4. 비활성화

```bash
launchctl unload ~/Library/LaunchAgents/com.user.chartbook.plist
```

### 5. 로그 확인

```bash
tail -f ~/workspace/dev/chartbook/logs/update.log
```

---

## 새 차트 추가

`pipeline/config.yaml` 만 편집하면 된다. 새 항목을 추가하고 `source: yahoo` 또는
`source: fred` 를 지정한 뒤 파이프라인을 실행하면 자동으로 `data/<id>.json`이 생성되고
`index.json`에 반영된다.

```yaml
# 예시
- id: nasdaq
  section: "주식시장"
  type: timeseries
  source: yahoo
  title: "NASDAQ 100"
  tickers:
    - "^NDX"
  series_names:
    "^NDX": "NASDAQ 100"
  lookback_years: 6
```

---

## 주의사항

- `.env` 파일은 절대 커밋하지 않는다 (`.gitignore` 등록됨).
- `data/` 의 JSON 파일은 커밋 여부를 프로젝트 정책에 따라 결정한다.
- `logs/*.log` 는 `.gitignore`에서 제외되어 커밋되지 않는다.

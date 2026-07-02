#!/usr/bin/env bash
# serve.sh — Chartbook + 로컬 대시보드 통합 HTTP 서버 (개발/열람용)
# dev 루트를 서빙해서 차트북과 형제 대시보드를 같은 origin(localhost)에 띄운다.
# 배포 없이 전부 로컬로 연결됨. 127.0.0.1 바인딩(네트워크 노출 방지).
set -euo pipefail

DEV_ROOT="/Users/ai/workspace/dev"
# 8765는 jarvis-voice 데몬이 점유 → 8770으로 변경(링크 카드 URL도 동일 포트). 충돌 회피.
PORT=8770

cd "${DEV_ROOT}"

echo ""
echo "========================================================"
echo " Chartbook 로컬 서버 시작 (dev 루트, 127.0.0.1 전용)"
echo " 차트북:        http://localhost:${PORT}/chartbook/site/"
echo " 피어밸류:      http://localhost:${PORT}/peer-valuation-monitor/"
echo " 금융상품:      http://localhost:${PORT}/financial-products/"
echo " 쇼티지:        http://localhost:${PORT}/structural-shortage-dashboard/"
echo " 액티브ETF:     http://localhost:${PORT}/active-etf-tracker/web/"
echo " 머니플로우:    http://localhost:${PORT}/money-flow/money-flow-2026.html"
echo " 종료: Ctrl+C"
echo "========================================================"
echo ""

exec python3 -m http.server "${PORT}" --bind 127.0.0.1

#!/usr/bin/env bash
# run.sh — 차트 제작/관리 툴 실행
# admin UI: http://localhost:8772/admin
# 8765는 jarvis-voice 데몬이 점유 → 8772로 변경. 충돌 회피.
set -euo pipefail

TOOL_DIR="/Users/ai/workspace/dev/chartbook/tool"
VENV="/Users/ai/workspace/dev/chartbook/.venv"   # 상위 chartbook venv 재사용
PORT="${PORT:-8772}"

cd "${TOOL_DIR}"

# venv 활성화 (없으면 안내)
if [[ -f "${VENV}/bin/activate" ]]; then
  # shellcheck source=/dev/null
  source "${VENV}/bin/activate"
else
  echo "venv 없음: ${VENV}"
  echo "  → python3 -m venv ${VENV} && ${VENV}/bin/pip install -r ${TOOL_DIR}/requirements.txt"
  exit 1
fi

# .env 로드(있으면) — FRED/ECOS 키
if [[ -f "${TOOL_DIR}/.env" ]]; then
  set -a; source "${TOOL_DIR}/.env"; set +a
fi

echo "========================================================"
echo " Chartbook 관리 툴"
echo " Admin UI : http://localhost:${PORT}/admin"
echo " API      : http://localhost:${PORT}/api/sources"
echo " 종료     : Ctrl+C"
echo "========================================================"

exec uvicorn server.main:app --reload --port "${PORT}"

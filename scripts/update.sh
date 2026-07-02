#!/usr/bin/env bash
# update.sh — Chartbook 데이터 파이프라인 실행 스크립트
# 매일 launchd가 자동 실행하거나 수동으로 실행해도 안전하다.
set -euo pipefail

CHARTBOOK_DIR="/Users/ai/workspace/dev/chartbook"
LOG_FILE="${CHARTBOOK_DIR}/logs/update.log"
VENV_ACTIVATE="${CHARTBOOK_DIR}/.venv/bin/activate"
ENV_FILE="${CHARTBOOK_DIR}/.env"

# ── 로그 헬퍼 ─────────────────────────────────────────────────────
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOG_FILE}"
}

# ── 실행 시작 구분선 ──────────────────────────────────────────────
{
    echo ""
    echo "========================================================"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] update.sh 시작"
    echo "========================================================"
} >> "${LOG_FILE}" 2>&1

# ── 작업 디렉토리 이동 ────────────────────────────────────────────
cd "${CHARTBOOK_DIR}"

# ── venv 활성화 ───────────────────────────────────────────────────
if [[ ! -f "${VENV_ACTIVATE}" ]]; then
    log "ERROR: venv not found at ${VENV_ACTIVATE}"
    log "  → python -m venv .venv && .venv/bin/pip install -r pipeline/requirements.txt"
    exit 1
fi
# shellcheck source=/dev/null
source "${VENV_ACTIVATE}"
log "venv 활성화: ${VIRTUAL_ENV}"

# ── .env 로드 (선택) ──────────────────────────────────────────────
if [[ -f "${ENV_FILE}" ]]; then
    # export VAR=VALUE 형태만 안전하게 읽는다
    set -a
    # shellcheck source=/dev/null
    source "${ENV_FILE}"
    set +a
    log ".env 로드 완료"
else
    log ".env 없음 — FRED_API_KEY 미설정 (FRED 차트 스킵)"
fi

# ── 파이프라인 실행 ───────────────────────────────────────────────
log "python pipeline/run.py 실행 중..."
python pipeline/run.py >> "${LOG_FILE}" 2>&1
EXIT_CODE=$?

if [[ ${EXIT_CODE} -eq 0 ]]; then
    log "파이프라인 완료 (exit 0)"
else
    log "ERROR: 파이프라인 종료 코드 ${EXIT_CODE}"
    exit "${EXIT_CODE}"
fi

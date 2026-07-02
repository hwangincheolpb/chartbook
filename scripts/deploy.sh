#!/usr/bin/env bash
# deploy.sh — chartbook GitHub Pages 자동 배포
# 매일 06:50 launchd(com.user.chartbook.deploy)가 실행.
# data/·site/ 변경이 있으면 커밋 후 push, 없으면 no-op.
set -uo pipefail

CHARTBOOK_DIR="/Users/ai/workspace/dev/chartbook"
LOG_FILE="${CHARTBOOK_DIR}/logs/deploy.log"
mkdir -p "${CHARTBOOK_DIR}/logs"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "${LOG_FILE}"
}

cd "${CHARTBOOK_DIR}" || { log "ERROR: cd 실패"; exit 1; }

# 변경 여부 확인 (.gitignore 반영된 상태 기준)
if [[ -z "$(git status --porcelain)" ]]; then
    log "deploy ok — 변경 없음 (no-op)"
    exit 0
fi

git add -A >> "${LOG_FILE}" 2>&1
if ! git commit -m "daily data update $(date '+%Y-%m-%d')" >> "${LOG_FILE}" 2>&1; then
    log "ERROR: git commit 실패"
    exit 1
fi

if git push origin main >> "${LOG_FILE}" 2>&1; then
    log "deploy ok — push 완료"
else
    log "ERROR: git push 실패"
    exit 1
fi

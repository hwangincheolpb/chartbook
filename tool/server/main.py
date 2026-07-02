"""
main.py — 차트 제작/관리 툴 FastAPI 앱

허브가 읽는 실제 레지스트리(data/index.json + data/<id>.json, CONTRACT.md)를 CRUD 한다.
admin UI는 /admin 에서 정적 서빙.

실행: tool/run.sh  (uvicorn server.main:app --reload --port 8772)
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# .env 로드 (tool/.env 또는 chartbook/.env)
try:
    from dotenv import load_dotenv

    TOOL_DIR = Path(__file__).resolve().parent.parent
    for env_path in (TOOL_DIR / ".env", TOOL_DIR.parent / ".env"):
        if env_path.exists():
            load_dotenv(env_path)
except Exception:  # noqa: BLE001
    pass

from . import cache, registry, transform  # noqa: E402
from .adapters import SEARCHABLE, all_adapters, get_adapter  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("chartbook-tool")

app = FastAPI(title="Chartbook 관리 툴", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 로컬 admin/허브에서 호출 허용
    allow_methods=["*"],
    allow_headers=["*"],
)

ADMIN_DIR = Path(__file__).resolve().parent.parent / "admin"


# ─── 소스 목록 ──────────────────────────────────────────────────
@app.get("/api/sources")
def api_sources() -> dict[str, Any]:
    out = []
    for name, ad in all_adapters().items():
        out.append(
            {
                "source": name,
                "needs_key": ad.needs_key,
                "available": ad.available(),
            }
        )
    # manual은 어댑터 없이 항상 사용 가능(수동 입력/링크 차트)
    out.insert(0, {"source": "manual", "needs_key": False, "available": True})
    return {"sources": out}


# ─── 검색 ───────────────────────────────────────────────────────
@app.get("/api/search")
def api_search(
    q: str = Query(..., min_length=1),
    source: str = Query("all"),
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    sources = SEARCHABLE if source in ("all", "") else [source]
    for s in sources:
        ad = get_adapter(s)
        if ad is None:
            continue
        if ad.needs_key and not ad.available():
            continue  # 키 없는 소스는 조용히 건너뜀
        try:
            results.extend(ad.search(q))
        except Exception as e:  # noqa: BLE001
            logger.warning("검색 실패 [%s]: %s", s, e)
    return {"query": q, "source": source, "count": len(results), "results": results}


# ─── 미리보기 ───────────────────────────────────────────────────
@app.get("/api/preview")
def api_preview(
    source: str = Query(...),
    id: str = Query(...),
    transform: str = Query("none"),
) -> dict[str, Any]:
    ad = get_adapter(source)
    if ad is None:
        raise HTTPException(400, f"알 수 없는 소스: {source}")
    res = ad.fetch(id)
    dates = res.get("dates") or []
    values = res.get("values") or []
    if transform and transform != "none" and values:
        from .transform import apply_transform

        dates, values = apply_transform(dates, values, transform)
    # 미리보기는 마지막 ~400개만 (응답 경량화). 원본 길이는 meta에.
    n = len(dates)
    if n > 400:
        dates, values = dates[-400:], values[-400:]
    return {
        "source": source,
        "id": id,
        "dates": dates,
        "values": values,
        "count": n,
        "meta": res.get("meta", {}),
        "error": res.get("error"),
    }


# ─── 레지스트리 / 주제 ──────────────────────────────────────────
@app.get("/api/registry")
def api_registry() -> dict[str, Any]:
    return registry.read_index()


@app.get("/api/topics")
def api_topics() -> dict[str, Any]:
    """주제(=section) 목록 + 섹션별 차트."""
    idx = registry.read_index()
    by_section: dict[str, list[dict[str, Any]]] = {}
    for c in idx.get("charts", []):
        by_section.setdefault(c.get("section", "기타"), []).append(c)
    topics = [{"section": s, "charts": ch} for s, ch in by_section.items()]
    return {"topics": topics, "sections": registry.list_sections()}


# ─── 차트 추가 ──────────────────────────────────────────────────
_ID_RE = re.compile(r"[^a-z0-9_]+")


def _slug(text: str) -> str:
    s = _ID_RE.sub("_", text.strip().lower()).strip("_")
    return s or "chart"


@app.post("/api/charts")
def api_add_chart(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """
    body 예:
    {
      "section": "환율" 또는 "topicId",     # 주제(없으면 생성됨 = 그냥 새 section 라벨)
      "id": "eurusd" (선택, 없으면 title 슬러그),
      "title": "EUR/USD",
      "summary": "유로/달러",
      "type": "line|bar|table|link",
      "unit": "index",
      "source": "yfinance|dbnomics|krx|fred|ecos|manual",
      "series": [{"sourceId":"EURUSD=X","label":"EUR/USD","transform":"none"}],
      "sourceNote": "Yahoo Finance",
      "url": "" (link 타입일 때),
      "note": ""
    }
    내부차트(source!=manual,link)면 즉시 fetch해서 data/<id>.json 생성.
    link/manual이면 data만 저장(링크/수동).
    """
    section = payload.get("section") or payload.get("topicId") or "기타"
    title = payload.get("title") or "(제목 없음)"
    chart_type = payload.get("type") or "line"
    unit = payload.get("unit") or ""
    summary = payload.get("summary") or ""
    note = payload.get("note") or ""
    source = payload.get("source") or "manual"
    series_defs = payload.get("series") or []
    source_note = payload.get("sourceNote") or source

    chart_id = payload.get("id") or _slug(title)
    # id 충돌 방지: 이미 있으면 접미사
    base_id = chart_id
    n = 2
    while registry.chart_exists(chart_id) and not payload.get("overwrite"):
        chart_id = f"{base_id}_{n}"
        n += 1

    # 허브 index.json type 매핑: line/bar/table → timeseries (허브는 timeseries 렌더)
    # link → 허브엔 link 타입이 없으므로 timeseries 빈 차트 대신 manual 취급.
    index_type = "timeseries"
    ready = True

    if source in ("manual", "link") or chart_type in ("table", "link"):
        # 수동/링크: 사용자가 직접 넣은 data를 그대로 저장(있으면), 없으면 빈 시리즈.
        chart_data = payload.get("data") or {
            "id": chart_id,
            "type": "timeseries",
            "title": title,
            "subtitle": summary,
            "source": source_note,
            "unit": unit,
            "updated": transform._now_kst(),
            "series": [],
        }
        if payload.get("url"):
            chart_data.setdefault("links", []).append(
                {"label": title, "url": payload["url"]}
            )
            ready = False  # 데이터 없는 링크 카드는 placeholder
        result = registry.upsert_chart(chart_id, section, index_type, chart_data, ready=ready)
        return {"ok": True, "id": chart_id, **result}

    # 내부차트: 어댑터로 즉시 fetch
    ad = get_adapter(source)
    if ad is None:
        raise HTTPException(400, f"알 수 없는 소스: {source}")
    if ad.needs_key and not ad.available():
        # 키 없으면 placeholder(ready:false)로 등록 — 키 추가 후 /refresh로 채움
        chart_data = {
            "id": chart_id,
            "type": "timeseries",
            "title": title,
            "subtitle": summary,
            "source": source_note,
            "unit": unit,
            "updated": transform._now_kst(),
            "series": [],
            "note": f"{source} 키 필요 — 키 설정 후 /api/refresh",
            "_series_defs": series_defs,
            "_source": source,
        }
        result = registry.upsert_chart(chart_id, section, index_type, chart_data, ready=False)
        return {"ok": True, "id": chart_id, "ready": False, "reason": "key needed", **result}

    if not series_defs:
        raise HTTPException(400, "series가 비어 있습니다 (내부차트는 1개 이상 필요)")

    fetched: dict[str, dict[str, Any]] = {}
    for sd in series_defs:
        sid = sd.get("sourceId")
        if not sid:
            continue
        res = ad.fetch(sid)
        cache.save(f"{chart_id}__{registry._now_kst()[:10]}__{_slug(sid)}", res)
        fetched[sid] = res

    chart_data = transform.build_timeseries(
        chart_id=chart_id,
        title=title,
        summary=summary,
        unit=unit,
        source_label=source_note,
        series_defs=series_defs,
        fetched=fetched,
        note=note,
    )
    # refresh를 위해 소스/시리즈 정의를 차트에 저장(허브는 무시, 우리만 사용)
    chart_data["_source"] = source
    chart_data["_series_defs"] = series_defs

    has_data = any(s.get("data") for s in chart_data.get("series", []))
    result = registry.upsert_chart(
        chart_id, section, index_type, chart_data, ready=has_data
    )
    return {"ok": True, "id": chart_id, "ready": has_data, "points": {
        s["name"]: len(s["data"]) for s in chart_data.get("series", [])
    }, **result}


# ─── 차트 삭제 ──────────────────────────────────────────────────
@app.delete("/api/charts/{topic_id}/{tile_id}")
def api_delete_chart(topic_id: str, tile_id: str) -> dict[str, Any]:
    """
    topic_id(=section)는 호환을 위해 받지만 삭제는 tile_id(=chart id) 기준.
    """
    if not registry.chart_exists(tile_id):
        raise HTTPException(404, f"차트 없음: {tile_id}")
    result = registry.delete_chart(tile_id)
    return {"ok": True, "id": tile_id, **result}


# ─── 갱신 ───────────────────────────────────────────────────────
def _refresh_one(chart_id: str) -> dict[str, Any]:
    chart = registry.read_chart(chart_id)
    if chart is None:
        return {"id": chart_id, "ok": False, "reason": "차트 데이터 파일 없음"}

    source = chart.get("_source")
    series_defs = chart.get("_series_defs")

    # 우리 도구로 만든 내부차트만 _source/_series_defs 보유.
    # 파이프라인이 만든 차트(sp500 등)는 이 필드가 없으므로 건너뜀(파이프라인 담당).
    if not source or source in ("manual", "link") or not series_defs:
        return {"id": chart_id, "ok": False, "reason": "내부차트 아님(파이프라인/수동) — 건너뜀"}

    ad = get_adapter(source)
    if ad is None:
        return {"id": chart_id, "ok": False, "reason": f"알 수 없는 소스 {source}"}
    if ad.needs_key and not ad.available():
        return {"id": chart_id, "ok": False, "reason": f"{source} 키 필요"}

    fetched: dict[str, dict[str, Any]] = {}
    for sd in series_defs:
        sid = sd.get("sourceId")
        if not sid:
            continue
        res = ad.fetch(sid)
        cache.save(f"{chart_id}__{registry._now_kst()[:10]}__{_slug(sid)}", res)
        fetched[sid] = res

    new_data = transform.build_timeseries(
        chart_id=chart_id,
        title=chart.get("title", chart_id),
        summary=chart.get("subtitle", ""),
        unit=chart.get("unit", ""),
        source_label=chart.get("source", source),
        series_defs=series_defs,
        fetched=fetched,
        note=chart.get("note", ""),
    )
    new_data["_source"] = source
    new_data["_series_defs"] = series_defs

    has_data = any(s.get("data") for s in new_data.get("series", []))
    # index에서 section/type 보존하며 upsert
    idx = registry.read_index()
    section = next(
        (c.get("section") for c in idx.get("charts", []) if c.get("id") == chart_id),
        "기타",
    )
    registry.upsert_chart(chart_id, section, "timeseries", new_data, ready=has_data)
    return {
        "id": chart_id,
        "ok": True,
        "ready": has_data,
        "points": {s["name"]: len(s["data"]) for s in new_data.get("series", [])},
    }


@app.post("/api/refresh")
def api_refresh(chartId: str | None = Query(None)) -> dict[str, Any]:
    """
    chartId 지정 시 해당 차트만, 없으면 우리 도구가 만든 내부차트 전체 갱신.
    파이프라인/수동/링크 차트는 건너뛴다(소유권 분리).
    """
    if chartId:
        return {"refreshed": [_refresh_one(chartId)]}
    out = []
    for c in registry.read_index().get("charts", []):
        cid = c.get("id")
        chart = registry.read_chart(cid)
        if chart and chart.get("_source") and chart.get("_series_defs"):
            out.append(_refresh_one(cid))
    return {"refreshed": out, "count": len(out)}


# ─── intake: 사진 → 차트 (헤드리스 chart-reproduce) ────────────
# 흐름: 이미지 업로드 → inbox 저장 → claude -p 헤드리스 백그라운드 호출
#       → chart-reproduce 스킬(auto 모드)이 "인박스" 섹션에 드래프트 등록.
CHARTBOOK_DIR = Path(__file__).resolve().parent.parent.parent  # dev/chartbook
INBOX_DIR = CHARTBOOK_DIR / "inbox"
INTAKE_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"  # tool/logs
JOBS_FILE = INBOX_DIR / "jobs.json"
WORKSPACE_DIR = Path.home() / "workspace"

_ALLOWED_IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")

# 잡 상태: 메모리 dict가 진실, jobs.json은 재시작 대비 백업.
# {job_id: {"id","image","log","status","created","exit_code","charts_before":[...]}}
_jobs: dict[str, dict[str, Any]] = {}
_procs: dict[str, subprocess.Popen] = {}


def _jobs_save() -> None:
    try:
        INBOX_DIR.mkdir(parents=True, exist_ok=True)
        JOBS_FILE.write_text(
            json.dumps(_jobs, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("jobs.json 저장 실패: %s", e)


def _jobs_load() -> None:
    if not JOBS_FILE.exists():
        return
    try:
        _jobs.update(json.loads(JOBS_FILE.read_text(encoding="utf-8")))
        # 재시작 후 프로세스 핸들은 없음 → processing 잡은 고아 처리
        for j in _jobs.values():
            if j.get("status") == "processing":
                j["status"] = "stale"
                j["detail"] = "서버 재시작으로 프로세스 추적 유실 — 로그 확인 필요"
    except Exception as e:  # noqa: BLE001
        logger.warning("jobs.json 로드 실패: %s", e)


_jobs_load()


def _chart_ids() -> set[str]:
    return {c.get("id") for c in registry.read_index().get("charts", [])}


def _log_tail(path: str, lines: int = 30) -> str:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        return "\n".join(text.splitlines()[-lines:])
    except Exception:  # noqa: BLE001
        return "(로그 없음)"


@app.post("/api/intake")
def api_intake(image: UploadFile = File(...)) -> dict[str, Any]:
    """차트 사진 업로드 → inbox 저장 → 헤드리스 claude 잡 생성 → 즉시 반환."""
    claude_bin = shutil.which("claude") or (
        str(Path.home() / ".nvm/versions/node/v22.22.0/bin/claude")
        if (Path.home() / ".nvm/versions/node/v22.22.0/bin/claude").exists()
        else None
    )
    if not claude_bin:
        raise HTTPException(500, "claude 바이너리를 찾을 수 없음 (PATH 확인)")

    orig = image.filename or "chart.png"
    ext = Path(orig).suffix.lower() or ".png"
    if ext not in _ALLOWED_IMG_EXT:
        raise HTTPException(400, f"이미지 파일만 가능 ({', '.join(sorted(_ALLOWED_IMG_EXT))})")
    safe_stem = _SAFE_NAME_RE.sub("_", Path(orig).stem).strip("_") or "chart"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    img_path = INBOX_DIR / f"{ts}_{safe_stem}{ext}"

    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    INTAKE_LOG_DIR.mkdir(parents=True, exist_ok=True)
    img_path.write_bytes(image.file.read())

    job_id = uuid.uuid4().hex[:12]
    log_path = INTAKE_LOG_DIR / f"intake_{job_id}.log"
    prompt = (
        f"chart-reproduce 스킬을 auto 모드로 실행: 이미지 {img_path} 를 판독해 "
        "chartbook에 드래프트 등록해줘. 서버는 이미 떠있으니 새로 띄우지 말고 "
        "registry 직접 사용."
    )
    # 서버가 Claude Code 세션 안에서 기동된 경우 CLAUDE_*/ANTHROPIC_* 환경변수가
    # 중첩 claude 인증을 깨뜨림(401) → 스크럽한 깨끗한 env로 실행.
    clean_env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("CLAUDE", "ANTHROPIC")) and k != "BAGGAGE"
    }
    log_f = open(log_path, "w", encoding="utf-8")  # noqa: SIM115 (Popen이 소유)
    try:
        proc = subprocess.Popen(
            [claude_bin, "-p", prompt, "--permission-mode", "acceptEdits"],
            cwd=str(WORKSPACE_DIR),
            stdout=log_f,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=clean_env,
        )
    except Exception as e:  # noqa: BLE001
        log_f.close()
        raise HTTPException(500, f"claude 실행 실패: {e}") from e

    _jobs[job_id] = {
        "id": job_id,
        "image": str(img_path),
        "log": str(log_path),
        "status": "processing",
        "created": time.time(),
        "exit_code": None,
        "charts_before": sorted(_chart_ids()),
    }
    _procs[job_id] = proc
    _jobs_save()
    logger.info("intake 잡 생성: %s (pid=%s, image=%s)", job_id, proc.pid, img_path.name)
    return {"job_id": job_id, "status": "processing", "image": str(img_path)}


@app.get("/api/intake/{job_id}")
def api_intake_status(job_id: str) -> dict[str, Any]:
    """잡 상태: processing / done(새 차트 감지) / error(로그 tail 포함) / stale."""
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, f"잡 없음: {job_id}")

    proc = _procs.get(job_id)
    if job["status"] == "processing" and proc is not None:
        rc = proc.poll()
        if rc is not None:
            job["exit_code"] = rc
            new_charts = sorted(_chart_ids() - set(job.get("charts_before", [])))
            job["new_charts"] = new_charts
            if rc == 0:
                job["status"] = "done"
                if not new_charts:
                    job["detail"] = "완료(exit 0)했으나 index.json에 새 차트 없음 — 로그 확인"
            else:
                job["status"] = "error"
                job["detail"] = f"claude 종료 코드 {rc}"
            _procs.pop(job_id, None)
            _jobs_save()

    out = {k: v for k, v in job.items() if k != "charts_before"}
    if job["status"] in ("error", "stale"):
        out["log_tail"] = _log_tail(job["log"])
    return out


# ─── admin 정적 서빙 ────────────────────────────────────────────
@app.get("/")
def root() -> JSONResponse:
    return JSONResponse({"ok": True, "admin": "/admin", "api": "/api/sources"})


@app.get("/admin")
def admin_index() -> FileResponse:
    return FileResponse(ADMIN_DIR / "index.html")


# /admin/app.js 등 정적 파일
app.mount("/admin", StaticFiles(directory=str(ADMIN_DIR), html=True), name="admin")

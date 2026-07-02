'use strict';
// 차트 관리 툴 admin — 결정적 검색 → 미리보기 → 추가/삭제/갱신

const API = ''; // 같은 오리진(/api)
let selected = null;       // 선택된 검색 결과 {source,id,label,meta}
let previewChart = null;

function $(id) { return document.getElementById(id); }

function toast(msg) {
  const t = $('toast');
  t.textContent = msg; t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2200);
}

async function jget(url) {
  const r = await fetch(API + url);
  if (!r.ok) throw new Error((await r.text()) || r.status);
  return r.json();
}
async function jpost(url, body) {
  const r = await fetch(API + url, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.status);
  return data;
}
async function jdel(url) {
  const r = await fetch(API + url, { method: 'DELETE' });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.status);
  return data;
}

// ── 소스 상태 칩 ──────────────────────────────────────────────
async function loadSources() {
  try {
    const { sources } = await jget('/api/sources');
    const el = $('sources');
    el.innerHTML = '';
    sources.forEach(s => {
      const chip = document.createElement('span');
      const ok = s.available;
      chip.className = 'src-chip ' + (ok ? 'on' : 'off');
      chip.textContent = s.source + (s.needs_key ? (ok ? ' 🔑✓' : ' 🔑 키필요') : '');
      el.appendChild(chip);
    });
    // 키 없는 FRED/ECOS 옵션 비활성 표시
    sources.forEach(s => {
      if (s.needs_key && !s.available) {
        const opt = [...$('source').options].find(o => o.value === s.source);
        if (opt) { opt.disabled = true; opt.text += ' (키없음)'; }
      }
    });
  } catch (e) { toast('소스 로드 실패: ' + e.message); }
}

// ── 검색 ──────────────────────────────────────────────────────
async function doSearch() {
  const q = $('q').value.trim();
  if (!q) return;
  const source = $('source').value;
  const box = $('results');
  box.innerHTML = '<div class="muted" style="padding:10px;">검색 중…</div>';
  try {
    const { results } = await jget(`/api/search?q=${encodeURIComponent(q)}&source=${source}`);
    if (!results.length) { box.innerHTML = '<div class="muted" style="padding:10px;">결과 없음</div>'; return; }
    box.innerHTML = '';
    results.forEach(r => {
      const d = document.createElement('div');
      d.className = 'result';
      d.innerHTML = `<div class="lbl"><span class="badge src">${r.source}</span>${escapeHtml(r.label)}</div>
        <div class="meta">${escapeHtml(r.id)}</div>`;
      d.onclick = () => selectResult(r, d);
      box.appendChild(d);
    });
  } catch (e) { box.innerHTML = `<div class="muted" style="padding:10px;">검색 오류: ${e.message}</div>`; }
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"]/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;' }[c]));
}

// ── 선택 + 미리보기 ───────────────────────────────────────────
async function selectResult(r, el) {
  selected = r;
  document.querySelectorAll('.result.sel').forEach(x => x.classList.remove('sel'));
  el.classList.add('sel');
  $('selInfo').value = `${r.source} : ${r.id}`;
  $('title').value = r.meta?.name || r.meta?.title || r.label.split(' — ')[1] || r.id;
  $('sourceNote').value = sourceLabel(r.source);
  $('addBtn').disabled = false;
  await loadPreview();
}

function sourceLabel(s) {
  return ({ yfinance:'Yahoo Finance', dbnomics:'DBnomics', krx:'KRX', fred:'FRED', ecos:'한국은행 ECOS' })[s] || s;
}

async function loadPreview() {
  if (!selected) return;
  const tf = $('transform').value;
  $('previewMeta').textContent = '불러오는 중… (yfinance는 몇 초 걸릴 수 있음)';
  try {
    const d = await jget(`/api/preview?source=${selected.source}&id=${encodeURIComponent(selected.id)}&transform=${tf}`);
    if (d.error) { $('previewMeta').textContent = '오류: ' + d.error; drawPreview([], []); return; }
    if (!d.values.length) { $('previewMeta').textContent = '데이터 없음'; drawPreview([], []); return; }
    $('previewMeta').textContent = `${d.count}개 포인트 · ${d.dates[0]} ~ ${d.dates[d.dates.length-1]} · 최신 ${d.values[d.values.length-1]}`;
    drawPreview(d.dates, d.values);
  } catch (e) { $('previewMeta').textContent = '미리보기 오류: ' + e.message; }
}

function drawPreview(dates, values) {
  const ctx = $('previewChart');
  if (previewChart) previewChart.destroy();
  previewChart = new Chart(ctx, {
    type: $('type').value === 'bar' ? 'bar' : 'line',
    data: { labels: dates, datasets: [{ data: values, borderColor:'#1d4ed8', backgroundColor:'rgba(29,78,216,.15)', borderWidth:1.5, pointRadius:0, tension:.1 }] },
    options: { responsive:true, plugins:{ legend:{ display:false } }, scales:{ x:{ ticks:{ maxTicksLimit:6, font:{size:10} } }, y:{ ticks:{ font:{size:10} } } } },
  });
}

// ── 주제 목록 ─────────────────────────────────────────────────
async function loadTopics() {
  try {
    const { sections } = await jget('/api/topics');
    const sel = $('topicSel');
    sel.innerHTML = '';
    if (!sections.length) { sel.innerHTML = '<option value="">(주제 없음 — 신규 입력)</option>'; return; }
    sections.forEach(s => { const o = document.createElement('option'); o.value = s; o.text = s; sel.appendChild(o); });
  } catch (e) { /* ignore */ }
}

// ── 차트 추가 ─────────────────────────────────────────────────
async function addChart() {
  if (!selected) return;
  const section = $('topicNew').value.trim() || $('topicSel').value || '기타';
  const body = {
    section,
    title: $('title').value.trim() || selected.id,
    summary: $('summary').value.trim(),
    type: $('type').value,
    unit: $('unit').value.trim(),
    source: selected.source,
    sourceNote: $('sourceNote').value.trim(),
    series: [{ sourceId: selected.id, label: $('title').value.trim() || selected.id, transform: $('transform').value }],
  };
  $('addBtn').disabled = true;
  try {
    const res = await jpost('/api/charts', body);
    toast(`추가됨: ${res.id} (${res.ready === false ? 'placeholder' : 'ready'})`);
    $('topicNew').value = '';
    await loadTopics(); await loadChartList();
  } catch (e) { toast('추가 실패: ' + e.message); }
  finally { $('addBtn').disabled = false; }
}

// ── 레지스트리 목록 ──────────────────────────────────────────
async function loadChartList() {
  try {
    const { topics } = await jget('/api/topics');
    const el = $('chartList');
    el.innerHTML = '';
    if (!topics.length) { el.innerHTML = '<div class="muted">등록된 차트 없음</div>'; return; }
    topics.forEach(t => {
      const h = document.createElement('div'); h.className = 'topic'; h.textContent = t.section;
      el.appendChild(h);
      t.charts.forEach(c => {
        const row = document.createElement('div'); row.className = 'chart-item';
        row.innerHTML = `<div class="info"><div>${escapeHtml(c.id)} <span class="badge">${c.type}</span>${c.ready ? '' : '<span class="badge" style="background:#fef3c7;color:#92400e;">placeholder</span>'}</div></div>`;
        const btns = document.createElement('div');
        const del = document.createElement('button'); del.className = 'danger'; del.textContent = '삭제';
        del.onclick = () => deleteChart(t.section, c.id);
        btns.appendChild(del);
        row.appendChild(btns);
        el.appendChild(row);
      });
    });
  } catch (e) { $('chartList').innerHTML = '오류: ' + e.message; }
}

async function deleteChart(section, id) {
  if (!confirm(`차트 삭제: ${id} ?`)) return;
  try { await jdel(`/api/charts/${encodeURIComponent(section)}/${encodeURIComponent(id)}`); toast('삭제됨: ' + id); await loadChartList(); }
  catch (e) { toast('삭제 실패: ' + e.message); }
}

async function refreshAll() {
  toast('갱신 중…');
  try { const r = await jpost('/api/refresh'); toast(`갱신 완료: ${r.count}개`); await loadChartList(); }
  catch (e) { toast('갱신 실패: ' + e.message); }
}

// ── 이벤트 바인딩 ─────────────────────────────────────────────
$('searchBtn').onclick = doSearch;
$('q').addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });
$('transform').onchange = loadPreview;
$('type').onchange = loadPreview;
$('addBtn').onclick = addChart;
$('refreshAllBtn').onclick = refreshAll;
$('reloadBtn').onclick = loadChartList;

loadSources(); loadTopics(); loadChartList();

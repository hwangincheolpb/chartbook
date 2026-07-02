/* =========================================================
   Market Chart Book — charts.js
   Fetches ../data/index.json, renders all charts in order
   ========================================================= */

'use strict';

/* ---- Theme management ---- */
const THEME_KEY = 'chartbook_theme';

function getTheme() {
  return localStorage.getItem(THEME_KEY) || 'light';
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem(THEME_KEY, theme);
  const btn = document.getElementById('theme-toggle');
  if (btn) {
    btn.innerHTML = theme === 'dark'
      ? '<span>☀</span> Light'
      : '<span>☾</span> Dark';
  }
}

function toggleTheme() {
  const current = getTheme();
  const next = current === 'dark' ? 'light' : 'dark';
  applyTheme(next);
  // Re-render all ECharts instances with new theme colours
  refreshAllCharts();
}

/* ---- Colour palette per theme ----
   단일 소스: CSS 변수(--c0..--c6, --chart-*)를 읽는다.
   라이트/다크 팔레트는 style.css에서만 관리. */
const PALETTE_SIZE = 7;

function cssVar(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

function getPalette() {
  const colors = [];
  for (let i = 0; i < PALETTE_SIZE; i++) {
    colors.push(cssVar('--c' + i, '#888888'));
  }
  return {
    bg:          cssVar('--chart-bg', '#ffffff'),
    grid:        cssVar('--chart-grid', '#e8e7e5'),
    axis:        cssVar('--chart-axis', '#a8a29e'),
    axisLabel:   cssVar('--chart-text', '#57534e'),
    tooltip:     cssVar('--chart-tooltip', '#ffffff'),
    tooltipBdr:  cssVar('--chart-tooltip-border', '#d6d3d1'),
    tooltipText: cssVar('--chart-tooltip-text', '#1c1917'),
    colors,
  };
}

/* ---- 추정/계획 시리즈 자동 스타일 규칙 ----
   시리즈 이름에 '계획'/'추정'/'가이던스'/'전망'/'예상'/'(E)' 포함 시
   점선 + 낮은 불투명도로 자동 렌더 (데이터 파일 수정 불필요). */
const ESTIMATE_RE = /계획|추정|가이던스|전망|예상|\(E\)/;

function isEstimateSeries(name) {
  return ESTIMATE_RE.test(name || '');
}

/* ---- Registry of ECharts instances ---- */
const chartInstances = new Map();  // id → echarts instance
const chartDataCache = new Map();  // id → parsed chart data

/* ---- rAF + setTimeout 레이스 — 숨겨진 탭에서는 rAF가 영원히 안 불림
       (백그라운드 탭으로 열어두는 아침 사용 패턴 대응). 둘 중 먼저 온 쪽 1회 실행 ---- */
function nextFrame(fn) {
  let done = false;
  const runOnce = () => { if (!done) { done = true; fn(); } };
  requestAnimationFrame(runOnce);
  setTimeout(runOnce, 60);
}

/* ---- Utility: format date ---- */
function fmtDate(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    return d.toLocaleDateString('ko-KR', { year: 'numeric', month: 'short', day: 'numeric' });
  } catch { return iso; }
}

/* ---- Utility: escape HTML (data 문자열에 <, > 포함 가능) ---- */
function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

/* ---- Utility: note 분해 — 논지(캡션) vs 각주([출처]/[한계]/[주의] 등) ----
   note 형식: "논지: ... [논리 교정] ... [한계] ... [출처] ..."
   - 대괄호 마커 앞의 리드 텍스트 = 논지 캡션 (차트 아래 콜아웃)
   - [라벨] 이후 각 구간 = 각주 라인 (작게, footnote)
   - 마커가 없으면 note 전체를 논지 캡션으로 취급 */
function splitNote(note) {
  if (!note) return { thesis: '', footnotes: [] };
  const stripThesisLabel = (s) => {
    const m = s.match(/^\s*논지\s*[::]\s*([\s\S]*)$/);
    return m ? m[1].trim() : s.trim();
  };
  const markerRe = /\[([^\]\n]{1,20})\]\s*/g;
  const markers = [...note.matchAll(markerRe)];
  if (!markers.length) {
    return { thesis: stripThesisLabel(note), footnotes: [] };
  }
  const thesis = stripThesisLabel(note.slice(0, markers[0].index));
  const footnotes = markers.map((m, i) => {
    const start = m.index + m[0].length;
    const end = i + 1 < markers.length ? markers[i + 1].index : note.length;
    return { label: m[1], text: note.slice(start, end).trim() };
  });
  return { thesis, footnotes };
}

/* ---- Utility: format number for tooltip ---- */
function fmtNum(v, unit) {
  if (v === null || v === undefined) return '—';
  if (unit === '%') return v.toFixed(2) + '%';
  if (unit === 'x')  return v.toFixed(1) + 'x';
  return v.toLocaleString('en-US', { maximumFractionDigits: 2 });
}

/* ---- Detect a "spread" timeseries that benefits from a zero reference line ---- */
function isSpreadChart(chartData) {
  if (!chartData || chartData.unit !== '%') return false;
  if (chartData.id === 'yield_spread') return true;
  // single series whose name looks like a spread (e.g. "10Y-3M", "스프레드")
  if (chartData.series && chartData.series.length === 1) {
    const n = (chartData.series[0].name || '');
    if (/-|spread|스프레드/i.test(n)) return true;
  }
  return false;
}

/* ---- Build ECharts option for a timeseries chart ---- */
function buildTimeseriesOption(chartData) {
  const p = getPalette();
  const { series, unit } = chartData;
  const showZeroLine = isSpreadChart(chartData);
  // 숫자 x축 지원: 최상위 "xAxisType": "value" 이면 time 대신 value 축
  // (예: megaprojects — x = 시작 후 경과 연차). 필드 없으면 기존 time 축.
  const isValueX = chartData.xAxisType === 'value';
  const xAxisName = chartData.xAxisName || '';

  // 이중축 지원: 시리즈별 yAxis(0|1) + 최상위 unit2(우측 보조축 라벨). CONTRACT 참조.
  const hasDualAxis = (series || []).some((s) => s.yAxis === 1);
  // 커스텀 기준선: 최상위 markLines [{value, label, axis}] (예: ls_rate_peak 4.85 CTA선)
  const customMarks = (chartData.markLines || []).filter((m) => typeof m.value === 'number');

  const echartsSeries = (series || []).map((s, i) => {
    const est = isEstimateSeries(s.name);
    const color = p.colors[i % p.colors.length];
    return {
    name: s.name,
    type: 'line',
    yAxisIndex: hasDualAxis && s.yAxis === 1 ? 1 : 0,
    data: (s.data || []).map(([x, val]) => [x, val]),
    smooth: false,
    symbol: 'none',
    lineStyle: {
      width: 1.5,
      color,
      type: est ? 'dashed' : 'solid',
      opacity: est ? 0.65 : 1,
    },
    itemStyle: {
      color,
      opacity: est ? 0.65 : 1,
    },
    emphasis: { disabled: false },
    // Horizontal reference lines: spread zero-line + CONTRACT markLines(값 기준선).
    // 각 기준선은 자기 axis(0|1)와 같은 축의 첫 시리즈에 붙인다.
    ...(() => {
      const myAxis = hasDualAxis && s.yAxis === 1 ? 1 : 0;
      const firstOfAxis = (series || []).findIndex(
        (x) => (hasDualAxis && x.yAxis === 1 ? 1 : 0) === myAxis
      ) === i;
      const marks = [];
      if (showZeroLine && i === 0) {
        marks.push({ yAxis: 0, label: { formatter: '0% (역전선)' } });
      }
      if (firstOfAxis) {
        customMarks
          .filter((m) => (m.axis || 0) === myAxis)
          .forEach((m) => marks.push({
            yAxis: m.value,
            label: { formatter: m.label ? `${m.label} ${m.value}` : String(m.value) },
            lineStyle: { color: p.colors[6] || '#b91c1c', type: 'dashed', width: 1.2 },
          }));
      }
      if (!marks.length) return {};
      return {
        markLine: {
          silent: true,
          symbol: 'none',
          lineStyle: { color: p.axis, type: 'dashed', width: 1 },
          label: {
            show: true,
            position: 'insideEndTop',
            color: p.axisLabel,
            fontSize: 9,
          },
          data: marks,
        },
      };
    })(),
    };
  });

  return {
    backgroundColor: p.bg,
    animation: true,
    animationDuration: 400,
    color: p.colors,
    grid: {
      top: 16,
      right: 20,
      bottom: isValueX && xAxisName ? 44 : 28,   // extra room for x-axis name
      left: 62,
      containLabel: false,
    },
    xAxis: {
      type: isValueX ? 'value' : 'time',
      ...(isValueX && xAxisName ? {
        name: xAxisName,
        nameLocation: 'middle',
        nameGap: 26,
        nameTextStyle: { color: p.axisLabel, fontSize: 10 },
      } : {}),
      axisLine: { lineStyle: { color: p.grid } },
      axisTick: { lineStyle: { color: p.grid } },
      axisLabel: {
        color: p.axisLabel,
        fontSize: 10,
        formatter: isValueX
          ? (val) => String(val)
          : (val) => {
              const d = new Date(val);
              return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`;
            },
      },
      splitLine: { show: false },
    },
    yAxis: (() => {
      const axisBase = (name) => ({
        type: 'value',
        name: name || '',
        scale: true,   // 데이터 범위에 맞게 자동 스케일 (0 강제 시작 X)
        nameTextStyle: {
          color: p.axisLabel,
          fontSize: 10,
          padding: [0, 0, 0, 0],
        },
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: {
          color: p.axisLabel,
          fontSize: 10,
          formatter: (val) => {
            if (Math.abs(val) >= 1000) return (val/1000).toFixed(1) + 'k';
            return val;
          },
        },
        splitLine: { lineStyle: { color: p.grid, type: 'solid', width: 1 } },
      });
      if (!hasDualAxis) return axisBase(unit);
      const right = axisBase(chartData.unit2);
      right.splitLine = { show: false };  // 보조축 격자 생략(겹침 방지)
      return [axisBase(unit), right];
    })(),
    legend: (series || []).length > 1 ? {
      top: 0,
      right: 0,
      textStyle: { color: p.axisLabel, fontSize: 10 },
      itemWidth: 16,
      itemHeight: 2,
      icon: 'rect',
    } : { show: false },
    tooltip: {
      trigger: 'axis',
      axisPointer: {
        type: 'cross',
        crossStyle: { color: p.axis, width: 1 },
        lineStyle: { color: p.axis, width: 1, type: 'dashed' },
      },
      backgroundColor: p.tooltip,
      borderColor: p.tooltipBdr,
      borderWidth: 1,
      textStyle: { color: p.tooltipText, fontSize: 11 },
      padding: [8, 12],
      formatter(params) {
        if (!params || !params.length) return '';
        let head;
        if (isValueX) {
          head = xAxisName ? `${xAxisName} ${params[0].axisValue}` : String(params[0].axisValue);
        } else {
          const date = new Date(params[0].axisValue);
          head = date.toLocaleDateString('ko-KR', { year: 'numeric', month: 'short', day: 'numeric' });
        }
        let html = `<div style="margin-bottom:4px;font-size:10px;opacity:.7">${head}</div>`;
        params.forEach(p2 => {
          const val = p2.value[1];
          const dot = `<span style="display:inline-block;width:8px;height:2px;background:${p2.color};margin-right:5px;vertical-align:middle;border-radius:1px"></span>`;
          html += `<div style="display:flex;justify-content:space-between;gap:16px">
            <span>${dot}${p2.seriesName}</span>
            <span style="font-weight:600">${fmtNum(val, unit)}</span>
          </div>`;
        });
        return html;
      },
    },
    // 슬라이더 줌 바 제거 — inside 줌만 유지 (Ctrl/Cmd+휠 줌, 드래그 팬.
    // 일반 휠은 페이지 스크롤에 양보)
    dataZoom: [
      {
        type: 'inside',
        zoomOnMouseWheel: 'ctrl',
        moveOnMouseWheel: false,
        moveOnMouseMove: true,
      },
    ],
    series: echartsSeries,
  };
}

/* ---- Render a timeseries chart card ---- */
function renderTimeseries(containerId, chartData) {
  const container = document.getElementById(containerId);
  if (!container) return;

  // Destroy old instance if re-rendering
  if (chartInstances.has(containerId)) {
    chartInstances.get(containerId).dispose();
  }

  const chart = echarts.init(container, null, { renderer: 'canvas' });
  chart.setOption(buildTimeseriesOption(chartData));
  chartInstances.set(containerId, chart);
}

/* ---- Build ECharts option for a curve_snapshot (yield curve) ---- */
function buildCurveSnapshotOption(chartData) {
  const p = getPalette();
  const { maturities, snapshots, unit } = chartData;

  // Map each snapshot's data onto the category axis order
  const echartsSeries = snapshots.map((snap, i) => {
    const byMat = {};
    (snap.data || []).forEach(([mat, val]) => { byMat[mat] = val; });
    const data = maturities.map(mat => (mat in byMat ? byMat[mat] : null));
    const est = isEstimateSeries(snap.label);
    const color = p.colors[i % p.colors.length];
    return {
      name: snap.label,
      type: 'line',
      data,
      smooth: 0.3,
      symbol: 'circle',
      symbolSize: 6,
      connectNulls: true,
      lineStyle: { width: 2, color, type: est ? 'dashed' : 'solid', opacity: est ? 0.65 : 1 },
      itemStyle: { color, opacity: est ? 0.65 : 1 },
      emphasis: { focus: 'series' },
    };
  });

  return {
    backgroundColor: p.bg,
    animation: true,
    animationDuration: 400,
    color: p.colors,
    grid: { top: 20, right: 24, bottom: 36, left: 56, containLabel: false },
    xAxis: {
      type: 'category',
      data: maturities,
      boundaryGap: false,
      axisLine: { lineStyle: { color: p.grid } },
      axisTick: { alignWithLabel: true, lineStyle: { color: p.grid } },
      axisLabel: { color: p.axisLabel, fontSize: 11 },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      name: unit || '',
      scale: true,
      nameTextStyle: { color: p.axisLabel, fontSize: 10 },
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        color: p.axisLabel,
        fontSize: 10,
        formatter: (val) => val.toFixed(1),
      },
      splitLine: { lineStyle: { color: p.grid, type: 'solid', width: 1 } },
    },
    legend: {
      top: 0,
      right: 0,
      textStyle: { color: p.axisLabel, fontSize: 10 },
      itemWidth: 16,
      itemHeight: 2,
      icon: 'rect',
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: p.axis, width: 1, type: 'dashed' } },
      backgroundColor: p.tooltip,
      borderColor: p.tooltipBdr,
      borderWidth: 1,
      textStyle: { color: p.tooltipText, fontSize: 11 },
      padding: [8, 12],
      formatter(params) {
        if (!params || !params.length) return '';
        const mat = params[0].axisValue;
        let html = `<div style="margin-bottom:4px;font-size:10px;opacity:.7">만기 ${mat}</div>`;
        params.forEach(p2 => {
          if (p2.value === null || p2.value === undefined) return;
          const dot = `<span style="display:inline-block;width:8px;height:2px;background:${p2.color};margin-right:5px;vertical-align:middle;border-radius:1px"></span>`;
          html += `<div style="display:flex;justify-content:space-between;gap:16px">
            <span>${dot}${p2.seriesName}</span>
            <span style="font-weight:600">${fmtNum(p2.value, unit)}</span>
          </div>`;
        });
        return html;
      },
    },
    series: echartsSeries,
  };
}

/* ---- Render a curve_snapshot chart card ---- */
function renderCurveSnapshot(containerId, chartData) {
  const container = document.getElementById(containerId);
  if (!container) return;

  if (chartInstances.has(containerId)) {
    chartInstances.get(containerId).dispose();
  }

  const chart = echarts.init(container, null, { renderer: 'canvas' });
  chart.setOption(buildCurveSnapshotOption(chartData));
  chartInstances.set(containerId, chart);
}

/* ---- Build heatmap cell background colour ---- */
function heatColor(val) {
  const abs = Math.abs(val);
  // clamp intensity: 0–1 scaled to ±5%
  const intensity = Math.min(abs / 5.0, 1.0);
  const dark = getTheme() === 'dark';

  if (val === 0) {
    return {
      bg: dark ? '#292524' : '#f5f5f5',
      text: dark ? '#a8a29e' : '#44403c',
    };
  }

  if (val > 0) {
    // green spectrum
    if (dark) {
      // dark: muted greens
      const r = Math.round(20 - intensity * 5);
      const g = Math.round(80 + intensity * 83);
      const b = Math.round(44);
      return {
        bg: `rgba(${r}, ${g}, ${b}, ${0.25 + intensity * 0.55})`,
        text: intensity > 0.4 ? '#86efac' : '#4ade80',
      };
    } else {
      const r = Math.round(187 - intensity * 170);
      const g = Math.round(247 - intensity * 80);
      const b = Math.round(208 - intensity * 180);
      return {
        bg: `rgb(${r}, ${g}, ${b})`,
        text: intensity > 0.5 ? '#14532d' : '#166534',
      };
    }
  } else {
    // red spectrum
    if (dark) {
      const r = Math.round(150 + intensity * 100);
      const g = Math.round(30);
      const b = Math.round(30);
      return {
        bg: `rgba(${r}, ${g}, ${b}, ${0.25 + intensity * 0.55})`,
        text: intensity > 0.4 ? '#fca5a5' : '#f87171',
      };
    } else {
      const r = Math.round(254 - intensity * 8);
      const g = Math.round(202 - intensity * 170);
      const b = Math.round(202 - intensity * 170);
      return {
        bg: `rgb(${r}, ${g}, ${b})`,
        text: intensity > 0.5 ? '#7f1d1d' : '#991b1b',
      };
    }
  }
}

/* ---- Render the sector performance table ---- */
function renderHeatmapPerf(containerId, chartData) {
  const container = document.getElementById(containerId);
  if (!container) return;

  const { periods, items } = chartData;

  let html = `<div class="sector-table-wrapper">
    <table class="sector-table">
      <thead>
        <tr>
          <th>섹터</th>
          <th>티커</th>
          ${periods.map(p => `<th>${p}</th>`).join('')}
        </tr>
      </thead>
      <tbody>`;

  items.forEach(item => {
    html += `<tr>
      <td>${item.name}</td>
      <td style="color:var(--text-muted)">${item.ticker}</td>`;

    periods.forEach(period => {
      const val = item.perf[period];
      if (val === undefined || val === null) {
        html += `<td><span class="heat-cell" style="background:var(--ph-bg);color:var(--text-muted)">—</span></td>`;
      } else {
        const { bg, text } = heatColor(val);
        const sign = val > 0 ? '+' : '';
        html += `<td><span class="heat-cell" style="background:${bg};color:${text}">${sign}${val.toFixed(1)}%</span></td>`;
      }
    });

    html += '</tr>';
  });

  html += `</tbody></table></div>`;
  container.innerHTML = html;
}

/* ---- Refresh all ECharts (theme toggle) ---- */
function refreshAllCharts() {
  // Re-render ECharts + tables with the new palette.
  // chartDataCache is keyed by chart id; ECharts instances are keyed by
  // container id ("<id>-chart"), tables live under "<id>-body".
  chartDataCache.forEach((data, id) => {
    if (data.type === 'timeseries') {
      const inst = chartInstances.get(id + '-chart');
      if (inst) inst.setOption(buildTimeseriesOption(data), true);
    } else if (data.type === 'curve_snapshot') {
      const inst = chartInstances.get(id + '-chart');
      if (inst) inst.setOption(buildCurveSnapshotOption(data), true);
    } else if (data.type === 'heatmap_perf') {
      renderHeatmapPerf(id + '-body', data);
    }
  });
}

/* ---- Section content containers (so cards group under their section
       regardless of their position in index.charts) ---- */
const sectionBodies = new Map();   // sectionName → content container element
const sectionHeaders = new Map();  // sectionName → header element

/* ---- Collapsible sections — 접힘 상태 (localStorage 기억) ----
   기본값: "이선엽 체인"만 펼침, 나머지 접힘 ("아침 10초 확인" 구조).
   ECharts는 display:none에서 init하면 width=0 → 접힌 섹션의 차트는
   pendingRenders에 쌓아 두고 펼칠 때 lazy-init한다. */
const SECTIONS_KEY = 'chartbook_sections_v1';
const DEFAULT_EXPANDED = new Set(['이선엽 체인']);
const pendingRenders = new Map();  // sectionName → [renderFn, ...]

let sectionState = (() => {
  try { return JSON.parse(localStorage.getItem(SECTIONS_KEY)) || {}; }
  catch { return {}; }
})();

function saveSectionState() {
  try { localStorage.setItem(SECTIONS_KEY, JSON.stringify(sectionState)); }
  catch { /* private mode 등 — 무시 */ }
}

function isSectionExpanded(name) {
  return name in sectionState ? !!sectionState[name] : DEFAULT_EXPANDED.has(name);
}

function queuePendingRender(sectionName, fn) {
  if (!pendingRenders.has(sectionName)) pendingRenders.set(sectionName, []);
  pendingRenders.get(sectionName).push(fn);
}

function flushPendingRenders(sectionName) {
  const fns = pendingRenders.get(sectionName);
  if (!fns || !fns.length) return;
  pendingRenders.set(sectionName, []);
  fns.forEach(fn => nextFrame(fn));
}

function expandSection(name) {
  const body = sectionBodies.get(name);
  const header = sectionHeaders.get(name);
  if (!body) return;
  body.classList.remove('collapsed');
  if (header) header.classList.remove('collapsed');
  sectionState[name] = 1;
  saveSectionState();
  // 접힌 채로 대기하던 차트 lazy-init + 이미 그려진 차트 폭 보정
  flushPendingRenders(name);
  nextFrame(() => {
    body.querySelectorAll('.chart-body').forEach(el => {
      const inst = chartInstances.get(el.id);
      if (inst) inst.resize();
    });
  });
}

function collapseSection(name) {
  const body = sectionBodies.get(name);
  const header = sectionHeaders.get(name);
  if (!body) return;
  body.classList.add('collapsed');
  if (header) header.classList.add('collapsed');
  sectionState[name] = 0;
  saveSectionState();
}

function toggleSection(name) {
  const body = sectionBodies.get(name);
  if (!body) return;
  if (body.classList.contains('collapsed')) expandSection(name);
  else collapseSection(name);
}

/* ---- Create section header + content container, return the container ---- */
function ensureSection(sectionName, container) {
  if (sectionBodies.has(sectionName)) return sectionBodies.get(sectionName);
  const sectionId = 'section-' + sectionName.replace(/\s+/g, '-');
  const num = String(sectionBodies.size + 1).padStart(2, '0');
  const header = document.createElement('div');
  header.className = 'section-header collapsible';
  header.id = sectionId;
  header.innerHTML = `<span class="section-num">${num}</span><span class="section-label">${escapeHtml(sectionName)}</span><div class="section-line"></div><span class="section-chevron" aria-hidden="true">▾</span>`;
  header.setAttribute('role', 'button');
  header.setAttribute('tabindex', '0');
  header.setAttribute('aria-label', `${sectionName} 섹션 접기/펼치기`);
  header.addEventListener('click', () => toggleSection(sectionName));
  header.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleSection(sectionName); }
  });
  container.appendChild(header);
  const body = document.createElement('div');
  body.className = 'section-body';
  container.appendChild(body);
  if (!isSectionExpanded(sectionName)) {
    body.classList.add('collapsed');
    header.classList.add('collapsed');
  }
  sectionBodies.set(sectionName, body);
  sectionHeaders.set(sectionName, header);
  return body;
}

/* ---- Snapshot board — "아침 10초 확인" 카드 (data/snapshot.json) ---- */
const SNAP_STATE_LABEL = { good: '양호', warn: '주의', alert: '경보', neutral: '' };

function fmtSnapValue(v) {
  if (v === null || v === undefined) return '—';
  if (Math.abs(v) >= 1000) return v.toLocaleString('en-US', { maximumFractionDigits: 1 });
  if (Math.abs(v) >= 100) return v.toFixed(1);
  return v.toFixed(2);
}

function snapCardHtml(card) {
  const state = ['good', 'warn', 'alert', 'neutral'].includes(card.state) ? card.state : 'neutral';
  const badgeText = card.badge || SNAP_STATE_LABEL[state];
  const badge = badgeText
    ? `<span class="snap-badge state-${state}">${escapeHtml(badgeText)}</span>`
    : '';
  let d1Html = '';
  if (typeof card.d1 === 'number') {
    const dir = card.d1 > 0 ? 'up' : (card.d1 < 0 ? 'down' : 'flat');
    const arrow = card.d1 > 0 ? '▲' : (card.d1 < 0 ? '▼' : '＝');
    d1Html = `<span class="snap-d1 ${dir}">${arrow} ${Math.abs(card.d1).toFixed(2)}%</span>`;
  }
  return `
    <div class="snap-card state-${state}" data-link="${escapeHtml(card.link || '')}" role="button" tabindex="0"
         aria-label="${escapeHtml(card.label)} — 해당 차트로 이동">
      <div class="snap-top">
        <span class="snap-label">${escapeHtml(card.label)}</span>
        ${badge}
      </div>
      <div class="snap-value-row">
        <span class="snap-value">${fmtSnapValue(card.value)}${card.unit ? `<span class="snap-unit">${escapeHtml(card.unit)}</span>` : ''}</span>
        ${d1Html}
      </div>
      ${card.caption ? `<div class="snap-caption">${escapeHtml(card.caption)}</div>` : ''}
    </div>`;
}

/* 스냅샷 카드 클릭 → (접힌 섹션이면 펼치고) 해당 차트로 스크롤 + 하이라이트 */
function gotoChartAnchor(link) {
  if (!link) return;
  const target = document.querySelector(link);
  if (!target) return;
  // 카드가 속한 섹션 찾기 → 접혀 있으면 펼침
  for (const [name, body] of sectionBodies) {
    if (body.contains(target)) {
      if (body.classList.contains('collapsed')) expandSection(name);
      break;
    }
  }
  nextFrame(() => {
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    target.classList.add('anchor-highlight');
    setTimeout(() => target.classList.remove('anchor-highlight'), 2000);
  });
}

async function renderSnapshotBoard() {
  const board = document.getElementById('snapshot-board');
  if (!board) return;
  let snap;
  try {
    const resp = await fetch('../data/snapshot.json', { cache: 'no-store' });
    if (!resp.ok) return;  // snapshot 없음 → 보드 숨김(빈 컨테이너)
    snap = await resp.json();
  } catch (e) {
    console.warn('snapshot.json 로드 실패 (보드 생략):', e);
    return;
  }
  const cards = (snap && snap.cards) || [];
  if (!cards.length) return;
  board.innerHTML = cards.map(snapCardHtml).join('');
  board.classList.add('has-cards');
  board.querySelectorAll('.snap-card').forEach(el => {
    const link = el.getAttribute('data-link');
    if (!link) return;
    el.addEventListener('click', () => gotoChartAnchor(link));
    el.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); gotoChartAnchor(link); }
    });
  });
}

/* ---- Create chart card DOM ---- */
function createChartCard(meta, chartData) {
  const card = document.createElement('div');
  card.className = 'chart-card';
  card.id = 'card-' + meta.id;   // 스냅샷 보드/앵커 링크 타깃

  const title = chartData?.title || meta.id;
  const subtitle = chartData?.subtitle || '';
  const source = chartData?.source || '';
  const updated = chartData?.updated || '';
  const note = chartData?.note || '';

  let bodyHtml;
  if (meta.type === 'timeseries' || meta.type === 'curve_snapshot') {
    bodyHtml = `<div class="chart-body" id="${meta.id}-chart"></div>`;
  } else if (meta.type === 'heatmap_perf') {
    bodyHtml = `<div id="${meta.id}-body"></div>`;
  } else {
    bodyHtml = '<div style="padding:8px;color:var(--text-muted)">Unknown chart type</div>';
  }

  // note → 논지 캡션(콜아웃) + 각주(footnote) 분리
  const { thesis, footnotes } = splitNote(note);

  const footerParts = [];
  if (source) footerParts.push(`<span class="chart-source">Source: ${escapeHtml(source)}</span>`);
  if (updated) footerParts.push(`<span class="chart-updated">Updated: ${fmtDate(updated)}</span>`);

  const footnoteHtml = footnotes.length
    ? `<div class="chart-footnote">${footnotes.map(f =>
        `<div class="fn-line"><span class="fn-label">${escapeHtml(f.label)}</span>${escapeHtml(f.text)}</div>`
      ).join('')}</div>`
    : '';

  card.innerHTML = `
    <div class="chart-header">
      <div class="chart-title">${escapeHtml(title)}</div>
      ${subtitle ? `<div class="chart-subtitle">${escapeHtml(subtitle)}</div>` : ''}
    </div>
    ${bodyHtml}
    ${thesis ? `<div class="chart-thesis"><span class="thesis-label">논지</span>${escapeHtml(thesis)}</div>` : ''}
    <div class="chart-footer">
      ${footerParts.join('')}
    </div>
    ${footnoteHtml}
  `;

  return card;
}

/* ---- Create external-link card (type: "link") ---- */
function createLinkCard(meta) {
  const card = document.createElement('div');
  card.className = 'link-card';

  const title    = meta.title    || meta.id;
  const subtitle = meta.subtitle || '';
  const source   = meta.source   || '';
  const note     = meta.note     || '';
  const url      = meta.url       || '';
  const isLive   = !!meta.live;
  // 웹 배포(GitHub Pages 등)에서는 localhost 딥링크가 죽은 링크 → 클릭/임베드 비활성
  const pageIsLocal = ['localhost', '127.0.0.1', '::1', ''].includes(location.hostname);
  const urlIsLocal  = /^https?:\/\/(localhost|127\.0\.0\.1)(:|\/|$)/i.test(url);
  const deadOnWeb   = urlIsLocal && !pageIsLocal;
  const clickable = !!url && !deadOnWeb;

  const badge = isLive
    ? `<span class="link-badge live">LIVE ↗</span>`
    : `<span class="link-badge local">로컬</span>`;

  // Optional live embed preview (only when preview:"embed" + url + live).
  // iframe is scaled-down and pointer-events:none so the whole card stays clickable.
  const showEmbed = meta.preview === 'embed' && url && isLive && !deadOnWeb;
  const embedHtml = showEmbed
    ? `<div class="link-embed">
         <iframe class="link-embed-frame" src="${url}" loading="lazy"
                 tabindex="-1" aria-hidden="true" referrerpolicy="no-referrer"
                 title="${title} 미리보기"></iframe>
       </div>`
    : '';

  card.innerHTML = `
    <div class="link-card-top">
      <div class="link-title">${escapeHtml(title)}</div>
      ${badge}
    </div>
    ${subtitle ? `<div class="link-subtitle">${escapeHtml(subtitle)}</div>` : ''}
    ${embedHtml}
    <div class="link-card-footer">
      ${source ? `<span class="chart-source">${escapeHtml(source)}</span>` : ''}
      ${url ? `<span class="link-url">${escapeHtml(url.replace(/^https?:\/\//, ''))}</span>` : ''}
    </div>
    ${note ? `<div class="chart-note">${escapeHtml(note)}</div>` : ''}
  `;

  if (clickable) {
    card.classList.add('clickable');
    card.setAttribute('role', 'link');
    card.setAttribute('tabindex', '0');
    card.setAttribute('aria-label', `${title} (새 탭으로 열기)`);
    const open = () => window.open(url, '_blank', 'noopener');
    card.addEventListener('click', open);
    card.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); }
    });
  } else {
    card.classList.add('disabled');
    if (deadOnWeb) {
      card.setAttribute('title', '로컬 전용 대시보드 — 웹에서는 열 수 없습니다');
      card.style.cursor = 'default';
      card.style.opacity = '0.65';
    }
  }

  return card;
}

/* ---- Create placeholder card ---- */
function createPlaceholderCard(meta) {
  const card = document.createElement('div');
  card.className = 'placeholder-card';
  card.innerHTML = `
    <div class="placeholder-icon">📋</div>
    <div class="placeholder-text">
      <div class="placeholder-title">${meta.id} — 데이터 준비 중</div>
      <div class="placeholder-desc">FRED API 키 필요 · 파이프라인 연결 후 자동 업데이트됩니다</div>
    </div>
  `;
  return card;
}

/* ---- Build section nav links ---- */
function buildNav(sections) {
  const nav = document.getElementById('header-nav');
  if (!nav) return;
  const seen = new Set();
  sections.forEach(s => {
    if (seen.has(s)) return;
    seen.add(s);
    const a = document.createElement('a');
    a.className = 'nav-link';
    a.href = '#section-' + s.replace(/\s+/g, '-');
    a.textContent = s;
    // 접힌 섹션도 미니목차 클릭 시 펼치며 이동 (기본 앵커 스크롤은 그대로 진행)
    a.addEventListener('click', () => expandSection(s));
    nav.appendChild(a);
  });
}

/* ---- Main init ---- */
async function init() {
  // Apply persisted theme immediately
  applyTheme(getTheme());

  // 스냅샷 보드 (병렬 — 차트 로드와 독립, 실패해도 본문 렌더에 영향 없음)
  renderSnapshotBoard();

  const loadingEl = document.getElementById('loading');
  const errorEl   = document.getElementById('error-msg');
  const mainEl    = document.getElementById('main');

  try {
    // 1. Fetch index (no-store: data refreshes daily, always pull current)
    const indexResp = await fetch('../data/index.json', { cache: 'no-store' });
    if (!indexResp.ok) throw new Error(`index.json fetch failed: ${indexResp.status}`);
    const index = await indexResp.json();

    // Update header last-updated
    const updatedEl = document.getElementById('header-updated');
    if (updatedEl && index.updated) {
      updatedEl.textContent = fmtDate(index.updated);
    }

    // Build section nav (first-appearance order)
    const sections = index.charts.map(c => c.section);
    buildNav(sections);

    // Pre-create all sections in first-appearance order so their headers/order
    // are stable even when link cards are appended at the end of the array.
    sections.forEach(s => ensureSection(s, mainEl));

    // Hide loading
    loadingEl.style.display = 'none';

    // 2. Fetch each chart's data in order and render into its section container
    for (const meta of index.charts) {
      const sectionBody = ensureSection(meta.section, mainEl);

      // External-link card — no data file to fetch
      if (meta.type === 'link') {
        sectionBody.appendChild(createLinkCard(meta));
        continue;
      }

      if (!meta.ready) {
        sectionBody.appendChild(createPlaceholderCard(meta));
        continue;
      }

      // Fetch chart data
      let chartData = null;
      try {
        const resp = await fetch(`../data/${meta.file}`, { cache: 'no-store' });
        if (!resp.ok) throw new Error(`${meta.file} fetch failed: ${resp.status}`);
        chartData = await resp.json();
      } catch (fetchErr) {
        console.warn(`Failed to load chart data for ${meta.id}:`, fetchErr);
        sectionBody.appendChild(createPlaceholderCard(meta));
        continue;
      }

      // Cache data
      chartDataCache.set(meta.id, chartData);

      // Build card
      const card = createChartCard(meta, chartData);
      sectionBody.appendChild(card);

      // Render chart (after DOM insertion so sizes are available).
      // 접힌 섹션(display:none)에서 ECharts init하면 width=0 →
      // 접혀 있으면 pendingRenders에 쌓고 펼칠 때 lazy-init.
      const collapsed = sectionBody.classList.contains('collapsed');
      if (meta.type === 'timeseries') {
        const renderFn = () => renderTimeseries(meta.id + '-chart', chartData);
        if (collapsed) queuePendingRender(meta.section, renderFn);
        else nextFrame(renderFn);
      } else if (meta.type === 'curve_snapshot') {
        const renderFn = () => renderCurveSnapshot(meta.id + '-chart', chartData);
        if (collapsed) queuePendingRender(meta.section, renderFn);
        else nextFrame(renderFn);
      } else if (meta.type === 'heatmap_perf') {
        // HTML 테이블 — 숨겨진 상태에서도 렌더 무해
        renderHeatmapPerf(meta.id + '-body', chartData);
      }
    }

    // 3. Window resize → resize all ECharts
    window.addEventListener('resize', () => {
      chartInstances.forEach(instance => instance.resize());
    });

  } catch (err) {
    console.error('Chart book init error:', err);
    loadingEl.style.display = 'none';
    errorEl.style.display = 'block';
    errorEl.textContent = `데이터 로드 오류: ${err.message}`;
  }
}

// Boot
document.addEventListener('DOMContentLoaded', init);

// Theme toggle button
document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('theme-toggle');
  if (btn) btn.addEventListener('click', toggleTheme);
});

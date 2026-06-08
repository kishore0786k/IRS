const IRS_CHARTS = window.IRS || (window.IRS = {});
IRS_CHARTS.API_BASE = IRS_CHARTS.API_BASE || "http://localhost:5000/api";

IRS_CHARTS.palette = {
  blue: "#4e86ff",
  blue2: "#7fb0ff",
  green: "#31c46b",
  orange: "#ff9e4f",
  red: "#f35f5f",
  purple: "#a36fff",
  teal: "#26d0ce",
  gray: "#7f8ca8",
  text: "#edf2ff",
  muted: "#8090b8",
  grid: "rgba(120,160,240,0.10)",
};

IRS_CHARTS._charts = {};
IRS_CHARTS.activeParams = () => window.IRS_STATE || {};

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const toNum = (v, d = 0) => {
  const n = Number(v);
  return Number.isFinite(n) ? n : d;
};
const arr = (v) => Array.isArray(v) ? v.slice() : [];
const deepClone = (obj) => JSON.parse(JSON.stringify(obj));
function deepMerge(base, over) {
  const out = deepClone(base || {});
  for (const [k, v] of Object.entries(over || {})) {
    if (v && typeof v === 'object' && !Array.isArray(v)) out[k] = deepMerge(out[k] || {}, v);
    else out[k] = v;
  }
  return out;
}
function alpha(hex, a = 0.2) {
  const h = String(hex || '#4e86ff').replace('#', '');
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${a})`;
}
function titleText(name) {
  const p = IRS_CHARTS.activeParams();
  return `${name} | Pt=${toNum(p.Pt, 10)}W | N=${toNum(p.N, 64)} | K=${toNum(p.K_users, 3)} | f=${toNum(p.freq_GHz, 3.5).toFixed(1)}GHz | alpha=${toNum(p.alpha, 2.8).toFixed(1)}`;
}
function axisTitle(text) {
  return {
    display: true,
    text,
    color: IRS_CHARTS.palette.muted,
    font: { size: 12, weight: '600' },
    padding: { top: 8 },
  };
}
function setText(id, value) { const el = document.getElementById(id); if (el) el.textContent = value; }
function emitToast(msg, kind = 'info') { document.dispatchEvent(new CustomEvent('irs:toast', { detail: { msg, kind } })); }
function pointArr(x, y) { return arr(x).map((v, i) => ({ x: toNum(v), y: toNum(arr(y)[i], 0) })); }

function isBandDataset(dataset) {
  if (!dataset) return false;
  if (dataset.bandDataset) return true;
  const label = String(dataset.label || '').toLowerCase();
  return label.includes('band floor') || label.includes('95% ci');
}

IRS_CHARTS.baseOpts = {
  responsive: true,
  maintainAspectRatio: false,
  animation: { duration: 500, easing: 'easeInOutQuart' },
  interaction: { mode: 'index', intersect: false },
  plugins: {
    legend: {
      display: true,
      position: 'bottom',
      labels: {
        usePointStyle: true,
        boxWidth: 12,
        boxHeight: 10,
        padding: 14,
        color: IRS_CHARTS.palette.muted,
        font: { size: 11 },
        filter: (item, chart) => {
          const datasets = chart?.data?.datasets || chart?.datasets || [];
          return !isBandDataset(datasets[item.datasetIndex]);
        },
      },
    },
    tooltip: {
      mode: 'index',
      intersect: false,
      backgroundColor: 'rgba(8,13,24,0.95)',
      borderColor: 'rgba(120,160,240,0.25)',
      borderWidth: 1,
      titleColor: IRS_CHARTS.palette.text,
      bodyColor: IRS_CHARTS.palette.text,
      padding: 11,
      filter: (ctx) => {
        const ds = ctx?.dataset || ctx?.chart?.data?.datasets?.[ctx?.datasetIndex];
        return !isBandDataset(ds);
      },
    },
  },
  layout: { padding: { left: 6, right: 10, top: 8, bottom: 6 } },
  scales: {
    x: {
      ticks: { color: IRS_CHARTS.palette.muted, font: { size: 11 }, padding: 6, maxTicksLimit: 8, autoSkip: true, maxRotation: 0 },
      grid: { color: IRS_CHARTS.palette.grid },
      border: { color: 'rgba(120,160,240,0.16)' },
    },
    y: {
      ticks: { color: IRS_CHARTS.palette.muted, font: { size: 11 }, padding: 6, maxTicksLimit: 6 },
      grid: { color: IRS_CHARTS.palette.grid },
      border: { color: 'rgba(120,160,240,0.16)' },
    },
  },
};

IRS_CHARTS.getCanvas = (id) => document.getElementById(id);
IRS_CHARTS.line = (label, data, color, opts = {}) => ({
  label,
  data,
  borderColor: color,
  backgroundColor: opts.fill ? alpha(color, 0.18) : 'transparent',
  fill: opts.fill || false,
  tension: opts.tension ?? 0,
  pointRadius: opts.pointRadius ?? 3.4,
  pointHoverRadius: opts.pointHoverRadius ?? 4.5,
  pointBackgroundColor: color,
  pointBorderColor: '#0d1322',
  pointBorderWidth: opts.pointBorderWidth ?? 1.1,
  borderWidth: opts.bw ?? 2,
  borderDash: opts.dash || [],
  spanGaps: false,
});
IRS_CHARTS.xyLine = (label, points, color, opts = {}) => ({
  label,
  data: points,
  parsing: false,
  showLine: true,
  borderColor: color,
  backgroundColor: 'transparent',
  fill: false,
  tension: opts.tension ?? 0,
  pointRadius: opts.pointRadius ?? 0,
  pointHoverRadius: 3,
  pointBackgroundColor: color,
  pointBorderColor: color,
  borderWidth: opts.bw ?? 2,
  borderDash: opts.dash || [],
});
IRS_CHARTS.radarDs = (label, data, color) => ({
  label,
  data,
  borderColor: color,
  backgroundColor: alpha(color, 0.20),
  borderWidth: 2,
  pointRadius: 3,
  pointBackgroundColor: color,
  pointBorderColor: color,
});

function upsert(id, cfg, live = false) {
  const canvas = IRS_CHARTS.getCanvas(id);
  if (!canvas || typeof Chart === 'undefined') return null;
  const ctx = canvas.getContext('2d');
  const existing = IRS_CHARTS._charts[id];
  const mergedOpts = deepMerge(IRS_CHARTS.baseOpts, cfg.options || {});
  if (live) mergedOpts.animation = false;

  const nextData = { labels: cfg.data?.labels ? cfg.data.labels.slice() : [], datasets: (cfg.data?.datasets || []).map((d) => ({ ...d })) };

  if (existing && existing.config && existing.config.type === cfg.type) {
    existing.data.labels = nextData.labels;
    existing.data.datasets = nextData.datasets;
    existing.options = mergedOpts;
    existing.update(live ? 'none' : undefined);
    return existing;
  }

  if (existing) existing.destroy();
  IRS_CHARTS._charts[id] = new Chart(ctx, { type: cfg.type, data: nextData, options: mergedOpts });
  return IRS_CHARTS._charts[id];
}
IRS_CHARTS.upsert = upsert;

function classifyLabel(label) {
  const t = String(label || '').toLowerCase();
  if (/greedy/.test(t)) return 'greedy';
  if (/random/.test(t)) return 'random';
  if (/no\s*-?\s*irs|direct/.test(t)) return 'none';
  if (/fixed\s*1/.test(t)) return 'fixed1bit';
  if (/fixed.*quant/.test(t)) return 'fixed_quant';
  if (/irs-?noma/.test(t)) return 'irs_noma';
  if (/irs-?oma/.test(t)) return 'irs_oma';
  if (/no-?irs-?noma/.test(t)) return 'no_irs_noma';
  if (/irs-?pls/.test(t)) return 'irs_pls';
  if (/no-?irs-?pls/.test(t)) return 'no_irs_pls';
  if (/adaptive|optimized|opt|proposed|hybrid/.test(t)) return 'opt';
  return '';
}
function labelForKey(key, fallback) {
  const map = {
    opt: 'IRS-Opt (Proposed)',
    ao_lit: 'AO Baseline',
    greedy: 'IRS-Greedy',
    greedy_pls: 'IRS-Greedy PLS',
    random: 'IRS-Random',
    none: 'No IRS (Direct Link)',
    none_line: 'No IRS (Direct Link)',
    no_irs: 'No IRS (Direct Link)',
    fixed1bit: 'Fixed 1-bit IRS',
    fixed_quant: 'Fixed Quantization',
    irs_noma: 'IRS-NOMA (Proposed)',
    irs_oma: 'IRS-OMA',
    no_irs_noma: 'No IRS-NOMA',
    irs_pls: 'IRS-PLS (Proposed)',
    no_irs_pls: 'No IRS-PLS',
    N_large: 'Large IRS-Opt',
    N_small: 'Compact IRS-Opt',
  };
  return map[key] || fallback || key;
}
function extractSeriesValues(entry) {
  if (Array.isArray(entry)) return entry.slice();
  if (!entry || typeof entry !== 'object') return [];
  return arr(entry.mean ?? entry.y ?? entry.values ?? entry.data);
}
function extractSpreadValues(entry) {
  if (!entry || typeof entry !== 'object') return [];
  return arr(entry.spread ?? entry.ci ?? entry.band ?? []);
}
function collectSeries(data) {
  const out = [];
  const seen = new Set();
  const push = (key, label, y, x = null, spread = null) => {
    const yy = extractSeriesValues(y);
    if (!yy.length) return;
    const dedupeKey = `${key}:${label}`;
    if (seen.has(dedupeKey)) return;
    seen.add(dedupeKey);
    const ss = extractSpreadValues(spread ?? y);
    out.push({ key, label, y: yy, x: arr(x).length ? arr(x) : null, spread: ss.length === yy.length ? ss : null });
  };

  if (data && Array.isArray(data.datasets)) {
    data.datasets.forEach((ds, i) => {
      const key = classifyLabel(ds?.label) || `series_${i}`;
      const label = ds?.label || labelForKey(key, `Series ${i + 1}`);
      push(key, label, ds?.mean ?? ds?.y ?? ds?.data ?? ds?.values, ds?.x ?? data.x, ds?.spread ?? ds?.ci);
    });
  }
  const directKeys = ['opt','greedy','greedy_pls','random','none','none_line','no_irs','fixed1bit','fixed_quant','irs_noma','irs_oma','no_irs_noma','irs_pls','no_irs_pls','adaptive','fixed','ideal','N_large','N_small','large','small','bpsk','bpsk_irs','qpsk','qpsk_irs','qam16','qam16_irs','qpsk_no_irs','gain_vs_greedy_pct'];
  directKeys.forEach((k) => {
    const entry = data?.[k];
    const values = extractSeriesValues(entry);
    if (values.length) push(k, labelForKey(k, k), entry, data.x);
  });
  return out;
}
function xLabels(data, fallbackLen = 0) {
  const candidates = [data?.x, data?.distances, data?.N_values, data?.Pt_values, data?.bits, data?.snr_db, data?.csi_error, data?.mc];
  for (const c of candidates) {
    if (Array.isArray(c) && c.length) return c;
  }
  return Array.from({ length: fallbackLen }, (_, i) => i + 1);
}
function metricFromRows(rows, key) { return rows.map((r) => toNum(r[key], 0)); }
function normalizeRow(r) {
  return {
    scheme: r.scheme || r.id || 'unknown',
    label: r.label || labelForKey(r.scheme || r.id || '', r.scheme || r.id || 'unknown'),
    snr: toNum(r.snr ?? r.avg_snr_db ?? r.avg_snr ?? 0),
    rate: toNum(r.rate ?? r.avg_rate ?? r.avg_noma ?? 0),
    secrecy: toNum(r.secrecy ?? r.avg_secrecy ?? 0),
    ee: toNum(r.ee ?? r.avg_ee ?? 0),
    outage: toNum(r.outage ?? r.outage_5dB ?? 0),
    fairness: toNum(r.fairness ?? r.fairness_index ?? 0),
    gain_vs_greedy_pct: toNum(r.gain_vs_greedy_pct ?? 0),
    complexity: r.complexity ?? '--',
  };
}
function rowsFromComparison(data) {
  if (Array.isArray(data)) return data.map(normalizeRow);
  if (Array.isArray(data?.rows)) return data.rows.map(normalizeRow);
  return Object.entries(data || {}).map(([scheme, item]) => normalizeRow({ scheme, ...item }));
}
function bestBy(rows, key, dir = 'desc') {
  if (!rows.length) return null;
  return rows.slice().sort((a, b) => dir === 'desc' ? (toNum(b[key]) - toNum(a[key])) : (toNum(a[key]) - toNum(b[key])))[0];
}
function summarySeriesColor(index) {
  const colors = [IRS_CHARTS.palette.blue, IRS_CHARTS.palette.purple, IRS_CHARTS.palette.orange, IRS_CHARTS.palette.gray, IRS_CHARTS.palette.green, IRS_CHARTS.palette.teal, IRS_CHARTS.palette.red];
  return colors[index % colors.length];
}
function buildLineDatasets(series, opts = {}) {
  const datasets = [];
  series.forEach((s, i) => {
    const color = s.color || summarySeriesColor(i);
    if (s.spread?.length === s.y.length) {
      const lower = s.y.map((v, idx) => toNum(v) - toNum(s.spread[idx]));
      const upper = s.y.map((v, idx) => toNum(v) + toNum(s.spread[idx]));
      datasets.push({
        label: `${s.label} band floor`,
        data: lower,
        bandDataset: true,
        borderColor: 'transparent',
        backgroundColor: 'transparent',
        pointRadius: 0,
        pointHoverRadius: 0,
        borderWidth: 0,
        fill: false,
      });
      datasets.push({
        label: `${s.label} 95% CI`,
        data: upper,
        bandDataset: true,
        borderColor: 'transparent',
        backgroundColor: alpha(color, 0.09),
        pointRadius: 0,
        pointHoverRadius: 0,
        borderWidth: 0,
        fill: '-1',
      });
    }
    datasets.push(IRS_CHARTS.line(s.label, s.y, color, {
      dash: s.dash || [],
      pointRadius: opts.pointRadius ?? 3.4,
      bw: opts.bw ?? 2,
      fill: false,
      tension: opts.tension ?? 0.06,
    }));
  });
  return datasets;
}
function genericSweepChart(id, title, subtitle, data, xLabel, yLabel, live = false, opts = {}) {
  const labels = xLabels(data, collectSeries(data)[0]?.y?.length || 0);
  const series = collectSeries(data).map((s, i) => ({ ...s, color: opts.colors?.[i] || summarySeriesColor(i), dash: opts.dashes?.[i] || [] }));
  upsert(id, {
    type: 'line',
    data: { labels, datasets: buildLineDatasets(series, opts) },
    options: {
      plugins: { title: { display: true, text: titleText(title), color: IRS_CHARTS.palette.text, font: { size: 13, weight: '600' } } },
      scales: { x: { title: axisTitle(xLabel) }, y: { title: axisTitle(yLabel) } },
    },
  }, live);
}

function previewParams() { return IRS_CHARTS.activeParams(); }
function schemeFactor(scheme) {
  const s = String(scheme || 'opt').toLowerCase();
  if (s === 'opt') return 1.0;
  if (s === 'greedy') return 0.92;
  if (s === 'random') return 0.68;
  if (s === 'fixed1bit') return 0.78;
  if (s === 'fixed_quant') return 0.85;
  if (s === 'none') return 0.55;
  return 0.8;
}
function localPreviewSummary(params, scheme) {
  const p = params || {};
  const pt = Math.max(toNum(p.Pt, 10), 0.1);
  const n = Math.max(toNum(p.N, 64), 1);
  const dist = Math.max(toNum(p.dist_m, 15), 1);
  const k = Math.max(toNum(p.K_users, 3), 1);
  const alpha = Math.max(toNum(p.alpha, 2.8), 1);
  const freq = toNum(p.freq_GHz, 3.5);
  const rician = toNum(p.rician_K, 5);
  const bits = Math.max(toNum(p.phase_bits, 3), 1);
  const sc = schemeFactor(scheme);
  const snr = 25.5 + 10 * Math.log10(pt) + 2.6 * Math.log10(n) - 10 * alpha * Math.log10(dist) + 0.35 * rician + (scheme === 'none' ? -1.1 : 0) + (scheme === 'greedy' ? 0.45 : 0) + (scheme === 'random' ? -0.8 : 0) + (scheme === 'fixed1bit' ? 0.15 : 0) + (scheme === 'fixed_quant' ? 0.35 : 0) - 0.15 * Math.max(freq - 3.5, 0);
  const snrLin = Math.pow(10, snr / 10);
  const rate = Math.log2(1 + snrLin) * (0.5 + 0.08 * Math.log2(k + 1)) * sc;
  const secrecy = Math.max(0, 0.42 * Math.log2(1 + snrLin) * (scheme === 'none' ? 0.35 : sc));
  const ee = (rate * 18e6) / (pt + 0.005 * n + 0.1 + 0.0002 * bits * n) / 1e6;
  return { snr, rate, secrecy, ee };
}
function previewSweep(key) {
  const p = previewParams();
  const schemeList = ['opt', 'greedy', 'random', 'none'];
  let xs = [];
  if (key === 'distance') xs = [2,4,6,8,10,12,15,18,21,24,27];
  else if (key === 'N') xs = [4,8,12,16,24,32,48,64,96,128,192,256];
  else if (key === 'bits') xs = [1,2,3,4,5,6,7,8];
  else if (key === 'noma') xs = [1,2,3,4,5,6,7,8];
  else if (key === 'nomaN') xs = [4,8,12,16,24,32,48,64,96,128,192,256];
  else if (key === 'secrecy') xs = [8,12,16,24,32,48,64,96,128,192,256];
  else if (key === 'ee') xs = [4,8,12,16,20,24,28];
  else if (key === 'csi') xs = [0,0.04,0.08,0.12,0.18,0.25];
  const series = schemeList.map((scheme) => {
    const vals = xs.map((x) => {
      const pp = { ...p };
      if (key === 'distance') pp.dist_m = x;
      if (key === 'N') pp.N = x;
      if (key === 'bits') pp.phase_bits = x;
      if (key === 'noma') pp.K_users = x;
      if (key === 'nomaN') pp.N = x;
      if (key === 'secrecy') pp.N = x;
      if (key === 'ee') pp.Pt = x;
      if (key === 'csi') pp.csi_error_var = x;
      const m = localPreviewSummary(pp, scheme);
      if (key === 'secrecy') return m.secrecy;
      if (key === 'ee') return m.ee;
      if (key === 'csi') return scheme === 'opt' ? m.secrecy * (1 - 0.8 * x) : scheme === 'greedy' ? m.secrecy * (1 - 0.9 * x) : scheme === 'random' ? m.secrecy * (1 - 1.1 * x) : m.secrecy * (1 - 0.7 * x);
      if (key === 'noma') return m.rate * (1 + 0.06 * Math.log2(x + 1));
      if (key === 'nomaN') return m.rate;
      if (key === 'bits') return m.rate * (0.94 + 0.03 * x);
      if (key === 'N') return m.snr;
      return m.snr;
    });
    return { label: labelForKey(scheme), y: vals, color: summarySeriesColor(schemeList.indexOf(scheme)), dash: scheme === 'random' ? [5, 4] : scheme === 'greedy' ? [4, 4] : scheme === 'none' ? [8, 4] : [] };
  });
  return { x: xs, datasets: series };
}

IRS_CHARTS.liveUpdate = (params) => {
  window.IRS_STATE = { ...params };
  const summary = localPreviewSummary(params, params.scheme || 'opt');
  setText('kpiSNR', `${summary.snr.toFixed(2)} dB`);
  setText('kpiRate', summary.rate.toFixed(3));
  setText('kpiSec', summary.secrecy.toFixed(3));
  setText('kpiEE', summary.ee.toFixed(3));
  setText('kpiSNRNote', `${String(params.scheme || 'opt').toUpperCase()} preview`);
  setText('simClock', 'live preview');

  genericSweepChart('chartDistance', 'Received SNR vs Distance', 'Optimized IRS, greedy IRS, random phase, and no IRS', previewSweep('distance'), 'Tx-Rx Distance (m)', 'Average SNR (dB)', true);
  genericSweepChart('chartNScale', 'SNR vs IRS Elements N', 'Element scaling under all available baselines', previewSweep('N'), 'IRS Elements N', 'Average SNR (dB)', true);
  genericSweepChart('chartBits', 'Spectral Efficiency vs Phase Bits', 'Quantization sensitivity from preview model', previewSweep('bits'), 'Phase Bits (b)', 'Spectral Efficiency (bps/Hz)', true);
  genericSweepChart('chartNoma', 'NOMA Sum Rate vs N', 'Sum-rate evolution for each IRS strategy', previewSweep('nomaN'), 'IRS Elements N', 'Sum Rate (bps/Hz)', true);
};

IRS_CHARTS.renderDistanceChart = (data) => genericSweepChart('chartDistance', 'Received SNR vs Distance', 'Optimized IRS, greedy IRS, random phase, and no IRS', data, 'Tx-Rx Distance (m)', 'Average SNR (dB)');
IRS_CHARTS.renderNScaleChart = (data) => genericSweepChart('chartNScale', 'SNR vs IRS Elements N', 'Element scaling under all available baselines', data, 'IRS Elements N', 'Average SNR (dB)');
IRS_CHARTS.renderBitsChart = (data) => genericSweepChart('chartBits', 'Spectral Efficiency vs Phase Bits', 'Quantization sensitivity from backend sweep', data, 'Phase Bits (b)', 'Spectral Efficiency (bps/Hz)');
IRS_CHARTS.renderNomaChart = (data) => genericSweepChart('chartNoma', 'NOMA Sum Rate vs N', 'Sum-rate evolution for each IRS strategy', data, 'IRS Elements N', 'Sum Rate (bps/Hz)');
IRS_CHARTS.renderSecrecyChart = (data) => genericSweepChart('chartSecrecyFull', 'Secrecy Rate vs N', 'Legitimate-link advantage under secrecy-aware control', data, 'IRS Elements N', 'Secrecy Rate (bps/Hz)');
IRS_CHARTS.renderEEChart = (data) => genericSweepChart('chartEEFull', 'Energy Efficiency vs Tx Power', 'Power-rate tradeoff across IRS strategies', data, 'Tx Power (W)', 'Energy Efficiency (Mbits/Joule)');
IRS_CHARTS.renderCSIChart = (data) => {
  genericSweepChart('chartCSIError', 'Secrecy Rate vs CSI Error', 'Robustness under imperfect CSI', data, 'CSI error variance', 'Secrecy Rate (bps/Hz)');
  IRS_CHARTS.renderGainChart(data);
};
IRS_CHARTS.renderGainChart = (data) => {
  const x = xLabels(data, 0);
  let y = null;
  if (Array.isArray(data?.gain_vs_greedy_pct)) y = data.gain_vs_greedy_pct;
  else {
    const s = collectSeries(data);
    const opt = s.find((v) => v.key === 'opt' || /opt|proposed|hybrid|adaptive/i.test(v.label))?.y;
    const greedy = s.find((v) => v.key === 'greedy' || /greedy/i.test(v.label))?.y;
    if (opt && greedy && opt.length === greedy.length) {
      y = opt.map((v, i) => ((toNum(v) - toNum(greedy[i])) / Math.max(Math.abs(toNum(greedy[i], 1e-9)), 1e-9)) * 100);
    }
  }
  if (!y || !y.length) return;
  upsert('chartGainGreedy', {
    type: 'line',
    data: {
      labels: x.length ? x : Array.from({ length: y.length }, (_, i) => i + 1),
      datasets: [IRS_CHARTS.line('Gain vs Greedy (%)', y, IRS_CHARTS.palette.green, { dash: [4, 4], fill: false, tension: 0.04 })],
    },
    options: {
      plugins: { title: { display: true, text: titleText('Gain vs Greedy (%) vs CSI Error'), color: IRS_CHARTS.palette.text, font: { size: 12, weight: '600' } } },
      scales: { x: { title: axisTitle('CSI error variance') }, y: { title: axisTitle('Gain vs Greedy (%)') } },
    },
  });
};
IRS_CHARTS.renderBERChart = (data) => {
  if (!data) return;
  const labels = arr(data.x ?? data.snr_db ?? data.snr ?? []);
  const datasets = [];
  const bpsk = arr(data.bpsk ?? data.bpsk_irs);
  const qpsk = arr(data.qpsk ?? data.qpsk_irs);
  const qam16 = arr(data.qam16 ?? data.qam16_irs);
  if (bpsk.length) datasets.push(IRS_CHARTS.line('BPSK + IRS', bpsk, IRS_CHARTS.palette.blue));
  if (qpsk.length) datasets.push(IRS_CHARTS.line('QPSK + IRS', qpsk, IRS_CHARTS.palette.teal, { dash: [4, 3], tension: 0.02 }));
  if (qam16.length) datasets.push(IRS_CHARTS.line('16-QAM + IRS', qam16, IRS_CHARTS.palette.green, { dash: [3, 3], tension: 0.02 }));
  if (arr(data.qpsk_no_irs).length) datasets.push(IRS_CHARTS.line('QPSK No IRS (Baseline)', data.qpsk_no_irs, IRS_CHARTS.palette.gray, { dash: [6, 4], bw: 1.5, tension: 0.02 }));
  if (!datasets.length) return;
  upsert('chartBERFull', {
    type: 'line',
    data: { labels, datasets },
    options: {
      plugins: { title: { display: true, text: titleText('BER vs SNR'), color: IRS_CHARTS.palette.text, font: { size: 12, weight: '600' } } },
      scales: { x: { title: axisTitle('SNR (dB)') }, y: { type: 'logarithmic', title: axisTitle('BER'), ticks: { color: IRS_CHARTS.palette.muted, callback: (v) => Number(v).toExponential(0) } } },
    },
  });
};
IRS_CHARTS.renderRadarChart = (data) => {
  if (!data) return;
  const labels = arr(data.labels ?? data.kpis ?? ['SNR', 'Rate', 'Secrecy', 'EE', 'Coverage']);
  const datasets = [];
  if (arr(data.values).length) datasets.push(IRS_CHARTS.radarDs(data.scheme || 'Active Scheme', data.values, IRS_CHARTS.palette.blue));
  if (arr(data.opt).length) datasets.push(IRS_CHARTS.radarDs('Proposed (IRS-Opt)', data.opt, IRS_CHARTS.palette.blue));
  if (arr(data.random).length) datasets.push(IRS_CHARTS.radarDs('IRS-Random', data.random, IRS_CHARTS.palette.orange));
  if (arr(data.none).length) datasets.push(IRS_CHARTS.radarDs('No IRS Baseline', data.none, IRS_CHARTS.palette.gray));
  if (!datasets.length) return;
  upsert('chartRadarFull', {
    type: 'radar',
    data: { labels, datasets },
    options: {
      plugins: { title: { display: true, text: titleText('Radar - Normalized KPI'), color: IRS_CHARTS.palette.text, font: { size: 12, weight: '600' } } },
      scales: {
        r: {
          suggestedMin: 0,
          suggestedMax: 100,
          angleLines: { color: 'rgba(120,160,240,0.12)' },
          grid: { color: 'rgba(120,160,240,0.12)' },
          pointLabels: { color: IRS_CHARTS.palette.muted, font: { size: 10 } },
          ticks: { color: IRS_CHARTS.palette.muted, backdropColor: 'transparent', font: { size: 9 }, callback: (v) => `${v}%` },
        },
      },
    },
  });
};
IRS_CHARTS.renderCDFChart = (data) => {
  if (!data) return;
  let series = [];
  if (Array.isArray(data.datasets)) {
    series = data.datasets.map((ds, i) => ({ label: ds.label || `Series ${i + 1}`, points: pointArr(ds.x ?? data.x, ds.y ?? ds.cdf_y ?? []) }));
  } else if (data.opt || data.random || data.none) {
    const pick = (obj) => pointArr(obj?.x ?? data.x, obj?.y ?? obj?.cdf_y ?? []);
    series = [
      { label: 'IRS-Opt (Proposed)', points: pick(data.opt) },
      { label: 'IRS-Random', points: pick(data.random) },
      { label: 'No IRS Baseline', points: pick(data.none) },
    ].filter((s) => s.points.length);
  } else if (Array.isArray(data.x) && Array.isArray(data.y)) {
    series = [{ label: 'CDF', points: pointArr(data.x, data.y) }];
  }
  const colors = [IRS_CHARTS.palette.blue, IRS_CHARTS.palette.orange, IRS_CHARTS.palette.gray, IRS_CHARTS.palette.green];
  const dashes = [[], [5, 4], [8, 4], [3, 3]];
  const datasets = series.map((s, i) => IRS_CHARTS.xyLine(s.label, s.points, colors[i % colors.length], { dash: dashes[i % dashes.length] }));
  upsert('chartCDFFull', {
    type: 'scatter',
    data: { datasets },
    options: {
      plugins: { title: { display: true, text: titleText('CDF / Outage Analysis'), color: IRS_CHARTS.palette.text, font: { size: 12, weight: '600' } } },
      scales: { x: { type: 'linear', title: axisTitle('SNR (dB)') }, y: { type: 'linear', min: 0, max: 1, title: axisTitle('Cumulative Distribution F(x)') } },
    },
  });
};
IRS_CHARTS.renderComparison = (data) => {
  const rows = rowsFromComparison(data);
  const tbody = document.getElementById('compareTableBody');
  if (tbody) {
    tbody.innerHTML = rows.map((r) => {
      const bestTag = r.scheme === bestBy(rows, 'snr')?.scheme ? '<span class="badge good">Top SNR</span>' : '';
      return `<tr>
        <td class="scheme-name">${r.label} ${bestTag}</td>
        <td>${r.snr.toFixed(2)}</td>
        <td>${r.rate.toFixed(3)}</td>
        <td>${r.secrecy.toFixed(3)}</td>
        <td>${r.ee.toFixed(3)}</td>
        <td>${(r.outage * 100).toFixed(1)}%</td>
        <td>${r.gain_vs_greedy_pct.toFixed(2)}%</td>
        <td>${r.fairness ? r.fairness.toFixed(3) : '--'}</td>
      </tr>`;
    }).join('');
  }

  const snrBest = bestBy(rows, 'snr');
  const rateBest = bestBy(rows, 'rate');
  const secrecyBest = bestBy(rows, 'secrecy');
  const eeBest = bestBy(rows, 'ee');
  const gainBest = bestBy(rows, 'gain_vs_greedy_pct');
  const outageBest = bestBy(rows, 'outage', 'asc');

  if (snrBest) { setText('bestScheme', snrBest.label); setText('bestSNR', `${snrBest.snr.toFixed(2)} dB`); }
  if (rateBest) { setText('bestRateScheme', rateBest.label); setText('bestRate', rateBest.rate.toFixed(3)); }
  if (secrecyBest) { setText('bestSecrecyScheme', secrecyBest.label); setText('bestSecrecy', secrecyBest.secrecy.toFixed(3)); }
  if (eeBest) { setText('bestEEScheme', eeBest.label); setText('bestEE', eeBest.ee.toFixed(3)); }

  const labels = rows.map((r) => r.label);
  upsert('chartCompareBar', {
    type: 'bar',
    data: {
      labels,
      datasets: [
        { label: 'Gain vs Greedy (%)', data: metricFromRows(rows, 'gain_vs_greedy_pct'), backgroundColor: alpha(IRS_CHARTS.palette.green, 0.62), borderColor: IRS_CHARTS.palette.green, borderWidth: 1 },
        { label: 'Outage @ 5 dB (%)', data: rows.map((r) => r.outage * 100), backgroundColor: alpha(IRS_CHARTS.palette.orange, 0.60), borderColor: IRS_CHARTS.palette.orange, borderWidth: 1 },
      ],
    },
    options: {
      indexAxis: 'y',
      plugins: { title: { display: true, text: titleText('Comparison Summary'), color: IRS_CHARTS.palette.text, font: { size: 12, weight: '600' } } },
      scales: { x: { title: axisTitle('Percent (%)') }, y: { title: axisTitle('Scheme') } },
    },
  });

  return rows;
};
IRS_CHARTS.renderConvergenceChart = (data) => {
  const conv = Array.isArray(data?.convergence) ? data.convergence : Array.isArray(data) ? data : [];
  if (!conv.length) return;
  const labels = conv.map((d) => toNum(d.mc ?? d.samples ?? d.n ?? d.N, 0));
  const snr = conv.map((d) => toNum(d.snr ?? d.avg_snr_db ?? d.mean_snr ?? 0));
  const std = conv.map((d) => toNum(d.std ?? d.std_dev ?? 0));
  const ci = conv.map((d) => toNum(d.ci95 ?? d.ci ?? 0));
  upsert('chartConvergence', {
    type: 'line',
    data: {
      labels,
      datasets: [
        IRS_CHARTS.line('Average SNR', snr, IRS_CHARTS.palette.blue),
        IRS_CHARTS.line('Std Dev', std, IRS_CHARTS.palette.orange, { dash: [5, 4], tension: 0.04 }),
        IRS_CHARTS.line('95% CI', ci, IRS_CHARTS.palette.green, { dash: [3, 3], tension: 0.04 }),
      ],
    },
    options: {
      plugins: { title: { display: true, text: 'Monte Carlo Convergence', color: IRS_CHARTS.palette.text, font: { size: 12, weight: '600' } } },
      scales: { x: { title: axisTitle('MC samples') }, y: { title: axisTitle('Value') } },
    },
  });
};
IRS_CHARTS.renderPublication = (data) => {
  const panel = document.getElementById('publicationSummary');
  if (!panel) return;
  if (!data || typeof data !== 'object') {
    panel.innerHTML = '<p>No publication summary returned by the backend yet.</p>';
    return;
  }
  const items = [];
  if (Array.isArray(data.highlights)) items.push(`<ul class="mini-list">${data.highlights.map((v) => `<li>${v}</li>`).join('')}</ul>`);
  if (data.summary) items.push(`<p>${data.summary}</p>`);
  if (data.claim) items.push(`<p><b>Claim:</b> ${data.claim}</p>`);
  panel.innerHTML = items.join('') || '<p>Publication summary data received.</p>';
};

IRS_CHARTS.ensureChartCard = (id, title, subtitle = '') => {
  if (document.getElementById(id)) return;
  const host = document.querySelector('#tab-charts .chart-grid') || document.body;
  const card = document.createElement('article');
  card.className = 'chart-card';
  card.innerHTML = `<header class="chart-head"><div><h3>${title}</h3><p>${subtitle}</p></div></header><div class="chart-wrap"><canvas id="${id}"></canvas></div>`;
  host.appendChild(card);
};

IRS_CHARTS._canvasToDataURL = (canvas) => {
  const off = document.createElement('canvas');
  off.width = canvas.width;
  off.height = canvas.height;
  const ctx = off.getContext('2d');
  ctx.fillStyle = '#080d18';
  ctx.fillRect(0, 0, off.width, off.height);
  ctx.drawImage(canvas, 0, 0);
  return off.toDataURL('image/png');
};
IRS_CHARTS.EXPORT_CHARTS = [
  { id: 'chartDistance', file: '01_SNR_vs_Distance' },
  { id: 'chartNScale', file: '02_SNR_vs_N' },
  { id: 'chartBits', file: '03_Spectral_Efficiency_vs_Bits' },
  { id: 'chartNoma', file: '04_NOMA_SumRate_vs_N' },
  { id: 'chartSecrecyFull', file: '05_Secrecy_vs_N' },
  { id: 'chartEEFull', file: '06_EE_vs_TxPower' },
  { id: 'chartBERFull', file: '07_BER_vs_SNR' },
  { id: 'chartRadarFull', file: '08_Radar_KPI' },
  { id: 'chartCDFFull', file: '09_CDF_SNR' },
  { id: 'chartCSIError', file: '10_Secrecy_vs_CSI' },
  { id: 'chartGainGreedy', file: '11_Gain_vs_Greedy_CSI' },
  { id: 'chartConvergence', file: '12_Convergence' },
  { id: 'chartCompareBar', file: '13_Comparison_Summary' },
];
IRS_CHARTS.exportAllVisible = async () => {
  const charts = IRS_CHARTS.EXPORT_CHARTS;
  const payload = [];
  const missing = [];
  charts.forEach(({ id, file }) => {
    const canvas = document.getElementById(id);
    if (!canvas || !IRS_CHARTS._charts[id]) { missing.push(file); return; }
    try {
      payload.push({ filename: `${file}.png`, data: IRS_CHARTS._canvasToDataURL(canvas) });
    } catch {
      missing.push(file);
    }
  });
  if (!payload.length) {
    emitToast('No charts have data yet - run a simulation first.', 'error');
    return;
  }
  try {
    const res = await fetch(`${IRS_CHARTS.API_BASE}/export`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ charts: payload, params: IRS_CHARTS.activeParams(), mode: IRS_CHARTS.activeParams().mode || 'medium' }),
    });
    if (!res.ok) throw new Error(await res.text().catch(() => `HTTP ${res.status}`));
    const result = await res.json();
    let msg = `Saved ${result.count || result.saved?.length || 0} chart(s) -> ${result.folder || 'results/'}`;
    if (missing.length) msg += ` | ${missing.length} skipped`;
    if (result.manifest) msg += ' | manifest saved';
    if ((result.errors || []).length) msg += ` | ${result.errors.length} error(s)`;
    emitToast(msg, (result.errors || []).length ? 'error' : 'success');
  } catch (err) {
    emitToast(`Export failed: ${err.message}`, 'error');
  }
};

IRS_CHARTS.upsert = upsert;
IRS_CHARTS.classifyLabel = classifyLabel;
IRS_CHARTS.collectSeries = collectSeries;
IRS_CHARTS.rowsFromComparison = rowsFromComparison;
IRS_CHARTS.genericSweepChart = genericSweepChart;
IRS_CHARTS.previewSweep = previewSweep;
IRS_CHARTS.previewSummary = localPreviewSummary;

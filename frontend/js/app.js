const IRS_APP = window.IRS || (window.IRS = {});
IRS_APP.API_BASE = IRS_APP.API_BASE || 'http://localhost:5000/api';
const BACKEND_ROOT = IRS_APP.API_BASE.replace(/\/api\/?$/, '') || 'http://localhost:5000';

const state = {
  params: {
    Pt: 10,
    N: 64,
    freq_GHz: 3.5,
    phase_bits: 3,
    dist_m: 15,
    K_users: 3,
    rician_K: 5,
    alpha: 2.8,
    d_irs: 5,
    d_irs_rx: 10,
    d_eve: 12,
    scheme: 'opt',
    mode: 'medium',
    csi_mode: 'imperfect',
    csi_error_var: 0.08,
    secrecy_weight: 0.18,
  },
  busy: false,
  scene: null,
  activeTab: 'overview',
  backendOnline: null,
  backendChecking: false,
  initialAutoRun: false,
  liveDebounce: null,
};
window.IRS_STATE = state.params;

const $ = (id) => document.getElementById(id);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function setText(id, value) { const el = $(id); if (el) el.textContent = value; }
function toast(message, kind = 'info') {
  const el = $('toast');
  if (!el) return;
  el.className = `toast ${kind} show`;
  el.textContent = message;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove('show'), 3200);
}
function showLoading(title = 'Running simulation...', sub = 'Monte Carlo in progress') {
  setText('loadingText', title);
  setText('loadingSub', sub);
  $('loadingOverlay')?.classList.add('active');
  state.busy = true;
}
function hideLoading() {
  $('loadingOverlay')?.classList.remove('active');
  state.busy = false;
}

const SLIDER_MAP = [
  ['sPt', 'Pt', 'float', (v) => `${v} W`],
  ['sN', 'N', 'int', (v) => `${v}`],
  ['sF', 'freq_GHz', 'float', (v) => `${Number(v).toFixed(1)} GHz`],
  ['sB', 'phase_bits', 'int', (v) => `${v} bits`],
  ['sD', 'dist_m', 'float', (v) => `${v} m`],
  ['sK', 'K_users', 'int', (v) => `${v} users`],
  ['sRK', 'rician_K', 'float', (v) => `${v} dB`],
  ['sDirs', 'd_irs', 'float', (v) => `${v} m`],
  ['sDirr', 'd_irs_rx', 'float', (v) => `${v} m`],
  ['sDeve', 'd_eve', 'float', (v) => `${v} m`],
];

function readSliders() {
  SLIDER_MAP.forEach(([id, key, type, format]) => {
    const el = $(id);
    if (!el) return;
    state.params[key] = type === 'int' ? parseInt(el.value, 10) : parseFloat(el.value);
    setText(`${id}Val`, format(state.params[key]));
  });
  const scheme = $('sScheme');
  if (scheme) state.params.scheme = scheme.value;
  const mode = $('sMode');
  if (mode) state.params.mode = mode.value;
  const csi = $('sCSI');
  if (csi) {
    state.params.csi_mode = csi.value;
    state.params.csi_error_var = csi.value === 'perfect' ? 0 : 0.08;
  }
  window.IRS_STATE = { ...state.params };
}

function scheduleLiveUpdate() {
  clearTimeout(state.liveDebounce);
  state.liveDebounce = setTimeout(() => {
    if (typeof IRS_APP.liveUpdate === 'function') IRS_APP.liveUpdate(state.params);
  }, 120);
}

function wireSliders() {
  SLIDER_MAP.forEach(([id, , type, format]) => {
    const el = $(id);
    if (!el) return;
    setText(`${id}Val`, format(type === 'int' ? parseInt(el.value, 10) : parseFloat(el.value)));
    el.addEventListener('input', () => {
      readSliders();
      scheduleLiveUpdate();
      if (state.scene?.setParams) {
        state.scene.setParams({ ...state.params, K: state.params.K_users, freq: state.params.freq_GHz });
      }
    });
  });
  $('sScheme')?.addEventListener('change', () => {
    readSliders();
    scheduleLiveUpdate();
    if (state.scene?.setParams) {
      state.scene.setParams({ ...state.params, K: state.params.K_users, freq: state.params.freq_GHz });
    }
  });
  $('sMode')?.addEventListener('change', () => { readSliders(); });
  $('sCSI')?.addEventListener('change', () => {
    readSliders();
    scheduleLiveUpdate();
    if (state.scene?.setParams) {
      state.scene.setParams({ ...state.params, K: state.params.K_users, freq: state.params.freq_GHz });
    }
  });
}

function wireTabs() {
  $$('.tab').forEach((btn) => btn.addEventListener('click', () => switchTab(btn.dataset.tab)));
}

function switchTab(name) {
  $$('.tab').forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
  $$('.tab-panel').forEach((p) => p.classList.remove('active'));
  const target = $('tab-' + name);
  if (target) target.classList.add('active');
  state.activeTab = name;
  if (name === 'scene') {
    const SceneCtor = window.IRSScene3D || window.IRSScene;
    if (!state.scene && typeof SceneCtor === 'function') state.scene = new SceneCtor('sceneCanvas');
    if (state.scene) {
      state.scene.setParams({ ...state.params, K: state.params.K_users, freq: state.params.freq_GHz });
      state.scene.start?.();
    }
  } else {
    state.scene?.stop?.();
  }
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 180000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...options, signal: ctrl.signal });
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new Error(`${res.status} ${res.statusText}${text ? ' - ' + text : ''}`);
    }
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}
async function apiPost(endpoint, body = {}, timeoutMs = 180000) {
  return fetchWithTimeout(`${IRS_APP.API_BASE}/${endpoint}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }, timeoutMs);
}

function applyKPIs(data) {
  if (!data) return;
  const snr = data.avg_snr_db ?? data.snr_db ?? data.snr ?? null;
  const rate = data.avg_rate ?? data.avg_noma ?? data.rate ?? null;
  const sec = data.avg_secrecy ?? data.secrecy_rate ?? null;
  const ee = data.avg_ee ?? data.energy_efficiency ?? null;
  const out = data.outage_5dB ?? data.outage_prob ?? null;
  setText('kpiSNR', snr != null ? Number(snr).toFixed(2) + ' dB' : '--');
  setText('kpiRate', rate != null ? Number(rate).toFixed(3) : '--');
  setText('kpiSec', sec != null ? Number(sec).toFixed(3) : '--');
  setText('kpiEE', ee != null ? Number(ee).toFixed(3) : '--');
  setText('kpiSNRNote', out != null ? `outage @5dB: ${(Number(out) * 100).toFixed(1)}%` : 'backend result');
  if (data._time != null) setText('simClock', `last: ${Number(data._time).toFixed(2)}s`);
}
function livePreview() { if (typeof IRS_APP.liveUpdate === 'function') IRS_APP.liveUpdate(state.params); }
function setBackendButtonsEnabled(enabled) {
  ['btnRunOverview','btnRunAll','btnRunCompare','btnRunRadar','btnRunCDF','btnRunCSI','btnRunBatch','btnExportAll'].forEach((id) => { const el = $(id); if (el) el.disabled = !enabled && id !== 'btnExportAll'; });
}
function updateBackendStatus(online) {
  setText('serverStatus', online ? 'Connected' : 'Offline - live preview active');
  $('serverDot')?.classList.toggle('ok', !!online);
  $('serverDot')?.classList.toggle('err', !online);
  setBackendButtonsEnabled(!!online);
}

async function checkBackend() {
  if (state.backendChecking) return;
  state.backendChecking = true;
  try {
    const json = await fetchWithTimeout(BACKEND_ROOT + '/', { method: 'GET' }, 6000);
    if (!json || !json.project) throw new Error('Unexpected response');
    const wasOffline = state.backendOnline !== true;
    state.backendOnline = true;
    updateBackendStatus(true);
    if (wasOffline) toast('Backend connected on port 5000', 'success');
  } catch {
    const wasOnline = state.backendOnline !== false;
    state.backendOnline = false;
    updateBackendStatus(false);
    if (wasOnline) toast('Backend not running - live preview mode', 'info');
  } finally {
    state.backendChecking = false;
  }
  if (state.backendOnline && !state.initialAutoRun && !state.busy) {
    state.initialAutoRun = true;
    setTimeout(() => { runOverview().catch(() => {}); }, 150);
  }
}

function withQuietFailure(promise, label) {
  return promise.catch((err) => { toast(`${label} failed: ${err.message}`, 'error'); return null; });
}

async function runOverview() {
  showLoading('Running overview...', 'Fetching the optimized overview bundle');
  try {
    const overview = await withQuietFailure(apiPost('overview', state.params, 180000), 'Overview');
    if (!overview) return;
    applyKPIs(overview.metrics || overview);
    IRS_APP.renderDistanceChart?.(overview.distance || overview.metrics);
    IRS_APP.renderNScaleChart?.(overview.N || overview.metrics);
    IRS_APP.renderBitsChart?.(overview.bits || overview.metrics);
    IRS_APP.renderNomaChart?.(overview.noma || overview.metrics);
    setText('simClock', `overview done ${new Date().toLocaleTimeString()}`);
    toast('Overview updated from backend', 'success');
  } finally {
    hideLoading();
  }
}

async function runAllCharts() {
  showLoading('Running all charts...', 'Fetching the full dashboard bundle from the backend');
  try {
    const batch = await withQuietFailure(apiPost('batch', state.params, 480000), 'All charts bundle');
    if (!batch) return;
    applyKPIs(batch.metrics || batch);
    IRS_APP.renderSecrecyChart?.(batch.secrecy || batch.metrics);
    IRS_APP.renderEEChart?.(batch.ee || batch.metrics);
    IRS_APP.renderBERChart?.(batch.ber || batch.metrics);
    IRS_APP.renderRadarChart?.(batch.radar || batch.metrics);
    IRS_APP.renderCDFChart?.(batch.cdf || batch.metrics);
    IRS_APP.renderCSIChart?.(batch.csi || batch.metrics);
    IRS_APP.renderConvergenceChart?.(batch.convergence || batch.metrics);
    if (batch.compare) IRS_APP.renderComparison?.(batch.compare);
    toast('All charts updated', 'success');
  } finally {
    hideLoading();
  }
}

async function runComparison() {
  showLoading('Running scheme comparison...', 'Benchmarking available IRS schemes');
  try {
    const data = await withQuietFailure(apiPost('compare', state.params), 'Comparison');
    IRS_APP.renderComparison?.(data);
    toast('Comparison table updated', 'success');
  } finally { hideLoading(); }
}

async function runRadar() {
  showLoading('Running radar analysis...', 'Extracting normalized KPI snapshot');
  try {
    const radar = await withQuietFailure(apiPost('radar', state.params), 'Radar');
    IRS_APP.renderRadarChart?.(radar);
    toast('Radar updated', 'success');
  } finally { hideLoading(); }
}

async function runCDF() {
  showLoading('Running CDF analysis...', 'Computing outage distribution');
  try {
    const cdf = await withQuietFailure(apiPost('cdf', state.params), 'CDF');
    IRS_APP.renderCDFChart?.(cdf);
    toast('CDF updated', 'success');
  } finally { hideLoading(); }
}

async function runCSI() {
  showLoading('Running CSI sweep...', 'Sweeping CSI error and gain vs greedy');
  try {
    const csi = await withQuietFailure(apiPost('sweep/csi', state.params), 'CSI sweep');
    IRS_APP.renderCSIChart?.(csi);
    toast('CSI sweep updated', 'success');
  } finally { hideLoading(); }
}

async function runBatch() {
  showLoading('Running full batch...', 'Fetching every chart source in one call');
  try {
    const batch = await withQuietFailure(apiPost('batch', state.params, 480000), 'Batch');
    if (!batch) return;
    applyKPIs(batch.metrics || batch);
    IRS_APP.renderDistanceChart?.(batch.distance || batch.metrics);
    IRS_APP.renderNScaleChart?.(batch.N || batch.metrics);
    IRS_APP.renderBitsChart?.(batch.bits || batch.metrics);
    IRS_APP.renderNomaChart?.(batch.noma || batch.metrics);
    IRS_APP.renderSecrecyChart?.(batch.secrecy || batch.metrics);
    IRS_APP.renderEEChart?.(batch.ee || batch.metrics);
    IRS_APP.renderBERChart?.(batch.ber || batch.metrics);
    IRS_APP.renderRadarChart?.(batch.radar || batch.metrics);
    IRS_APP.renderCDFChart?.(batch.cdf || batch.metrics);
    IRS_APP.renderCSIChart?.(batch.csi || batch.metrics);
    IRS_APP.renderConvergenceChart?.(batch.convergence || batch.metrics);
    if (batch.compare) IRS_APP.renderComparison?.(batch.compare);
    toast('Batch completed', 'success');
  } finally { hideLoading(); }
}

function wireButtons() {
  const bind = (id, fn) => { const el = $(id); if (el) el.addEventListener('click', fn); };
  bind('btnRunOverview', () => runOverview());
  bind('btnRunAll', () => runAllCharts());
  bind('btnRunCompare', () => runComparison());
  bind('btnRunRadar', () => runRadar());
  bind('btnRunCDF', () => runCDF());
  bind('btnRunCSI', () => runCSI());
  bind('btnRunBatch', () => runBatch());
  bind('btnReconnect', () => checkBackend());
  bind('btnExportAll', () => IRS_APP.exportAllVisible?.());
  $$('.btn-export').forEach((btn) => btn.addEventListener('click', () => IRS_APP.exportCanvas?.(btn.dataset.target)));
}

function init() {
  wireSliders();
  wireTabs();
  wireButtons();
  readSliders();
  document.addEventListener('irs:toast', (e) => toast(e.detail?.msg || '', e.detail?.kind || 'info'));
  livePreview();
  checkBackend();
  setInterval(() => { if (!state.busy && !state.backendChecking) checkBackend().catch(() => {}); }, 60000);
}

Object.assign(IRS_APP, {
  liveUpdate: IRS_APP.liveUpdate,
  runOverview,
  runAllCharts,
  runComparison,
  runRadar,
  runCDF,
  runCSI,
  runBatch,
  checkBackend,
  exportCanvas: (id) => {
    const canvas = document.getElementById(id);
    if (!canvas || !IRS_CHARTS._charts[id]) return toast('Chart is not ready yet.', 'error');
    const url = IRS_CHARTS._canvasToDataURL(canvas);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${id}.png`;
    a.click();
  },
});

document.addEventListener('DOMContentLoaded', init);

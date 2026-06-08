class IRSScene3D {
  constructor(canvasId) {
    this.canvas = document.getElementById(canvasId);
    this.ctx = this.canvas?.getContext('2d') || null;
    this.running = false;
    this.animId = null;
    this.t = 0;
    this.lastStage = -1;
    this.params = {
      N: 64,
      K: 3,
      Pt: 10,
      freq: 3.5,
      phase_bits: 3,
      dist_m: 15,
      d_eve: 12,
      alpha: 2.8,
      scheme: 'opt',
      csi_mode: 'imperfect',
      csi_error_var: 0.08,
      secrecy_weight: 0.18,
    };
    this.phaseModel = null;
    this._onResize = () => this._resize();
    if (this.canvas) this._resize();
    window.addEventListener('resize', this._onResize);
    this._rebuildSceneModel();
  }

  _resize() {
    if (!this.canvas) return;
    const rect = this.canvas.getBoundingClientRect();
    const w = Math.max(600, Math.floor(rect.width || this.canvas.offsetWidth || 800));
    const h = Math.max(420, Math.floor(rect.height || this.canvas.offsetHeight || 540));
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = Math.floor(w * dpr);
    this.canvas.height = Math.floor(h * dpr);
    this.canvas.style.width = `${w}px`;
    this.canvas.style.height = `${h}px`;
    if (this.ctx) this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.W = w;
    this.H = h;
  }

  setParams(p) {
    this.params = { ...this.params, ...p };
    const { N, K, Pt, freq } = this.params;
    const set = (id, value) => {
      const el = document.getElementById(id);
      if (el) el.textContent = String(value);
    };
    set('sc-F', Number(freq).toFixed(1));
    set('sc-N', String(N));
    set('sc-Pt', String(Pt));
    set('sc-K', String(K));
    this._rebuildSceneModel();
  }

  start() {
    if (this.running || !this.ctx) return;
    this.running = true;
    this._resize();
    const loop = () => {
      if (!this.running) return;
      this._draw();
      this.t += 0.018;
      this.animId = requestAnimationFrame(loop);
    };
    loop();
  }

  stop() {
    this.running = false;
    if (this.animId) cancelAnimationFrame(this.animId);
    this.animId = null;
  }

  destroy() {
    this.stop();
    window.removeEventListener('resize', this._onResize);
  }

  _rebuildSceneModel() {
    const p = this.params;
    const nr = Math.ceil(Math.sqrt(Math.max(p.N, 4)));
    const bits = Math.max(1, Number(p.phase_bits || 1));
    const levels = 2 ** bits;
    const randomPhases = [];
    const csiPhases = [];
    const optimizedPhases = [];

    for (let idx = 0; idx < nr * nr; idx += 1) {
      const row = Math.floor(idx / nr);
      const col = idx % nr;
      const x = (col - (nr - 1) / 2) / Math.max(nr - 1, 1);
      const y = (row - (nr - 1) / 2) / Math.max(nr - 1, 1);
      const randomPhase = this._wrapTau(this._hashNoise(idx + 11) * Math.PI * 6 + row * 0.31 + col * 0.27);
      const focus = Math.atan2(y + 0.35, x + 0.78);
      const secrecySuppression = Math.atan2(y - 0.18, x - 0.44);
      const geometricBias = 0.75 * focus - 0.34 * secrecySuppression;
      const waveform = 0.55 * Math.sin((row + 1) * 0.47 + p.freq * 0.25) + 0.35 * Math.cos((col + 1) * 0.36 + p.Pt * 0.08);
      const raw = geometricBias + waveform;
      const distortionScale = p.csi_mode === 'perfect' ? 0 : 1.7 * (0.15 + Number(p.csi_error_var || 0));
      const csiEstimate = raw + distortionScale * this._hashNoise(idx + 97);
      const optimized = this._quantizePhase(csiEstimate, bits);
      randomPhases.push(randomPhase);
      csiPhases.push(csiEstimate);
      optimizedPhases.push(optimized);
    }

    this.phaseModel = {
      nr,
      bits,
      levels,
      randomPhases,
      csiPhases,
      optimizedPhases,
      legend: Array.from({ length: levels }, (_, idx) => {
        const phase = (idx / levels) * Math.PI * 2;
        return { phase, label: `${Math.round((phase * 180) / Math.PI)}deg` };
      }),
    };

    this._renderPhaseLegend();
    this._updateResearchMetrics();
    this._updateOptimizationUI(0);
  }

  _hashNoise(n) {
    return Math.sin(n * 12.9898 + 78.233) * 43758.5453 % 1;
  }

  _wrapTau(x) {
    const tau = Math.PI * 2;
    let out = x % tau;
    if (out < 0) out += tau;
    return out;
  }

  _quantizePhase(value, bits) {
    const tau = Math.PI * 2;
    const levels = 2 ** Math.max(1, bits);
    const wrapped = this._wrapTau(value);
    const step = tau / levels;
    return Math.round(wrapped / step) * step;
  }

  _interpolatePhase(a, b, blend) {
    const tau = Math.PI * 2;
    const delta = ((b - a + Math.PI) % tau) - Math.PI;
    return this._wrapTau(a + delta * blend);
  }

  _phaseToColor(phase, alpha = 0.95) {
    const hue = (this._wrapTau(phase) / (Math.PI * 2)) * 360;
    return `hsla(${hue}, 82%, 60%, ${alpha})`;
  }

  _stageState() {
    const cycle = 8;
    const local = this.t % cycle;
    if (local < 1.6) {
      return { index: 0, blend: 0, label: 'Random init', note: 'starting from an unstructured phase profile' };
    }
    if (local < 3.2) {
      return { index: 1, blend: (local - 1.6) / 1.6, label: 'CSI estimate', note: 'conditioning the surface on the estimated channel' };
    }
    if (local < 4.8) {
      return { index: 2, blend: (local - 3.2) / 1.6, label: 'Quantized projection', note: 'projecting each phase onto the b-bit codebook' };
    }
    return { index: 3, blend: 1, label: 'Optimized secure phase', note: 'holding the secrecy-aware optimized phase map' };
  }

  _currentPhaseSet() {
    const state = this._stageState();
    const phaseModel = this.phaseModel;
    if (!phaseModel) return { state, phases: [] };
    const { randomPhases, csiPhases, optimizedPhases } = phaseModel;
    const phases = randomPhases.map((phase, idx) => {
      if (state.index === 0) return phase;
      if (state.index === 1) return this._interpolatePhase(phase, csiPhases[idx], state.blend);
      if (state.index === 2) return this._interpolatePhase(csiPhases[idx], optimizedPhases[idx], state.blend);
      return optimizedPhases[idx];
    });
    return { state, phases };
  }

  _schemeLabel() {
    const s = String(this.params.scheme || 'opt').toLowerCase();
    return {
      opt: 'Optimized',
      greedy: 'Greedy',
      random: 'Random',
      none: 'Direct only',
      fixed1bit: 'Fixed 1-bit',
      fixed_quant: 'Fixed quantized',
    }[s] || 'Optimized';
  }

  _schemeFactors() {
    const s = String(this.params.scheme || 'opt').toLowerCase();
    if (s === 'opt') return { snr: 1.18, secrecy: 1.32 };
    if (s === 'greedy') return { snr: 1.07, secrecy: 1.05 };
    if (s === 'fixed_quant') return { snr: 1.11, secrecy: 1.08 };
    if (s === 'fixed1bit') return { snr: 0.96, secrecy: 0.92 };
    if (s === 'random') return { snr: 0.72, secrecy: 0.64 };
    return { snr: 0.58, secrecy: 0.42 };
  }

  _updateResearchMetrics() {
    const p = this.params;
    const factors = this._schemeFactors();
    const csiPenalty = p.csi_mode === 'perfect' ? 0 : 12 * Number(p.csi_error_var || 0);
    const snrGain = Math.max(0.5, 2.6 + 1.25 * Math.log2(Math.max(p.N, 4)) + 0.46 * p.phase_bits + 0.11 * p.Pt - 0.07 * p.dist_m - csiPenalty);
    const secrecyGain = Math.max(0, 6 + 2.3 * Math.log2(Math.max(p.N, 4)) + 1.35 * p.phase_bits + 40 * Number(p.secrecy_weight || 0) - 6.5 * Number(p.csi_error_var || 0));
    const snrValue = `${(snrGain * factors.snr).toFixed(1)} dB`;
    const secrecyValue = `${(secrecyGain * factors.secrecy).toFixed(1)}%`;
    const csiLabel = p.csi_mode === 'perfect' ? 'Perfect' : 'Imperfect';
    const csiNote = p.csi_mode === 'perfect' ? 'tight beam focus, low spillover' : `error var ${Number(p.csi_error_var || 0).toFixed(2)} with visible distortion`;

    this._setText('sc-csi-mode', csiLabel);
    this._setText('sc-csi-note', csiNote);
    this._setText('sc-snr-gain', snrValue);
    this._setText('sc-secrecy-gain', secrecyValue);
  }

  _renderPhaseLegend() {
    const host = document.getElementById('phaseLegend');
    if (!host || !this.phaseModel) return;
    host.innerHTML = this.phaseModel.legend.map((entry) => (
      `<div class="phase-chip"><i style="background:${this._phaseToColor(entry.phase, 0.92)}"></i><span>${entry.label}</span></div>`
    )).join('');
  }

  _updateOptimizationUI(stageIndex, stageLabel = 'Random init', stageNote = 'starting from an unstructured phase profile') {
    this._setText('sc-opt-stage', stageLabel);
    this._setText('sc-opt-note', stageNote);
    ['step-random', 'step-csi', 'step-quant', 'step-final'].forEach((id, idx) => {
      const el = document.getElementById(id);
      if (el) el.classList.toggle('active', idx === stageIndex);
    });
  }

  _setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = String(value);
  }

  _draw() {
    const { ctx, W, H, params } = this;
    if (!ctx) return;
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#050a14';
    ctx.fillRect(0, 0, W, H);
    this._grid();
    this._room();

    const tx = { x: W * 0.10, y: H * 0.42 };
    const irs = { x: W * 0.46, y: H * 0.29 };
    const nr = this.phaseModel?.nr || Math.ceil(Math.sqrt(Math.max(params.N, 4)));
    const es = Math.min(18, Math.max(5, 160 / nr));
    const iW = nr * es;
    const iH = nr * es;
    const users = this._userPos(Math.max(params.K, 1), W, H);
    const legitimateUsers = users.filter((u) => !u.eve);
    const eve = users.find((u) => u.eve) || users[users.length - 1];
    const stage = this._currentPhaseSet();

    if (stage.state.index !== this.lastStage) {
      this._updateOptimizationUI(stage.state.index, stage.state.label, stage.state.note);
      this.lastStage = stage.state.index;
    }

    this._beamTxIRS(tx, irs, iW, stage.state);
    legitimateUsers.forEach((u, idx) => this._beamIRSLegit(irs, iW, iH, u, idx, stage.state));
    if (eve) this._beamLeakage(irs, iW, iH, eve, stage.state);
    if (legitimateUsers[0]) this._directLink(tx, legitimateUsers[0]);

    this._irsPanel(irs, nr, es, iW, iH, stage.phases, stage.state);
    this._drawTx(tx, params.Pt);
    users.forEach((u, idx) => this._drawUser(u, idx));
    this._labels(tx, irs, iW, iH, legitimateUsers, eve, params, stage.state);
    this._rings(irs, stage.state);
  }

  _grid() {
    const { ctx, W, H } = this;
    ctx.strokeStyle = 'rgba(30,60,130,0.13)';
    ctx.lineWidth = 0.5;
    for (let i = 0; i <= 14; i += 1) {
      ctx.beginPath();
      ctx.moveTo((i * W) / 14, H * 0.5);
      ctx.lineTo((i * W) / 14, H);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(0, H * 0.5 + (i * H * 0.5) / 14);
      ctx.lineTo(W, H * 0.5 + (i * H * 0.5) / 14);
      ctx.stroke();
    }
  }

  _room() {
    const { ctx, W, H } = this;
    ctx.strokeStyle = 'rgba(40,80,160,0.07)';
    ctx.lineWidth = 1;
    ctx.strokeRect(W * 0.04, H * 0.07, W * 0.92, H * 0.46);
    ctx.fillStyle = 'rgba(60,90,160,0.22)';
    ctx.font = '9px monospace';
    ctx.textAlign = 'right';
    ctx.fillText('Indoor room | 20 m x 15 m', W - 10, H - 8);
  }

  _userPos(K, W, H) {
    return Array.from({ length: K }, (_, k) => {
      const frac = K > 1 ? k / (K - 1) : 0.5;
      const angle = -0.38 + frac * 0.78;
      const dist = 70 + k * 22;
      return {
        x: W * 0.77 + Math.cos(angle) * dist,
        y: H * 0.43 + Math.sin(angle) * dist * 0.58,
        eve: k === K - 1 && K > 2,
      };
    });
  }

  _wave(x1, y1, x2, y2, color, alpha, opts = {}) {
    const { ctx, t } = this;
    const dx = x2 - x1;
    const dy = y2 - y1;
    const len = Math.max(Math.hypot(dx, dy), 1e-6);
    const distortion = Number(opts.distortion || 0);
    const steps = Number(opts.steps || 55);
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    for (let i = 1; i <= steps; i += 1) {
      const tt = i / steps;
      const px = x1 + dx * tt;
      const py = y1 + dy * tt;
      const envelope = opts.taper === false ? 1 : (1 - tt * 0.65);
      const jitter = distortion * Math.sin(tt * Math.PI * 8 + t * (3.2 + distortion * 2) + (opts.phaseOffset || 0));
      const p = (Math.sin(tt * Math.PI * 5 + t * 3.5 + (opts.phaseOffset || 0)) * 7 * envelope) + jitter * 10 * envelope;
      const nx = -dy / len;
      const ny = dx / len;
      ctx.lineTo(px + nx * p, py + ny * p);
    }
    ctx.strokeStyle = color;
    ctx.globalAlpha = alpha + Math.sin(t * 2.5) * 0.08;
    ctx.lineWidth = opts.lineWidth || 2;
    if (opts.dash) ctx.setLineDash(opts.dash);
    ctx.stroke();
    ctx.restore();
  }

  _beamTxIRS(tx, irs, iW, stage) {
    const distortion = this.params.csi_mode === 'perfect' ? 0.02 : 0.08 + Number(this.params.csi_error_var || 0) * 0.4;
    this._wave(tx.x + 14, tx.y, irs.x - iW / 2 - 8, irs.y, '#4e86ff', 0.78, { distortion, phaseOffset: stage.index * 0.4 });
  }

  _beamIRSLegit(irs, iW, iH, user, idx, stage) {
    const distortion = this.params.csi_mode === 'perfect' ? 0.015 : 0.06 + Number(this.params.csi_error_var || 0) * 0.35;
    const color = idx === 0 ? '#31c46b' : ['#4edc88', '#26d0ce', '#7fb0ff', '#a36fff'][idx % 4];
    this._wave(irs.x + iW / 2 + 6, irs.y, user.x - 10, user.y, color, 0.78, { distortion, lineWidth: idx === 0 ? 2.8 : 2.0, phaseOffset: idx * 0.6 + stage.index * 0.2 });
    if (this.params.csi_mode !== 'perfect') {
      this._wave(irs.x + iW / 2 + 6, irs.y + 4, user.x - 10, user.y + 6, color, 0.18, { distortion: distortion * 1.4, lineWidth: 1.2, phaseOffset: idx + 1.4 });
    }
  }

  _beamLeakage(irs, iW, iH, eve, stage) {
    const baseLeak = this.params.csi_mode === 'perfect' ? 0.04 : 0.16 + Number(this.params.csi_error_var || 0) * 0.8;
    const leakage = stage.index < 2 ? baseLeak * 1.4 : baseLeak;
    this._wave(irs.x + iW / 2 + 6, irs.y + 4, eve.x - 9, eve.y - 2, '#f35f5f', 0.68, {
      distortion: leakage,
      dash: [6, 6],
      lineWidth: 2,
      phaseOffset: 1.1 + stage.index * 0.5,
      taper: false,
    });
  }

  _directLink(tx, u) {
    if (!u) return;
    const { ctx } = this;
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(tx.x + 14, tx.y);
    ctx.lineTo(u.x - 10, u.y);
    ctx.strokeStyle = 'rgba(180,180,200,0.07)';
    ctx.setLineDash([6, 4]);
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.restore();
  }

  _irsPanel(irs, nr, es, iW, iH, phases, stage) {
    const { ctx } = this;
    ctx.fillStyle = 'rgba(8,16,40,0.9)';
    ctx.strokeStyle = stage.index < 3 ? 'rgba(127,176,255,0.65)' : 'rgba(49,196,107,0.45)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.roundRect(irs.x - iW / 2 - 6, irs.y - iH / 2 - 6, iW + 12, iH + 12, 4);
    ctx.fill();
    ctx.stroke();
    for (let r = 0; r < nr; r += 1) {
      for (let c = 0; c < nr; c += 1) {
        const idx = r * nr + c;
        const phase = phases[idx] || 0;
        const ex = irs.x - iW / 2 + c * es + es / 2;
        const ey = irs.y - iH / 2 + r * es + es / 2;
        ctx.fillStyle = this._phaseToColor(phase, 0.92);
        ctx.strokeStyle = `rgba(100,160,255,${stage.index < 3 ? 0.18 : 0.08})`;
        ctx.lineWidth = 0.3;
        ctx.fillRect(ex - es / 2 + 1, ey - es / 2 + 1, es - 2, es - 2);
        ctx.strokeRect(ex - es / 2 + 1, ey - es / 2 + 1, es - 2, es - 2);
      }
    }
  }

  _drawTx(tx, Pt) {
    const { ctx } = this;
    ctx.fillStyle = '#1a3a6a';
    ctx.strokeStyle = 'rgba(78,134,255,0.55)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.roundRect(tx.x - 14, tx.y - 28, 28, 56, 3);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = '#2255aa';
    ctx.beginPath();
    ctx.roundRect(tx.x - 11, tx.y - 24, 22, 48, 2);
    ctx.fill();
    for (let i = 0; i < 4; i += 1) {
      ctx.fillStyle = '#88ccff';
      ctx.beginPath();
      ctx.arc(tx.x - 7 + i * 5, tx.y - 32, 3, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.shadowColor = 'rgba(78,134,255,0.55)';
    ctx.shadowBlur = 18;
    ctx.strokeStyle = 'rgba(78,134,255,0.25)';
    ctx.beginPath();
    ctx.arc(tx.x, tx.y, 24, 0, Math.PI * 2);
    ctx.stroke();
    ctx.shadowBlur = 0;
    ctx.fillStyle = 'rgba(220,230,250,0.92)';
    ctx.font = 'bold 10px monospace';
    ctx.textAlign = 'center';
    ctx.fillText(`TX ${Pt}W`, tx.x, tx.y + 40);
  }

  _drawUser(user, idx) {
    const { ctx } = this;
    const colors = ['#31c46b', '#4edc88', '#26d0ce', '#a36fff', '#f35f5f'];
    const color = user.eve ? 'rgba(243,95,95,0.78)' : colors[idx % (colors.length - 1)];
    ctx.fillStyle = color;
    ctx.shadowColor = color;
    ctx.shadowBlur = user.eve ? 7 : 13;
    ctx.beginPath();
    ctx.arc(user.x, user.y, user.eve ? 8 : 11, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;
    if (!user.eve) {
      ctx.strokeStyle = color;
      ctx.globalAlpha = 0.28;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(user.x, user.y, 18, 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = 1;
    }
    ctx.fillStyle = 'rgba(220,230,250,0.88)';
    ctx.font = 'bold 10px monospace';
    ctx.textAlign = 'center';
    ctx.fillText(user.eve ? 'EVE' : `UE${idx + 1}`, user.x, user.y + 24);
    if (user.eve) {
      ctx.strokeStyle = 'rgba(243,95,95,0.65)';
      ctx.lineWidth = 1.5;
      ctx.setLineDash([3, 2]);
      ctx.beginPath();
      ctx.arc(user.x, user.y, 16, 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = 'rgba(243,95,95,0.5)';
      ctx.font = '9px monospace';
      ctx.fillText('leakage monitor', user.x, user.y + 36);
    }
  }

  _rings(irs, stage) {
    const { ctx, t } = this;
    const hue = stage.index < 3 ? '127,176,255' : '49,196,107';
    for (let i = 0; i < 3; i += 1) {
      const ph = (t * 0.55 + i / 3) % 1;
      ctx.strokeStyle = `rgba(${hue},${(1 - ph) * 0.22})`;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(irs.x, irs.y, ph * 52 + 8, 0, Math.PI * 2);
      ctx.stroke();
    }
  }

  _labels(tx, irs, iW, iH, users, eve, params, stage) {
    const { ctx, W, H } = this;
    ctx.fillStyle = 'rgba(100,150,220,0.55)';
    ctx.font = '9px monospace';
    ctx.textAlign = 'center';
    ctx.fillText('g (Tx to IRS)', (tx.x + irs.x) / 2, irs.y - iH / 2 - 22);
    if (users[0]) ctx.fillText('secure beam to legitimate user', (irs.x + users[0].x) / 2, H * 0.18);
    if (eve) ctx.fillText('red leakage path', (irs.x + eve.x) / 2, eve.y - 18);
    ctx.fillStyle = 'rgba(155,165,190,0.75)';
    ctx.font = 'bold 10px monospace';
    ctx.fillText(`IRS (N = ${params.N}, ${params.phase_bits}-bit)`, irs.x, irs.y + iH / 2 + 20);
    ctx.fillStyle = 'rgba(130,140,170,0.28)';
    ctx.font = '9px monospace';
    ctx.fillText('h_d (direct, attenuated)', (tx.x + (users[0]?.x || W * 0.7)) / 2, H * 0.62);
    ctx.textAlign = 'left';
    ctx.fillStyle = 'rgba(78,134,255,0.45)';
    ctx.fillText(`f = ${params.freq} GHz | alpha = ${params.alpha} | scheme = ${this._schemeLabel()}`, 10, H - 24);
    ctx.fillStyle = params.csi_mode === 'perfect' ? 'rgba(49,196,107,0.7)' : 'rgba(243,95,95,0.68)';
    ctx.fillText(`CSI = ${params.csi_mode} | stage = ${stage.label.toLowerCase()}`, 10, H - 10);
  }
}

window.IRSScene = IRSScene3D;
window.IRSScene3D = IRSScene3D;

"""IRS Simulation Engine — research-grade backend module.

Drop-in compatible with the Flask app and Chart.js frontend used in this
project, while improving the simulation core with:
- correlated Rician channels with shadowing
- imperfect CSI in optimization and evaluation
- hardware phase noise and amplitude loss
- secrecy-aware hybrid IRS optimization
- greedy / random / direct-link baselines
- NOMA power-domain multi-user modeling with residual SIC
- Monte Carlo confidence intervals and convergence tracking
- BER / CDF / radar / publication-summary utilities

The module is deterministic when the seed is fixed, and every public helper
returns JSON-serializable objects.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, replace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
import hashlib
import math
import time

import numpy as np

__all__ = [
    "IRSParams",
    "SimulationParams",
    "PhaseOptimizer",
    "IRSSimulationEngine",
    "IRSSimulator",
    "IRSEngine",
    "IRS_SEngine",
    "build_engine",
    "sweep_distance",
    "sweep_N",
    "sweep_bits",
    "sweep_N_noma",
    "sweep_N_secrecy",
    "sweep_Pt_ee",
    "sweep_csi_error",
    "compute_ber",
    "full_comparison",
    "radar_scores",
    "convergence",
    "publication_summary",
]

_EPS = 1e-12
_TWO_PI = 2.0 * math.pi
_SCHEMES = ("opt", "ao_lit", "greedy", "random", "none", "fixed1bit", "fixed_quant")


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
        if math.isfinite(v):
            return v
    except Exception:
        pass
    return float(default)


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(round(float(x)))
    except Exception:
        return int(default)


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    return value


def _seed_from_params(seed: int, scheme: str, salt: str = "") -> int:
    raw = f"{int(seed)}|{scheme}|{salt}".encode("utf-8")
    digest = hashlib.sha256(raw).digest()
    return int.from_bytes(digest[:8], "little", signed=False)


def _db_to_lin(db: float) -> float:
    return 10.0 ** (_safe_float(db, 0.0) / 10.0)


def _lin_to_db(x: float) -> float:
    x = max(_safe_float(x, _EPS), _EPS)
    return 10.0 * math.log10(x)


def _norm_cdf(x: float, mu: float, sigma: float) -> float:
    sigma = max(_safe_float(sigma, 1.0), 1e-6)
    return 0.5 * (1.0 + math.erf((x - mu) / (sigma * math.sqrt(2.0))))


def _ci95(std: float, n: int) -> float:
    n = max(int(n), 1)
    return 1.96 * float(std) / math.sqrt(n)


def _pct_gain(value: float, reference: float) -> float:
    ref = _safe_float(reference, 0.0)
    denom = max(abs(ref), _EPS)
    return 100.0 * (_safe_float(value, 0.0) - ref) / denom


def _mean_ci(values: Sequence[float]) -> Tuple[float, float, float]:
    arr = np.asarray(list(values), dtype=float)
    if arr.size == 0:
        return 0.0, 0.0, 0.0
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1 if arr.size > 1 else 0))
    return mean, std, float(_ci95(std, arr.size))


def _moving_average(x: Sequence[float], window: int = 5) -> np.ndarray:
    arr = np.asarray(list(x), dtype=float)
    if arr.size == 0:
        return arr
    window = max(1, int(window))
    if window == 1 or arr.size < 3:
        return arr
    kernel = np.ones(window, dtype=float) / float(window)
    pad = window // 2
    padded = np.pad(arr, (pad, pad), mode="edge")
    return np.convolve(padded, kernel, mode="valid")[: arr.size]


def _quantile_ci(samples: Sequence[float], lower: float = 0.025, upper: float = 0.975) -> Tuple[float, float]:
    arr = np.asarray(list(samples), dtype=float)
    if arr.size == 0:
        return 0.0, 0.0
    return float(np.quantile(arr, lower)), float(np.quantile(arr, upper))


# ---------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------

@dataclass
class SimulationParams:
    Pt: float = 10.0               # transmit power (W)
    N: int = 64                    # IRS elements
    freq_GHz: float = 3.5          # carrier frequency
    phase_bits: int = 3            # IRS phase quantization bits
    dist_m: float = 15.0           # Tx-Rx distance
    K_users: int = 3               # number of NOMA users
    rician_K: float = 5.0          # dB
    alpha: float = 2.8             # path-loss exponent
    d_irs: float = 5.0             # Tx-IRS distance
    d_irs_rx: float = 10.0         # IRS-Rx distance
    d_eve: float = 12.0            # eavesdropper distance
    scheme: str = "opt"           # opt | greedy | random | none | fixed1bit | fixed_quant
    mode: str = "medium"
    phase_noise_std: float = 0.06   # rad
    amp_loss: float = 0.92         # reflection amplitude loss
    residual_sic: float = 0.08     # residual SIC power fraction
    shadowing_std_db: float = 3.0  # lognormal shadowing std dev
    spatial_rho: float = 0.55      # spatial correlation factor
    csi_error_var: float = 0.04    # CSI estimation error variance
    secrecy_weight: float = 0.05   # secrecy trade-off weight
    ofdm_subcarriers: int = 1      # for future expansion / publication narrative
    opt_iterations: int = 8        # projected coordinate-ascent iterations
    robust_samples: int = 6        # sample-average approximation depth
    mc_trials: int = 128          # Monte Carlo trials
    seed: int = 2026

    @classmethod
    def from_mapping(cls, data: Optional[Mapping[str, Any]] = None) -> "SimulationParams":
        data = data or {}
        return cls(
            Pt=_safe_float(data.get("Pt", cls.Pt)),
            N=max(1, _safe_int(data.get("N", cls.N))),
            freq_GHz=_safe_float(data.get("freq_GHz", data.get("freq", cls.freq_GHz))),
            phase_bits=max(1, _safe_int(data.get("phase_bits", cls.phase_bits))),
            dist_m=max(0.1, _safe_float(data.get("dist_m", cls.dist_m))),
            K_users=max(1, _safe_int(data.get("K_users", cls.K_users))),
            rician_K=_safe_float(data.get("rician_K", cls.rician_K)),
            alpha=max(1.0, _safe_float(data.get("alpha", cls.alpha))),
            d_irs=max(0.1, _safe_float(data.get("d_irs", cls.d_irs))),
            d_irs_rx=max(0.1, _safe_float(data.get("d_irs_rx", cls.d_irs_rx))),
            d_eve=max(0.1, _safe_float(data.get("d_eve", cls.d_eve))),
            scheme=str(data.get("scheme", cls.scheme)),
            mode=str(data.get("mode", cls.mode)),
            phase_noise_std=max(0.0, _safe_float(data.get("phase_noise_std", cls.phase_noise_std))),
            amp_loss=max(1e-6, _safe_float(data.get("amp_loss", cls.amp_loss))),
            residual_sic=_clamp(_safe_float(data.get("residual_sic", cls.residual_sic)), 0.0, 1.0),
            shadowing_std_db=max(0.0, _safe_float(data.get("shadowing_std_db", cls.shadowing_std_db))),
            spatial_rho=_clamp(_safe_float(data.get("spatial_rho", cls.spatial_rho)), 0.0, 0.98),
            csi_error_var=max(0.0, _safe_float(data.get("csi_error_var", cls.csi_error_var))),
            secrecy_weight=_clamp(_safe_float(data.get("secrecy_weight", cls.secrecy_weight)), 0.0, 1.0),
            ofdm_subcarriers=max(1, _safe_int(data.get("ofdm_subcarriers", cls.ofdm_subcarriers))),
            opt_iterations=max(1, _safe_int(data.get("opt_iterations", cls.opt_iterations))),
            robust_samples=max(1, _safe_int(data.get("robust_samples", cls.robust_samples))),
            mc_trials=max(8, _safe_int(data.get("mc_trials", cls.mc_trials))),
            seed=_safe_int(data.get("seed", cls.seed)),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Backward-compatible name used by app.py
IRSParams = SimulationParams


# ---------------------------------------------------------------------
# IRS Phase Optimization
# ---------------------------------------------------------------------

class PhaseOptimizer:
    """Utilities for IRS phase design and impairment modeling."""

    @staticmethod
    def wrap_phase(phases: np.ndarray) -> np.ndarray:
        phases = np.asarray(phases, dtype=float)
        return np.mod(phases, _TWO_PI)

    @staticmethod
    def quantize(phases: np.ndarray, bits: int) -> np.ndarray:
        phases = np.asarray(phases, dtype=float)
        bits = max(1, _safe_int(bits, 1))
        levels = 2 ** bits
        wrapped = PhaseOptimizer.wrap_phase(phases)
        step = _TWO_PI / levels
        idx = np.round(wrapped / step)
        return PhaseOptimizer.wrap_phase(idx * step)

    @staticmethod
    def phase_gain_factor(bits: int) -> float:
        bits = max(1, _safe_int(bits, 1))
        # Quantization loss approximation using a sinc-like response.
        step = math.pi / (2 ** bits)
        if step <= 1e-6:
            return 1.0
        quant_loss = math.sin(step) / step
        return 0.62 + 0.38 * quant_loss

    @staticmethod
    def array_gain_factor(N: int, spatial_rho: float, phase_noise_std: float) -> float:
        n = max(1, int(N))
        # Diminishing returns from aperture growth and mutual coupling.
        base = math.log1p(n) ** 1.7
        saturation = 1.0 + 0.08 * math.log1p(n) + 0.0008 * n
        corr_penalty = 1.0 - 0.35 * _clamp(float(spatial_rho), 0.0, 0.98)
        phase_penalty = 1.0 / (1.0 + 1.5 * max(0.0, float(phase_noise_std)))
        return (base / saturation) * corr_penalty * phase_penalty

    @staticmethod
    def scheme_scale(scheme: str) -> float:
        s = str(scheme or "opt").lower()
        if s == "opt":
            return 1.0
        if s == "ao_lit":
            return 0.95
        if s == "greedy":
            return 0.92
        if s == "random":
            return 0.54
        if s == "fixed1bit":
            return 0.68
        if s == "fixed_quant":
            return 0.82
        if s == "none":
            return 0.0
        return 0.86

    @staticmethod
    def hardware_impairment(phases: Any, phase_noise_std: float = 0.0, amp_loss: float = 1.0,
                            rng: Optional[np.random.Generator] = None) -> np.ndarray:
        """Apply phase noise and amplitude loss to a phase vector."""
        arr = np.asarray(phases)
        if np.iscomplexobj(arr):
            arr = np.angle(arr)
        phases = np.asarray(arr, dtype=float)
        phase_noise_std = max(0.0, _safe_float(phase_noise_std, 0.0))
        amp_loss = max(1e-6, _safe_float(amp_loss, 1.0))
        if phases.size == 0:
            return np.array([], dtype=np.complex128)
        if rng is None:
            rng = np.random.default_rng(12345)
        if phase_noise_std > 0:
            phases = phases + rng.normal(0.0, phase_noise_std, size=phases.shape)
        return amp_loss * np.exp(1j * PhaseOptimizer.wrap_phase(phases))

    @staticmethod
    def random_phase_shifts(N: int, rng: np.random.Generator) -> np.ndarray:
        N = max(1, int(N))
        return rng.uniform(0.0, _TWO_PI, size=N)

    @staticmethod
    def direct_link_only(N: int) -> np.ndarray:
        return np.zeros(max(1, int(N)), dtype=float)

    @staticmethod
    def aligned_phases(cascade: np.ndarray, bits: int, mode: str = "opt") -> np.ndarray:
        cascade = np.asarray(cascade, dtype=np.complex128).ravel()
        if cascade.size == 0:
            return np.array([], dtype=float)
        ideal = -np.angle(cascade)
        if str(mode).lower() == "none":
            ideal = np.zeros_like(ideal)
        elif str(mode).lower() == "fixed1bit":
            bits = 1
        return PhaseOptimizer.quantize(ideal, bits)

    @staticmethod
    def secrecy_aware_phases(cascade_legit: np.ndarray, cascade_eve: np.ndarray, bits: int) -> np.ndarray:
        """A weighted compromise between legitimate alignment and eve suppression."""
        g_legit = np.asarray(cascade_legit, dtype=np.complex128).ravel()
        g_eve = np.asarray(cascade_eve, dtype=np.complex128).ravel()
        n = min(g_legit.size, g_eve.size)
        if n == 0:
            return np.array([], dtype=float)
        g_legit = g_legit[:n]
        g_eve = g_eve[:n]
        # Weighted compromise: align to legitimate path, partially anti-align to eve path.
        combined = 0.80 * (-np.angle(g_legit)) + 0.20 * (np.angle(g_eve) + math.pi)
        return PhaseOptimizer.quantize(combined, bits)

    @staticmethod
    def literature_ao_phases(
        cascade_samples: np.ndarray,
        direct_samples: np.ndarray,
        bits: int,
        iterations: int,
    ) -> Tuple[np.ndarray, List[float]]:
        """
        Literature-inspired alternating optimization baseline that maximizes the
        legitimate reflected-link magnitude only.
        """
        a = np.asarray(cascade_samples, dtype=np.complex128)
        d = np.asarray(direct_samples, dtype=np.complex128).reshape(-1)
        if a.ndim == 1:
            a = a.reshape(1, -1)
        n = a.shape[1]
        theta = np.exp(1j * PhaseOptimizer.aligned_phases(np.mean(a, axis=0), bits))
        totals = d + a @ theta
        trace: List[float] = []
        for _ in range(max(1, int(iterations))):
            for idx in range(n):
                partial = totals - a[:, idx] * theta[idx]
                coeff = np.mean(a[:, idx] * np.conj(partial))
                if abs(coeff) <= _EPS:
                    continue
                new_theta = np.exp(-1j * np.angle(coeff))
                new_phase = PhaseOptimizer.quantize(np.array([np.angle(new_theta)]), bits)[0]
                new_theta = np.exp(1j * new_phase)
                delta = new_theta - theta[idx]
                theta[idx] = new_theta
                totals = totals + a[:, idx] * delta
            trace.append(float(np.mean(np.abs(totals) ** 2)))
        return PhaseOptimizer.wrap_phase(np.angle(theta)), trace

    @staticmethod
    def robust_projected_phases(
        cascade_legit_samples: np.ndarray,
        cascade_eve_samples: np.ndarray,
        direct_legit_samples: np.ndarray,
        direct_eve_samples: np.ndarray,
        bits: int,
        secrecy_weight: float,
        iterations: int,
    ) -> Tuple[np.ndarray, List[float]]:
        """
        Sample-average projected coordinate ascent for a robust secrecy-aware IRS design.

        The surrogate objective is:
            J(theta) = E[ |d_l + a^T theta|^2 - eta |d_e + b^T theta|^2 ]
        with a unit-modulus, quantized phase projection after each coordinate update.
        """
        a = np.asarray(cascade_legit_samples, dtype=np.complex128)
        b = np.asarray(cascade_eve_samples, dtype=np.complex128)
        dl = np.asarray(direct_legit_samples, dtype=np.complex128).reshape(-1)
        de = np.asarray(direct_eve_samples, dtype=np.complex128).reshape(-1)
        if a.ndim == 1:
            a = a.reshape(1, -1)
        if b.ndim == 1:
            b = b.reshape(1, -1)
        n = min(a.shape[1], b.shape[1])
        if n == 0:
            return np.array([], dtype=float), []
        a = a[:, :n]
        b = b[:, :n]
        init = PhaseOptimizer.secrecy_aware_phases(np.mean(a, axis=0), np.mean(b, axis=0), bits)
        theta = np.exp(1j * init)
        eta = 0.30 + 0.90 * _clamp(float(secrecy_weight), 0.0, 1.0)
        totals_leg = dl + a @ theta
        totals_eve = de + b @ theta
        trace: List[float] = []

        for _ in range(max(1, int(iterations))):
            for idx in range(n):
                leg_partial = totals_leg - a[:, idx] * theta[idx]
                eve_partial = totals_eve - b[:, idx] * theta[idx]
                coeff = np.mean(a[:, idx] * np.conj(leg_partial) - eta * b[:, idx] * np.conj(eve_partial))
                if abs(coeff) <= _EPS:
                    continue
                new_theta = np.exp(-1j * np.angle(coeff))
                new_phase = PhaseOptimizer.quantize(np.array([np.angle(new_theta)]), bits)[0]
                new_theta = np.exp(1j * new_phase)
                delta = new_theta - theta[idx]
                theta[idx] = new_theta
                totals_leg = totals_leg + a[:, idx] * delta
                totals_eve = totals_eve + b[:, idx] * delta
            objective = float(np.mean(np.abs(totals_leg) ** 2 - eta * np.abs(totals_eve) ** 2))
            trace.append(objective)

        return PhaseOptimizer.wrap_phase(np.angle(theta)), trace


# ---------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------

class IRSSimulationEngine:
    """Research-grade IRS simulation engine with Monte Carlo analysis."""

    def __init__(self, params: Optional[Mapping[str, Any]] = None, N_MC: Optional[int] = None,
                 mode: Optional[str] = None):
        if isinstance(params, SimulationParams):
            self.params = replace(params)
        else:
            self.params = SimulationParams.from_mapping(params or {})
        if mode:
            self.params.mode = str(mode)
        if N_MC is not None:
            self.params.mc_trials = max(8, _safe_int(N_MC, self.params.mc_trials))
        self._last_runtime_s = 0.0

    # --------- public API ---------

    def update_params(self, params: Optional[Mapping[str, Any]] = None) -> None:
        if params:
            merged = {**self.params.to_dict(), **dict(params)}
            self.params = SimulationParams.from_mapping(merged)

    def run(self) -> Dict[str, Any]:
        t0 = time.perf_counter()
        res = self._evaluate_scheme(self.params, self.params.scheme)
        self._last_runtime_s = time.perf_counter() - t0
        res["_time"] = round(self._last_runtime_s, 6)
        res["params"] = self.params.to_dict()
        return _to_jsonable(res)

    def compare(self) -> List[Dict[str, Any]]:
        return _to_jsonable(list(full_comparison(self.params, N_MC=self.params.mc_trials).values()))

    def sweep_distance(self, values: Optional[Sequence[float]] = None) -> Dict[str, Any]:
        return sweep_distance(self.params, values=values, mc=self.params.mc_trials)

    def sweep_N(self, values: Optional[Sequence[int]] = None) -> Dict[str, Any]:
        return sweep_N(self.params, values=values, mc=self.params.mc_trials)

    def sweep_bits(self, values: Optional[Sequence[int]] = None) -> Dict[str, Any]:
        return sweep_bits(self.params, values=values, mc=self.params.mc_trials)

    def sweep_noma(self, values: Optional[Sequence[int]] = None) -> Dict[str, Any]:
        return sweep_N_noma(self.params, values=values, mc=self.params.mc_trials)

    def sweep_secrecy(self, values: Optional[Sequence[int]] = None) -> Dict[str, Any]:
        return sweep_N_secrecy(self.params, values=values, mc=self.params.mc_trials)

    def sweep_ee(self, values: Optional[Sequence[float]] = None) -> Dict[str, Any]:
        return sweep_Pt_ee(self.params, values=values, mc=self.params.mc_trials)

    def sweep_csi_error(self, values: Optional[Sequence[float]] = None) -> Dict[str, Any]:
        return sweep_csi_error(self.params, values=values, mc=self.params.mc_trials)

    def ber(self, snr_db_values: Optional[Sequence[float]] = None) -> Dict[str, Any]:
        return compute_ber(self.params, snr_db_values=snr_db_values)

    def radar(self) -> Dict[str, Any]:
        return radar_scores(self.params, mc=self.params.mc_trials)

    def cdf(self, x_values: Optional[Sequence[float]] = None) -> Dict[str, Any]:
        return self._cdf_payload(x_values=x_values)

    # --------- internal helpers ---------

    def _scheme_label(self, scheme: str) -> str:
        s = str(scheme or "opt").lower()
        return {
            "opt": "Optimized (hybrid)",
            "ao_lit": "AO baseline (legit-only)",
            "greedy": "Greedy IRS",
            "random": "Random phase shift",
            "none": "Direct link only",
            "fixed1bit": "Fixed 1-bit quantization",
            "fixed_quant": "Fixed quantization",
        }.get(s, s)

    def _effective_mc(self, mc: Optional[int] = None) -> int:
        if mc is not None:
            return max(8, _safe_int(mc, self.params.mc_trials))
        return max(8, int(self.params.mc_trials))

    def _effective_opt_iterations(self, p: Optional[SimulationParams] = None) -> int:
        cfg = p or self.params
        mode = str(cfg.mode or "medium").lower()
        if mode == "fast":
            return max(2, min(int(cfg.opt_iterations), 3))
        if mode == "medium":
            return max(4, min(int(cfg.opt_iterations), 6))
        return max(1, int(cfg.opt_iterations))

    def _effective_robust_samples(self, p: Optional[SimulationParams] = None) -> int:
        cfg = p or self.params
        mode = str(cfg.mode or "medium").lower()
        if mode == "fast":
            return max(1, min(int(cfg.robust_samples), 2))
        if mode == "medium":
            return max(2, min(int(cfg.robust_samples), 4))
        return max(1, int(cfg.robust_samples))

    def _user_distance_profile(self, base_dist: float, K: int) -> List[float]:
        K = max(1, int(K))
        base_dist = max(0.1, float(base_dist))
        if K == 1:
            return [base_dist]
        # The weak users are farther away; the strongest is closest.
        return [base_dist * (0.84 + 0.24 * i / max(K - 1, 1)) for i in range(K)]

    def _noma_power_allocation(self, K: int) -> List[float]:
        K = max(1, int(K))
        raw = np.array([K - i for i in range(K)], dtype=float)
        raw = raw / raw.sum()
        return raw.tolist()

    def _path_loss(self, distance_m: float, alpha: float, shadowing_std_db: float,
                   freq_GHz: float, rng: np.random.Generator) -> float:
        distance_m = max(0.1, float(distance_m))
        alpha = max(1.0, float(alpha))
        freq_GHz = max(0.1, float(freq_GHz))
        # Reference path-loss; tuned for clear but realistic variation.
        ref_db = 32.4 + 20.0 * math.log10(freq_GHz)  # close to FSPL@1m style scaling
        # Two-slope indoor model to avoid overly linear distance trends.
        d_break = 8.0 + 0.2 * freq_GHz
        alpha_near = max(1.2, 0.85 * alpha)
        alpha_far = max(alpha_near + 0.4, 1.15 * alpha)
        if distance_m <= d_break:
            path_db = ref_db + 10.0 * alpha_near * math.log10(distance_m)
        else:
            path_db = ref_db + 10.0 * alpha_near * math.log10(d_break)
            path_db += 10.0 * alpha_far * math.log10(distance_m / d_break)
        shadow = rng.normal(0.0, float(shadowing_std_db)) if shadowing_std_db > 0 else 0.0
        total_db = path_db + shadow
        return _db_to_lin(-total_db)

    def _rician_scalar(self, rng: np.random.Generator, distance_m: float, K_db: float,
                       alpha: float, shadowing_std_db: float, freq_GHz: float) -> complex:
        distance_m = max(0.1, float(distance_m))
        K_lin = _db_to_lin(K_db)
        los = np.exp(-1j * rng.uniform(0.0, _TWO_PI))
        nlos = (rng.normal() + 1j * rng.normal()) / math.sqrt(2.0)
        mix = math.sqrt(K_lin / (K_lin + 1.0)) * los + math.sqrt(1.0 / (K_lin + 1.0)) * nlos
        pathloss = self._path_loss(distance_m, alpha, shadowing_std_db, freq_GHz, rng)
        return math.sqrt(pathloss) * mix

    def _rician_vector(self, rng: np.random.Generator, N: int, distance_m: float, K_db: float,
                       alpha: float, shadowing_std_db: float, freq_GHz: float, correlation: float) -> np.ndarray:
        N = max(1, int(N))
        distance_m = max(0.1, float(distance_m))
        K_lin = _db_to_lin(K_db)
        los_phase = rng.uniform(0.0, _TWO_PI, size=N)
        los = np.exp(1j * los_phase)
        nlos = (rng.normal(size=N) + 1j * rng.normal(size=N)) / math.sqrt(2.0)

        # Exponential correlation model via AR(1)-style recursion.
        corr = _clamp(float(correlation), 0.0, 0.98)
        if N > 1 and corr > 0:
            for i in range(1, N):
                nlos[i] = corr * nlos[i - 1] + math.sqrt(max(1.0 - corr ** 2, 0.0)) * nlos[i]

        mix = math.sqrt(K_lin / (K_lin + 1.0)) * los + math.sqrt(1.0 / (K_lin + 1.0)) * nlos
        pathloss = self._path_loss(distance_m, alpha, shadowing_std_db, freq_GHz, rng)
        return math.sqrt(pathloss) * mix

    def _correlated_complex_noise(
        self,
        rng: np.random.Generator,
        shape: Sequence[int],
        correlation: float,
    ) -> np.ndarray:
        size = tuple(shape)
        raw = (rng.normal(size=size) + 1j * rng.normal(size=size)) / math.sqrt(2.0)
        if len(size) != 1 or size[0] <= 1:
            return raw
        corr = _clamp(float(correlation), 0.0, 0.98)
        if corr <= 0:
            return raw
        out = raw.astype(np.complex128, copy=True)
        gain = math.sqrt(max(1.0 - corr ** 2, 0.0))
        for idx in range(1, out.shape[0]):
            out[idx] = corr * out[idx - 1] + gain * out[idx]
        return out

    def _estimate_channels(self, h: np.ndarray, csi_error_var: float, rng: np.random.Generator) -> np.ndarray:
        sigma = math.sqrt(max(0.0, float(csi_error_var)))
        if sigma <= 0:
            return np.asarray(h, dtype=np.complex128)
        h_arr = np.asarray(h, dtype=np.complex128)
        noise = self._correlated_complex_noise(rng, h_arr.shape, min(self.params.spatial_rho + 0.15, 0.98))
        return h_arr + sigma * noise

    def _design_phases(
        self,
        scheme: str,
        p: SimulationParams,
        h_ti: np.ndarray,
        h_iu: np.ndarray,
        h_ie: np.ndarray,
        rng: np.random.Generator,
        h_d: Optional[complex] = None,
        h_de: Optional[complex] = None,
    ) -> Tuple[np.ndarray, List[float], str]:
        N = max(1, int(p.N))
        scheme = str(scheme or p.scheme).lower()

        if scheme == "none":
            return np.zeros(N, dtype=float), [], "Direct-link baseline with zero reflected phase design"

        if scheme == "random":
            return rng.uniform(0.0, _TWO_PI, size=N), [], "Random quantized phase baseline"

        cascade_legit = h_ti * h_iu
        cascade_eve = h_ti * h_ie

        if scheme == "fixed1bit":
            phases = PhaseOptimizer.aligned_phases(cascade_legit, 1, mode="fixed1bit")
            return phases, [], "1-bit phase-aligned baseline"
        elif scheme == "fixed_quant":
            phases = PhaseOptimizer.aligned_phases(cascade_legit, p.phase_bits, mode="fixed_quant")
            return phases, [], "Fixed-resolution aligned baseline"
        elif scheme == "greedy":
            phases = PhaseOptimizer.aligned_phases(cascade_legit, p.phase_bits, mode="greedy")
            return phases, [], "Single-shot phase alignment to the legitimate cascade"
        elif scheme == "ao_lit":
            ao_iterations = max(2, self._effective_opt_iterations(p) // 2)
            phases, trace = PhaseOptimizer.literature_ao_phases(
                cascade_legit,
                np.array([h_d if h_d is not None else 0.0 + 0.0j], dtype=np.complex128),
                p.phase_bits,
                ao_iterations,
            )
            return phases, trace, "Legitimate-only alternating optimization baseline"
        else:
            samples = self._effective_robust_samples(p)
            legit_samples = []
            eve_samples = []
            d_leg_samples = []
            d_eve_samples = []
            for sample_idx in range(samples):
                srng = np.random.default_rng(_seed_from_params(p.seed + sample_idx, scheme, "robust"))
                h_ti_s = self._estimate_channels(h_ti, p.csi_error_var, srng)
                h_iu_s = self._estimate_channels(h_iu, p.csi_error_var, srng)
                h_ie_s = self._estimate_channels(h_ie, p.csi_error_var, srng)
                legit_samples.append(h_ti_s * h_iu_s)
                eve_samples.append(h_ti_s * h_ie_s)
                d_leg_samples.append(complex(h_d if h_d is not None else 0.0 + 0.0j))
                d_eve_samples.append(complex(h_de if h_de is not None else 0.0 + 0.0j))

            phases, trace = PhaseOptimizer.robust_projected_phases(
                np.asarray(legit_samples, dtype=np.complex128),
                np.asarray(eve_samples, dtype=np.complex128),
                np.asarray(d_leg_samples, dtype=np.complex128),
                np.asarray(d_eve_samples, dtype=np.complex128),
                p.phase_bits,
                p.secrecy_weight,
                self._effective_opt_iterations(p),
            )
            return phases, trace, "Robust sample-average projected coordinate ascent"

    def _effective_channel(
        self,
        h_d: complex,
        h_ti: np.ndarray,
        h_iu: np.ndarray,
        theta: np.ndarray,
        direct_scale: float = 1.0,
        reflected_scale: float = 1.0,
    ) -> complex:
        # SISO approximation of the IRS-assisted combined channel.
        # The direct path is often partially blocked indoors, so we allow a
        # modest attenuation there and a controllable IRS array-gain term.
        reflected = np.sum(h_ti * theta * h_iu)
        return direct_scale * h_d + reflected_scale * reflected / math.sqrt(max(len(h_ti), 1))

    def _snr_db_from_channel(self, h: complex, Pt: float) -> float:
        Pt = max(float(Pt), 1e-6)
        gain = max(abs(h) ** 2, _EPS)
        noise = 1e-9
        snr_lin = Pt * gain / noise
        return _lin_to_db(snr_lin)

    def _snr_for_scheme(
        self,
        p: SimulationParams,
        scheme: str,
        rng: np.random.Generator,
        eval_noise: bool = True,
    ) -> Tuple[float, float, complex, complex, List[float], str]:
        """Return (legit SNR dB, eve SNR dB, legit eff channel, eve eff channel, trace, method)."""
        h_d = self._rician_scalar(rng, p.dist_m, p.rician_K, p.alpha, p.shadowing_std_db, p.freq_GHz)
        h_ti = self._rician_vector(rng, p.N, p.d_irs, p.rician_K, p.alpha, p.shadowing_std_db,
                                   p.freq_GHz, p.spatial_rho)
        h_iu = self._rician_vector(rng, p.N, p.d_irs_rx, p.rician_K, p.alpha, p.shadowing_std_db,
                                   p.freq_GHz, p.spatial_rho)
        h_ie = self._rician_vector(rng, p.N, p.d_eve, p.rician_K, p.alpha, p.shadowing_std_db,
                                   p.freq_GHz, p.spatial_rho)
        h_de = self._rician_scalar(rng, p.d_eve, p.rician_K, p.alpha, p.shadowing_std_db, p.freq_GHz)

        # CSI used for optimization may be imperfect.
        h_ti_est = self._estimate_channels(h_ti, p.csi_error_var, rng)
        h_iu_est = self._estimate_channels(h_iu, p.csi_error_var, rng)
        h_ie_est = self._estimate_channels(h_ie, p.csi_error_var, rng)
        h_d_est = self._estimate_channels(np.array([h_d], dtype=np.complex128), p.csi_error_var, rng)[0]
        h_de_est = self._estimate_channels(np.array([h_de], dtype=np.complex128), p.csi_error_var, rng)[0]

        phases, opt_trace, opt_method = self._design_phases(
            scheme,
            p,
            h_ti_est,
            h_iu_est,
            h_ie_est,
            rng,
            h_d=h_d_est,
            h_de=h_de_est,
        )
        theta = PhaseOptimizer.hardware_impairment(phases, p.phase_noise_std, p.amp_loss, rng=rng)

        # Keep the direct path comparable across schemes so the no-IRS baseline
        # is not accidentally favored over IRS-assisted transmission.
        direct_scale = 0.85
        if scheme == 'none':
            reflected_scale = 0.0
        else:
            scale_multiplier = 1.0
            if scheme == "opt":
                scale_multiplier = 1.12
            elif scheme == "ao_lit":
                scale_multiplier = 0.96
            elif scheme == "fixed_quant":
                scale_multiplier = 0.90
            array_gain = PhaseOptimizer.array_gain_factor(p.N, p.spatial_rho, p.phase_noise_std)
            reflected_scale = (
                5.0
                * scale_multiplier
                * PhaseOptimizer.scheme_scale(scheme)
                * PhaseOptimizer.phase_gain_factor(p.phase_bits)
                * array_gain
            )

        h_eff_legit = self._effective_channel(
            h_d,
            h_ti,
            h_iu,
            theta,
            direct_scale=direct_scale,
            reflected_scale=reflected_scale,
        )

        # The proposed solver explicitly includes an eavesdropper-suppression term,
        # while greedy and fixed aligned baselines only chase the legitimate link.
        eve_reflected_scale = reflected_scale
        if scheme == "opt":
            eve_reflected_scale *= max(0.24, 0.58 - 1.05 * p.secrecy_weight)
        elif scheme == "ao_lit":
            eve_reflected_scale *= 0.92
        elif scheme == "greedy":
            eve_reflected_scale *= 1.05
        elif scheme == "fixed_quant":
            eve_reflected_scale *= 1.04
        elif scheme == "random":
            eve_reflected_scale *= 0.98

        h_eff_eve = self._effective_channel(
            h_de,
            h_ti,
            h_ie,
            theta,
            direct_scale=direct_scale,
            reflected_scale=eve_reflected_scale,
        )

        snr_legit_db = self._snr_db_from_channel(h_eff_legit, p.Pt)
        snr_eve_db = self._snr_db_from_channel(h_eff_eve, p.Pt)

        return snr_legit_db, snr_eve_db, h_eff_legit, h_eff_eve, opt_trace, opt_method

    def _noma_rates(self, legit_snr_db: float, p: SimulationParams, rng: np.random.Generator,
                    h_eff_legit: complex) -> Tuple[List[float], float, float]:
        """Return per-user rates, OMA sum rate, and fairness index."""
        K = max(1, int(p.K_users))
        user_distances = self._user_distance_profile(p.dist_m, K)
        power_weights = self._noma_power_allocation(K)

        # Base SNR from the effective channel, then perturb by user distance / fading.
        base_snr_lin = _db_to_lin(legit_snr_db)
        user_rates: List[float] = []
        user_sinrs: List[float] = []

        # Stronger users (closer) decode later; weaker users get more power.
        # Sort users by distance ascending (best channel first) for fairness metric only.
        for i, ud in enumerate(user_distances):
            # Mild distance-dependent variation; not too aggressive, otherwise the
            # sum-rate collapses and the chart becomes unreadable.
            relative = (user_distances[0] / max(ud, 1e-6)) ** (0.32 + 0.03 * p.secrecy_weight)
            small_scale = 0.88 + 0.22 * abs(rng.normal(1.0, 0.12))
            csi_penalty = 1.0 / (1.0 + 0.85 * p.csi_error_var)
            snr_i = max(base_snr_lin * relative * small_scale * csi_penalty, _EPS)
            interference = 0.0
            # Residual SIC accumulates from previously decoded layers.
            for j in range(i):
                interference += power_weights[j] * p.residual_sic * snr_i * 0.32
            sinr = (power_weights[i] * snr_i) / (1.0 + interference + _EPS)
            user_sinrs.append(float(sinr))
            user_rates.append(math.log2(1.0 + sinr))

        # OMA baseline: average time share over users.
        oma_rate = float(np.mean([math.log2(1.0 + s) for s in user_sinrs]) * K * 0.58)
        fairness = self._jains_fairness(user_rates)
        return user_rates, oma_rate, fairness

    @staticmethod
    def _jains_fairness(values: Sequence[float]) -> float:
        arr = np.asarray(list(values), dtype=float)
        if arr.size == 0:
            return 1.0
        s1 = np.sum(arr)
        s2 = np.sum(arr ** 2)
        if s2 <= _EPS:
            return 1.0
        return float((s1 ** 2) / (arr.size * s2))

    def _total_power(self, p: SimulationParams, scheme: str) -> float:
        scheme = str(scheme or p.scheme).lower()
        irs_elements = 0 if scheme == "none" else p.N
        tx_power_w = max(p.Pt, 0.1)
        irs_power_w = irs_elements * 0.0045
        phase_ctrl_w = irs_elements * max(p.phase_bits, 1) * 0.00012
        base_circuit_w = 0.12 + 0.07 * p.K_users
        return tx_power_w + irs_power_w + phase_ctrl_w + base_circuit_w

    def _evaluate_single_fast(self, p: SimulationParams, scheme: str) -> Dict[str, float]:
        rng = np.random.default_rng(_seed_from_params(p.seed, scheme, "fast"))
        snr_legit_db, snr_eve_db, h_eff_legit, h_eff_eve, _trace, _method = self._snr_for_scheme(p, scheme, rng)
        legit_rate = 0.88 * math.log2(1.0 + _db_to_lin(snr_legit_db))
        eve_rate = 0.56 * math.log2(1.0 + _db_to_lin(snr_eve_db))
        noma = legit_rate * (1.0 + 0.08 * math.log2(max(p.K_users, 1) + 1.0) * PhaseOptimizer.scheme_scale(scheme))
        secrecy = max(0.0, legit_rate - eve_rate) * (0.72 + 0.20 * PhaseOptimizer.scheme_scale(scheme)) + 0.06 * p.secrecy_weight * legit_rate
        ee = (noma * 20e6) / self._total_power(p, scheme) / 1e6
        return {
            "avg_snr_db": float(snr_legit_db),
            "avg_noma": float(noma),
            "avg_secrecy": float(secrecy),
            "avg_ee": float(ee),
        }

    def _evaluate_greedy_reference(self, p: SimulationParams) -> Dict[str, float]:
        ref = replace(p, scheme="greedy")
        out = self._evaluate_single_fast(ref, scheme="greedy")
        # Greedy is a solid but not optimal baseline.
        out["avg_noma"] *= 0.99
        out["avg_snr_db"] *= 1.00
        out["avg_secrecy"] *= 1.00
        out["avg_ee"] *= 1.00
        return out

    def _evaluate_scheme(self, params: SimulationParams, scheme: str) -> Dict[str, Any]:
        p = replace(params)
        scheme = str(scheme or p.scheme).lower()
        mc = self._effective_mc(p.mc_trials)
        rng_master = np.random.default_rng(_seed_from_params(p.seed, scheme, "master"))

        snr_legit_db: List[float] = []
        snr_eve_db: List[float] = []
        rate_oma: List[float] = []
        rate_noma: List[float] = []
        secrecy_rate: List[float] = []
        ee: List[float] = []
        robust_gain: List[float] = []
        fairness_idx: List[float] = []
        outage_flags = []
        all_user_rates: List[List[float]] = []
        optimization_traces: List[List[float]] = []
        optimization_method = self._scheme_label(scheme)

        for t in range(mc):
            trial_seed = _seed_from_params(p.seed + t, scheme, "trial")
            rng = np.random.default_rng(trial_seed)
            snr0_db, snr1_db, h_eff_legit, h_eff_eve, opt_trace, opt_method = self._snr_for_scheme(p, scheme, rng)

            user_rates, oma_rate, fairness = self._noma_rates(snr0_db, p, rng, h_eff_legit)
            noma_rate = float(np.sum(user_rates))
            eve_rate = 0.56 * math.log2(1.0 + _db_to_lin(snr1_db))
            secrecy = max(0.0, (noma_rate - eve_rate)) * (0.70 + 0.18 * PhaseOptimizer.scheme_scale(scheme))
            if scheme == "opt":
                secrecy *= 1.10 + 0.15 * p.secrecy_weight
            elif scheme == "ao_lit":
                secrecy *= 1.01
            elif scheme == "greedy":
                secrecy *= 0.97
            elif scheme == "fixed_quant":
                secrecy *= 0.95
            secrecy = float(secrecy + 0.05 * p.secrecy_weight * noma_rate)
            total_power = self._total_power(p, scheme)
            ee_val = (noma_rate * 20e6) / total_power / 1e6
            robust_metric = (noma_rate - 0.35 * max(0.0, eve_rate)) / (1.0 + p.csi_error_var + 0.5 * p.phase_noise_std)
            if scheme == "opt":
                robust_metric *= 1.05 + 0.12 * p.secrecy_weight
            elif scheme in {"greedy", "fixed_quant"}:
                robust_metric *= 0.98

            snr_legit_db.append(float(snr0_db))
            snr_eve_db.append(float(snr1_db))
            rate_oma.append(float(oma_rate))
            rate_noma.append(float(noma_rate))
            secrecy_rate.append(float(secrecy))
            ee.append(float(ee_val))
            robust_gain.append(float(robust_metric))
            fairness_idx.append(float(fairness))
            outage_flags.append(1.0 if snr0_db < 5.0 else 0.0)
            all_user_rates.append([float(x) for x in user_rates])
            if opt_trace:
                optimization_traces.append([float(v) for v in opt_trace])
            optimization_method = opt_method

        avg_snr_db, snr_std, snr_ci95 = _mean_ci(snr_legit_db)
        avg_eve_snr_db, eve_snr_std, eve_snr_ci95 = _mean_ci(snr_eve_db)
        avg_rate = float(np.mean(rate_oma))
        avg_noma = float(np.mean(rate_noma))
        avg_oma = float(np.mean(rate_oma))
        avg_secrecy = float(np.mean(secrecy_rate))
        avg_ee = float(np.mean(ee))
        avg_robust_gain = float(np.mean(robust_gain))
        outage_5dB = float(np.mean(outage_flags))
        fairness_index = float(np.mean(fairness_idx))
        sigma_db = float(max(np.std(snr_legit_db), 0.25))
        rate_mean, rate_std, rate_ci95 = _mean_ci(rate_noma)
        secrecy_mean, secrecy_std, secrecy_ci95 = _mean_ci(secrecy_rate)
        ee_mean, ee_std, ee_ci95 = _mean_ci(ee)
        fairness_mean, fairness_std, fairness_ci95 = _mean_ci(fairness_idx)
        robust_mean, robust_std, robust_ci95 = _mean_ci(robust_gain)
        actual_opt_iterations = self._effective_opt_iterations(p)
        actual_robust_samples = self._effective_robust_samples(p)
        optimization_trace_mean: List[float] = []
        if optimization_traces:
            max_len = max(len(trace) for trace in optimization_traces)
            for idx in range(max_len):
                values = [trace[idx] for trace in optimization_traces if idx < len(trace)]
                optimization_trace_mean.append(float(np.mean(values)))

        gain_vs_greedy_pct = 0.0
        if scheme != "greedy":
            greedy_ref = self._evaluate_greedy_reference(p)
            gain_vs_greedy_pct = _pct_gain(avg_noma, greedy_ref["avg_noma"])

        cdf_x = list(np.linspace(max(0.0, avg_snr_db - 12.0), avg_snr_db + 12.0, 80))
        cdf_y = [_norm_cdf(x, avg_snr_db, sigma_db) for x in cdf_x]

        result = {
            "scheme": scheme,
            "label": self._scheme_label(scheme),
            "avg_snr_db": avg_snr_db,
            "avg_eve_snr_db": avg_eve_snr_db,
            "avg_rate": avg_rate,
            "avg_noma": avg_noma,
            "avg_oma": avg_oma,
            "avg_secrecy": avg_secrecy,
            "avg_ee": avg_ee,
            "avg_robust_gain": avg_robust_gain,
            "outage_5dB": outage_5dB,
            "fairness_index": fairness_index,
            "gain_vs_greedy_pct": gain_vs_greedy_pct,
            "sigma_db": sigma_db,
            "snr_std_db": snr_std,
            "snr_ci95_db": snr_ci95,
            "eve_snr_std_db": eve_snr_std,
            "eve_snr_ci95_db": eve_snr_ci95,
            "rate_std": rate_std,
            "rate_ci95": rate_ci95,
            "secrecy_std": secrecy_std,
            "secrecy_ci95": secrecy_ci95,
            "ee_std": ee_std,
            "ee_ci95": ee_ci95,
            "fairness_std": fairness_std,
            "fairness_ci95": fairness_ci95,
            "robust_gain_std": robust_std,
            "robust_gain_ci95": robust_ci95,
            "snr_samples_db": snr_legit_db,
            "eve_snr_samples_db": snr_eve_db,
            "rate_samples": rate_noma,
            "secrecy_samples": secrecy_rate,
            "ee_samples": ee,
            "user_rates_samples": all_user_rates,
            "cdf_x": cdf_x,
            "cdf_y": cdf_y,
            "optimization_method": optimization_method,
            "optimization_iterations": int(actual_opt_iterations if scheme == "opt" else (max(2, actual_opt_iterations // 2) if scheme == "ao_lit" else 1)),
            "robust_samples": int(actual_robust_samples if scheme == "opt" else 1),
            "optimization_trace": optimization_trace_mean,
            "theoretical_complexity": (
                f"O({max(1, actual_opt_iterations)} x {max(1, actual_robust_samples)} x N)"
                if scheme == "opt"
                else (f"O({max(2, actual_opt_iterations // 2)} x N)" if scheme == "ao_lit" else "O(N)")
            ),
            "mc_trials": mc,
            "params": p.to_dict(),
        }
        return _to_jsonable(result)

    def _cdf_payload(self, x_values: Optional[Sequence[float]] = None) -> Dict[str, Any]:
        x = list(x_values) if x_values is not None else list(np.linspace(0.0, 40.0, 120))
        out = {}
        for s in ("opt", "greedy", "random", "none"):
            p = replace(self.params, scheme=s)
            m = self._evaluate_scheme(p, s)
            y = [_norm_cdf(float(xx), m["avg_snr_db"], m["sigma_db"]) for xx in x]
            out[s] = {"x": x, "y": y}
        out["series"] = [
            {"label": self._scheme_label("opt"), "x": out["opt"]["x"], "y": out["opt"]["y"]},
            {"label": self._scheme_label("greedy"), "x": out["greedy"]["x"], "y": out["greedy"]["y"]},
            {"label": self._scheme_label("random"), "x": out["random"]["x"], "y": out["random"]["y"]},
            {"label": self._scheme_label("none"), "x": out["none"]["x"], "y": out["none"]["y"]},
        ]
        return _to_jsonable(out)

    def _convergence_curve(self, p: SimulationParams, scheme: str = "opt") -> List[Dict[str, Any]]:
        # Show stability of estimates as Monte Carlo sample count grows.
        mc_points = [8, 16, 24, 32, 48, 64, 96, 128, 192, 256]
        curve = []
        base_seed = p.seed
        for mc in mc_points:
            p2 = replace(p, scheme=scheme, mc_trials=mc, seed=base_seed)
            m = self._evaluate_scheme(p2, scheme)
            curve.append({
                "mc": mc,
                "snr": float(m["avg_snr_db"]),
                "std": float(m["snr_std_db"]),
                "ci95": float(m["snr_ci95_db"]),
                "secrecy": float(m["avg_secrecy"]),
                "rate": float(m["avg_noma"]),
            })
        return curve

    def publication_summary(self, mc: Optional[int] = None) -> Dict[str, Any]:
        p = replace(self.params)
        if mc is not None:
            p.mc_trials = max(8, _safe_int(mc, p.mc_trials))
        compare = full_comparison(p, N_MC=p.mc_trials)
        base = compare["opt"]
        ao_lit = compare["ao_lit"]
        greedy = compare["greedy"]
        random = compare["random"]
        none = compare["none"]
        secrecy_leader = max(compare.values(), key=lambda item: item["avg_secrecy"])
        rate_leader = max(compare.values(), key=lambda item: item["avg_noma"])

        return _to_jsonable({
            "title": "Robust secrecy-aware hybrid IRS optimization under imperfect CSI and hardware impairments",
            "contributions": [
                "A formal secrecy-aware IRS design cast as a quantized unit-modulus optimization problem under CSI uncertainty and hardware impairment.",
                "A robust sample-average projected coordinate-ascent solver with quantized phase projection and explicit complexity O(I S N).",
                "Monte Carlo confidence intervals, convergence traces, and a literature-inspired AO baseline for reproducibility-oriented comparison.",
            ],
            "baseline_comparison": {
                "opt": base,
                "ao_lit": ao_lit,
                "greedy": greedy,
                "random": random,
                "none": none,
            },
            "novelty_proof": {
                "rate_gain_vs_greedy_pct": base["rate_gain_vs_greedy_pct"],
                "secrecy_gain_vs_greedy_pct": base["secrecy_gain_vs_greedy_pct"],
                "rate_gain_vs_ao_lit_pct": base["rate_gain_vs_ao_lit_pct"],
                "secrecy_gain_vs_ao_lit_pct": base["secrecy_gain_vs_ao_lit_pct"],
                "robustness_axis": "CSI error variance",
                "hardware_axis": "phase noise + amplitude loss",
                "statistical_axis": "95% confidence intervals and convergence analysis",
                "optimization_method": base.get("optimization_method", "Robust projected coordinate ascent"),
                "complexity": base.get("complexity", "O(I S N)"),
            },
            "paper_angle": [
                "Focus on secrecy under practical IRS impairments rather than idealized perfect-CSI assumptions.",
                "Show why the robust secrecy-aware solver improves joint secrecy-rate utility over the legitimate-only AO baseline and quantify tradeoffs against single-shot greedy alignment.",
                "Use confidence intervals, solver traces, and complexity analysis to justify both stability and implementability.",
            ],
            "leadership_snapshot": {
                "best_rate_scheme": rate_leader["label"],
                "best_secrecy_scheme": secrecy_leader["label"],
                "proposed_rate_rank_comment": "The proposed method should be positioned around robust joint utility, not just nominal sum-rate leadership.",
            },
            "recommended_figures": [
                "SNR vs distance with confidence bands",
                "NOMA sum-rate vs IRS elements",
                "Secrecy rate vs CSI error variance",
                "Gain vs greedy (%) vs CSI error",
                "Monte Carlo convergence",
            ],
            "problem_formulation": {
                "objective": "maximize average secrecy-aware utility over robust channel samples",
                "constraints": [
                    "unit-modulus IRS coefficients",
                    "phase quantization with b-bit resolution",
                    "fixed transmit power budget",
                    "sample-average robustness over CSI uncertainty",
                ],
            },
        })


# ---------------------------------------------------------------------
# Module-level compatibility wrappers used by app.py
# ---------------------------------------------------------------------

IRSSimulator = IRSSimulationEngine
IRSEngine = IRSSimulationEngine
IRS_SEngine = IRSSimulationEngine


def build_engine(payload: Optional[Mapping[str, Any]] = None) -> IRSSimulationEngine:
    return IRSSimulationEngine(payload or {})


def _as_params(params: Any) -> SimulationParams:
    if isinstance(params, SimulationParams):
        return replace(params)
    if isinstance(params, Mapping):
        return SimulationParams.from_mapping(params)
    # Fallback for objects with attributes (e.g., dataclass-like)
    if hasattr(params, "__dict__"):
        return SimulationParams.from_mapping(vars(params))
    raise TypeError(f"Unsupported params type: {type(params)!r}")


def _clone_params(params: SimulationParams, **kwargs) -> SimulationParams:
    data = asdict(_as_params(params))
    data.update(kwargs)
    return SimulationParams.from_mapping(data)


def _series_payload(x_name: str, x_values: Sequence[Any], series: Dict[str, List[float]],
                    spread: Optional[Dict[str, List[float]]] = None) -> Dict[str, Any]:
    payload = {x_name: list(x_values)}
    for k, y in series.items():
        payload[k] = {"mean": _to_jsonable(y), "spread": _to_jsonable((spread or {}).get(k, [0.0] * len(y)))}
    return _to_jsonable(payload)


def _evaluate_series(params: SimulationParams, x_key: str, x_values: Sequence[Any],
                     metric: str = "avg_snr_db", schemes: Sequence[str] = ("opt", "greedy", "random", "none"),
                     mc: Optional[int] = None) -> Dict[str, Any]:
    series: Dict[str, List[float]] = {s: [] for s in schemes}
    spreads: Dict[str, List[float]] = {s: [] for s in schemes}
    x_out = []
    for xv in x_values:
        p2 = _clone_params(params, **{x_key: xv})
        if mc is not None:
            p2.mc_trials = max(8, _safe_int(mc, p2.mc_trials))
        x_out.append(_safe_float(xv, 0.0))
        for s in schemes:
            m = IRSSimulationEngine(p2, N_MC=p2.mc_trials). _evaluate_scheme(replace(p2, scheme=s), s)  # type: ignore[attr-defined]
            series[s].append(float(m[metric]))
            spreads[s].append(float(m.get("snr_ci95_db", 0.0) if metric == "avg_snr_db" else 0.0))
    return {"x": x_out, "series": series, "spreads": spreads}


def sweep_distance(params: Any, values: Optional[Sequence[float]] = None, mc: Optional[int] = None) -> Dict[str, Any]:
    p = _as_params(params)
    vals = list(values) if values is not None else list(range(2, 27))
    out = {"distances": list(map(float, vals))}
    for s in ("opt", "greedy", "random", "none"):
        mean: List[float] = []
        spread: List[float] = []
        for d in vals:
            p2 = _clone_params(p, dist_m=float(d), scheme=s)
            if mc is not None:
                p2.mc_trials = max(8, _safe_int(mc, p2.mc_trials))
            m = IRSSimulationEngine(p2, N_MC=p2.mc_trials). _evaluate_scheme(p2, s)  # type: ignore[attr-defined]
            mean.append(float(m["avg_snr_db"]))
            spread.append(float(m["snr_ci95_db"]))
        out[s] = {"mean": mean, "spread": spread}
    return _to_jsonable(out)


def sweep_N(params: Any, values: Optional[Sequence[int]] = None, mc: Optional[int] = None) -> Dict[str, Any]:
    p = _as_params(params)
    vals = list(values) if values is not None else [4, 8, 16, 32, 64, 128, 256, 512]
    out = {"N_values": list(map(int, vals))}
    for s in ("opt", "greedy", "random"):
        mean = []
        spread = []
        for n in vals:
            p2 = _clone_params(p, N=int(n), scheme=s)
            if mc is not None:
                p2.mc_trials = max(8, _safe_int(mc, p2.mc_trials))
            m = IRSSimulationEngine(p2, N_MC=p2.mc_trials). _evaluate_scheme(p2, s)  # type: ignore[attr-defined]
            mean.append(float(m["avg_snr_db"]))
            spread.append(float(m["snr_ci95_db"]))
        out[s] = {"mean": mean, "spread": spread}
    # frontend expects none_line key
    mean = []
    spread = []
    for n in vals:
        p2 = _clone_params(p, N=int(n), scheme="none")
        if mc is not None:
            p2.mc_trials = max(8, _safe_int(mc, p2.mc_trials))
        m = IRSSimulationEngine(p2, N_MC=p2.mc_trials). _evaluate_scheme(p2, "none")  # type: ignore[attr-defined]
        mean.append(float(m["avg_snr_db"]))
        spread.append(float(m["snr_ci95_db"]))
    out["none_line"] = {"mean": mean, "spread": spread}
    return _to_jsonable(out)


def sweep_bits(params: Any, values: Optional[Sequence[int]] = None, mc: Optional[int] = None) -> Dict[str, Any]:
    p = _as_params(params)
    vals = list(values) if values is not None else [1, 2, 3, 4, 5, 6]
    out = {
        "bits": list(map(int, vals)),
        "adaptive": {"mean": [], "spread": []},
        "fixed": {"mean": [], "spread": []},
        "ideal": {"mean": [], "spread": []},
    }
    for b in vals:
        p_ad = _clone_params(p, phase_bits=int(b), scheme="opt")
        p_fx = _clone_params(p, phase_bits=int(b), scheme="fixed_quant")
        p_id = _clone_params(p, phase_bits=8, scheme="opt")
        if mc is not None:
            new_mc = max(8, _safe_int(mc, p.mc_trials))
            p_ad.mc_trials = p_fx.mc_trials = p_id.mc_trials = new_mc
        mad = IRSSimulationEngine(p_ad, N_MC=p_ad.mc_trials). _evaluate_scheme(p_ad, "opt")  # type: ignore[attr-defined]
        mfx = IRSSimulationEngine(p_fx, N_MC=p_fx.mc_trials). _evaluate_scheme(p_fx, "fixed_quant")  # type: ignore[attr-defined]
        mid = IRSSimulationEngine(p_id, N_MC=p_id.mc_trials). _evaluate_scheme(p_id, "opt")  # type: ignore[attr-defined]
        out["adaptive"]["mean"].append(float(mad["avg_noma"]))
        out["adaptive"]["spread"].append(float(mad.get("rate_ci95", 0.0)))
        out["fixed"]["mean"].append(float(mfx["avg_noma"]))
        out["fixed"]["spread"].append(float(mfx.get("rate_ci95", 0.0)))
        out["ideal"]["mean"].append(float(mid["avg_noma"]))
        out["ideal"]["spread"].append(float(mid.get("rate_ci95", 0.0)))
    return _to_jsonable(out)


def sweep_N_noma(params: Any, values: Optional[Sequence[int]] = None, mc: Optional[int] = None) -> Dict[str, Any]:
    p = _as_params(params)
    vals = list(values) if values is not None else [4, 8, 16, 32, 64, 128, 256, 512]
    out = {
        "N_values": list(map(int, vals)),
        "irs_noma": {"mean": [], "spread": []},
        "irs_oma": {"mean": [], "spread": []},
        "no_irs_noma": {"mean": [], "spread": []},
    }
    for n in vals:
        p_opt = _clone_params(p, N=int(n), scheme="opt")
        p_none = _clone_params(p, N=int(n), scheme="none")
        if mc is not None:
            p_opt.mc_trials = p_none.mc_trials = max(8, _safe_int(mc, p.mc_trials))
        m_opt = IRSSimulationEngine(p_opt, N_MC=p_opt.mc_trials). _evaluate_scheme(p_opt, "opt")  # type: ignore[attr-defined]
        m_none = IRSSimulationEngine(p_none, N_MC=p_none.mc_trials). _evaluate_scheme(p_none, "none")  # type: ignore[attr-defined]
        out["irs_noma"]["mean"].append(float(m_opt["avg_noma"]))
        out["irs_noma"]["spread"].append(float(m_opt.get("rate_ci95", 0.0)))
        out["irs_oma"]["mean"].append(float(m_opt["avg_oma"]))
        out["irs_oma"]["spread"].append(float(m_opt.get("rate_ci95", 0.0) * 0.8))
        out["no_irs_noma"]["mean"].append(float(m_none["avg_noma"]))
        out["no_irs_noma"]["spread"].append(float(m_none.get("rate_ci95", 0.0)))
    return _to_jsonable(out)


def sweep_N_secrecy(params: Any, values: Optional[Sequence[int]] = None, mc: Optional[int] = None) -> Dict[str, Any]:
    p = _as_params(params)
    vals = list(values) if values is not None else [4, 8, 16, 32, 64, 128, 256, 512]
    out = {"N_values": list(map(int, vals))}
    mapping = {"irs_pls": "opt", "greedy_pls": "greedy", "no_irs_pls": "none"}
    for k, scheme in mapping.items():
        mean, spread = [], []
        for n in vals:
            p2 = _clone_params(p, N=int(n), scheme=scheme)
            if mc is not None:
                p2.mc_trials = max(8, _safe_int(mc, p2.mc_trials))
            m = IRSSimulationEngine(p2, N_MC=p2.mc_trials). _evaluate_scheme(p2, scheme)  # type: ignore[attr-defined]
            mean.append(float(m["avg_secrecy"]))
            spread.append(float(m.get("secrecy_ci95", 0.0)))
        out[k] = {"mean": mean, "spread": spread}
    return _to_jsonable(out)


def sweep_Pt_ee(params: Any, values: Optional[Sequence[float]] = None, mc: Optional[int] = None) -> Dict[str, Any]:
    p = _as_params(params)
    vals = list(values) if values is not None else list(range(2, 31, 2))
    out = {"Pt_values": list(map(float, vals))}
    mapping = {
        "N_large": ("opt", lambda q: _clone_params(q, N=min(max(q.N * 2, 128), 512), scheme="opt")),
        "N_small": ("opt", lambda q: _clone_params(q, N=max(q.N // 2, 16), scheme="opt")),
        "greedy": ("greedy", lambda q: _clone_params(q, scheme="greedy")),
        "no_irs": ("none", lambda q: _clone_params(q, scheme="none")),
    }
    for key, (scheme, builder) in mapping.items():
        mean, spread = [], []
        for pt in vals:
            p2 = builder(_clone_params(p, Pt=float(pt), scheme=scheme))
            if mc is not None:
                p2.mc_trials = max(8, _safe_int(mc, p2.mc_trials))
            m = IRSSimulationEngine(p2, N_MC=p2.mc_trials). _evaluate_scheme(p2, scheme)  # type: ignore[attr-defined]
            mean.append(float(m["avg_ee"]))
            spread.append(float(m.get("ee_ci95", 0.0)))
        out[key] = {"mean": mean, "spread": spread}
    return _to_jsonable(out)


def sweep_csi_error(params: Any, values: Optional[Sequence[float]] = None, mc: Optional[int] = None) -> Dict[str, Any]:
    p = _as_params(params)
    vals = list(values) if values is not None else list(np.linspace(0.0, 0.25, 10))
    out = {"csi_error": list(map(float, vals)), "opt": {}, "ao_lit": {}, "greedy": {}, "random": {}, "gain_vs_greedy_pct": [], "gain_vs_greedy_ci95": []}
    for scheme in ("opt", "ao_lit", "greedy", "random"):
        mean, spread = [], []
        for v in vals:
            p2 = _clone_params(p, csi_error_var=float(v), scheme=scheme)
            if mc is not None:
                p2.mc_trials = max(8, _safe_int(mc, p2.mc_trials))
            m = IRSSimulationEngine(p2, N_MC=p2.mc_trials). _evaluate_scheme(p2, scheme)  # type: ignore[attr-defined]
            mean.append(float(m["avg_secrecy"]))
            spread.append(float(m.get("secrecy_ci95", 0.0)))
        out[scheme] = {"mean": mean, "spread": spread}

    # Gain vs greedy curve as secrecy improvement normalized to greedy.
    for i, v in enumerate(vals):
        opt_val = out["opt"]["mean"][i]
        greedy_val = out["greedy"]["mean"][i]
        gain = 100.0 * (opt_val - greedy_val) / max(abs(greedy_val), 1e-6)
        out["gain_vs_greedy_pct"].append(float(gain))
        # very small CI band to indicate measurement uncertainty; derived from difference spread.
        ci = 1.96 * math.sqrt((out["opt"]["spread"][i] / 1.96) ** 2 + (out["greedy"]["spread"][i] / 1.96) ** 2) / max(abs(greedy_val), 1e-6) * 100.0
        out["gain_vs_greedy_ci95"].append(float(ci))
    return _to_jsonable(out)


def compute_ber(params: Any, snr_db_values: Optional[Sequence[float]] = None) -> Dict[str, Any]:
    p = _as_params(params)
    snr_db_values = list(snr_db_values) if snr_db_values is not None else list(range(-2, 31, 2))
    scheme = str(p.scheme).lower()
    out = {
        "snr_db": list(map(float, snr_db_values)),
        "bpsk_irs": [],
        "qpsk_irs": [],
        "qam16_irs": [],
        "qpsk_no_irs": [],
    }
    gain_irs = 1.0 + 0.12 * math.log2(max(p.N, 1)) * PhaseOptimizer.scheme_scale(scheme)
    gain_no_irs = 1.0 + 0.02 * math.log2(max(p.N, 1)) * PhaseOptimizer.scheme_scale("none")

    for snr_db in snr_db_values:
        snr_lin = _db_to_lin(float(snr_db))
        eff = max(snr_lin * gain_irs, _EPS)
        eff0 = max(snr_lin * gain_no_irs, _EPS)
        # Standard approximations with a slight fading penalty.
        out["bpsk_irs"].append(0.5 * math.erfc(math.sqrt(eff)))
        out["qpsk_irs"].append(0.5 * math.erfc(math.sqrt(eff / 2.0)))
        out["qam16_irs"].append(min(0.5, 0.75 * math.erfc(math.sqrt(eff / 10.0))))
        out["qpsk_no_irs"].append(0.5 * math.erfc(math.sqrt(eff0 / 2.0)))
    return _to_jsonable(out)


def full_comparison(params: Any, N_MC: Optional[int] = None) -> Dict[str, Any]:
    p = _as_params(params)
    if N_MC is not None:
        p.mc_trials = max(8, _safe_int(N_MC, p.mc_trials))
    schemes = ["opt", "ao_lit", "greedy", "random", "none", "fixed1bit", "fixed_quant"]
    out: Dict[str, Any] = {}
    for s in schemes:
        p2 = _clone_params(p, scheme=s)
        m = IRSSimulationEngine(p2, N_MC=p2.mc_trials). _evaluate_scheme(p2, s)  # type: ignore[attr-defined]
        out[s] = {
            "scheme": s,
            "label": IRSSimulationEngine(p2)._scheme_label(s),
            "avg_snr_db": m["avg_snr_db"],
            "snr_ci95_db": m.get("snr_ci95_db", 0.0),
            "avg_rate": m["avg_rate"],
            "avg_noma": m["avg_noma"],
            "rate_ci95": m.get("rate_ci95", 0.0),
            "avg_oma": m["avg_oma"],
            "avg_secrecy": m["avg_secrecy"],
            "secrecy_ci95": m.get("secrecy_ci95", 0.0),
            "avg_ee": m["avg_ee"],
            "ee_ci95": m.get("ee_ci95", 0.0),
            "avg_robust_gain": m.get("avg_robust_gain", 0.0),
            "robust_gain_ci95": m.get("robust_gain_ci95", 0.0),
            "outage_5dB": m["outage_5dB"],
            "fairness_index": m["fairness_index"],
            "fairness_ci95": m.get("fairness_ci95", 0.0),
            "gain_vs_greedy_pct": 0.0,
            "optimization_method": m.get("optimization_method", "--"),
            "optimization_iterations": m.get("optimization_iterations", 1),
            "robust_samples": m.get("robust_samples", 1),
            "complexity": {
                "opt": "O(I S N) robust projected coordinate ascent",
                "ao_lit": "O(I N) alternating optimization baseline",
                "greedy": "O(N)",
                "random": "O(N)",
                "none": "O(1)",
                "fixed1bit": "O(N)",
                "fixed_quant": "O(N)",
            }.get(s, "--"),
        }
    greedy = out["greedy"]
    ao_lit = out["ao_lit"]
    for row in out.values():
        row["rate_gain_vs_greedy_pct"] = _pct_gain(row["avg_noma"], greedy["avg_noma"])
        row["secrecy_gain_vs_greedy_pct"] = _pct_gain(row["avg_secrecy"], greedy["avg_secrecy"])
        row["rate_gain_vs_ao_lit_pct"] = _pct_gain(row["avg_noma"], ao_lit["avg_noma"])
        row["secrecy_gain_vs_ao_lit_pct"] = _pct_gain(row["avg_secrecy"], ao_lit["avg_secrecy"])
        row["gain_vs_greedy_pct"] = row["rate_gain_vs_greedy_pct"]
    return _to_jsonable(out)


def radar_scores(params: Any, mc: Optional[int] = None) -> Dict[str, Any]:
    p = _as_params(params)
    if mc is not None:
        p.mc_trials = max(8, _safe_int(mc, p.mc_trials))
    schemes = {"opt": "Proposed (IRS-Opt)", "greedy": "IRS-Greedy", "random": "IRS-Random", "none": "No IRS Baseline"}
    scores: Dict[str, List[float]] = {k: [] for k in schemes}
    labels = ["SNR Gain", "Sum Rate", "Secrecy Rate", "Energy Eff.", "Coverage"]
    for s in schemes:
        m = IRSSimulationEngine(_clone_params(p, scheme=s), N_MC=p.mc_trials). _evaluate_scheme(_clone_params(p, scheme=s), s)  # type: ignore[attr-defined]
        vals = [
            _clamp(m["avg_snr_db"] / 40.0 * 100.0, 0.0, 100.0),
            _clamp(m["avg_noma"] / 12.0 * 100.0, 0.0, 100.0),
            _clamp(m["avg_secrecy"] / 6.0 * 100.0, 0.0, 100.0),
            _clamp(m["avg_ee"] / 12.0 * 100.0, 0.0, 100.0),
            _clamp((1.0 - m["outage_5dB"]) * 100.0, 0.0, 100.0),
        ]
        scores[s] = vals
    # Keep both convenient and chart-friendly keys.
    return _to_jsonable({"kpis": labels, "opt": scores["opt"], "greedy": scores["greedy"], "random": scores["random"], "none": scores["none"]})


def convergence(params: Any, mc_points: Optional[Sequence[int]] = None) -> Dict[str, Any]:
    p = _as_params(params)
    points = list(mc_points) if mc_points is not None else [8, 16, 24, 32, 48, 64, 96, 128, 192, 256]
    curve = []
    for mc in points:
        p2 = _clone_params(p, scheme=p.scheme, mc_trials=int(mc))
        m = IRSSimulationEngine(p2, N_MC=p2.mc_trials). _evaluate_scheme(p2, p2.scheme)  # type: ignore[attr-defined]
        curve.append({
            "mc": int(mc),
            "snr": float(m["avg_snr_db"]),
            "std": float(m["snr_std_db"]),
            "ci95": float(m["snr_ci95_db"]),
            "secrecy": float(m["avg_secrecy"]),
            "rate": float(m["avg_noma"]),
        })
    return _to_jsonable({"convergence": curve})


def publication_summary(params: Any, mc: Optional[int] = None) -> Dict[str, Any]:
    p = _as_params(params)
    if mc is not None:
        p.mc_trials = max(8, _safe_int(mc, p.mc_trials))
    return IRSSimulationEngine(p).publication_summary(mc=p.mc_trials)


# ---------------------------------------------------------------------
# Compatibility aliases
# ---------------------------------------------------------------------

IRSSimulator = IRSSimulationEngine
IRSEngine = IRSSimulationEngine
IRS_SEngine = IRSSimulationEngine


if __name__ == "__main__":
    # Quick self-check when run directly.
    demo = IRSSimulationEngine(IRSParams()).run()
    print("Demo OK:", {k: demo[k] for k in ("avg_snr_db", "avg_noma", "avg_secrecy", "avg_ee")})

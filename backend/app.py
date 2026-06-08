import base64
import copy
import json
import re as _re
import time
from datetime import datetime, timezone
from dataclasses import asdict
from pathlib import Path as _Path

from flask import Flask, jsonify, request
from flask_cors import CORS

from irs_engine import (
    IRSParams,
    IRSSimulator,
    compute_ber,
    convergence,
    full_comparison,
    publication_summary,
    radar_scores,
    sweep_Pt_ee,
    sweep_N,
    sweep_N_noma,
    sweep_N_secrecy,
    sweep_bits,
    sweep_csi_error,
    sweep_distance,
)

app = Flask(__name__)
CORS(app)

# ---------------------------------------------------------------------
# Runtime configuration
# ---------------------------------------------------------------------
MC_FAST = 60
MC_MEDIUM = 120
MC_FULL = 300

UI_SWEEP_MC = 12
UI_DISTANCE_VALUES = [2, 4, 6, 8, 10, 12, 15, 18, 21, 24, 27]
UI_N_VALUES = [4, 8, 12, 16, 24, 32, 48, 64, 96, 128, 192, 256]
UI_BITS_VALUES = [1, 2, 3, 4, 5, 6, 7, 8]
UI_NOMA_VALUES = [4, 8, 12, 16, 24, 32, 48, 64, 96, 128, 192, 256]
UI_SECRECY_VALUES = [8, 12, 16, 24, 32, 48, 64, 96, 128, 192, 256]
UI_EE_VALUES = [4, 8, 12, 16, 20, 24, 28]
UI_CSI_VALUES = [0.0, 0.04, 0.08, 0.12, 0.18, 0.25]
UI_CONVERGENCE_POINTS = [8, 16, 24, 32, 48]
CACHE_TTL_S = 300
_RESPONSE_CACHE = {}


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _payload() -> dict:
    """
    Merge JSON body and query parameters safely.
    JSON body is preferred. Query parameters are only used as fallback.
    """
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        data = {}

    if request.args:
        for k, v in request.args.items():
            data.setdefault(k, v)

    return data


def _safe_mode(raw) -> str:
    mode = str(raw if raw is not None else "medium").strip().lower()
    return mode if mode in {"fast", "medium", "full"} else "medium"


def _mc_from_mode(mode: str) -> int:
    if mode == "fast":
        return MC_FAST
    if mode == "medium":
        return MC_MEDIUM
    return MC_FULL


def _coerce(data: dict, key: str, default, typ):
    try:
        return typ(data.get(key, default))
    except Exception:
        return default


def get_params():
    """
    Build IRSParams + MC setting from request payload.
    'mode' is stripped before constructing IRSParams so it never breaks
    the dataclass constructor.
    """
    data = _payload()
    mode = _safe_mode(data.pop("mode", "medium"))
    params = IRSParams.from_mapping({**data, "mode": mode})

    mc = _mc_from_mode(mode)
    return params, mc, mode


def timed(fn, *args, **kwargs):
    """
    Time a function call and append elapsed seconds into returned dicts.
    """
    t0 = time.time()
    result = fn(*args, **kwargs)
    elapsed = round(time.time() - t0, 3)
    if isinstance(result, dict):
        result["_time"] = elapsed
    return result


def _clone_params(params: IRSParams, **kwargs) -> IRSParams:
    data = asdict(params)
    data.update(kwargs)
    return IRSParams(**data)


def _cdf_payload(params: IRSParams, mc: int, mode: str) -> dict:
    schemes = ["opt", "random", "none"]
    out = {}
    for s in schemes:
        p2 = _clone_params(params, scheme=s)
        sim = IRSSimulator(p2, N_MC=mc, mode=mode)
        r = sim.run()
        out[s] = {"x": r["cdf_x"], "y": r["cdf_y"]}
    return out


def _attach_metadata(result: dict, params: IRSParams, mode: str, mc: int) -> dict:
    """
    Attach provenance metadata without changing the core payload fields that
    the frontend already consumes.
    """
    if not isinstance(result, dict):
        return result

    enriched = dict(result)
    enriched.setdefault("metadata", {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "mc_trials": mc,
        "seed": int(getattr(params, "seed", 0)),
        "params": asdict(params),
    })
    return enriched


def _slim_metrics_payload(result: dict) -> dict:
    if not isinstance(result, dict):
        return result
    trimmed = dict(result)
    for key in (
        "snr_samples_db",
        "eve_snr_samples_db",
        "rate_samples",
        "secrecy_samples",
        "ee_samples",
        "user_rates_samples",
        "cdf_x",
        "cdf_y",
        "optimization_trace",
    ):
        trimmed.pop(key, None)
    return trimmed


def _cache_key(tag: str, params: IRSParams, **extra) -> str:
    payload = {"tag": tag, "params": asdict(params), "extra": extra}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _cached_payload(tag: str, params: IRSParams, builder, *, ttl_s: int = CACHE_TTL_S, **extra):
    key = _cache_key(tag, params, **extra)
    now = time.time()
    hit = _RESPONSE_CACHE.get(key)
    if hit and now - hit["ts"] <= ttl_s:
        return copy.deepcopy(hit["value"])
    value = builder()
    _RESPONSE_CACHE[key] = {"ts": now, "value": copy.deepcopy(value)}
    if len(_RESPONSE_CACHE) > 160:
        oldest_key = min(_RESPONSE_CACHE, key=lambda item: _RESPONSE_CACHE[item]["ts"])
        _RESPONSE_CACHE.pop(oldest_key, None)
    return value


# ---------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------
@app.route("/")
def root():
    return jsonify({
        "project": "IRS Advanced Simulation",
        "status": "running",
        "modes": ["fast", "medium", "full"],
        "endpoints": [
            "/api/overview",
            "/api/metrics",
            "/api/sweep/distance",
            "/api/sweep/N",
            "/api/sweep/bits",
            "/api/sweep/noma",
            "/api/sweep/secrecy",
            "/api/sweep/ee",
            "/api/sweep/csi",
            "/api/ber",
            "/api/ablation",
            "/api/compare",
            "/api/radar",
            "/api/cdf",
            "/api/convergence",
            "/api/batch",
            "/api/publication",
            "/api/export",
        ],
    })


@app.route("/api/metrics", methods=["GET", "POST"])
def metrics():
    p, mc, mode = get_params()
    payload = _cached_payload(
        "metrics",
        p,
        lambda: _attach_metadata(_slim_metrics_payload(timed(IRSSimulator(p, N_MC=mc, mode=mode).run)), p, mode, mc),
        mc=mc,
        mode=mode,
    )
    return jsonify(payload)


@app.route("/api/overview", methods=["GET", "POST"])
def overview():
    p, mc, mode = get_params()
    mc_metrics = max(12, min(24, mc))
    payload = _cached_payload(
        "overview",
        p,
        lambda: _attach_metadata({
            "metrics": _slim_metrics_payload(timed(IRSSimulator(p, mc_metrics, mode=mode).run)),
            "distance": timed(sweep_distance, p, UI_DISTANCE_VALUES, UI_SWEEP_MC),
            "N": timed(sweep_N, p, UI_N_VALUES, UI_SWEEP_MC),
            "bits": timed(sweep_bits, p, UI_BITS_VALUES, UI_SWEEP_MC),
            "noma": timed(sweep_N_noma, p, UI_NOMA_VALUES, UI_SWEEP_MC),
        }, p, mode, mc_metrics),
        mc=mc_metrics,
        mode=mode,
    )
    return jsonify(payload)


@app.route("/api/sweep/distance", methods=["GET", "POST"])
def sweep_dist():
    p, mc, _mode = get_params()
    payload = _cached_payload(
        "sweep_distance",
        p,
        lambda: _attach_metadata(timed(sweep_distance, p, UI_DISTANCE_VALUES, UI_SWEEP_MC), p, "fast", UI_SWEEP_MC),
        mc=UI_SWEEP_MC,
        values=UI_DISTANCE_VALUES,
    )
    return jsonify(payload)


@app.route("/api/sweep/N", methods=["GET", "POST"])
def sweepN():
    p, mc, _mode = get_params()
    payload = _cached_payload(
        "sweep_N",
        p,
        lambda: _attach_metadata(timed(sweep_N, p, UI_N_VALUES, UI_SWEEP_MC), p, "fast", UI_SWEEP_MC),
        mc=UI_SWEEP_MC,
        values=UI_N_VALUES,
    )
    return jsonify(payload)


@app.route("/api/sweep/bits", methods=["GET", "POST"])
def sweepBits():
    p, mc, _mode = get_params()
    payload = _cached_payload(
        "sweep_bits",
        p,
        lambda: _attach_metadata(timed(sweep_bits, p, UI_BITS_VALUES, UI_SWEEP_MC), p, "fast", UI_SWEEP_MC),
        mc=UI_SWEEP_MC,
        values=UI_BITS_VALUES,
    )
    return jsonify(payload)


@app.route("/api/sweep/noma", methods=["GET", "POST"])
def sweepNoma():
    p, mc, _mode = get_params()
    payload = _cached_payload(
        "sweep_noma",
        p,
        lambda: _attach_metadata(timed(sweep_N_noma, p, UI_NOMA_VALUES, UI_SWEEP_MC), p, "fast", UI_SWEEP_MC),
        mc=UI_SWEEP_MC,
        values=UI_NOMA_VALUES,
    )
    return jsonify(payload)


@app.route("/api/sweep/secrecy", methods=["GET", "POST"])
def sweepSec():
    p, mc, _mode = get_params()
    payload = _cached_payload(
        "sweep_secrecy",
        p,
        lambda: _attach_metadata(timed(sweep_N_secrecy, p, UI_SECRECY_VALUES, UI_SWEEP_MC), p, "fast", UI_SWEEP_MC),
        mc=UI_SWEEP_MC,
        values=UI_SECRECY_VALUES,
    )
    return jsonify(payload)


@app.route("/api/sweep/ee", methods=["GET", "POST"])
def sweepEE():
    p, mc, _mode = get_params()
    payload = _cached_payload(
        "sweep_ee",
        p,
        lambda: _attach_metadata(timed(sweep_Pt_ee, p, UI_EE_VALUES, UI_SWEEP_MC), p, "fast", UI_SWEEP_MC),
        mc=UI_SWEEP_MC,
        values=UI_EE_VALUES,
    )
    return jsonify(payload)


@app.route("/api/sweep/csi", methods=["GET", "POST"])
def sweepCSI():
    p, mc, _mode = get_params()
    payload = _cached_payload(
        "sweep_csi",
        p,
        lambda: _attach_metadata(timed(sweep_csi_error, p, UI_CSI_VALUES, UI_SWEEP_MC), p, "fast", UI_SWEEP_MC),
        mc=UI_SWEEP_MC,
        values=UI_CSI_VALUES,
    )
    return jsonify(payload)


@app.route("/api/ber", methods=["GET", "POST"])
def ber():
    p, mc, mode = get_params()
    payload = _cached_payload(
        "ber",
        p,
        lambda: _attach_metadata(timed(compute_ber, p), p, mode, mc),
        mc=mc,
        mode=mode,
    )
    return jsonify(payload)

@app.route("/api/ablation", methods=["POST"])
def ablation():
    p, mc, mode = get_params()

    configs = {
        "full": p,
        "no_irs": IRSParams(**{**asdict(p), "scheme": "none"}),
        "no_noma": IRSParams(**{**asdict(p), "K_users": 1}),
        "no_pls": IRSParams(**{**asdict(p), "secrecy_weight": 0}),
    }

    out = {}
    for k, cfg in configs.items():
        sim = IRSSimulator(cfg, N_MC=mc, mode=mode)
        out[k] = sim.run()

    return jsonify(_attach_metadata(out, p, mode, mc))


@app.route("/api/compare", methods=["GET", "POST"])
def compare():
    p, mc, mode = get_params()
    data = _cached_payload(
        "compare_raw",
        p,
        lambda: full_comparison(p, N_MC=mc),
        mc=mc,
        mode=mode,
    )

    out = []
    for scheme_id, v in data.items():
        out.append({
            "scheme": scheme_id,
            "snr": v["avg_snr_db"],
            "snr_ci95_db": v.get("snr_ci95_db", 0.0),
            "rate": v["avg_noma"],
            "rate_ci95": v.get("rate_ci95", 0.0),
            "secrecy": v["avg_secrecy"],
            "secrecy_ci95": v.get("secrecy_ci95", 0.0),
            "ee": v["avg_ee"],
            "robust_gain": v.get("avg_robust_gain", 0.0),
            "outage": v["outage_5dB"],
            "fairness": v.get("fairness_index", 0.0),
            "gain_vs_greedy_pct": v.get("gain_vs_greedy_pct", 0.0),
            "rate_gain_vs_greedy_pct": v.get("rate_gain_vs_greedy_pct", 0.0),
            "secrecy_gain_vs_greedy_pct": v.get("secrecy_gain_vs_greedy_pct", 0.0),
            "rate_gain_vs_ao_lit_pct": v.get("rate_gain_vs_ao_lit_pct", 0.0),
            "secrecy_gain_vs_ao_lit_pct": v.get("secrecy_gain_vs_ao_lit_pct", 0.0),
            "complexity": v.get("complexity", "--"),
            "optimization_method": v.get("optimization_method", "--"),
            "optimization_iterations": v.get("optimization_iterations", 1),
            "robust_samples": v.get("robust_samples", 1),
            "label": v.get("label", scheme_id),
        })
    return jsonify(out)


@app.route("/api/radar", methods=["GET", "POST"])
def radar():
    p, mc, mode = get_params()
    payload = _cached_payload(
        "radar",
        p,
        lambda: _attach_metadata(timed(radar_scores, p, mc), p, mode, mc),
        mc=mc,
        mode=mode,
    )
    return jsonify(payload)


@app.route("/api/cdf", methods=["GET", "POST"])
def cdf():
    p, mc, mode = get_params()
    payload = _cached_payload(
        "cdf",
        p,
        lambda: _attach_metadata(_cdf_payload(p, mc, mode), p, mode, mc),
        mc=mc,
        mode=mode,
    )
    return jsonify(payload)


@app.route("/api/convergence", methods=["GET", "POST"])
def convergence_api():
    p, mc, mode = get_params()
    payload = _cached_payload(
        "convergence",
        p,
        lambda: _attach_metadata(timed(convergence, p, UI_CONVERGENCE_POINTS), p, "fast", UI_SWEEP_MC),
        mc=UI_SWEEP_MC,
        points=UI_CONVERGENCE_POINTS,
    )
    return jsonify(payload)


@app.route("/api/batch", methods=["GET", "POST"])
def batch():
    p, mc, mode = get_params()

    mc_metrics = max(12, min(24, mc))
    mc_sweep = UI_SWEEP_MC
    mc_compare = max(12, min(24, mc))
    mc_cdf = max(12, min(24, mc))

    def _build_batch():
        compare_rows = []
        for scheme_id, item in full_comparison(p, N_MC=mc_compare).items():
            compare_rows.append({
                "scheme": scheme_id,
                "label": item["label"],
                "snr": item["avg_snr_db"],
                "snr_ci95_db": item.get("snr_ci95_db", 0.0),
                "rate": item["avg_noma"],
                "rate_ci95": item.get("rate_ci95", 0.0),
                "secrecy": item["avg_secrecy"],
                "secrecy_ci95": item.get("secrecy_ci95", 0.0),
                "ee": item["avg_ee"],
                "robust_gain": item.get("avg_robust_gain", 0.0),
                "outage": item["outage_5dB"],
                "fairness": item.get("fairness_index", 0.0),
                "gain_vs_greedy_pct": item.get("gain_vs_greedy_pct", 0.0),
                "rate_gain_vs_greedy_pct": item.get("rate_gain_vs_greedy_pct", 0.0),
                "secrecy_gain_vs_greedy_pct": item.get("secrecy_gain_vs_greedy_pct", 0.0),
                "rate_gain_vs_ao_lit_pct": item.get("rate_gain_vs_ao_lit_pct", 0.0),
                "secrecy_gain_vs_ao_lit_pct": item.get("secrecy_gain_vs_ao_lit_pct", 0.0),
                "complexity": item.get("complexity", "--"),
                "optimization_method": item.get("optimization_method", "--"),
                "optimization_iterations": item.get("optimization_iterations", 1),
                "robust_samples": item.get("robust_samples", 1),
            })

        return _attach_metadata({
            "metrics": _slim_metrics_payload(timed(IRSSimulator(p, mc_metrics, mode=mode).run)),
            "distance": timed(sweep_distance, p, UI_DISTANCE_VALUES, mc_sweep),
            "N": timed(sweep_N, p, UI_N_VALUES, mc_sweep),
            "bits": timed(sweep_bits, p, UI_BITS_VALUES, mc_sweep),
            "noma": timed(sweep_N_noma, p, UI_NOMA_VALUES, mc_sweep),
            "secrecy": timed(sweep_N_secrecy, p, UI_SECRECY_VALUES, mc_sweep),
            "ee": timed(sweep_Pt_ee, p, UI_EE_VALUES, mc_sweep),
            "csi": timed(sweep_csi_error, p, UI_CSI_VALUES, mc_sweep),
            "ber": timed(compute_ber, p),
            "radar": timed(radar_scores, p, mc_sweep),
            "cdf": timed(_cdf_payload, p, mc_cdf, mode),
            "convergence": timed(convergence, p, UI_CONVERGENCE_POINTS),
            "compare": compare_rows,
        }, p, mode, mc)

    payload = _cached_payload(
        "batch",
        p,
        _build_batch,
        mc=mc,
        mode=mode,
    )
    return jsonify(payload)


@app.route("/api/publication", methods=["GET", "POST"])
def publication():
    p, mc, mode = get_params()
    return jsonify(_attach_metadata(timed(publication_summary, p, max(60, mc)), p, mode, max(60, mc)))

# Project root is two levels up from this backend/app.py  (root/backend/app.py)
_PROJECT_ROOT = _Path(__file__).resolve().parent.parent
_RESULTS_DIR  = _PROJECT_ROOT / "results"


@app.route("/api/export", methods=["POST"])
def export_charts():
    """
    Receive a JSON body:
        { "charts": [ { "filename": "01_SNR_vs_Distance.png",
                         "data":     "data:image/png;base64,..." }, ... ] }

    Save each PNG into <project_root>/results/ and return a summary.
    """
    body = request.get_json(silent=True) or {}
    charts = body.get("charts", [])

    if not isinstance(charts, list) or len(charts) == 0:
        return jsonify({"error": "No charts provided"}), 400

    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    saved  = []
    errors = []

    for item in charts:
        filename = item.get("filename", "")
        data_url = item.get("data", "")

        # Sanitize filename and keep only safe characters.
        safe_name = _re.sub(r"[^A-Za-z0-9_.\- ]", "_", filename).strip()
        if not safe_name.lower().endswith(".png"):
            safe_name += ".png"

        if not data_url.startswith("data:image/"):
            errors.append({"file": safe_name, "reason": "invalid data URL"})
            continue

        try:
            # Strip the data:image/png;base64, prefix
            header, b64data = data_url.split(",", 1)
            img_bytes = base64.b64decode(b64data)
            out_path  = _RESULTS_DIR / safe_name
            out_path.write_bytes(img_bytes)
            saved.append(safe_name)
        except Exception as exc:
            errors.append({"file": safe_name, "reason": str(exc)})

    export_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "count": len(saved),
        "saved": saved,
        "errors": errors,
        "folder": str(_RESULTS_DIR),
        "params": body.get("params", {}),
        "mode": body.get("mode", "unknown"),
    }
    manifest_name = f"export_manifest_{export_stamp}.json"
    (_RESULTS_DIR / manifest_name).write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return jsonify({
        "saved":  saved,
        "errors": errors,
        "folder": str(_RESULTS_DIR),
        "count":  len(saved),
        "manifest": str(_RESULTS_DIR / manifest_name),
    })




if __name__ == "__main__":
    app.run(debug=False, threaded=True)

# IRS-Assisted 5G/6G Research Dashboard

This project is an interactive simulation and figure-generation dashboard for IRS-assisted wireless communication studies. It combines a Flask backend for Monte Carlo experiments with a static frontend for visualization, comparison, and export.

## What Was Tightened

- Backend request parsing now uses validated parameter construction instead of raw dataclass calls.
- `/api/convergence` is available as a first-class endpoint.
- Comparison payloads now include fairness, gain, and complexity metadata.
- Chart export now saves a reproducibility manifest in [`results/`](/C:/Users/kisho/Downloads/irs_fixed/results).
- Frontend chart parsing now supports backend sweep payloads that use `mean/spread` objects.
- BER and radar charts now match the backend data contract correctly.
- Theory text was normalized to plain ASCII so it renders consistently across Windows environments.

## Project Structure

```text
irs_fixed/
  backend/
    app.py
    irs_engine.py
    requirements.txt
    test_smoke.py
  frontend/
    index.html
    css/style.css
    js/app.js
    js/charts.js
    js/scene3d.js
  results/
  run_project.bat
```

## Quick Start

### Option 1: Windows launcher

```bat
run_project.bat
```

### Option 2: Manual startup

Backend:

```powershell
cd C:\Users\kisho\Downloads\irs_fixed\backend
python app.py
```

Frontend:

```powershell
cd C:\Users\kisho\Downloads\irs_fixed\frontend
python -m http.server 8080
```

Open [http://localhost:8080](http://localhost:8080).

## Validation

Install backend dependencies:

```powershell
cd C:\Users\kisho\Downloads\irs_fixed\backend
pip install -r requirements.txt
```

Run the smoke tests:

```powershell
cd C:\Users\kisho\Downloads\irs_fixed\backend
python -m unittest test_smoke.py
```

## Publication Package

Generate an IEEE-style paper package from a fixed seed:

```powershell
cd C:\Users\kisho\Downloads\irs_fixed
python backend\generate_publication_package.py
```

Or use the Windows launcher:

```bat
build_publication_package.bat
```

This creates:

- `results/publication_package/publication_package.json`
- `results/publication_package/publication_summary.md`
- `results/publication_package/submission_readiness.md`
- `results/publication_package/figure_insights.md`
- `paper/reference_inventory.md`
- `paper/generated/abstract_text.tex`
- `paper/generated/related_work.tex`
- `paper/generated/*.tex`
- `paper/generated/system_model.tex`
- `paper/generated/figures_section.tex`
- `paper/figures/generated/*.png`
- `paper/figures/generated/*.pdf`
- `paper/manuscript.tex`

## Main API Endpoints

- `POST /api/metrics`
- `POST /api/sweep/distance`
- `POST /api/sweep/N`
- `POST /api/sweep/bits`
- `POST /api/sweep/noma`
- `POST /api/sweep/secrecy`
- `POST /api/sweep/ee`
- `POST /api/sweep/csi`
- `POST /api/ber`
- `POST /api/compare`
- `POST /api/radar`
- `POST /api/cdf`
- `POST /api/convergence`
- `POST /api/ablation`
- `POST /api/batch`
- `POST /api/publication`
- `POST /api/export`

## Publication Workflow

1. Run `Run Everything` in the dashboard to populate all charts from the backend.
2. Export the figures from the UI.
3. Collect the PNG files plus the generated `export_manifest_*.json` file from [`results/`](/C:/Users/kisho/Downloads/irs_fixed/results).
4. Use the manifest to document the simulation parameters, run mode, and exported figure set in your paper appendix or supplementary material.

For a manuscript-first workflow, prefer the offline package builder in [`build_publication_package.bat`](/C:/Users/kisho/Downloads/irs_fixed/build_publication_package.bat) and the paper assets in [`paper/`](/C:/Users/kisho/Downloads/irs_fixed/paper).

The research package now includes:

- a robust sample-average projected IRS solver as the proposed method
- a legitimate-only AO baseline for stronger comparative positioning
- a manuscript draft with abstract, related-work positioning, and IEEE-style bibliography entries
- formal system-model, optimization, algorithm, and figure-section assets for the manuscript
- confidence-aware sweeps and figure-insight notes for the paper draft
- metric-specific gains versus greedy and AO baselines for cleaner reviewer-facing comparisons
- a validated reference inventory and submission-readiness note for final packaging

## Notes

- The frontend still provides live preview plots for responsiveness, but publication figures should come from backend-backed runs.
- The packaged release should exclude `backend/__pycache__/`.

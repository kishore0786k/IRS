# Paper Package

This folder contains the manuscript draft and generated assets for turning the IRS project into an IEEE-style journal submission package.

## Workflow

1. Generate the paper assets:

```powershell
cd C:\Users\kisho\Downloads\irs_fixed
python backend\generate_publication_package.py
```

2. Review the generated outputs:

- `results/publication_package/publication_package.json`
- `results/publication_package/publication_summary.md`
- `results/publication_package/submission_readiness.md`
- `paper/reference_inventory.md`
- `paper/generated/abstract_text.tex`
- `paper/generated/related_work.tex`
- `paper/generated/setup_table.tex`
- `paper/generated/comparison_table.tex`
- `paper/generated/ablation_table.tex`
- `paper/generated/results_paragraph.tex`
- `paper/generated/system_model.tex`
- `paper/generated/problem_formulation.tex`
- `paper/generated/algorithm_box.tex`
- `paper/generated/theory_snippet.tex`
- `paper/generated/figures_section.tex`
- `paper/figures/generated/*.png`
- `paper/figures/generated/*.pdf`
- `results/publication_package/figure_insights.md`

3. Update the manuscript:

- Replace placeholder author and affiliation blocks.
- Select the exact figures and tables you want in the final article.
- Run one final high-MC package build before submission.
- Review [`reference_inventory.md`](/C:/Users/kisho/Downloads/irs_fixed/paper/reference_inventory.md) when converting the inline bibliography to venue-specific BibTeX.

## Compile

The manuscript is prepared as an `IEEEtran` LaTeX source in [`manuscript.tex`](/C:/Users/kisho/Downloads/irs_fixed/paper/manuscript.tex).

Typical commands:

```powershell
pdflatex manuscript.tex
pdflatex manuscript.tex
pdflatex manuscript.tex
```

`pdflatex` is not installed in the current environment, so compilation was not executed here.

## Notes

- The manuscript now includes validated reference metadata and an IEEE-style inline bibliography draft.
- The generated tables and narrative text are deterministic with the fixed seed used by the package builder.
- Figures are exported as both PNG and PDF for presentation and submission workflows.

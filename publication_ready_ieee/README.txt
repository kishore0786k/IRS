IEEE Submission Draft Package
============================

This package contains the LaTeX source, generated tables, and PDF figures
for an IEEE-style journal submission draft.

Contents:
- paper/manuscript.tex
- paper/generated/*.tex (abstract, system model, tables, results, algorithm)
- paper/figures/generated/*.pdf (publication figures)
- results/publication_package/*.md and publication_package.json (reproducibility)
- paper/reference_inventory.md (reference verification notes)

Compile:
1) Open a TeX environment that includes IEEEtran.cls.
2) From the paper/ folder, run:
   pdflatex manuscript.tex
   pdflatex manuscript.tex
   pdflatex manuscript.tex

Notes:
- Replace or confirm DOI/volume/pages for references marked as “verify via IEEE Xplore.”
- Confirm authors, affiliations, and contact emails are correct.

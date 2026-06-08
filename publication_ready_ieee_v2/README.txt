IEEE Submission Draft Package (v2)
==================================

This package contains the LaTeX source, generated tables, and publication
figures for an IEEE-style journal submission draft.

Contents:
- paper/manuscript.tex
- paper/generated/*.tex (abstract, system model, results, tables, algorithm)
- paper/figures/generated/*.pdf (publication figures)
- results/publication_package/* (reproducibility artifacts)
- paper/reference_inventory.md (reference metadata and verification notes)

Overleaf:
1) Upload the entire zip as a new project.
2) Set the main file to paper/manuscript.tex.
3) Compile with IEEEtran (default in Overleaf).

Notes:
- The introduction cites 20 references in numeric order with single citations.
- Some reference metadata are marked “verify via IEEE Xplore”; update those
  before final submission.

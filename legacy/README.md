# legacy/ — exploratory pre-paper analysis scripts

These scripts belong to **earlier exploratory experiment phases** (phase1,
phase1.5, phase1.6, phase2.2) that preceded the final energy cost model. They
are preserved here to document the full research process, but they are **not part
of the reproducible paper pipeline**:

- The raw data they consume (phase1/1.5/1.6/2.2 runs) is intentionally **not
  shipped** in this repository — see `.gitignore` and the README "Data
  Description" section — so running these scripts on a clean clone will fail with
  missing-file errors. That is expected.
- The scripts that reproduce the paper's figures live in
  [`scripts/analysis/`](../scripts/analysis) and [`analysis/`](../analysis); see
  the top-level [README](../README.md) "Reproducing the Paper".

| Script | Phase it analyzed |
|--------|-------------------|
| `comprehensive_analysis.py` | Phase 1 — host-level AI vs non-AI |
| `paper_figure.py`, `phase1_5_analysis.py`, `phase1.5_heavy_analysis.py`, `merge_all_data.py`, `merge_csv.py` | Phase 1.5 — early cgroup-based attribution |
| `phase1.6_analysis.py`, `phase1.6_analysis_v2.py`, `phase1.6_full_table.py`, `comprehensive_table.py`, `attribution_validation_chart.py`, `energy_attribution_validation.py` | Phase 1.6 — 2-workload (YOLO+Node.js) attribution & validation |
| `phase2.2_attribution_analysis.py`, `extract_phase2.2_data.py`, `extract_phase2_data.py`, `extract_fio_data.py` | Phase 2.2 — fixed/free-frequency attribution checks |

The final paper uses the 4-workload (YOLO / GPT2 / ResNet / Node.js) phase-3
experiments for attribution and validation.

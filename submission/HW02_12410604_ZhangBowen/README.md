# MA216 HW-02 package

Student: Zhang Bowen (张博文), 12410604.

T1–T15, A1–A5 and the independently audited Part III are assembled with actual outputs and full AI-use disclosure. The student confirmed the I3 pre-feedback attempts and reflection on October 11. The I1(b) post-session correction and re-derived passages remain explicitly disclosed. Review and understand the submitted material; no unaided authorship of the AI-assisted sections is asserted.

## Reproduction

Python 3.10+ is required. From this directory:

```text
python -m pip install -r requirements.txt
python -m pytest code/ -v
python code/experiments.py
python code/debug_checks.py ai_debug_exercise
python code/debug_checks.py ai_debug_repaired
python code/verify_part_iii.py
python code/build_report_tables.py
```

The original debugging check intentionally exits with code 1 and reports 0/8 passes. The repaired check exits with code 0 and reports 8/8 passes. The full test suite in this run gave 45 passes and no skipped tasks after the Part III regression tests; the earlier 37-pass run is preserved. Actual outputs are in `results/`.

Compile the report with a local LaTeX installation, from the **report directory**:

```text
cd report
pdflatex -interaction=nonstopmode -halt-on-error report.tex
pdflatex -interaction=nonstopmode -halt-on-error report.tex
```

Copy `report/report.pdf` to `12410604_ZhangBowen_HW-02.pdf` after rebuilding. No shell escape is required. Figures and CSVs are already included, so PDF compilation does not require re-running simulations. Editable source is `report/report.tex` with generated table fragments. `code/build_report_tables.py` reads actual CSV values rather than embedding hand-transcribed numeric tables.

## Files and provenance

- `code/student_tasks.py`: completed instructor interfaces; all experiments call these implementations.
- `code/experiments.py`: A1–A5 and I1 numerical evidence generator.
- `code/test_student_tasks.py`: unchanged supplied starter suite.
- `code/test_extended.py`: additional independent analytical and boundary tests.
- `code/ai_debug_exercise.py`: unchanged intentionally flawed supplied exercise.
- `code/ai_debug_repaired.py`: independently implemented repair checked against A5.
- `code/debug_checks.py`: actual before/after checks.
- `data/assignment_parameters.json`: unchanged supplied parameters.
- `results/A4_single_sum.csv`: separately generated first n=1000 sum.
- `results/A4_standardized_sums_n1000.csv`: required 10,000 saved standardized sums, used for both histogram and Q-Q.
- `results/A5_rmse_repetitions.csv`: all 100 independent repetition outputs.
- `results/environment.json`: actual versions, RNG stream allocation and statistical conventions.
- `figures/`: 11 original assessed figures, each in PNG and PDF format.
- `ai_logs/`: honest disclosure, audit evidence, debugging change log and completion guide.

No supplied illustrative uniform-sum figure or data was used as an assessed result. The master seed is 20260927. Child stream indices 0–8 are documented in the environment manifest. Sample variances use ddof=1; normal plotting positions are (i-0.5)/M; histogram heights are densities. No KDE is used.

Only the instructor-provided scaffolds, starter tests, original debugging file and assignment parameters were reused. Newly written code and report are AI-assisted drafts. No instructor reference implementation, paid API or external dataset was used.

The handout deadline is September 27, 2026 at 23:59 UTC+8. This local package was produced on October 10, 2026; any course extension or submission arrangement must be checked against the student's actual Blackboard record.

## October 11 integration

All supplied originals are preserved in `ai_logs/supplied_20261011/`. Rerun outputs and a separate integration audit identify actual mathematical errors, residual proposed-patch defects and recorded chronology confirmation. The revised declaration discloses Codex drafting of Parts I and II. The incompatible independent-authorship claims were corrected, and the student confirmed the I3 reflection and attempt chronology. See `ai_logs/INTEGRATION_AUDIT_20261011.md` and the completion guide.

The final revised records supersede the initial integration audit where explicitly noted in `ai_logs/FINAL_REVISION_20261011.md`. Private notes are omitted from the archive; disclosure remains. Rebuild the package with `python code/package_checks.py` followed by `python code/package_submission.py`.

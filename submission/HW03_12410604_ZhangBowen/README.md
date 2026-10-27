# HW03 question-by-question worked solutions

Current request: complete the remaining R1 reading requirement and package the worked solutions as `12410604_ZhangBowen_HW-03.zip`. The archive records the AI-assisted source consultation and does not attest personal reading.

- Chinese explanation: `report/chinese_worked_solutions.md`.
- English PDF: `12410604_ZhangBowen_HW-03.pdf`; editable source is `report/worked_solutions.tex` with its included fragments. A local build also produces `report/worked_solutions.pdf`.
- Theory T1–T8, A1–A3 actual final-count runs, an I1 audit using two independently prompted DeepSeek sessions (same-provider limitation disclosed), and I2 actual before/after repairs are included.
- R1 is a four-page source-based comparison of two books: Tsay, third edition, pp. 2–23, and Hull, Chapter 14. The assignment specifies Hull's eleventh edition; the complete text lawfully accessible here was a ninth-edition course copy, pp. 302–320. All Hull page and equation citations are therefore labelled as ninth-edition locations, section names are cross-checked against the eleventh-edition contents, and the eleventh edition's new §14.8 was not read. The edition deviation and AI assistance are disclosed.
- The student reported no earlier independent/pre-AI attempt. The saved initial I2 diagnosis is an assistant diagnosis, not a historical student record.

## Reproduction

Python 3.10+ and the packages in `requirements.txt` are needed. From this folder:

```text
python -m pip install -r requirements.txt
python -m pytest code/ -q
python code/returns_analysis.py --input <MSFT_prices.csv> --expected-hash ce807ba43ff39e775faebda202ad5d8476569efa74973284a93216fbae8eff9f
python code/experiments_gbm.py --run-tests
python code/debug_checks.py code/ai_debug_exercise.py --output results/I2_original_checks.json
python code/debug_checks.py code/ai_debug_proposed.py --output results/I2_proposed_checks.json
python code/debug_checks.py code/ai_debug_repaired.py --output results/I2_final_checks.json
python code/build_report.py
```

The original and first proposal intentionally return exit code 1 in the checks (1/11 and 8/11). The final repair returns 0 (11/11). The final complete pytest suite gave **111 passed, no skips**, including 44 additional repair checks. Actual execution records are under `results/`.

To rebuild the English PDF with a local TeX installation:

```text
cd report
pdflatex -interaction=nonstopmode -halt-on-error worked_solutions.tex
pdflatex -interaction=nonstopmode -halt-on-error worked_solutions.tex
```

The completed instructor entry point is `python code/run_student.py --input <MSFT_prices.csv>`. Without an input it explicitly records A1 as not run and runs A2/A3; this is not an assertion that A1 has been completed on substitute data. All original instructor files are retained under `source_instructor/`; no skipped scaffold test is collected as a pass.

## Frozen real input

MSFT adjusted close, USD, 2021-10-14 to 2026-10-14 inclusive; retrieved 2026-10-21. Local frozen data are at the workspace `data/hw03_private/MSFT_prices.csv`, with the original response alongside it. These private vendor data have not been copied into a submission archive. `data/provenance.json` provides the exact request, field, adjustment, retrieval time and hashes. Public historical access and `code/fetch_market_data.py --output <private-folder>` provide an access route; a later provider revision may have a different hash and must not silently replace the frozen input.

Sample variance uses n−1. Higher central-moment ratios use moments divided by n. Master seed 21603 creates separate child streams `(1,)` for A1 permutation, `(2,)` for A2, `(3,)` for A3 and `(4,)` for stress. No seed is reset within a replication loop. I2's standalone routine has its own documented default seed.

## AI records

I1 and I2 contain complete actual prompt/response exchanges. `ai_logs/AI_use_declaration.md` describes the scope and chronology. The runtime is DeepSeek; earlier draft labels naming OpenAI models were incorrect and are corrected throughout. The I1 audit used two independently prompted DeepSeek sessions, and the same-provider limitation is disclosed. Machine-readable visible-session exports exclude private reasoning, system/developer instructions and account metadata; the export index records cutoff times. No absent personal attempt or reading has been fabricated.

# Primary-source verification and implementation choices

Access date: 2026-10-20 (Asia/Shanghai).

## Published paper

Moreira, A., and Muir, T. (2017). *Volatility-Managed Portfolios*. *The Journal of Finance*, 72(4), 1611–1644. DOI: https://doi.org/10.1111/jofi.12513.

Primary copies: [Moreira-hosted PDF](https://amoreira2.github.io/alan-moreira.github.io/VolPortfolios_published.pdf); [Muir's published-version link](https://www.dropbox.com/s/4y24nnab001bd0l/JF_PublishedVersion_Moreira_Muir_2017.pdf?dl=0). The downloaded final pagination is used below.

| Location | Verified fact or numeric target |
|---|---|
| p. 1616, equations (1)–(2), footnote 6 | Prior-month centered daily squared returns are summed; inverse variance scales the next monthly excess return. Full-sample c equalizes unconditional standard deviations. |
| p. 1619, Table I, Panel A, Mkt column | Alpha 4.86; alpha SE 1.56; beta 0.61; beta SE 0.05; N 1,065; R² 0.37; RMSE 51.39. |
| p. 1619, Table I caption | Monthly returns multiplied by 12 and expressed in percent; heteroskedasticity-adjusted SE; main sample described as 1926–2015. |
| p. 1619, Table I, Panel B | FF3-controlled market alpha 5.45; SE 1.56. |
| p. 1622, Table II | Market original Sharpe 0.42; managed Sharpe 0.51; appraisal ratio 0.33. |
| p. 1626, Table V, Panel A | Baseline managed Sharpe 0.52; cap 1 alpha 2.12, SE 0.71, Sharpe 0.52; cap 1.5 alpha 3.10, SE 0.98, Sharpe 0.53. |

The paper's Tables II and V differ slightly in reported managed Sharpe. Keep both references explicit.

## Decisions that must remain visible

- Exact endpoint: the main-paper caption gives years only. **August 1926–April 2015 is an inference**, matching 1,065 monthly observations after the July 1926 initial variance month. Do not describe it as a verbatim date range from the authors.
- Operational realized variance: use actual calendar-month trading days and their arithmetic mean: `sum((daily_excess_return - month_mean)**2)`. Equation (2) uses 22 trading days as notation; the variable-day implementation is an explicit convention. A fixed-day-variance alternative changes month-specific relative weights and is a useful sensitivity, not an identical constant rescaling.
- White HC1 is a declared implementation of heteroskedasticity-adjusted inference; the paper does not specify HC0 versus HC1. HAC, if reported, is a robustness check.
- A fixed full-sample c preserves scale-invariant Sharpe and t-statistics but uses future information for absolute position size. Label this original replication convention. A subsequent evaluation with c estimated only in a prior training window is a separate chronological experiment.
- Cap the baseline exposure using the same c. Re-normalizing after the cap would undo the stated cap. A cost calculation based on `abs(weight.diff())` is a simplified target-weight turnover convention. The paper reports absolute weight changes but does not specify a drift equation.
- Report sampling/reconstruction differences without tuning the code to force the printed targets.

## Official data and vintage limitations

[French Data Library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html), [factor definitions](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/f-f_factors.html), and [CRSP changes](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/changes_crsp.html) are the primary documentation.

Current FF3 CSV downloads: [monthly](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_CSV.zip) and [daily](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_daily_CSV.zip). Raw download snapshots and hashes should be retained.

French reconstructs historical returns when updating data. Its main page documents the move from legacy FIZ to CIZ starting with the January 2025 release: CIZ compounds daily returns with dividends reinvested on ex-dates; legacy monthly returns reinvest dividends at month-end. Therefore neither a current download nor a 2024 FIZ archive is the authors' original 2015 vintage. A same-period FIZ/CIZ comparison measures a data-reconstruction sensitivity, not new-investment performance.

[Tyler Muir's data page](https://tylersmuir.com/data.html) links an [updated managed-factor CSV](https://tylersmuir.com/data/VolManagedFactors.csv). It begins January 1927 and is updated from French data; it is **not** advertised as the original 2017 paper vintage. It is supplementary source evidence, not a substitute for reconstructing the strategy.

## Acquisition audit

`agent-reach` search routing was attempted first; its Exa command runner (`mcporter`) was unavailable, so primary sources were located and verified with the available web search tool. The prescribed Jina read produced no content. The final published PDF was downloaded from the author's Dropbox link through the corresponding Dropbox content host. `agent-reach check-update` reported version 1.5.0 current.

Downloaded final PDF: 815,279 bytes, SHA-256 `f0c9f2099b083e6d8d0eba64eb0cedd49c3e4c47f0a51c2181f163252ce8a9b1`.

Local source-verification assets are in the workspace's `tmp/project2_sources/`: final PDF, Table I page image, formation-equation page image, official HTML snapshots, and Muir's current managed-factor CSV. The academic paper retains its authors' and publisher's rights.

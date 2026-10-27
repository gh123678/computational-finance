# R1 reading notes, sources, and comparison

**Status.** Four pages of English notes covering two different books are in `report/reading.tex` (PDF pp. 19--22). The notes are AI-assisted and record source-based close reading; they do not attest that the student personally completed the reading. All quoted locations were actually opened; all numerical checks were recomputed independently.

## Book 1: Tsay

Ruey S. Tsay, *Analysis of Financial Time Series*, third edition, Wiley, 2010, ISBN 9780470414354. Publisher public excerpt:
<https://catalogimages.wiley.com/images/db/pdf/9780470414354.excerpt.pdf>

Pages used: printed pp. 2--23 (S1.1 pp. 2--6; S1.2 pp. 7--22; S1.3 pp. 22--23). Table 1.3 on p. 24 was inspected. Chapter 2 was not used.

Concepts and assumptions: simple and log returns; exact time aggregation; sample variance with divisor n-1 and moment ratios with divisor n; marginal versus conditional distributions; empirical diagnostics without a normality or independence assumption.

Independent reconstruction: `1 + R_t = P_t/P_(t-1)` and `r_t = log(P_t/P_(t-1))`; telescoping gives the product rule for gross returns and the sum rule for log returns; two-period simple returns contain the cross term `R_1 R_2`. Derivation of why a marginal distribution cannot identify dependence: for `X_t = Z_t Z_(t-1)`, `Cov(X_t, X_(t-1)) = 0` but `Cov(X_t^2, X_(t-1)^2) = 2`.

Checked examples:

- Example 1.1, p. 6: `100(e^0.0446 - 1) = 4.56095324%`; `4.46 - 7.34 + 10.77 = 7.89%`; `100(e^0.0789 - 1) = 8.20961070%`; adding separately transformed monthly simple returns gives `8.85521777%`, exposing the cross term.
- Example 1.2, pp. 10, 13: `0.06139878 / sqrt(6/9845) = 2.487092723`, two-sided normal tail `p = 0.0128792`, matching the printed calculation.
- Mixture on pp. 17--18: weights `0.95, 0.05`, variances `1, 16` give variance `1.75`, fourth moment `41.25`, excess kurtosis `10.46938776`.

Course connections and questions: T1, T4, T8, A1. Open questions: subsample stability; conditional volatility; dividend-adjustment interpretation.

## Book 2: Hull

The assignment specifies John C. Hull, *Options, Futures, and Other Derivatives*, eleventh U.S. edition, Pearson, copyright 2022 (published 2021), ISBN 9780136939979, Chapter 14, S14.1--14.8 and the appendix.

Edition handling: a complete eleventh-edition chapter text was not lawfully accessible from this environment, and no unofficial full-book copy was used. The text actually read was a course copy of the same Chapter 14 in the **ninth-edition printing**, pp. 302--320 (S14.1 pp. 302--303; S14.2 pp. 303--308; S14.3 pp. 308--311; S14.4--14.5 pp. 311--312; S14.6 pp. 313--314; S14.7 pp. 314--315; appendix pp. 319--320). All page numbers are ninth-edition pages, and equation numbers are those printed in that copy; neither is attributed to the eleventh edition. Section names are cross-checked against the publisher's eleventh-edition contents, which add S14.8 on fractional Brownian motion. That section was not read. The deviation from the specified edition is disclosed.

Concepts and assumptions: Markov property and its relation to weak-form efficiency; Wiener process with `Delta z = xi sqrt(Delta t)` and independent increments; generalized Wiener and Ito processes; constant expected arithmetic return `mu` and volatility `sigma`; geometric Brownian motion; Ito's lemma; lognormal terminal law. Assumptions are independent normal increments, constant coefficients, and the Markov property.

Independent reconstruction: expand `G(S,t)` to second order; substitute `Delta S = mu S Delta t + sigma S xi sqrt(Delta t)`; use `E[xi^2] = 1` to show `(Delta S)^2 = sigma^2 S^2 Delta t + o(Delta t)` survives at order `Delta t`; hence `dG = (G_S mu S + G_t + 0.5 G_SS sigma^2 S^2) dt + G_S sigma S dz`. For `G = log S`, this gives `d log S = (mu - sigma^2/2) dt + sigma dz`, whose integral is normal with mean `(mu - sigma^2/2)T` and variance `sigma^2 T`.

Checked example: Example 14.3 and Table 14.1. With `mu = 0.15`, `sigma = 0.30`, `Delta t = 0.0192`, the coefficient is `0.30 sqrt(0.0192) = 0.0415692` (book: `0.0416`). First row: `0.288 + 0.0415692(100)(0.52) = 2.4496 ~ 2.45`. Second row: `0.2941 + 0.0415692(102.45)(1.44) = 6.4277 ~ 6.43`. Both match the book.

Course connections and questions: T5(a) square-root scaling; T5(b) log-drift correction; T6 moments and prediction interval; T7 almost-sure growth `mu - sigma^2/2`; A2 exact terminal sampling; A3 Euler update. Hull does not treat calibration error, volatility clustering, or nonpositive Euler multipliers.

## Cross-book comparison

- Notation: Tsay writes `P_t`, `R_t`, `r_t`; Hull writes `S_t`, `mu`, `sigma`, `dz`. Hull's `mu` is the expected arithmetic return; the annual log drift is `m = mu - sigma^2/2`. With spacing `h`, `E r_i = mh`, `Var r_i = sigma^2 h`, and `E(e^r_i - 1) = e^(mu h) - 1`.
- Assumptions: Tsay's aggregation is an identity and his distributional discussion is empirical; Hull imposes independent normal increments, constant parameters, and Markov structure.
- Methods: Tsay diagnoses sample marginals, tails, and ACFs; Hull derives analytic moments and simulates paths. A1's diagnostics can reject a fitted i.i.d.-normal description but cannot identify the true law; A2's exact sampler removes discretization error only within the assumed model.
- Course conclusion: Tsay supplies the diagnostics, Hull supplies the model and numerical target; neither establishes weak-form efficiency or that real prices follow GBM.

## Remaining questions

Dividend/split adjustment and total-return interpretation; separation of sampling noise, parameter instability, and conditional heteroskedasticity in A1; model uncertainty beyond T8's plug-in standard error; distinction between a fixed 95% prediction interval and a Monte Carlo confidence interval; positivity and discretization bias of Euler schemes.

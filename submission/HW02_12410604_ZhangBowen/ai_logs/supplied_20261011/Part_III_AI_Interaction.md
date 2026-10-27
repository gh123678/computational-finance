# MA216 Homework 2 -- Part III: AI Interaction

Name: [enter locally]   Student ID: [enter locally]
Course: MA216 Computational Finance, Fall 2026

## Setup and provenance

Two distinct large language models were used, run in separate sessions of the
same CLI host (Claude Code) with the provider switched between sessions using
CC Switch (cc-switch):

- **Model A** -- Kimi provider; session of 2026-10-10; browsing unavailable;
  local code execution available (Python 3 / NumPy 2.4.6 / SciPy 1.16.3).
- **Model B** -- DeepSeek provider; session of 2026-10-11; browsing unavailable;
  local code execution available (same environment).

Neither interface disclosed an exact model version string; each is therefore
recorded as "not disclosed" together with the provider. All numeric results
below were produced by the student's own scripts using master seed 20260927
and are reproduced in `ai_logs/`. No identifying information was sent to either
model. Complete transcripts for I1--I3 (both models) are in `ai_logs/`.

---

## I1. Cross-model claim audit (6 pts)

Both models received the same four statements and were asked to classify each
as valid, invalid, or requiring qualification, with assumptions and
justification. Two substantive follow-ups were made per model, at least one
tied to a specific detail of that model's actual response.

### Audit table

| Claim | Model A (Kimi) | Model B (DeepSeek) | My final judgment | Independent evidence |
|---|---|---|---|---|
| **I1-a** nonnegative butterfly payoff guarantees positive profit | invalid | invalid | **invalid** | Financed profit `Pi_T = B_T - V0 e^{rT}`. With strikes 40/50/60 and premiums 12/5/2: cost = 4, financed = 4.2051, max payoff = 10 at S_T = 50, but profit = -4.2051 at S_T = 0/40/60/100. No-arbitrage forces `V0 > 0`, so the loss states (positive probability) give negative profit. |
| **I1-b** `D0(1+rc·t/m)^m` after t years | invalid except at t=1 | invalid for t≠1 | **invalid except t=1** | Correct annual-frequency form is `D0(1+rc/m)^{mt}` (T4a). The stated `D0(1+rc·t/m)^m` puts `t` in the rate and keeps exponent `m`, which T4(c) flags as inconsistent with `m` = annual frequency; it matches only at `t=1`. At t = 2, m = 12: stated 11047.13 vs correct 11049.41 (continuous exact 11051.71); at t = 1 both equal 10511.62, so t=1-only testing hides the error. |
| **I1-c** fixed n, larger M makes Z_n exactly Gaussian; bell histogram proves it | invalid | invalid | **invalid** | CLT is a limit in n. At n = 5 with Exp(1) summands, Z_n is standardized Gamma(5,1): skewness 2/sqrt(5) = 0.8944, and the sample skewness stays 0.88-0.89 for M = 1e3…1e6 (no drift to 0). M only shrinks Monte-Carlo noise; a bell shape is a diagnostic, not a proof. |
| **I1-d** `-log(U)/λ` and `-log(1-U)/λ` are the same law but differ pointwise | valid (endpoint caveats) | valid (endpoint caveats) | **valid** | Since `1-U ~ U(0,1)`, both are inverse-CDF transforms: `P(-log(1-U)/λ ≤ x) = 1-e^{-λx}`. From one U-stream (N=2e5, λ=2): KS 0.00155 for both vs 5% critical 0.00304; pointwise-equal fraction 1e-5; `-log(U)` needs a U=0 guard; `-log(1-U)` truncates above ≈36.74/λ. |

### Independent verification (hand derivation / counterexample / numeric test)

- **Hand counterexample (I1-a):** the butterfly is a tent function, zero on
  `S_T ≤ E1` and `S_T ≥ E3`. A nonnegative, non-identically-zero payoff priced
  with `V0 ≤ 0` would be an arbitrage (free nonnegative cash flow, strictly
  positive with positive probability); hence `V0 > 0` and `Pi_T < 0` on those
  rays. Confirmed numerically in `I1_numerical_test.py`, block (a).
- **Numeric test (I1-b):** `I1_numerical_test.py`, block (b), D0=10000,
  rc=0.05, t=2, m∈{1,2,4,12,52,365}: the stated `D0(1+rc·t/m)^m` under-accumulates
  by a small, m-dependent amount (25.00 at m=1, 2.28 at m=12, 0.08 at m=365),
  and coincides with the correct `D0(1+rc/m)^{mt}` at t=1.
- **Numeric test (I1-c):** `I1_numerical_test.py`, block (c); skewness ≈ 0.894
  for all M, confirming M ≠ n.
- **Numeric test (I1-d):** `I1_numerical_test.py`, block (d); both KS
  statistics below the 5% critical value; `log1p` identical to the naive form.

### Non-AI reference consulted

H. Pishro-Nik, *Introduction to Probability, Statistics, and Random Processes*,
Section 7.1.2 (CLT stated as convergence in distribution, not finite-n
normality): <https://www.probabilitycourse.com/chapter7/7_1_2_central_limit_theorem.php>.

### Model comparison (211 words)

Model A (Kimi) and Model B (DeepSeek) reached identical verdicts on all four
statements: (a) invalid, (b) invalid except at t = 1, (c) invalid,
(d) valid with endpoint qualifications. Agreement is not suspicious here --
the statements are objectively decidable, and both models independently
produced the same counterexamples, so no correct response needed relabeling.

The models differed in emphasis. On (a), Model B gave the sharper
no-arbitrage argument for why V0 > 0 is forced, separating the sign of the
payoff from the measure-dependent expectation; Model A led with the numeric
profit table. On (b), Model A located the fault at the misplaced t (it sits in
the rate rc·t/m instead of the exponent mt); Model B tied it directly to
T4(c)'s inconsistency and T4(b)'s total-periods convention
r~c = (N/t)(e^{rt/N} - 1). On (c), both
separated the limit in n from M as a replication count; Model B quantified the
Monte-Carlo skewness noise as sqrt(6/M), Model A only noted the direction. On
(d), both flagged the U = 0 hazard and the log1p point; Model B added the
float64 truncation value 36.74/λ and the antithetic-pairing remark.

Both responses were correct as written. My independent derivations and the
shared numerical test (seed 20260927) match both, so the transcripts reinforce
rather than contradict each other.

*Full transcripts: `ai_logs/I1_modelA_*_log.md`, `ai_logs/I1_modelB_*_log.md`;
audit CSV: `ai_logs/I1_audit_table.csv`.*

---

## I2. AI-assisted debugging with tests (5 pts)

The supplied `code/ai_debug_exercise.py` runs but is unreliable. It was
preserved unchanged as the "before" artifact.

### Pre-AI hypotheses (recorded before any model query)

By hand for S0=E=100, u=1.2, d=0.8, r=0.05, T=1: p* = 0.6281777, exact call
11.9508, exact put 7.0738, parity C-P = 4.8771. The original prints
price = -13.72, so a sign/masking error is certain. Hypotheses: (1) hardcoded
probability 0.65; (2) inverted event inequality; (3) payoff uses min instead of
max; (4) discounting sign flipped; (5) standard error divided by N not sqrt(N);
(6) no parameter validation.

### Checks designed before the AI query (`ai_logs/I2_checks.py`)

C1 analytical benchmark (|MC - 11.9508| ≤ 4·SE); C2 no-arbitrage bounds
[4.8771, 100]; C3 invalid-input rejection (e^{rT} ∉ (d,u); d>u; paths ≤ 0);
C4 discounting direction (rate=0 ⇒ price = E[payoff]); C5 SE scaling (4× paths
halves the SE).

### Before / after test output (actual runs)

| Check | Original file | Repaired file (both models) |
|---|---|---|
| C1 benchmark | FAIL (price -13.7071 vs exact 11.9508) | PASS (11.9775 within 4·SE=0.1162) |
| C2 bounds | FAIL (negative price) | PASS |
| C3 invalid inputs | 3 of 4 FAIL (no error) | PASS (all raise ValueError) |
| C4 rate=0 direction | FAIL (-12.97 vs 10.0000) | PASS (9.9731 vs 10.0000) |
| C5 SE scaling | FAIL (ratio 4.03 per 4× paths) | PASS (ratios 2.01, 2.00) |

Raw outputs: `ai_logs/I2_checks_before.txt`, `_after.txt` (Model A),
`_modelB_after.txt` (Model B).

### Defects and final change log

| # | Defect | Repair | Status |
|---|---|---|---|
| D1 | `probability = 0.65` hardcoded | risk-neutral `p* = (e^{rT}-d)/(u-d)` | accepted |
| D2 | `rng.random(paths) > p` | `<= p` | accepted |
| D3 | `np.minimum(terminal-strike, 0)` | `np.maximum(..., 0)` | accepted |
| D4 | `exp(+rT) * payoff.mean()` | `exp(-rT) * payoff.mean()` | accepted |
| D5 | `std(ddof=0)/paths` | `std(ddof=1)/sqrt(paths)` on discounted payoffs | accepted |
| D6 | no validation | `_validate()` enforcing 0<d<e^{rT}<u, positive spot/strike/paths | accepted |

Change log: the first patch passed C1-C5; a more challenging test set was then
added (`I2_extra_tests.py`): E1 paired put-call parity (4.9047 ± 0.0806 covers
4.8771); E2 exact replication equations (Δ=0.5, B0=-38.0492, V0=11.950823 =
exact; both terminal equations hold); E3 50-repetition CI coverage at N=1000
gives 47/50 -- one miss is not evidence of a bug. Accepted/revised/rejected:
D1-D6 accepted; the discounted-payoff SE and the `<=` choice accepted and
verified numerically (independent recomputation of e^{-rT}·raw std/√N matches
to 1e-12); the `expm1`-based p* robustness was recorded as a limitation rather
than implemented (immaterial for the assigned parameters). Both models'
repaired pricers agree with each other's exact prices to 1e-9.

*Files: `ai_logs/I2_repaired_pricer.py` (Model A),
`ai_logs/I2_repaired_pricer_modelB.py` (Model B),
`ai_logs/I2_extra_tests.py`; transcripts `ai_logs/I2_model*_log.md`.*

---

## I3. Socratic examination rehearsal (4 pts)

Two new questions were requested per model, one from each topic group (options
/ no-arbitrage; probability / limit theorems), with changed parameters and with
solutions withheld. Each attempt was written and saved before feedback.

### Model A questions (Kimi)

**A-i (one-period replication).** S0 = 80, u = 1.25, d = 0.9, r = 0.04,
T = 0.5; a derivative pays H_u = 30, H_d = 5. *(a)* verify no-arbitrage;
*(b)* find (Δ, B0) and V0; *(c)* compute p*; *(d)* assess pricing by the
discounted real-world expectation with P(up) = 0.6.

**A-ii (inverse transform + MC).** X with f(x) = 3x² on [0,1]: *(a)* invert
the CDF and give a sampler; *(b)* find μ, σ²; *(c)* give the MC SE, a 95% CI,
and the smallest N with SE ≤ 0.005; *(d)* assess "normal at N = 10".

*Verified final answers:* A-i: p* = 0.343432, Δ = 0.892857, B0 = -58.1118,
V0 = 13.3168 (replication and p*-forms agree to 1e-6); real-world recipe gives
19.604 ≠ V0. A-ii: F(x)=x³, X=U^{1/3}; μ=3/4, σ²=3/80=0.0375; SE=σ/√N,
N ≥ 1500. At N=10 the sample mean has skewness -0.277 ≠ 0, so "basically
normal" is wrong.

### Model B questions (DeepSeek)

**B-i (digital payoff).** S0 = 120, u = 1.15, d = 0.85, r = 0.03, T = 2;
a digital pays 20 (up) / 0 (down).

**B-ii (logistic).** f(x) = e^{-x}/(1+e^{-x})²: invert, find μ, σ², N for
SE ≤ 0.02, and assess normality at N = 10.

*Verified final answers:* B-i: p* = 0.706122, Δ = 0.555556, B0 = -53.3667,
V0 = 13.3000; real-world recipe gives 9.4176 ≠ V0. B-ii: F(x)=1/(1+e^{-x}),
X = log(U/(1-U)), μ = 0, σ² = π²/3, N ≥ 8225. At N = 10 the mean is symmetric
(skewness ≈ 0) but has excess kurtosis ≈ 0.12 (logistic has 6/5; measured
0.124), so the finite-N error is visible through kurtosis, not skewness.

### Feedback that changed my work

- Model A challenged my (A-i(d)) treatment: the primary object is the
  replication price; risk-neutral valuation is a corollary, so the real-world
  probability is irrelevant to price.
- Model B corrected my (B-ii(d)): I had claimed symmetry gives fast normal
  convergence; the model showed symmetry only removes skewness while the
  finite-N deviation lives in the excess kurtosis. The N = 10 simulation
  confirmed it.

### Reflection

This rehearsal shows what I can now do unaided: check the no-arbitrage
condition d < e^{rT} < u; solve the two-state replication system for any
terminal payoff (call, put, or digital); convert between the replication price
and the discounted risk-neutral expectation and argue why the real-world
probability does not enter the price; invert a CDF to build a sampler for a
non-textbook density; and size a Monte-Carlo run from SE = σ/√N, including
inverting it to N ≥ σ²/target².

The most useful correction was on normality at finite N. I had implicitly
treated "symmetric, so the CLT converges fast" as sufficient; the models
showed that symmetry only kills skewness, while the finite-N error of the mean
appears in the excess kurtosis -- confirmed by simulation (skewness ≈ 0,
excess kurtosis 0.12 at N = 10). This is a sharper mental model than "the CLT
makes it normal".

What remains uncertain: choosing N when the estimand is a quantile or a
coverage probability rather than a mean; handling near-arbitrage parameters
where p* suffers catastrophic cancellation; and executing all of the above
under exam time pressure. The AI was useful as an examiner that forced precise
language, but every generated question and every code patch was independently
checked before I relied on it.

*Files: `ai_logs/I3_modelA_*_log.md`, `ai_logs/I3_modelB_*_log.md`;
verification `ai_logs/I3_verification_output.txt`,
`ai_logs/I3_modelB_verification_output.txt`.*

---

## Reproducibility manifest (Part III artifacts)

Environment: Python 3 (Anaconda), NumPy 2.4.6, SciPy 1.16.3; master seed
20260927. All commands run from `ai_logs/`:

```
python I1_numerical_test.py                      # I1 numeric evidence
python I2_checks.py ai_debug_exercise            # I2 before: failures
python I2_checks.py I2_repaired_pricer           # I2 after (Model A): all pass
python I2_checks.py I2_repaired_pricer_modelB    # I2 after (Model B): all pass
python I2_extra_tests.py                         # I2 challenging tests
python I3_... / I3_modelB ...                    # I3 verification (see logs)
```

Supplied illustrative material (`figures/illustrative_*.pdf`,
`code/make_illustrations.py`) is presentation-only and is NOT reported as my
result. The A4 assessment data (n=1000 sample, four histograms, Q-Q plot) is
produced in Part II, not here.

## AI-use declaration

See `ai_logs/ai_use_declaration_filled.md`. Assistance outside Part III is
disclosed there as well, together with the authenticity statement.

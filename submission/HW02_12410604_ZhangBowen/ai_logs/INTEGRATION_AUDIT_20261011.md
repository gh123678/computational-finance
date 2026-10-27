# Initial-snapshot integration audit — October 11, 2026

**Historical snapshot:** this audit describes the first files received. The latest I1(b) correction and full-code I2 records supersede the earlier omissions; see `FINAL_REVISION_20261011.md`. Observed mathematical/code corrections remain valid.

The user's desktop originals remain unchanged. All supplied files are preserved byte-for-byte in `supplied_20261011/`, including their original claims and disclosures. Corrections are separate annotations, not purported new model replies.

## Provenance

The student directly confirms that Model A was Claude Code connected to Kimi's API. The supplied Model A headers say Anthropic/Claude, while the overview says Kimi. Record the student's confirmation and preserve the discrepancy. Model B is described as DeepSeek in the supplied records; exact versions are not consistently evidenced.

The I2 formatted logs contain placeholders for code prompts and responses rather than verbatim text. The README explicitly calls the I3 pre-feedback attempts examples. Raw exports and genuine prior attempts are therefore still required. No raw conversation-store access or identity proof was inferred from file names.

## Verified findings

1. I1(b) in the logs is `D0(1+rc/m)^m`; the handout says `D0(1+rc*t/m)^m`. The assigned expression at t=2,m=12 gives 11047.130674 versus correct 11049.413356. Both models must receive the actual statement with required follow-ups; their altered-prompt responses cannot be edited into an interaction that did not occur.
2. A nonzero nonnegative payoff needs positive-probability support for a strictly positive-price argument. The logs' universal loss-state probability claims are not justified by the stated distribution-free assumptions.
3. The two exponential transforms using the same uniform are antithetic. The supplied Model B response initially denies this, then partly contradicts itself. Independent covariance is negative.
4. The supplied KS routine misses the left empirical-CDF limit; its reported equality fraction uses `isclose`. Separate reruns use a genuine two-sided distance and exact equality.
5. The original I1 and I2 scripts reproduce their printed outputs. Their benchmark suites passing does not prove complete model-domain handling.
6. Both proposed repairs accept nonfinite spot and nonpositive maturity; a single path produces undefined sample SE. They reject allowed zero strike and silently interpret invalid exact-option kinds as puts. The independently implemented final code handles these domains; eight new regression cases pass.
7. Pairing does not remove stock randomness from call-minus-put in this model. Here call and put are negatively correlated and paired-difference SE is twice the call SE.
8. A zero-rate check cannot discriminate the two discounting signs. A nonzero-rate, seed-matched reconstruction does.
9. Beta(3,1) skewness is -0.860662966, and the mean at N=10 has skewness -0.272165527. Model A's -0.639 / -0.20 feedback numbers are wrong. The logistic variance and fourth moment are independently checked by quadrature.
10. I3 output files have no supplied generating scripts. `python I3_...` is not a reproduction command. Added analytic/quadrature checks do not claim to reconstruct unknown simulation streams.

## Actual execution and final disclosure

Original rerun outputs are in the parent `ai_logs/` directory. Independent checks and numerical values are in `results/part_iii_independent_verification.json`. The expanded meaningful test suite reports **45 passed**. The earlier 37-pass run remains preserved as its actual earlier output.

The supplied declaration asserts unaided T1–T15 and self-written A1–A5, contrary to the AI drafting used for this package. The package's revised declaration discloses OpenAI/Codex assistance and does not certify prior unaided attempts or the student's understanding. The supplied reflection is retained as a draft awaiting the student's review; it is not substituted for actual learning evidence.

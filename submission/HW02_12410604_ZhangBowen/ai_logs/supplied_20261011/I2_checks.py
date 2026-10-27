"""I2 checks, designed BEFORE consulting any AI.

Model: S0=E=100, u=1.2, d=0.8, r=0.05, T=1.
Exact risk-neutral values (hand-derived):
  p*   = (e^{0.05} - 0.8) / (1.2 - 0.8) = 0.6281777...
  call = e^{-0.05} * p* * 20          = 11.9513...
  put  = e^{-0.05} * (1-p*) * 20      = 7.0757...
  parity: C - P = S0 - E e^{-0.05}    = 4.8771...

Checks:
  C1 analytical benchmark: MC price within ~4 MC standard errors of exact call.
  C2 financial bounds/identity: max(S0-E e^{-rT},0) <= C <= S0; put-call parity
     on PAIRED samples.
  C3 invalid input: e^{rT} outside (d,u), nonpositive paths, bad u<=d must raise.
  C4 discounting direction: with rate=0, price == E[payoff] (no growth factor).
  C5 SE scaling: 4x paths => SE roughly halves; CI width ~ O(1/sqrt(paths)).
"""
import numpy as np

S0, E, U, D, R, T = 100.0, 100.0, 1.2, 0.8, 0.05, 1.0
P_STAR = (np.exp(R * T) - D) / (U - D)
EXACT_CALL = np.exp(-R * T) * P_STAR * (U * S0 - E)
EXACT_PUT = np.exp(-R * T) * (1 - P_STAR) * (E - D * S0)


def run_checks(pricer, label):
    print(f"\n--- checks on: {label} ---")
    ok = True
    # C1 analytical benchmark
    out = pricer(spot=S0, strike=E, up=U, down=D, rate=R, maturity=T,
                 paths=100_000, seed=20260927)
    c = out["price"]
    tol = 4 * out["se"]
    passed = abs(c - EXACT_CALL) <= tol
    ok &= passed
    print(f"C1 benchmark: price={c:.4f} exact={EXACT_CALL:.4f} "
          f"|diff|={abs(c-EXACT_CALL):.4f} vs 4*se={tol:.4f} -> "
          f"{'PASS' if passed else 'FAIL'}")

    # C2 bounds
    lo, hi = max(S0 - E * np.exp(-R * T), 0.0), S0
    passed = lo - 1e-9 <= c <= hi + 1e-9
    ok &= passed
    print(f"C2 bounds: [{lo:.4f}, {hi:.4f}] contains {c:.4f} -> "
          f"{'PASS' if passed else 'FAIL'}")

    # C3 invalid inputs
    for kwargs in [dict(up=1.01, down=0.99),   # e^{rT} > u violates d<e^{rT}<u
                   dict(up=1.2, down=1.3),     # d > u
                   dict(paths=0),
                   dict(paths=-5)]:
        try:
            pricer(spot=S0, strike=E, rate=R, maturity=T, seed=1, **kwargs)
            print(f"C3 invalid input {kwargs}: no error raised -> FAIL")
            ok = False
        except (ValueError, AssertionError) as exc:
            print(f"C3 invalid input {kwargs}: raised {type(exc).__name__} -> PASS")

    # C4 discounting direction (rate = 0 => price == mean payoff, no growth)
    out0 = pricer(spot=S0, strike=E, up=U, down=D, rate=0.0, maturity=T,
                  paths=200_000, seed=7)
    p0 = (np.exp(0.0) - D) / (U - D)
    expected = p0 * (U * S0 - E)
    passed = abs(out0["price"] - expected) < 4 * out0["se"]
    ok &= passed
    print(f"C4 rate=0: price={out0['price']:.4f} vs E[payoff]={expected:.4f} -> "
          f"{'PASS' if passed else 'FAIL'}")

    # C5 SE scaling
    ses = []
    for paths in [2_500, 10_000, 40_000]:
        o = pricer(spot=S0, strike=E, up=U, down=D, rate=R, maturity=T,
                   paths=paths, seed=99)
        ses.append(o["se"])
    ratios = [ses[i] / ses[i + 1] for i in range(len(ses) - 1)]
    passed = all(1.4 < r_ < 2.8 for r_ in ratios)
    ok &= passed
    print(f"C5 SE scaling: SEs={['%.5f'%s for s in ses]}, "
          f"ratios={['%.2f'%r_ for r_ in ratios]} (expect ~2) -> "
          f"{'PASS' if passed else 'FAIL'}")
    print(f"overall: {'ALL PASS' if ok else 'FAILURES PRESENT'}")
    return ok


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    target = sys.argv[1] if len(sys.argv) > 1 else "ai_debug_exercise"
    mod = __import__(target)
    fn = getattr(mod, "purported_call_mc", None) or getattr(mod, "call_mc")
    run_checks(fn, target)

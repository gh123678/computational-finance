"""I1 numerical test: reproducible checks for the four audited claims.

Seed: 20260927 (as suggested by the assignment).
Run: python I1_numerical_test.py
"""
import numpy as np

rng = np.random.default_rng(20260927)

print("=" * 70)
print("Claim (a): nonnegative butterfly payoff vs. financed profit")
print("=" * 70)
# Strikes 40/50/60, hypothetical premiums C(40)=12, C(50)=5, C(60)=2, r=0.05, T=1
E1, E2, E3 = 40.0, 50.0, 60.0
r, T = 0.05, 1.0
cost = 12.0 - 2 * 5.0 + 2.0          # net premium paid at t=0
financed = cost * np.exp(r * T)      # carried to expiry
S = np.array([0.0, 40.0, 45.0, 50.0, 55.0, 60.0, 100.0])
B = np.maximum(S - E1, 0) - 2 * np.maximum(S - E2, 0) + np.maximum(S - E3, 0)
profit = B - financed
print(f"net premium cost = {cost:.4f}, financed to T = {financed:.4f}")
print(f"max payoff = {B.max():.1f} at S_T = {S[np.argmax(B)]:.0f}")
for s, b, p in zip(S, B, profit):
    print(f"  S_T={s:6.1f}  payoff={b:5.1f}  financed profit={p:+8.4f}")
be_low = E1 + financed
be_high = E3 - financed
print(f"break-even prices: {be_low:.4f} and {be_high:.4f}")
print("=> payoff >= 0 everywhere, but profit < 0 outside "
      f"[{be_low:.2f}, {be_high:.2f}]. Claim (a) is INVALID.")

print()
print("=" * 70)
print("Claim (b): statement D0(1+rc*t/m)^m vs correct D0(1+rc/m)^(m*t), t=2")
print("=" * 70)
D0, rc, t = 10_000.0, 0.05, 2.0
exact = D0 * np.exp(rc * t)
for m in [1, 2, 4, 12, 52, 365]:
    stated = D0 * (1 + rc * t / m) ** m      # claim (b) formula: t sits in the rate
    right = D0 * (1 + rc / m) ** (m * t)     # correct annual-frequency formula (T4a)
    print(f"  m={m:3d}  stated={stated:12.4f}  correct={right:12.4f}  "
          f"exact(cont.)={exact:12.4f}  stated-correct={stated - right:+9.4f}")
print("At t=1 the stated form coincides with the correct one (mt = m):")
print(f"  t=1, m=12: stated = {D0 * (1 + rc * 1 / 12) ** 12:.4f}"
      f"  correct = {D0 * (1 + rc / 12) ** 12:.4f}")
print("Both forms also converge to the continuous limit D0*exp(rc*t) as m -> inf,")
print("which is why the stated form looks plausible. Claim (b) is INVALID for t != 1.")

print()
print("=" * 70)
print("Claim (c): fixed n, increasing M -- does the distribution become")
print("exactly Gaussian?")
print("=" * 70)
# Z_n from sums of n Exp(1) variables; true skewness = 2/sqrt(n) for any M.
def z_sample(n, M, rng):
    X = rng.standard_exponential((M, n))
    return (X.sum(axis=1) - n) / np.sqrt(n)

n = 5
true_skew = 2.0 / np.sqrt(n)   # Gamma(n,1) standardized skewness
for M in [1_000, 10_000, 100_000, 1_000_000]:
    z = z_sample(n, M, rng)
    m3 = np.mean((z - z.mean()) ** 3)
    sk = m3 / z.std() ** 3
    se_sk = np.sqrt(6.0 / M)   # rough normal-theory SE of sample skewness
    print(f"  n={n}, M={M:>9,}: sample skewness = {sk:+.4f} "
          f"(theory {true_skew:+.4f}, approx SE {se_sk:.4f})")
print("Skewness stays near 2/sqrt(n) = 0.894 as M grows: larger M estimates the")
print("TRUE (non-normal) distribution more precisely; it does not make it normal.")
print("Claim (c) is INVALID (also: a bell-shaped histogram is only a diagnostic).")

print()
print("=" * 70)
print("Claim (d): -log(U)/lam and -log(1-U)/lam from the SAME U stream")
print("=" * 70)
lam = 2.0
N = 200_000
U = rng.random(N)              # in [0,1)
X1 = -np.log(1.0 - U) / lam    # inverse-CDF form (log1p equivalent below)
X1b = -np.log1p(-U) / lam
X2 = -np.log(U) / lam if U.min() > 0 else None
# handle U=0 explicitly for the -log(U) form: redraw zeros (measure-zero event)
U2 = U.copy()
U2[U2 == 0.0] = np.nextafter(0.0, 1.0)
X2 = -np.log(U2) / lam

def ks_stat(x, lam):
    xs = np.sort(x)
    cdf_emp = np.arange(1, len(xs) + 1) / len(xs)
    cdf_the = 1 - np.exp(-lam * xs)
    return np.max(np.abs(cdf_emp - cdf_the))

ks1, ks2 = ks_stat(X1, lam), ks_stat(X2, lam)
crit = 1.36 / np.sqrt(N)   # approx 5% KS critical value
print(f"  KS(-log(1-U)/lam vs Exp(2)) = {ks1:.5f}  (5% crit {crit:.5f})")
print(f"  KS(-log(U)/lam   vs Exp(2)) = {ks2:.5f}  (5% crit {crit:.5f})")
print(f"  mean: {X1.mean():.5f} vs {X2.mean():.5f} (theory {1/lam:.5f})")
same = np.mean(np.isclose(X1, X2))
print(f"  fraction of pointwise-equal values from the same U: {same:.6f}")
print(f"  log1p vs naive near U=0: max |X1b-X1| = {np.max(np.abs(X1b-X1)):.3e}")
print("Both transforms are Exp(2) marginally but differ pointwise.")
print("Claim (d) is VALID (with endpoint care: U=0 must not reach log).")

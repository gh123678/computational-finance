"""I2 extra challenging test (added after the first patch passed C1-C5).

E1: paired Monte Carlo put-call parity -- same terminal states for call and put.
E2: replication equations of the exact prices (Delta, B0 from T15(b)).
E3: seed sensitivity -- two different seeds must both cover the exact price
    most of the time (spot check of the CI machinery, not a proof).
"""
import numpy as np
from I2_repaired_pricer import p_star, exact_price, _validate

S0, E, U, D, R, T = 100.0, 100.0, 1.2, 0.8, 0.05, 1.0

# E1 paired parity
rng = np.random.default_rng(20260927)
N = 200_000
p = p_star(U, D, R, T)
terminal = np.where(rng.random(N) <= p, U * S0, D * S0)
disc = np.exp(-R * T)
paired = disc * (np.maximum(terminal - E, 0) - np.maximum(E - terminal, 0))
lhs = paired.mean()
lhs_se = paired.std(ddof=1) / np.sqrt(N)
rhs = S0 - E * disc
print(f"E1 paired parity: C-P estimate={lhs:.4f} +- 1.96*{lhs_se:.4f}, "
      f"S0-Ee^{{-rT}}={rhs:.4f}, covered={abs(lhs-rhs) <= 1.96*lhs_se}")

# E2 replication of exact call
Cu = max(U * S0 - E, 0.0)
Cd = max(D * S0 - E, 0.0)
Delta = (Cu - Cd) / ((U - D) * S0)
B0 = np.exp(-R * T) * (Cu - Delta * U * S0)
V0 = Delta * S0 + B0
exact_c = exact_price(S0, E, U, D, R, T, "call")
print(f"E2 replication: Delta={Delta:.4f}, B0={B0:.4f}, V0={V0:.6f}, "
      f"exact={exact_c:.6f}, match={np.isclose(V0, exact_c)}")
up_ok = np.isclose(Delta * U * S0 + B0 * np.exp(R * T), Cu)
dn_ok = np.isclose(Delta * D * S0 + B0 * np.exp(R * T), Cd)
print(f"   terminal equations: up_state={up_ok}, down_state={dn_ok}")

# E3 CI coverage spot check, 50 repetitions at N=1000
cover = 0
for s in range(50):
    r_ = np.random.default_rng(10_000 + s)
    term = np.where(r_.random(1000) <= p, U * S0, D * S0)
    dp = disc * np.maximum(term - E, 0)
    m, se = dp.mean(), dp.std(ddof=1) / np.sqrt(1000)
    cover += abs(m - exact_c) <= 1.96 * se
print(f"E3 CI coverage at N=1000 over 50 reps: {cover}/50 "
      f"(expect about 47-48; one miss is not evidence of a bug)")

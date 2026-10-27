"""I2: deliberately flawed, instructor-authored teaching code. Preserve this original.
No claim is made that an AI generated this file. Diagnose it before requesting feedback.
"""
import numpy as np


def terminal_report(s0=100., mu=.08, sigma=.3, horizon=2., count=100000, seed=21603):
    rng = np.random.default_rng(seed)
    z = rng.standard_normal(count)
    samples = s0 * np.exp(mu*horizon + sigma*horizon*z)
    average = float(samples.mean())
    se = float(samples.std(ddof=0)/count)
    return {"mean": average, "variance": float(samples.var(ddof=0)),
            "se": se, "prediction_interval": [average-1.96*se, average+1.96*se]}


if __name__ == "__main__":
    print(terminal_report())

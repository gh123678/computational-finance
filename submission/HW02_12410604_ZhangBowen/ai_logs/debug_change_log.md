# Debugging change log and provenance

The original exercise is unchanged and intentionally authored to contain defects. It is not output from a named AI model.

This session's inspection and implemented changes:

| Original defect | Accepted repair | Independent evidence |
|---|---|---|
| Fixed probability 0.65 | `(exp(r*T)-down)/(up-down)` | Two-state martingale/replication formula; reconstructed draws against A5 |
| Up event `U > p` | `U < p` | Same seed draws match A5's price |
| `minimum(ST-K,0)` | `maximum(ST-K,0)` | Nonnegative call bounds; zero payoff above both states |
| Positive exponent in price | Discount each payoff with `exp(-r*T)` | Hand-replicated exact price and identical discounted sample calculation |
| Raw-payoff population SD divided by N | Discounted-payoff sample SD divided by sqrt(N) | Direct sample-SE reconstruction and 30 repetitions at two sizes |
| No valid-tree rejection | Strict `0 < down < exp(r*T) < up` | Invalid and equality-boundary tests |
| Missing input checks | Finite data, spot>0, strike>=0, maturity>0, integer paths>=2 | Invalid count and tree tests plus A5 test suite |

The original got 0/8 checks; the repaired file got 8/8. Actual outputs are saved. The repairs were drafted by AI in this session and executed locally. They do not stand in for unprovided earlier model transcripts or the student's pre-AI hypotheses. No claim is made that a previous model suggested, accepted or rejected any particular change.

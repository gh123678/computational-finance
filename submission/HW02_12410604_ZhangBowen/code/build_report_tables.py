"""Generate compact LaTeX tables directly from persisted experiment CSV files."""
from pathlib import Path
import csv

ROOT = Path(__file__).resolve().parents[1]


def table(out,source,columns,caption):
    rows = list(csv.DictReader((ROOT/'results'/f'{source}.csv').open(encoding='utf-8')))
    lines = [r'\begin{center}',r'\small',r'\begin{tabular}{'+'l'*len(columns)+'}',r'\toprule',
             ' & '.join(label for _,label,_ in columns)+r'\\',r'\midrule']
    for row in rows:
        vals = []
        for key,label,fmt in columns:
            value = row[key]
            vals.append(value if fmt is None else format(float(value),fmt))
        lines.append(' & '.join(vals)+r'\\')
    lines += [r'\bottomrule',r'\end{tabular}',r'\par\smallskip '+caption,r'\end{center}']
    (ROOT/'report'/f'table_{out}.tex').write_text('\n'.join(lines),encoding='utf-8')


def main():
    table('A1','A1_boundary',[('S_T','$S_T$','.0f'),('call_butterfly','Call butterfly','.1f'),('put_butterfly','Put butterfly','.1f')],'A1: Boundary values.')
    table('A2','A2_compounding',[('m','$m$','.0f'),('total_periods','$N$','.0f'),('matched_nominal','Matched $r_c$','.8f'),('relative_discrepancy','Matched rel. error','.2e'),('fixed_nominal_amount','Fixed-rate wealth','.5f'),('fixed_relative_error','Fixed rel. error','.2e')],'A2: Two-year rate conversion and fixed-rate accumulation.')
    table('A3_moments','A3_moments',[('rate','$\\lambda$','.0f'),('mean','Sample mean','.6f'),('theoretical_mean','Theory mean','.3f'),('variance_ddof1','Sample variance','.6f'),('theoretical_variance','Theory variance','.3f'),('histogram_area','Hist. area','.6f')],'A3: Moments, $N=100{,}000$ per rate, variance divisor $N-1$.')
    table('A3_quantiles','A3_quantiles',[('rate','$\\lambda$','.0f'),('p','$p$','.2f'),('empirical_quantile','Empirical quantile','.6f'),('analytical_quantile','Analytical quantile','.6f')],'A3: Empirical versus analytical quantiles.')
    table('A4','A4_summary',[('n','$n$','.0f'),('M','$M$','.0f'),('mean','Mean','.6f'),('variance_ddof1','Variance','.6f'),('skewness_bias_corrected','Sample skew','.6f'),('theoretical_skewness','Theory skew','.6f')],'A4: Mean theory 0, variance theory 1; variance divisor $M-1$.')
    table('A5_exact','A5_exact',[('kind','Kind',None),('price','Exact price','.8f'),('delta','$\\Delta$','.6f'),('bank','$B_0$','.8f'),('probability','$p^*$','.8f')],'A5: Exact pricing and replication.')
    # Separate option rows avoid an excessively wide price table.
    rows = list(csv.DictReader((ROOT/'results'/'A5_mc.csv').open()))
    flattened = []
    for row in rows:
        for kind in ['call','put']:
            flattened.append({'N':row['N'],'kind':kind,'price':row[kind],'se':row[kind+'_se'],
                              'low':row[kind+'_ci_low'],'high':row[kind+'_ci_high'],'exact':row['exact_'+kind]})
    with (ROOT/'results'/'A5_price_table.csv').open('w',newline='') as f:
        w = csv.DictWriter(f,fieldnames=flattened[0]); w.writeheader(); w.writerows(flattened)
    table('A5_mc','A5_price_table',[('N','$N$','.0f'),('kind','Kind',None),('price','Estimate','.6f'),('se','SE','.6f'),('low','95\\% low','.6f'),('high','95\\% high','.6f'),('exact','Exact','.6f')],'A5: Discounted payoff means and approximate 95\\% confidence intervals.')
    table('A5_parity','A5_mc',[('N','$N$','.0f'),('parity_residual','Paired residual','.6f'),('parity_se','Paired SE','.6f'),('parity_z_score','Residual / SE','.6f')],'A5: Paired put--call parity check; reference residual zero.')
    table('A5_rmse','A5_rmse',[('N','$N$','.0f'),('repetitions','Repetitions','.0f'),('RMSE','Observed RMSE','.6f'),('theoretical_RMSE','Population RMSE','.6f')],'A5: Independent repetitions; raw results retained.')


if __name__ == '__main__': main()

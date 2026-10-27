"""Reproduce A1-A5: python code/experiments.py, from any working directory."""
from pathlib import Path
import csv
import json
import platform
import numpy as np
import scipy
from scipy.stats import norm, skew
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import student_tasks as t

ROOT = Path(__file__).resolve().parents[1]
RESULTS, FIGURES = ROOT/'results', ROOT/'figures'
RESULTS.mkdir(exist_ok=True)
FIGURES.mkdir(exist_ok=True)
plt.rcParams.update({'font.size':11,'axes.spines.top':False,'axes.spines.right':False,'figure.dpi':130})
P = t.load_parameters()
SEED = P['seed']
streams = np.random.SeedSequence(SEED).spawn(9)


def table(name,rows):
    with (RESULTS/(name+'.csv')).open('w',newline='',encoding='utf-8') as f:
        writer = csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def save(name):
    plt.tight_layout()
    plt.savefig(FIGURES/(name+'.png'))
    plt.savefig(FIGURES/(name+'.pdf'))
    plt.close()


def density_hist(x,name,title,density=None):
    fig,ax = plt.subplots(figsize=(7,4))
    heights,edges,_ = ax.hist(x,bins=70,density=True,alpha=.65,label='Simulated density histogram')
    if density is not None:
        grid = np.linspace(min(x),max(x),700)
        ax.plot(grid,density(grid),color='darkorange',lw=2,label='Theoretical density')
    ax.set(xlabel='Value',ylabel='Density',title=title)
    ax.legend(fontsize=9)
    save(name)
    return float(np.dot(heights,np.diff(edges)))


def main():
    s = np.linspace(0,100,1001)
    call,put = t.call_payoff(s,50),t.put_payoff(s,50)
    fig,axes = plt.subplots(2,2,figsize=(9,6),sharex=True)
    for ax,title,y in zip(axes.flat,['Long call','Short call','Long put','Short put'],[call,-call,put,-put]):
        ax.plot(s,y); ax.axvline(50,color='gray',ls=':'); ax.axhline(0,color='gray',lw=.7)
        ax.set(title=title,xlabel='Terminal asset price',ylabel='Payoff')
    fig.suptitle('A1: Four basic expiry payoffs (strike 50)')
    save('A1_basic_payoffs')
    bc,bp = t.butterfly_payoff(s,(40,50,60)),t.butterfly_payoff(s,(40,50,60),'put')
    plt.figure(figsize=(7,4)); plt.plot(s,bc,label='Call butterfly'); plt.plot(s,bp,'--',label='Put butterfly')
    for k in [40,50,60]: plt.axvline(k,color='gray',ls=':',lw=.8)
    plt.annotate('Maximum payoff = 10',(50,10),xytext=(62,8),arrowprops={'arrowstyle':'->'})
    plt.xlabel('Terminal asset price'); plt.ylabel('Payoff'); plt.title('A1: Equal-spaced butterfly'); plt.legend()
    save('A1_butterfly_payoff')
    cost = 4.; financed = cost*np.exp(.05)
    plt.figure(figsize=(7,4)); plt.plot(s,t.financed_profit(bc,cost,.05,1),label='Financed profit')
    plt.axhline(0,color='gray',lw=.8)
    for k in [40+financed,60-financed]:
        plt.axvline(k,color='gray',ls=':'); plt.text(k,.3,f'{k:.4f}',ha='center',fontsize=9)
    plt.annotate(f'Maximum profit = {10-financed:.4f}',(50,10-financed),xytext=(62,4.5),arrowprops={'arrowstyle':'->'})
    plt.xlabel('Terminal asset price'); plt.ylabel('Financed terminal profit')
    plt.title('A1: Profit = payoff - initial cost × exp(rT)'); plt.legend()
    save('A1_butterfly_profit')
    table('A1_boundary',[{'S_T':v,'call_butterfly':float(t.butterfly_payoff(v,(40,50,60))),
                          'put_butterfly':float(t.butterfly_payoff(v,(40,50,60),'put'))} for v in [0,40,50,60,100]])
    summary = {'A1':{'max_call_put_discrepancy':float(np.max(np.abs(bc-bp))),'cost':cost,
                     'break_even_low':40+financed,'break_even_high':60-financed,'max_profit':10-financed}}
    target = 10000*np.exp(.1)
    rows = []
    for m in P['A2']['annual_frequencies']:
        rc = t.nominal_from_continuous(.05,m)
        rc_total = t.rate_for_total_periods(.05,2,2*m)
        amount = 10000*(1+rc/m)**(2*m)
        total_amount = 10000*(1+rc_total*2/(2*m))**(2*m)
        fixed = 10000*(1+.05/m)**(2*m)
        rows.append({'m':m,'total_periods':2*m,'matched_nominal':rc,'matched_total_nominal':rc_total,
                     'matched_amount':amount,'total_convention_amount':total_amount,'continuous_amount':target,
                     'relative_discrepancy':amount/target-1,'total_relative_discrepancy':total_amount/target-1,
                     'fixed_nominal_amount':fixed,'fixed_relative_error':fixed/target-1})
    table('A2_compounding',rows)
    plt.figure(figsize=(7,4)); plt.loglog([r['m'] for r in rows],[-r['fixed_relative_error'] for r in rows],'o-')
    plt.xlabel('Compounding periods per year m'); plt.ylabel('Absolute relative accumulation error')
    plt.title('A2: Fixed nominal rate 0.05; maturity 2 years'); save('A2_error')
    moments,quantiles = [],[]
    for index,lam in enumerate([1,2]):
        rng = np.random.default_rng(streams[index])
        x = t.exponential_samples(lam,100000,rng)
        area = density_hist(x,f'A3_exponential_rate{lam}',f'A3: Exp(rate={lam}), N=100,000',lambda v:lam*np.exp(-lam*v))
        moments.append({'rate':lam,'N':len(x),'mean':x.mean(),'theoretical_mean':1/lam,'variance_ddof1':x.var(ddof=1),
                        'theoretical_variance':1/lam**2,'histogram_area':area})
        for p in P['A3']['quantile_levels']:
            quantiles.append({'rate':lam,'p':p,'empirical_quantile':float(np.quantile(x,p,method='linear')),
                              'analytical_quantile':float(t.exponential_quantile(p,lam))})
    table('A3_moments',moments); table('A3_quantiles',quantiles)
    rng = np.random.default_rng(streams[2])
    single = float(t.standardized_exponential_sums(1000,1,1,rng)[0])
    table('A4_single_sum',[{'n':1000,'rate':1,'Z':single}])
    rows = []
    for index,n in enumerate([1,5,30,1000]):
        z = t.standardized_exponential_sums(n,10000,1,np.random.default_rng(streams[index+3]),250)
        area = density_hist(z,f'A4_hist_n{n}',f'A4: Exponential sums, n={n}, M=10,000',norm.pdf)
        rows.append({'n':n,'M':len(z),'mean':z.mean(),'variance_ddof1':z.var(ddof=1),'skewness_bias_corrected':skew(z,bias=False),
                     'theoretical_mean':0,'theoretical_variance':1,'theoretical_skewness':2/np.sqrt(n),'histogram_area':area})
        if n == 1000:
            table('A4_standardized_sums_n1000',[{'replication':i+1,'Z':v} for i,v in enumerate(z)])
            # Read the persisted sample: both the final histogram and Q-Q use this file.
            saved = np.genfromtxt(RESULTS/'A4_standardized_sums_n1000.csv',delimiter=',',names=True)['Z']
            density_hist(saved,'A4_hist_n1000','A4: Exponential sums, n=1000, M=10,000',norm.pdf)
            x,y = t.normal_qq(saved)
            table('A4_qq',[{'normal_quantile':a,'sample_quantile':b} for a,b in zip(x,y)])
            plt.figure(figsize=(6,6)); plt.scatter(x,y,s=6,alpha=.5,label='Saved simulated quantiles')
            lo,hi = min(x.min(),y.min()),max(x.max(),y.max())
            plt.plot([lo,hi],[lo,hi],'--',label='Reference y = x')
            plt.xlabel('Theoretical standard normal quantile'); plt.ylabel('Sample quantile')
            plt.title('A4: Normal Q-Q, n=1000, M=10,000'); plt.legend(); save('A4_qq_n1000')
            summary['A4'] = {'single_sum':single,'center_max_abs_difference':float(np.max(np.abs((y-x)[np.abs(x)<=2]))),
                             'lower_extreme_sample':float(y[0]),'lower_extreme_normal':float(x[0]),
                             'upper_extreme_sample':float(y[-1]),'upper_extreme_normal':float(x[-1])}
    table('A4_summary',rows)
    args = (100,100,1.2,.8,.05,1)
    exact = {kind:t.exact_binomial(*args,kind) for kind in ['call','put']}
    table('A5_exact',[{'kind':k,**v} for k,v in exact.items()])
    rng = np.random.default_rng(streams[7]); rows = []
    for n in [1000,10000,100000]:
        out = t.monte_carlo_binomial(*args,n,rng)
        rows.append({'N':n,**out,'exact_call':exact['call']['price'],'exact_put':exact['put']['price'],
                     'parity_z_score':out['parity_residual']/out['parity_se']})
    table('A5_mc',rows)
    rng = np.random.default_rng(streams[8]); rmse,raw = [],[]
    for n in [1000,10000]:
        errors = []
        for i in range(50):
            call = t.monte_carlo_binomial(*args,n,rng)['call']
            err = call-exact['call']['price']; errors.append(err)
            raw.append({'N':n,'repetition':i+1,'call':call,'error':err})
        p = exact['call']['probability']
        theoretical = 20*np.exp(-.05)*np.sqrt(p*(1-p)/n)
        rmse.append({'N':n,'repetitions':50,'RMSE':np.sqrt(np.mean(np.square(errors))),'theoretical_RMSE':theoretical})
    table('A5_rmse',rmse); table('A5_rmse_repetitions',raw)
    summary['A5'] = {'rmse_ratio':float(rmse[1]['RMSE']/rmse[0]['RMSE']),'predicted_ratio':1/np.sqrt(10)}
    # I1 reproducible counterexamples, without attributing claims to unprovided models.
    table('I1_numerical_checks',[
        {'check':'butterfly_profit_at_S0','value':float(t.financed_profit(0,4,.05,1)),'comparison':0},
        {'check':'wrong_annual_compounding_t2_m12','value':10000*(1+.05*2/12)**12,'comparison':10000*(1+.05/12)**24},
        {'check':'two_exponential_transforms_U_0.2_rate1','value':-np.log(.2),'comparison':-np.log1p(-.2)},
        {'check':'fixed_n1_standardized_sum_lower_bound','value':-1,'comparison':'normal has positive probability below -1'}])
    (RESULTS/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    manifest = {'master_seed':SEED,'rng':'NumPy default_rng / PCG64','stream_allocation':{
        '0':'A3 rate 1','1':'A3 rate 2','2':'A4 single sum','3':'A4 n=1','4':'A4 n=5','5':'A4 n=30',
        '6':'A4 n=1000','7':'A5 prices: continuing draws','8':'A5 RMSE: continuing draws'},
        'python':platform.python_version(),'numpy':np.__version__,'scipy':scipy.__version__,'matplotlib':matplotlib.__version__,
        'variance_divisor':'N-1 / ddof=1','empirical_quantiles':'linear interpolation',
        'skewness':'scipy.stats.skew(bias=False); adjusted Fisher-Pearson', 'batch_size':250,'run_date':'2026-10-10 Asia/Shanghai'}
    (RESULTS/'environment.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2)); print('All prescribed experiments generated.')


if __name__ == '__main__': main()

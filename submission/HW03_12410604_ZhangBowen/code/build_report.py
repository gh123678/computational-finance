"""Assemble the English worked solutions from actual CSV outputs."""
from pathlib import Path
import json
import math
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'report'

def table(headers,rows,align=None):
    align=align or ('l'+'r'*(len(headers)-1))
    return '\\begin{center}\n\\begin{tabular}{'+align+'}\n\\toprule\n'+' & '.join(headers)+r'\\\midrule'+'\n'+'\n'.join(' & '.join(map(str,row))+r'\\' for row in rows)+'\n\\bottomrule\n\\end{tabular}\n\\end{center}\n'

def f(x,d=6): return f'{float(x):.{d}f}'

def build():
    a=json.loads((ROOT/'results/A1_summary.json').read_text(encoding='utf8'))
    d,c,au=a['descriptive'],a['calibration'],a['audit']
    provenance=json.loads((ROOT/'data/provenance.json').read_text(encoding='utf8'))
    a2=pd.read_csv(ROOT/'results/A2_terminal_moments.csv').iloc[0]
    coverage=pd.read_csv(ROOT/'results/A2_prediction_coverage.csv').iloc[0]
    convergence=pd.read_csv(ROOT/'results/A3_convergence.csv')
    slope=pd.read_csv(ROOT/'results/A3_error_slope.csv').iloc[0]
    stress=pd.read_csv(ROOT/'results/A3_stress.csv').iloc[0]
    algorithms=r'''\subsection{A1. Five-year real-data return analysis}
\textbf{(a) Input and audit.} MSFT (Nasdaq), USD; Yahoo Finance public historical/chart interface; retrieved on 21 October 2026. The frozen window is 14 October 2021--14 October 2026, inclusive. The selected adjusted-close field includes the provider's split and dividend adjustments as of retrieval. It describes an adjusted return series, not a raw execution price. The input has '''+str(au['price_rows'])+r''' observations and '''+str(d['n'])+r''' adjacent log returns. There are zero duplicate dates, missing values, nonpositive prices, missing expected trading sessions, or unexpected observations. The longest calendar gap is four days. Weekends, exchange holidays and the 9 January 2025 Carter closure were audited; no nontrading dates were forward-filled.

The analyzed CSV SHA-256 is
\begin{quote}\small\path{'''+provenance['analyzed_csv_sha256']+r'''}\end{quote}
The exact raw-response hash, retrieval timestamp, request URL, currency and field definition are retained in \path{data/provenance.json}. Raw data remain in the private local data directory; redistribution rights were not established, so no public-data redistribution right is asserted. The downloader and public historical interface provide a course-access route. Any later provider revision must be identified by a changed hash, rather than presented as the same input.

\textbf{(b) Implemented statistics.} Let $n$ be the number of returns, $y_i=r_i-\bar r$, and $m_k=n^{-1}\sum y_i^k$. The variance uses $s^2=\sum y_i^2/(n-1)$; skewness is $m_3/m_2^{3/2}$ and excess kurtosis is $m_4/m_2^2-3$. The last two are uncorrected central-moment ratios, not bias-adjusted estimators.
'''+table(['Quantity','Observed value'],[
        ['Number of returns',str(d['n'])],['Daily mean',f(d['mean'],9)],['Daily variance',f(d['variance'],9)],
        ['Daily standard deviation',f(d['sd'],9)],['Skewness',f(d['skewness'])],['Excess kurtosis',f(d['excess_kurtosis'])]])+r'''
The histogram uses density normalization. The fitted normal uses $\bar r,s_r$; the Q--Q plot uses sorted $(r_i-\bar r)/s_r$ and theoretical quantiles $\Phi^{-1}((i-1/2)/n)$ with the reference $y=x$.

\textbf{(c) Tail comparison.} The counts use the strict inequality $|r_i-\bar r|>ks_r$; fitted-normal expected counts are $2n[1-\Phi(k)]$.
'''+table(['Threshold $k$','Observed','Normal expected'],[[t['threshold'],t['observed'],f(t['fitted_normal_expected'],7)] for t in a['tails']])+r'''
The fitted normal is a rough central reference. The Q--Q tails depart from its line and the observed tail counts exceed its expectations; this sample therefore does not support an exact fitted i.i.d.-normal description. These are fitted in-sample comparisons, not exact hypothesis tests: estimated standardization, dependence, parameter changes, dividend adjustments and a few extreme observations matter. No particular alternative tail law or market inefficiency follows.

\textbf{(d) Temporal diagnostics.} The code implements the exact global-mean/global-denominator ACF given in the handout. The same single seeded permutation is used for both return and squared-return comparisons. Returns have small ACFs at lags 1--20 (largest absolute value about 0.0524); some squared-return ACFs are positive, reaching about 0.0709. These observations neither prove independence nor establish a volatility model. One permuted squared-return ACF reaches about 0.1287, illustrating why one permutation is not a significance test. Permutation preserves the complete empirical marginal distribution, moments, tail counts and compounded final return; it changes ordering, intermediate paths and temporal dependence.

\textbf{(e) Calibration with $h=1/252$.}
'''+table(['Estimate','Value'],[
        [r'$\widehat m$ (year$^{-1}$)',f(c['m_hat'])],[r'$\widehat\sigma$ (year$^{-1/2}$)',f(c['sigma_hat'])],
        [r'$\widehat\sigma^2$ (year$^{-1}$)',f(c['sigma_squared_hat'])],[r'$\widehat\mu$ (year$^{-1}$)',f(c['mu_hat'])],
        [r'Plug-in SE$(\widehat m)$ (year$^{-1}$)',f(c['log_drift_se'])],[r'$H=nh$ (years)',f(c['horizon_years'])]])+r'''
The log-drift SE is about as large as its estimate. The physical drift is imprecisely estimated, and these parameters are descriptive constant-model estimates, not forecasts guaranteed by the data. Dividend-adjusted prices and annualization conventions must be kept consistent.

Checks include strict positive/finite prices and duplicate/date validation; exchange-calendar coverage and no forward filling; telescoping log-return/compounding identities; hand-calculated ACF and moment divisors; and preservation of marginal statistics under permutation. Commands and actual results are preserved alongside the code.
\clearpage
\fig{A1_histogram}{Density histogram and fitted normal for daily adjusted MSFT log returns.}{.86}
\fig{A1_qq}{Standardized-return normal Q--Q diagnostic. Extremes depart from the fitted Gaussian benchmark.}{.68}
\clearpage
\fig{A1_acf_returns}{Return ACF: original order and one seeded permutation.}{.88}
\fig{A1_acf_squared}{Squared-return ACF for the same two orders; neither curve is a significance threshold.}{.88}
\clearpage
\subsection{A2. Lognormal densities and exact terminal simulation}
\textbf{(a) Density and normalization.} For $T>0$, $\sigma>0$,
\[
 f_T(s)=\frac{1}{s\sigma\sqrt{2\pi T}}
 \exp\left\{-\frac{[\log(s/S_0)-(\mu-\sigma^2/2)T]^2}{2\sigma^2T}\right\},\quad s>0,
\]
and $f_T(s)=0$ for $s\leq0$. This follows by transforming the normal log price with Jacobian $1/s$. Elementary quadrature on $(0,\infty)$ gives integrals 1.0000000000000007 and 1.0000000000000002 for $S_0=T=1$, $\sigma=0.4$, $\mu=0.05,0.20$. Increasing $\mu$ shifts the log-price location upward; under common $Z$, it multiplies $S_T$ by $e^{\Delta\mu T}$ while preserving log variance.

\textbf{(b) Exact simulation.} Draw $Z_j\sim N(0,1)$ independently and set
\[
 S_T^{(j)}=S_0\exp[(\mu-\sigma^2/2)T+\sigma\sqrt{T}Z_j].
\]
No Euler stepping or library lognormal sampler is used. At the T6 parameters, $M=100{,}000$ gives
'''+table(['Quantity','Simulation','Analytical'],[
        ['Terminal mean',f(a2.sample_mean),f(a2.analytical_mean)],['Terminal variance',f(a2.sample_variance_n_minus_1),f(a2.analytical_variance)],
        ['Mean MCSE',f(a2.mean_mcse),f(math.sqrt(a2.analytical_variance/a2.M))]])+r'''
The approximate mean confidence interval is $\bar S\pm1.96s_S/\sqrt M$:
\[
 ['''+f(a2.mean_ci95_lower)+', '+f(a2.mean_ci95_upper)+r'''].
\]
The mean discrepancy is about $-0.988$ estimated MCSEs. Sampling variation is expected; a single nominal 95\% interval miss alone would not identify a program defect.

\textbf{(c) Fixed prediction-interval coverage.} T6's endpoints remain
$[46.693857,246.343711]$. The observed count inside is '''+str(int(coverage.inside_count))+r''' out of 100,000, or '''+f(coverage.empirical_fraction,6)+r'''. With rounded $z=1.96$, the exact model probability is $p_\star=2\Phi(1.96)-1=0.95000421$, and
\[
 \operatorname{SD}(\widehat p)=\sqrt{p_\star(1-p_\star)/M}='''+f(coverage.binomial_mcse_model,9)+r'''.
\]
The observed discrepancy is about 0.8645 MCSEs. This binomial error scale measures the coverage fraction; it is not uncertainty in the terminal mean.

For $T=0$, the terminal price is $S_0$; for $\sigma=0$, it is $S_0e^{\mu T}$. Both are point masses and have no ordinary lognormal density. The sampler and moment routines support them, while the ordinary-density routine raises an explicit error. Nonfinite inputs, nonpositive $S_0$, negative volatility/time and invalid counts are checked.
\fig{A2_density_comparison}{Analytical densities with common volatility and two physical drifts.}{.82}
\fig{A2_terminal_histogram}{100,000 exact terminal prices, density-normalized histogram and analytical density.}{.82}
\clearpage
\subsection{A3. Coupled discretizations and vanishing noise}
\textbf{(a) Coupling and updates.} Each path uses one 256-increment Brownian grid. For $n\in\{16,32,64,128,256\}$, consecutive fine increments are summed in blocks of $256/n$; consequently every resolution has the same terminal Brownian increment. With $h=1/n$ and coarse $\Delta W_i$, the implementations are
\begin{align*}
 G_T&=S_0e^{(\mu-\sigma^2/2)T+\sigma\sum_i\Delta W_i},\\
 E_{i+1}&=E_i(1+\mu h+\sigma\Delta W_i),\\
 V_{i+1}&=V_i(1+\mu h+\sigma\sqrt h\,\Delta W_i).
\end{align*}
Since $\Delta W_i=\sqrt hY_i$, the final line is exactly the specified wrong $\sigma hY_i$ scheme. All 20,000 paths are retained. Nonpositive multipliers are counted before updating, with no clipping or removal.

\textbf{(b) Independent analytical benchmarks.} Let $a=1+\mu h$ and let $c$ be the Brownian coefficient ($\sigma$ for Euler, $\sigma\sqrt h$ for the wrong scheme). For $X_n=S_0\prod_i(a+c\Delta W_i)$,
\begin{align*}
 \E X_n&=S_0a^n,&\E X_n^2&=S_0^2(a^2+c^2h)^n,\\
 \Var(X_n)&=S_0^2[(a^2+c^2h)^n-a^{2n}],\\
 \E[X_nG_T]&=S_0^2e^{\mu T}(a+c\sigma h)^n.
\end{align*}
The last identity follows by differentiating the Gaussian exponential moment. It independently checks coupling. Substituting the second and cross moments into
$\E[(X_n-G_T)^2]=\E X_n^2+\E G_T^2-2\E[X_nG_T]$ yields an exact finite-$n$ RMSE benchmark. The wrong scheme's distance from $d=S_0e^{\mu T}$ is $\Var(V_n)+(\E V_n-d)^2$ before taking the square root.

Here are the actual terminal moments; means and errors are in price units, variances in squared price units.
'''+table(['Method','$n$','Mean','Sample variance','Product variance'],[[r.method,int(r.n),f(r.sample_mean,4),f(r.sample_variance_n_minus_1,4),f(r.analytical_discrete_variance,4)] for _,r in convergence.iterrows()])+r'''
The common exact reference has sample mean 108.112308 and variance 1098.854857; the GBM population values are 108.328707 and 1105.145457. Monte Carlo variability explains their differences. The detailed CSV also reports mean, variance, cross-moment and squared-error uncertainty scales.
'''+table(['$n$','Euler vs. exact','Wrong vs. exact','Wrong vs. deterministic'],[[int(n),f(convergence[(convergence.method=='euler')&(convergence.n==n)].iloc[0].rmse_against_coupled_exact),f(convergence[(convergence.method=='wrong')&(convergence.n==n)].iloc[0].rmse_against_coupled_exact),f(convergence[(convergence.method=='wrong')&(convergence.n==n)].iloc[0].rmse_against_deterministic)] for n in [16,32,64,128,256]])+r'''
Regressing $\log(\mathrm{RMSE})$ on $\log h$ gives an observed Euler slope of 0.499243. This run is consistent with order $1/2$ strong convergence; an observed rate is not a proof. The wrong variance decreases toward zero and its deterministic-target RMSE falls, while its coupled GBM error increases toward $\sqrt{\Var(G_T)}\approx33.244$.

\textbf{(c) One-step stress test.} At $S_0=100$, $\mu=.08$, $\sigma=T=h=1$,
\[
 \Pp(1+.08+Y\leq0)=\Phi(-1.08)=0.1400710901.
\]
There are 14,178 nonpositive outcomes among 100,000 draws, fraction 0.141780. The model binomial MCSE is 0.0010975025; the discrepancy is about 1.5571 MCSEs. Clipping would replace the simulated law and corrupt both this probability diagnostic and moment/error calculations.

\textbf{(d) Cost and memory.} Batches have at most $B=1000$ paths. Runtime is $O(M[n_{\max}+\sum n])$, or $O(Mn_{\max})$ for these geometric resolutions. Peak working-array storage is $O(Bn_{\max})$: the finest-grid array uses 2,048,000 bytes and the conservative dominant-array estimate is 4,192,000 bytes. Retained terminal outputs use an additional $O(MK)$ space, 1,760,000 bytes for $K=5$ resolutions; no full path history is saved. These are array sizes, not measured total process memory.

Using an independent exact path would not measure pathwise approximation error. Even if Euler converged to one exact realization, an independent exact reference would leave limiting MSE $2\Var(G_T)$ rather than zero. The common Brownian grid removes this unrelated physical variation.
\clearpage
\fig{A3_coupled_error}{Log--log coupled errors: Euler approaches GBM, while the wrong scheme approaches the deterministic target.}{.88}
\fig{A3_variance}{Sample and exact finite-grid product variances; the wrong noise disappears as the grid is refined.}{.88}
'''
    (REPORT/'algorithms.tex').write_text(algorithms,encoding='utf8')
    i2root=ROOT/'results/I2_final_checks.json'
    i2text=r'''\subsection{I2. Repair of the instructor terminal-price routine}
The unchanged original was supplied in \path{code.zip} and preserved byte-for-byte, SHA-256
\begin{quote}\small\path{7f9bf4b6a5621cfdc427ecf0cf56621ff37c9a5662028570793a29aea8adf174}\end{quote}
The original is deliberately flawed instructor-authored teaching code; it is not attributed to an AI. The student reported having no earlier independent/pre-AI diagnostic record. The saved initial diagnosis and the 11-check design are explicitly an assistant baseline written before the separate repair-model request; they cannot satisfy a personal pre-AI chronology retrospectively. Rubric item (a) is therefore only partly met: the diagnosis and checks exist and precede the repair request, but they were not authored personally by the student. This gap is disclosed rather than backdated.

The original exponent uses $\mu T+\sigma TZ$, omitting $-\sigma^2T/2$ and replacing $\sqrt T$ by $T$. It computes SE as $s/M$ instead of $s/\sqrt M$, and labels a narrow interval for the simulated mean as a terminal prediction interval. It also lacks model/count validation. Correct code uses the exact A2 law, sample variance with divisor $M-1$, an explicitly named mean confidence interval, and analytical fixed prediction endpoints. Deterministic limits return exact zero variance and SE.

\begin{center}\small
\begin{tabular}{p{.24\linewidth}p{.52\linewidth}c}
\toprule
Required category & Executed checks (fixed script) & Count\\\midrule
Analytical benchmark & mean within 5 model MCSE; variance within 5\%; same-draw drift/time; divisor $M-1$ & 4\\
Uncertainty/interval & SE $=s/\sqrt M$; fixed population PI; separate mean CI; quadrupling $M$ halves SE & 4\\
Invalid/limiting input & $T=0$ point mass; $\sigma=0$ point mass; invalid model/count rejected & 3\\
\bottomrule
\end{tabular}
\end{center}
The same 11 checks in \path{code/debug_checks.py} were run unchanged against all three versions, so the before/after comparison does not use tests written after seeing a patch.

The unchanged original passed 1 of the 11 initial checks. At the default parameters it returned mean 140.073177, variance 8452.529174, SE 0.0009193764, and a purported prediction interval [140.071375,140.074979], instead of the T6 distribution and uncertainty scales.
'''
    if i2root.exists():
        q=json.loads(i2root.read_text(encoding='utf8'))
        o=q['actual_default_report']
        i2text+=r'''The final repair passes '''+str(q['passed'])+' of '+str(q['total'])+r''' checks. Its default mean is '''+f(o['mean'])+r''', sample variance '''+f(o['variance'])+r''', and mean MCSE '''+f(o['se'],9)+r'''. Its population prediction interval is [46.693857,246.343711], while its mean confidence interval is ['''+f(o['mean_confidence_interval'][0])+','+f(o['mean_confidence_interval'][1])+r''']. The seed differs from the A2 child stream; equality of sample outcomes is not expected. A separate same-draw check agrees with the A2 sampler to numerical precision.

Three substantive repair exchanges, including the actual candidate test output and a more demanding follow-up, are preserved in \path{ai_logs/I2_model_B.md}. The original, proposed patch and final repair remain separate. A passing candidate is reported honestly; no artificial model failure is invented. Accepted/revised decisions and all executed checks are recorded in the repair log.
The first proposal passed 8/11 direct checks: its numerical formulas were correct, but three checks failed because it renamed the original \texttt{prediction\_interval} key. Restoring that key as an alias of the explicitly named fixed-population interval resolved the compatibility regression. After 11/11 passed, 44 more demanding checks also passed: 36 same-draw comparisons across three drifts, three volatilities and four horizons, one prediction-interval/count invariance check, and seven invalid-input cases.

\textbf{Accepted, revised and rejected changes.} Accepted: the $-\sigma^2T/2$ log-drift correction, $\sigma\sqrt T$ noise scaling, divisor $M-1$, SE $=s/\sqrt M$, separation of the mean confidence interval from the fixed population prediction interval, input validation, and exact deterministic limits. Revised: the proposed removal of the \texttt{prediction\_interval} key was rejected as an API break and replaced by a backward-compatible alias with identical endpoints in every branch. Rejected: treating the three \texttt{KeyError} failures as numerical errors (they were not); changing formulas after the 11/11 pass with no failing evidence; and inventing a further failure to make the interaction look more eventful. The recorded 1/11, 8/11 and 11/11 outcomes are the actual executed results.

These checks establish tested model behavior, not empirical validity of GBM or numerical representability for every extreme input.
'''
    else:
        i2text+=r'\textbf{Status:} repair-model interaction and candidate verification are still being assembled; this section does not claim their completion.'
    i1=r'''\subsection{I1. Two-session audit}
Two independently prompted DeepSeek sessions, Model A and Model B, received the same four claims and mathematical conventions on 21 October 2026. The interface did not expose distinct backend build identifiers, so this is not a claim of two vendor-distinct models; it is a two-session audit within one provider. Earlier draft labels naming OpenAI models were incorrect and have been corrected. Neither session browsed or executed code while answering; the orchestrator ran the verification independently. The prompts were issued by the orchestrating assistant on the student's behalf, not typed personally by the student. Full initial prompts, actual replies and two substantive follow-ups per session are preserved separately.
'''+table(['Claim','A','B','Independent conclusion'],[
        ['Efficiency implies i.i.d. Gaussian','Invalid','Invalid','Mean restrictions do not fix a law'],
        [r'$\mu>0$ implies a.s. growth','Invalid','Invalid',r'Need $\mu>\sigma^2/2$'],
        ['More paths narrow a fixed PI','Invalid','Invalid','PI independent of replication count'],
        [r'Smooth $\sigma hY_i$ verifies GBM','Invalid','Invalid',r'Noise variance $\sigma^2Th\to0$']],align=r'p{.30\linewidth}lll')+r'''
\textbf{Hand argument 1.} Dividing $\log(S_t/S_0)$ by $t$ and using $W_t/t\to0$ gives $\mu-\sigma^2/2$. With $\mu=.10,\sigma=.50$, this is $-.025$: the price tends to zero almost surely although its expectation grows.

\textbf{Hand argument 2.} For the wrong scheme, independence gives the exact first and second product moments in T5. They converge to $d$ and $d^2$, so $\E[(V_n-d)^2]\to0$. This proof uses no invalid logarithm of a potentially negative multiplier.

\textbf{Numerical check.} A3 uses 20,000 coupled paths. Refining from 16 to 256 steps reduces Euler RMSE from 1.791140 to 0.448867, while the wrong scheme's variance drops from 65.467154 to 4.123023 and its GBM RMSE increases from 25.196830 to 31.160114. The independent finite-grid product/cross-moment checks agree within their Monte Carlo scales. This directly distinguishes visual smoothness from convergence to GBM.

\textbf{Response-specific follow-ups.} Model A initially illustrated mean-unpredictability with an unbounded product-normal sequence. A follow-up identified that it can be below $-1$ if called a positive-stock simple return. It supplied a bounded discrete martingale-difference construction with strictly positive gross returns and positively dependent squared returns. This is a qualified counterexample, not a claim that economic efficiency was proved. Its second follow-up derived the coupled cross-moment benchmark used in A3. Model B supplied a complete product-moment proof after its first response had relied on summed-noise intuition; its second follow-up clarified the Jensen/risk-benchmark qualification of a symmetric log-return example and computed MC uncertainty scaling.

\textbf{Comparison (206 words).} Both models rejected the four claims, so disagreement was not needed to make the audit useful. Model A gave a detailed distinction between conditional-mean restrictions and distributional assumptions, including an explicit dependent counterexample. Its initial product-normal example, however, could not be used unchanged as the simple return of a positive-price stock. A targeted follow-up produced a bounded construction and preserved the original limitation. Model B was more concise. Its initial argument about vanishing summed noise needed a product-moment justification for the multiplicative scheme; the follow-up supplied that proof. Its symmetric log-return example also required an economic benchmark because a zero expected log return does not mean a zero expected simple return.

Cochrane's discussion of Fama, actually consulted through Chicago Booth Review, emphasizes the relation between available information, trading rules, risk, and empirical evaluation. That perspective supports treating efficiency as an economic claim requiring a benchmark, rather than equating it with Gaussian noise. Neither model response establishes empirical efficiency. The useful difference was explanatory depth and which assumptions became explicit after questioning. Mathematical derivations and A3's independently executed coupled experiment provided the verification; fluent agreement alone did not. The record therefore reports qualified examples and completed checks without inventing an incorrect classification to create a model error.

Non-AI source: John H. Cochrane, ``Eugene Fama, Efficient Markets, and the Nobel Prize,'' Chicago Booth Review, 20 May 2014, \url{https://www.chicagobooth.edu/review/eugene-fama-efficient-markets-and-the-nobel-prize}. The Fama 1970 bibliographic record was checked; its full text was not claimed to have been read.
'''+i2text
    (REPORT/'ai_interaction.tex').write_text(i1,encoding='utf8')
    main=r'''\documentclass[11pt,a4paper]{article}
\usepackage[margin=23mm]{geometry}
\usepackage{amsmath,amssymb,booktabs,graphicx,array,longtable,float}
\usepackage[T1]{fontenc}
\usepackage{lmodern,microtype,xurl}
\usepackage{hyperref,fancyhdr}
\hypersetup{colorlinks=true,urlcolor=blue,linkcolor=blue,pdftitle={MA216 HW03 Worked Solutions}}
\pagestyle{fancy}\fancyhf{}\fancyhead[L]{MA216 Computational Finance}\fancyhead[R]{HW03 Worked Solutions}\fancyfoot[C]{\thepage}
\setlength{\headheight}{14pt}\setlength{\parindent}{0pt}\setlength{\parskip}{5pt}\setlength{\emergencystretch}{3em}
\newcommand{\E}{\mathbb E}\newcommand{\Pp}{\mathbb P}
\DeclareMathOperator{\Var}{Var}\DeclareMathOperator{\Cov}{Cov}
\newcommand{\fig}[3]{\begin{figure}[H]\centering\includegraphics[width=#3\linewidth]{../figures/#1.pdf}\caption{#2}\end{figure}}
\begin{document}
\begin{center}
{\LARGE\bfseries Homework 3: Worked Solutions}\par
{\large Asset Returns and Geometric Brownian Motion}\par
Prepared for Zhang Bowen (12410604)\par
MA216 Computational Finance, Fall 2026\par
21 October 2026
\end{center}
\textbf{Purpose and current status.} This is the requested question-by-question worked solution. T1--T8 and A1--A3 include derivations, implemented code and actual final-count outputs. I1 contains two independently prompted DeepSeek audit sessions with the same-provider limitation disclosed, plus genuine follow-ups. The supplied I2 original is preserved and actual repairs/tests are documented. R1 contains source-based notes on two different books, Tsay and Hull, with independent reconstructions, checked examples, and a cross-book comparison; the AI-assisted source consultation and the edition handling are disclosed in the notes.

\textbf{AI disclosure.} The student reported having no earlier independent attempt, pre-AI debugging record or reading record. These solutions are AI-assisted; no independent student authorship, prior chronology, personal reading, or invented conversations are asserted. Mathematical/numerical cross-checks were performed in this session, and actual outputs, original files and model replies are retained. The student must study the arguments and complete the source reading personally before making any corresponding submission declaration.

\textbf{Conventions.} Time is in years; $S_0>0$, $\mu$ is physical annual arithmetic drift, and $\sigma\geq0$ is annual volatility. Sample variances use divisor $n-1$ unless an explicitly labelled population/moment calculation says otherwise. Master seed 21603 uses separate PCG64/SeedSequence child streams: A1 permutation $(1,)$, A2 $(2,)$, A3 $(3,)$, stress $(4,)$. The I2 standalone API uses its documented seed argument separately.
\clearpage
\tableofcontents
\clearpage
\section{Part I: Theory}
\input{theory.tex}
\clearpage
\section{Part II: Algorithms}
\input{algorithms.tex}
\clearpage
\section{Part III: AI interaction}
\input{ai_interaction.tex}
\clearpage
\section{Part IV: Reading notes and cross-book comparison}
{\small
\input{reading.tex}
}
\end{document}
'''
    (REPORT/'worked_solutions.tex').write_text(main,encoding='utf8')
    print('Wrote English report source from actual result tables.')

if __name__=='__main__': build()

"""The single approved selection rule; old core selectors remain unchanged."""
import numpy as np
import pandas as pd


def select_retention(scores, previous_codes=(), gap=.05, cap=5):
    if gap != .05 or cap != 5:
        raise ValueError('Only the approved gap=.05/cap=5 experiment is supported')
    if scores.ts_code.duplicated().any() or scores.trade_date.nunique()>1:
        raise ValueError('One unique cross-section required')
    pool=scores.replace([np.inf,-np.inf],np.nan).dropna(subset=['score','industry']).copy()
    pool=pool.loc[pool.industry.astype(str).str.strip().ne('')]
    pool=pool.sort_values(['score','ts_code'],ascending=[False,True])
    rows={r['ts_code']:r for r in pool.to_dict('records')}
    previous=set(previous_codes)
    chosen=[];events=[];blocked=set();new=set()
    def fits(codes):
        sectors=[rows[c]['industry'] for c in codes]
        return all(sectors.count(s)<=5 for s in set(sectors))
    for code in sorted(previous-set(rows)):
        events.append(dict(kind='forced_exit',code=code,reason='ineligible',other_code='',old_score=np.nan,new_score=np.nan))
        blocked.add(code)
    for code in pool.loc[pool.ts_code.isin(previous),'ts_code']:
        if fits(chosen+[code]):
            chosen.append(code)
        else:
            events.append(dict(kind='forced_exit',code=code,reason='industry_cap',other_code='',old_score=rows[code]['score'],new_score=np.nan))
            blocked.add(code)
    for code in pool.ts_code:
        if len(chosen)==20:
            break
        if code not in chosen and code not in blocked and fits(chosen+[code]):
            chosen.append(code);new.add(code)
            events.append(dict(kind='initial_entry' if not previous else 'vacancy_fill',code=code,reason='fill',other_code='',old_score=np.nan,new_score=rows[code]['score']))
    for _ in range(cap):
        pair=None
        for candidate in pool.ts_code:
            if candidate in chosen or candidate in blocked:
                continue
            sellers=sorted((c for c in chosen if c not in new),key=lambda c:(rows[c]['score'],c))
            for seller in sellers:
                # Difference comparison can have binary rounding at .05;
                # compare to score + gap so an exact boundary is excluded.
                if rows[candidate]['score']<=rows[seller]['score']+gap:
                    break
                if fits([c for c in chosen if c!=seller]+[candidate]):
                    pair=(seller,candidate);break
            if pair:
                break
        if pair is None:
            break
        seller,candidate=pair
        chosen.remove(seller);chosen.append(candidate)
        blocked.add(seller);new.add(candidate)
        events.append(dict(kind='active_replace',code=seller,other_code=candidate,reason='gap_gt_05',old_score=rows[seller]['score'],new_score=rows[candidate]['score']))
    result=pd.DataFrame([rows[c] for c in chosen],columns=pool.columns)
    result['target_weight']=.049
    assert len(result)<=20 and fits(chosen)
    return result,pd.DataFrame(events,columns=['kind','code','reason','other_code','old_score','new_score'])

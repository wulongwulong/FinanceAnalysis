from __future__ import annotations
from ..common.indicators import enrich,crossed

WINDOW_LABELS={15:'15天',20:'1月',40:'2月',60:'3月',80:'4月',100:'5月',120:'6月'}

def _pos(rows,n):
    vals=[x['close'] for x in rows[-n:]];lo=min(vals);hi=max(vals);cur=vals[-1]
    return 50.0 if hi==lo else (cur-lo)/(hi-lo)*100

def _days_since(flags,limit=30):
    tail=flags[-limit:]
    for back,v in enumerate(reversed(tail)):
        if v:return back
    return None

def _rel(d,b,n):
    bm={x['date']:x['close'] for x in b};pairs=[(x['close'],bm[x['date']]) for x in d if x['date'] in bm]
    if len(pairs)<=n:return 0.0
    s0,b0=pairs[-n-1];s1,b1=pairs[-1]
    return ((s1/s0)/(b1/b0)-1)*100

def analyze_sector(raw,benchmark,windows):
    d=enrich(raw);b=enrich(benchmark)
    if len(d)<130:raise ValueError('行业历史行情不足130日')
    c,p=d[-1],d[-2];mc=crossed(p['dif'],p['dea'],c['dif'],c['dea']);kc=crossed(p['kdj_k'],p['kdj_d'],c['kdj_k'],c['kdj_d'])
    bar=('红柱延长' if c['macd_bar']>p['macd_bar'] else '红柱缩短') if c['macd_bar']>=0 else ('绿柱延长' if abs(c['macd_bar'])>abs(p['macd_bar']) else '绿柱缩短')
    golden=[];reclaim=[]
    for i in range(len(d)):
        if i==0:golden.append(False);reclaim.append(False);continue
        a,q=d[i],d[i-1]
        golden.append(q['dif']<=q['dea'] and a['dif']>a['dea'])
        reclaim.append(q.get('ma20') is not None and a.get('ma20') is not None and q['close']<q['ma20'] and a['close']>=a['ma20'])
    ages=[x for x in (_days_since(golden),_days_since(reclaim)) if x is not None];signal_age=min(ages) if ages else 99
    positions={WINDOW_LABELS[n]:round(_pos(d,n),1) for n in windows};pos15=positions.get('15天',50);pos120=positions.get('6月',50)
    rel15,rel20=_rel(d,b,15),_rel(d,b,20)
    timing=0;positives=[];negatives=[];ma20=c.get('ma20');ma20past=d[-6].get('ma20') if len(d)>=6 else None
    if ma20 is not None and c['close']>=ma20:timing+=3;positives.append('站上MA20')
    else:negatives.append('MA20下方')
    if ma20 is not None and ma20past is not None and ma20>ma20past:timing+=2;positives.append('MA20向上')
    if c['dif']>c['dea']:timing+=3;positives.append('MACD多头')
    if mc=='金叉':timing+=2;positives.append('MACD新金叉')
    if bar in ('红柱延长','绿柱缩短'):timing+=2;positives.append('MACD动能改善')
    if c['kdj_k']>c['kdj_d']:timing+=2;positives.append('KDJ多头')
    if kc=='金叉':timing+=1;positives.append('KDJ金叉')
    if c.get('boll_mid') is not None and c['close']>=c['boll_mid']:timing+=2;positives.append('BOLL中轨上方')
    vr=c.get('volume_ratio_5_20')
    if vr is not None and vr>=1.1:timing+=1;positives.append('量能改善')
    if rel15>0:timing+=1;positives.append('相对沪深300增强')
    if rel20>0:timing+=1
    timing=min(20,timing)
    turn=0
    if bar in ('红柱延长','绿柱缩短'):turn+=2
    if c['dif']>c['dea']:turn+=2
    if mc=='金叉':turn+=2
    if c['kdj_k']>c['kdj_d']:turn+=1
    if ma20 is not None and c['close']>=ma20:turn+=2
    if c.get('boll_mid') is not None and c['close']>=c['boll_mid']:turn+=1
    if rel15>0:turn+=2
    if vr is not None and vr>=1.1:turn+=1
    trend_confirm=ma20 is not None and ma20past is not None and c['close']>=ma20 and ma20>ma20past and c['dif']>c['dea']
    accelerated=pos15>=88 and positions.get('3月',50)>=65 and trend_confirm
    if pos120<=45 and turn>=8 and signal_age<=10:stage='A1';stage_name='A1 低位刚转强 ★★★★★'
    elif pos120<=60 and turn>=7 and trend_confirm:stage='A2';stage_name='A2 低位转强 ★★★★'
    elif accelerated:stage='A3';stage_name='A3 低位启动后已加速 ★★★'
    elif pos120<=50:stage='B';stage_name='B 低位等待'
    else:stage='C';stage_name='C 普通/高位观察'
    opportunity=40+turn*4+max(-10,min(12,rel15*1.5))+(8 if pos120<=40 else 3 if pos120<=60 else -8 if pos120>=85 else 0);opportunity=max(0,min(100,opportunity))
    rsi=c.get('rsi14');dist=(c['close']/ma20-1) if ma20 else 0
    risk=15+(18 if pos15>=90 else 0)+(15 if pos120>=85 else 0)+(12 if rsi is not None and rsi>=70 else 0)+(10 if dist>=.08 else 0)+(8 if mc=='死叉' else 0)+(8 if kc=='死叉' else 0);risk=max(0,min(100,risk));priority=opportunity+timing*2-risk*.7
    if pos15>=92 or (rsi is not None and rsi>=72) or dist>=.09:location='偏高'
    elif abs(dist)<=.035 and pos120<=65:location='理想区'
    elif abs(dist)<=.065 and pos120<=82:location='合理区'
    else:location='中性区'
    mids=[v for v in (ma20,c.get('boll_mid')) if v is not None];anchor=sum(mids)/len(mids) if mids else c['close'];atr=c.get('atr14') or c['close']*.02
    low=anchor-.65*atr;high=anchor+.65*atr;invalid=min(mids) - 1.6*atr if mids else c['close']-2*atr
    if stage in ('A1','A2') and location in ('理想区','合理区'):recommendation='小仓试探' if timing>=13 else '开始观察'
    elif stage=='A3':recommendation='等回踩'
    elif stage=='B':recommendation='继续等待'
    else:recommendation='暂不参与' if location=='偏高' else '观察'
    return {'date':c['date'].isoformat(),'close':round(c['close'],2),'stage':stage,'stage_name':stage_name,'signal_age':signal_age,'opportunity_score':round(opportunity,1),'risk_score':round(risk,1),'timing_score':int(timing),'priority_score':round(priority,2),'positions':positions,'rel_hs300_15':round(rel15,2),'rel_hs300_20':round(rel20,2),'rsi14':None if rsi is None else round(rsi,1),'volume_ratio':None if vr is None else round(vr,2),'macd_state':f"{mc or ('多头' if c['dif']>c['dea'] else '空头')} / {bar}",'kdj_state':f"{kc or ('多头' if c['kdj_k']>c['kdj_d'] else '空头')} K{c['kdj_k']:.1f}/D{c['kdj_d']:.1f}",'boll_state':'中轨上方' if c.get('boll_mid') is not None and c['close']>=c['boll_mid'] else '中轨下方','location':location,'ideal_low':round(low,2),'ideal_high':round(high,2),'invalid_below':round(invalid,2),'recommendation':recommendation,'positive_reasons':positives,'risk_reasons':negatives}

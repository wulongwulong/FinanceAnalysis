from __future__ import annotations
from pathlib import Path
from datetime import datetime
from ..common.csv_history import read_history_csv, write_history_csv
FIELDS=['signal_date','code','name','level','stage','close','opportunity_score','timing_score','location','ret_5','ret_10','ret_20','ret_40','max_drawdown_20']

def _date(v):return v if hasattr(v,'year') and not isinstance(v,str) else datetime.strptime(str(v)[:10],'%Y-%m-%d').date()
def update_sector_history(path:Path,meta,result,history_rows):
    rows=read_history_csv(path,FIELDS,('signal_date','code','stage','close'))
    key=(result['date'],meta['code'],result['stage'])
    if result['stage'] in ('A1','A2') and not any((r['signal_date'],r['code'],r['stage'])==key for r in rows):
        rows.append({'signal_date':result['date'],'code':meta['code'],'name':meta['name'],'level':meta['level'],'stage':result['stage'],'close':result['close'],'opportunity_score':result['opportunity_score'],'timing_score':result['timing_score'],'location':result['location'],'ret_5':'','ret_10':'','ret_20':'','ret_40':'','max_drawdown_20':''})
    d=sorted(history_rows,key=lambda x:_date(x['date']))
    for r in rows:
        if r['code']!=meta['code']:continue
        sd=_date(r['signal_date']);future=[x for x in d if _date(x['date'])>=sd];entry=float(r['close'])
        if not future:continue
        for n in (5,10,20,40):
            if len(future)>n:r[f'ret_{n}']=f"{(float(future[n]['close'])/entry-1)*100:.2f}"
        lows=[float(x['low']) for x in future[:min(21,len(future))]]
        if lows:r['max_drawdown_20']=f"{(min(lows)/entry-1)*100:.2f}"
    write_history_csv(path,FIELDS,rows)

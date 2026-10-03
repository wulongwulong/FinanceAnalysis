from __future__ import annotations
import csv,io
from ..common.data_source import _http_get
FRED={'WTI原油':'DCOILWTICO','Brent原油':'DCOILBRENTEU','美国10年期收益率':'DGS10','VIX':'VIXCLS','美元广义指数':'DTWEXBGS'}
STOOQ={'标普500':'^spx','纳斯达克':'^ndq','道琼斯':'^dji','费城半导体SOX':'^sox'}

def _position(vals,n):
    x=vals[-n:]
    if len(x)<5:return None
    lo=min(x);hi=max(x);return 50.0 if hi==lo else (x[-1]-lo)/(hi-lo)*100

def _summarize(name,vals,source):
    vals=[float(x) for x in vals if x is not None]
    if len(vals)<20:return None
    j=max(0,len(vals)-16);r15=(vals[-1]/vals[j]-1)*100;p15=_position(vals,15);p120=_position(vals,120);trend='强势' if r15>3 else '偏强' if r15>1 else '偏弱' if r15<-1 else '震荡'
    return {'name':name,'source':source,'last':round(vals[-1],3),'ret15':round(r15,2),'pos15':None if p15 is None else round(p15,1),'pos120':None if p120 is None else round(p120,1),'trend':trend}

def fetch_all():
    out=[];errors=[]
    for name,sid in FRED.items():
        try:
            txt=_http_get(f'https://fred.stlouisfed.org/graph/fredgraph.csv',{'id':sid});rows=list(csv.DictReader(io.StringIO(txt)));vals=[]
            for r in rows:
                raw=r.get(sid)
                try:vals.append(float(raw))
                except:pass
            item=_summarize(name,vals,f'FRED/{sid}')
            if item:out.append(item)
        except Exception as e:errors.append(f'{name}:{e}')
    for name,sym in STOOQ.items():
        try:
            txt=_http_get('https://stooq.com/q/d/l/',{'s':sym,'i':'d'});rows=list(csv.DictReader(io.StringIO(txt)));vals=[]
            for r in rows:
                try:vals.append(float(r.get('Close')))
                except:pass
            item=_summarize(name,vals,f'Stooq/{sym}')
            if item:out.append(item)
        except Exception as e:errors.append(f'{name}:{e}')
    return out,errors

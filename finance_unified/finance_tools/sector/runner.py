from __future__ import annotations
import csv, json
from pathlib import Path
from ..common.data_source import list_sw_indices, fetch_sw_history, fetch_hs300, fetch_security
from ..common.demo import sector_rows as demo_rows
from ..common.position_grid import load_grid
from .sector_engine import analyze_sector
from .target_timing import analyze_target
from .global_assets import fetch_all
from .history import update_sector_history
from .report import build

def load_mapping(root):
    path=root/'config/sector/target_mapping.csv'
    rows=[]
    with path.open('r',encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            if str(r.get('enabled','1')).strip().lower() in ('0','false','no','off'):
                continue
            code=str(r.get('code','')).strip()
            if not code:
                continue
            # Numbers/Excel 有时会把 000002 保存成 2；证券代码统一补足6位。
            if code.isdigit():
                code=code.zfill(6)
            rows.append({
                **r,
                'code':code,
                'name':str(r.get('name','')).strip(),
                'type':str(r.get('type') or 'ETF').strip().upper(),
                'sector_keywords':str(r.get('sector_keywords','')).strip(),
            })
    return rows

def map_targets(name,mapping):
    out=[]
    for r in mapping:
        kws=[k.strip() for k in r['sector_keywords'].split(';') if k.strip()]
        if any(k in name or name in k for k in kws):out.append(r)
    return out

def run(root: Path, demo=False, limit=0):
    settings=json.loads((root/'config/sector/settings.json').read_text(encoding='utf-8'));mapping=load_mapping(root);grid=load_grid(root/'config/sector/position_grid.csv');rules=json.loads((root/'config/rules.json').read_text(encoding='utf-8'));errors=[];sectors=[]
    if demo:
        benchmark=demo_rows(100,280,4000);names=[('801001','软件开发','二级行业'),('801002','半导体','二级行业'),('801003','电力','二级行业'),('801004','煤炭','一级行业'),('801005','自动化设备','二级行业'),('801006','饲料','二级行业'),('801007','银行','一级行业')];universe=[{'code':c,'name':n,'level':l,'rows':demo_rows(i+1,280,1500+i*100)} for i,(c,n,l) in enumerate(names)]
    else:
        print('[1/4] 正在获取沪深300基准...', flush=True)
        benchmark,bsource=fetch_hs300();print(f'      完成：{bsource}', flush=True);universe=[]
        print('[2/4] 正在获取申万行业列表...', flush=True)
        for level in settings['include_levels']:
            try:
                rows=list_sw_indices(level)
                print(f'      {level}：{len(rows)} 个行业', flush=True)
                for r in rows:universe.append({'code':r['code'],'name':r['name'],'level':level})
            except Exception as e:
                errors.append({'scope':level,'error':str(e)})
                print(f'      {level} 列表失败：{e}', flush=True)
        if limit:universe=universe[:limit]
    if not universe:raise RuntimeError('没有取得申万行业列表，请检查网络或运行日志')
    print(f'[3/4] 开始扫描行业，共 {len(universe)} 个...', flush=True)
    for i,u in enumerate(universe):
        try:
            rows=u.get('rows') if demo else fetch_sw_history(u['code']);r=analyze_sector(rows,benchmark,settings['sector_position_windows']);r.update({'code':u['code'],'name':u['name'],'level':u['level']});sectors.append(r);update_sector_history(root/'data/sector/sector_signals.csv',u,r,rows);print(f"[{i+1}/{len(universe)}] {u['name']} {r['stage']} {r['priority_score']}", flush=True)
        except Exception as e:errors.append({'scope':u['name'],'error':str(e)});print(f"ERR {u['name']}: {e}", flush=True)
    sectors.sort(key=lambda x:x['priority_score'],reverse=True);target_results=[];seen=set()
    # 标的执行层不再只看TOP候选：在全部已扫描板块中，为配置中的ETF/股票/LOF寻找优先级最高的匹配板块。
    # sectors 已按 priority_score 从高到低排序，seen 可保证同一标的只取最佳匹配板块。
    for s in sectors:
        for m in map_targets(s['name'],mapping):
            if m['code'] in seen:continue
            seen.add(m['code'])
            try:
                rows=demo_rows(300+len(seen),260,1.0) if demo else fetch_security(m['code'])[0];er=analyze_target(rows,s,rules,settings,code=m['code'],grid=grid);er.update({'code':m['code'],'name':m['name'],'asset_type':(m.get('type') or 'ETF').upper(),'sector_name':s['name'],'sector_stage':s['stage']});target_results.append(er)
            except Exception as e:errors.append({'scope':m['name'],'error':str(e)})
    if demo:globals_=[]
    else:
        print('[4/4] 正在获取全球资产环境...', flush=True)
        globals_,ge=fetch_all();errors.extend({'scope':'全球资产','error':e} for e in ge)
        print(f'      全球资产完成：{len(globals_)} 项，异常 {len(ge)} 项', flush=True)
    md,ht,data=build(sectors,target_results,globals_,errors,root/'outputs/sector',settings['final_focus_count']);print('');print(f'完成：行业 {len(sectors)}，标的执行 {len(target_results)}，异常 {len(errors)}');print(md);print(ht);print(data)
    if not sectors:raise SystemExit(2)
    return root/'outputs/sector/latest.html'

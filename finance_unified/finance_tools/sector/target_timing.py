from __future__ import annotations
from ..common.position_grid import apply_grid
from .target_rule_engine import analyze as analyze_base

def analyze_target(raw, sector, rules, settings, code=None, grid=()):
    base=analyze_base(raw,rules)
    if code is not None:base=apply_grid({**base,'code':code},grid)
    stage_cap=float(settings['sector_stage_caps'].get(sector['stage'],0))
    location_cap=float(settings['location_caps'].get(sector['location'],50))
    integrated=min(float(base['target_position_pct']),stage_cap,location_cap,float(settings.get('max_integrated_target_pct',80)))
    a=base['action_signal']
    if integrated<=0: advice='暂不参与'
    elif sector['stage']=='A3': advice='等回踩，不追高'
    elif sector['stage']=='B': advice='继续等待'
    elif sector['stage']=='C': advice='暂不参与'
    elif a in ('买入','加仓') and sector['location'] in ('理想区','合理区'): advice='可按综合目标分批'
    elif a in ('卖出','减仓','空仓'): advice='标的技术转弱，暂缓参与'
    else: advice='继续观察'
    grade='C' if integrated<=0 else 'S' if sector['stage'] in ('A1','A2') and sector['location']=='理想区' and a in ('买入','加仓') and sector['timing_score']>=12 else 'A' if sector['stage'] in ('A1','A2') and a in ('买入','加仓','持有') else 'B' if sector['stage'] in ('A3','B') else 'C'
    return {**base,'grade':grade,'sector_cap_pct':stage_cap,'location_cap_pct':location_cap,'integrated_target_pct':integrated,'integrated_advice':advice}

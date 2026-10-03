from __future__ import annotations
from pathlib import Path
import csv


def load_grid(path: Path):
    if not path.exists():
        return []
    rows=[]
    with path.open('r',encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(line for line in f if not line.lstrip().startswith('#'))
        for r in reader:
            code=str(r.get('code','')).strip()
            if not code: continue
            if code.isdigit(): code=code.zfill(6)
            try:
                rows.append({
                    'code':code,
                    'lower':float(r['lower']) if r.get('lower') else float('-inf'),
                    'upper':float(r['upper']) if r.get('upper') else float('inf'),
                    'target_position_pct':float(r['target_position_pct']),
                    'note':str(r.get('note','')).strip(),
                })
            except Exception:
                continue
    return rows


def apply_grid(item: dict, grid_rows: list[dict]) -> dict:
    out=dict(item)
    for r in grid_rows:
        if r['code']==out['code'] and r['lower'] <= float(out['close']) < r['upper']:
            out['target_position_pct']=r['target_position_pct']
            out['position_source']='网格'
            out['position_note']=r['note']
            return out
    return out

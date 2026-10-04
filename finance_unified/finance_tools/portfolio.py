"""人工维护的实际持仓；本机编辑页使用 Python 标准库。"""
from __future__ import annotations

import html
import json
import math
import os
import secrets
import tempfile
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


def validate_positions(positions):
    if not isinstance(positions, list):
        raise ValueError('持仓必须是列表')
    result, seen = [], set()
    for i, row in enumerate(positions, 1):
        if not isinstance(row, dict):
            raise ValueError(f'第{i}行格式错误')
        code = str(row.get('code', '')).strip()
        if not code.isascii() or not code.isdigit() or len(code) > 6:
            raise ValueError(f'第{i}行代码应为6位数字')
        code = code.zfill(6)
        if code in seen:
            raise ValueError(f'代码 {code} 重复；同一账户请合并为一条持仓')
        seen.add(code)
        name = str(row.get('name', '')).strip()
        if not name:
            raise ValueError(f'第{i}行请填写名称')
        values = {}
        for field, label in (('quantity', '持有数量'), ('average_cost', '平均成本')):
            value = row.get(field)
            if field == 'average_cost' and value in (None, ''):
                values[field] = None
                continue
            if isinstance(value, bool):
                raise ValueError(f'第{i}行{label}应为非负数')
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ValueError(f'第{i}行{label}应为非负数') from None
            if not math.isfinite(value) or value < 0:
                raise ValueError(f'第{i}行{label}应为有限的非负数')
            values[field] = value
        result.append({'code': code, 'name': name, **values, 'note': str(row.get('note', '')).strip()})
    return result


def load_holdings(root):
    path = Path(root) / 'data/portfolio/holdings.json'
    if not path.exists():
        return {'updated_at': '', 'positions': []}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        datetime.fromisoformat(data['updated_at'])
        return {'updated_at': data['updated_at'], 'positions': validate_positions(data['positions'])}
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
        raise ValueError(f'实际持仓文件读取失败：{path}（{error}）；请检查原文件，未将其当作空仓') from error


def save_holdings(root, positions, expected_updated_at):
    positions = validate_positions(positions)
    if load_holdings(root)['updated_at'] != expected_updated_at:
        raise ValueError('持仓已在其他页面修改。请重新加载后再保存，避免覆盖新数据')
    data = {'updated_at': datetime.now().isoformat(timespec='microseconds'), 'positions': positions}
    path = Path(root) / 'data/portfolio/holdings.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            json.dump(data, file, ensure_ascii=False, indent=2, allow_nan=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return data


def holdings_records(monitor):
    return [{**x['holding'], 'updated_at': x.get('holdings_updated_at', '')}
            for x in monitor or [] if x.get('holding') is not None]


def holdings_html(positions):
    rows = ''.join('<tr>' + ''.join(f'<td>{html.escape(str(value))}</td>' for value in (
        x['code'], x['name'], x['quantity'], '未填写' if x['average_cost'] is None else x['average_cost'],
        x['note'], x.get('updated_at', ''),
    )) + '</tr>' for x in positions)
    return '<!-- actual-holdings:start --><section id="holdings"><h2>实际持仓</h2><p><a href="/holdings" data-holdings-editor>维护实际持仓</a></p><div class="note">由你填写数量（股/份）和平均成本（元/股或份），未填写的标的不代表空仓。策略参考仓位另列；尚未计算账户仓位比例。持仓可以随时保存，技术分析与导出数据在下一次运行时更新。</div><table><thead><tr><th>代码</th><th>名称</th><th>持有数量</th><th>平均成本</th><th>备注</th><th>维护时间</th></tr></thead><tbody>' + (rows or '<tr><td colspan="6">当前没有持仓记录，可通过维护页面填写。</td></tr>') + '</tbody></table><script>if(location.protocol==="file:"){const link=document.querySelector("[data-holdings-editor]");link.href="#holdings";link.onclick=event=>{event.preventDefault();alert("请双击项目里的 维护持仓.command，打开可保存的持仓编辑页。");};}</script></section><!-- actual-holdings:end -->'


def holdings_markdown(monitor):
    rows = holdings_records(monitor)
    lines = ['## 实际持仓', '', '人工维护的数量和成本，策略参考仓位另列。未填写不代表空仓。', '']
    for x in rows:
        cost = '未填写' if x['average_cost'] is None else str(x['average_cost'])
        lines.append(f"- {x['code']} {x['name']}：数量 {x['quantity']}，平均成本 {cost}；备注 {x['note']}；维护时间 {x['updated_at']}")
    return '\n'.join(lines if rows else lines + ['尚未维护持仓。'])


def editor_html(token):
    return """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>维护实际持仓</title>
<style>body{font-family:-apple-system,"PingFang SC",sans-serif;max-width:1100px;margin:30px auto;padding:0 16px;color:#20242b;background:#f5f6f8}main{background:white;padding:24px;border-radius:14px}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:8px;border-bottom:1px solid #e5e7eb}input{box-sizing:border-box;width:100%;min-width:90px;padding:9px;border:1px solid #c8cdd5;border-radius:6px}button,a{cursor:pointer}button{padding:9px 14px;margin:8px 6px 8px 0;border:1px solid #c8cdd5;border-radius:6px;background:white}#save{background:#245fca;color:white}p{line-height:1.6}#status{min-height:24px;color:#245fca}.table{overflow:auto}.error{color:#b42318!important}</style>
<main><h1>维护实际持仓</h1><p><a href="/">返回分析报告</a></p><p>填写一个账户的持仓。数量单位为股/份，平均成本单位为元/股或份；不清楚成本可以留空。清仓可将数量改为0，也可移除该行后保存。数据保存在本项目中，关闭页面后仍保留。</p><p id="updated"></p>
<form id="form"><div class="table"><table><thead><tr><th>代码</th><th>名称</th><th>持有数量</th><th>平均成本</th><th>备注</th><th>操作</th></tr></thead><tbody id="rows"></tbody></table></div><button type="button" id="add">添加持仓</button><button id="save" type="submit" disabled>保存持仓</button><button type="button" id="reload">重新加载</button></form><p id="status" role="status" aria-live="polite"></p><p>保存后返回报告可查看实际持仓；标的技术分析及导出文件在下一次运行分析时更新。请保留启动窗口，关闭窗口会停止编辑服务。</p></main>
<script>
const token=TOKEN, body=document.querySelector('#rows'), status=document.querySelector('#status'), save=document.querySelector('#save');
let updated='', dirty=false;
function message(text,error=false){status.textContent=text;status.className=error?'error':'';}
function add(row={}){const tr=document.createElement('tr');
 for(const [key,label,type] of [['code','代码','text'],['name','名称','text'],['quantity','持有数量','number'],['average_cost','平均成本','number'],['note','备注','text']]){
  const td=document.createElement('td'), input=document.createElement('input');input.name=key;input.type=type;input.setAttribute('aria-label',label);input.value=row[key]??'';
  if(type==='number'){input.min='0';input.step='any';}if(['code','name','quantity'].includes(key))input.required=true;
  if(key==='code'){input.pattern='[0-9]{1,6}';input.maxLength=6;input.inputMode='numeric';}input.addEventListener('input',()=>{dirty=true;});td.append(input);tr.append(td);
 }
 const td=document.createElement('td'), button=document.createElement('button');button.type='button';button.textContent='移除';button.onclick=()=>{tr.remove();dirty=true;};td.append(button);tr.append(td);body.append(tr);
}
async function load(){save.disabled=true;try{const response=await fetch('/api/holdings');const data=await response.json();if(!response.ok)throw new Error(data.error);
 body.replaceChildren();for(const row of data.positions)add(row);updated=data.updated_at;document.querySelector('#updated').textContent='最近维护：'+(updated||'尚未保存');dirty=false;save.disabled=false;message('已加载本地持仓。');
}catch(error){message(error.message,true);}}
document.querySelector('#add').onclick=()=>{add();dirty=true;};document.querySelector('#reload').onclick=()=>{if(!dirty||confirm('重新加载会放弃未保存的修改，继续吗？'))load();};
document.querySelector('#form').onsubmit=async event=>{event.preventDefault();save.disabled=true;
 const positions=Array.from(body.children,tr=>Object.fromEntries(Array.from(tr.querySelectorAll('input'),input=>[input.name,input.value])));
 try{const response=await fetch('/api/holdings',{method:'POST',headers:{'Content-Type':'application/json','X-Portfolio-Token':token},body:JSON.stringify({positions,updated_at:updated})});const data=await response.json();if(!response.ok)throw new Error(data.error);
 updated=data.updated_at;dirty=false;document.querySelector('#updated').textContent='最近维护：'+updated;message('已保存到本地。返回报告即可查看持仓，技术分析在下一次运行时更新。');
 }catch(error){message(error.message,true);}finally{save.disabled=false;}
};window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});load();
</script></html>""".replace('TOKEN', json.dumps(token))


def make_server(root):
    root = Path(root)
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, content, content_type='application/json'):
            content = json.dumps(content, ensure_ascii=False) if content_type == 'application/json' else content
            content = content.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', content_type + '; charset=utf-8')
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(content)

        def local_request(self):
            host = f'127.0.0.1:{self.server.server_port}'
            return self.headers.get('Host') == host and self.headers.get('Origin', f'http://{host}') == f'http://{host}'

        def do_GET(self):
            if not self.local_request():
                return self.reply(403, {'error': '仅允许本机页面访问'})
            try:
                if self.path == '/api/holdings':
                    return self.reply(200, load_holdings(root))
                if self.path == '/holdings':
                    return self.reply(200, editor_html(token), 'text/html')
                if self.path in ('/', '/index.html'):
                    path = root / 'outputs/index.html'
                    page = path.read_text(encoding='utf-8') if path.exists() else '<h1>Finance 分析</h1><p>尚未生成报告。请运行分析。</p>'
                    data = load_holdings(root)
                    section = holdings_html([{**x, 'updated_at': data['updated_at']} for x in data['positions']])
                    start, end = '<!-- actual-holdings:start -->', '<!-- actual-holdings:end -->'
                    if start in page and end in page:
                        before, remainder = page.split(start, 1)
                        page = before + section + remainder.split(end, 1)[1]
                    else:
                        page += section
                    return self.reply(200, page, 'text/html')
                return self.reply(404, {'error': '页面不存在'})
            except (ValueError, OSError) as error:
                return self.reply(400, {'error': str(error)})

        def do_POST(self):
            if not self.local_request() or self.headers.get('X-Portfolio-Token') != token:
                return self.reply(403, {'error': '请从本机持仓页面保存'})
            if self.path != '/api/holdings':
                return self.reply(404, {'error': '页面不存在'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 131072 or self.headers.get('Content-Type') != 'application/json':
                    raise ValueError('请求应为有效的持仓数据')
                data = json.loads(self.rfile.read(size))
                saved = save_holdings(root, data['positions'], data['updated_at'])
                return self.reply(200, saved)
            except (ValueError, OSError, KeyError, TypeError) as error:
                return self.reply(400, {'error': str(error)})

    return HTTPServer(('127.0.0.1', 0), Handler)


def serve(root, edit=False):
    with make_server(root) as server:
        url = f'http://127.0.0.1:{server.server_port}' + ('/holdings' if edit else '/')
        print(f'本机报告与持仓维护：{url}\n请保留此窗口；按 Ctrl+C 结束服务。', flush=True)
        webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass

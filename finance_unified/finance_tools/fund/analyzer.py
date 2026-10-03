#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import os, math, time, shutil, re
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Tuple
from io import StringIO

import numpy as np
import pandas as pd

ak = None
SIGNAL_HORIZONS = (5, 10, 20, 40)

def detect_scan_slot(dt: datetime) -> str:
    """
    自动识别A股观察时段：
    - 09:25以前：盘前
    - 11:30~13:00：午盘
    - 15:00以后：收盘
    - 其他：盘中

    同一时段重复运行会覆盖该时段记录，避免误操作产生重复样本。
    """
    hm = dt.hour * 60 + dt.minute
    if hm < 9 * 60 + 25:
        return "盘前"
    if 11 * 60 + 30 <= hm < 13 * 60:
        return "午盘"
    if hm >= 15 * 60:
        return "收盘"
    return "盘中"

def configure_paths(root: Path, demo: bool = False):
    """初始化本次运行的目录、时间和数据源；导入模块时不创建文件。"""
    global ROOT, DATA, REPORTS, DAILY_REPORTS, ROLLING_REPORTS, LATEST_REPORTS
    global LOG_REPORTS, CHATGPT_FOLDER, CHATGPT_DAILY, CHATGPT_SUMMARY
    global CHATGPT_LATEST, CHATGPT_HISTORY, CACHE, HISTORY, SIGNALS
    global RUN_DT, TODAY, NOW, SCAN_TIME, SCAN_SLOT, RUN_TAG, CACHE_TAG, SW_REALTIME, ak
    ROOT = Path(root).resolve()
    DATA = ROOT / "data" / "fund"
    REPORTS = ROOT / "outputs" / "fund"
    DAILY_REPORTS = REPORTS / "01_每日归档"
    ROLLING_REPORTS = REPORTS / "02_滚动汇总"
    LATEST_REPORTS = REPORTS / "03_最新文件"
    LOG_REPORTS = REPORTS / "04_运行日志"
    CHATGPT_FOLDER = ROOT / "outputs" / "chatgpt" / "fund"
    CHATGPT_DAILY = CHATGPT_FOLDER / "01_全部扫描记录"
    CHATGPT_SUMMARY = CHATGPT_FOLDER / "02_滚动汇总"
    CHATGPT_LATEST = CHATGPT_FOLDER / "03_最新数据"
    CHATGPT_HISTORY = CHATGPT_FOLDER / "04_历史验证"
    CACHE = DATA / "缓存"
    HISTORY = DATA / "history.csv"
    SIGNALS = DATA / "a1_signals.csv"
    for path in (
        DATA, REPORTS, DAILY_REPORTS, ROLLING_REPORTS, LATEST_REPORTS, LOG_REPORTS, CACHE,
        CHATGPT_FOLDER, CHATGPT_DAILY, CHATGPT_SUMMARY, CHATGPT_LATEST, CHATGPT_HISTORY
    ):
        path.mkdir(parents=True, exist_ok=True)
    RUN_DT = datetime.now()
    TODAY = RUN_DT.strftime("%Y-%m-%d")
    NOW = RUN_DT.strftime("%Y-%m-%d %H:%M:%S")
    SCAN_TIME = RUN_DT.strftime("%H:%M:%S")
    SCAN_SLOT = detect_scan_slot(RUN_DT)
    RUN_TAG = f"{TODAY}_{SCAN_SLOT}"
    CACHE_TAG = RUN_TAG
    SW_REALTIME = {}
    if not demo:
        import akshare
        ak = akshare


PERIODS = {
    "15天": 15,
    "1个月": 21,
    "2个月": 42,
    "3个月": 63,
    "4个月": 84,
    "5个月": 105,
    "6个月": 126,
}

# 全球资产数据优先使用新浪 / FRED 免费公开数据，并保留ETF兜底。

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def norm(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    x = df.copy()
    mapping = {}
    for c in x.columns:
        s = str(c).strip().lower()
        if s in ("日期","date","datetime","时间"):
            mapping[c] = "date"
        elif s in ("开盘","今开盘","开盘指数","open"):
            mapping[c] = "open"
        elif s in ("收盘","收盘指数","最新价","close","latest"):
            mapping[c] = "close"
        elif s in ("最高","最高价","最高指数","high"):
            mapping[c] = "high"
        elif s in ("最低","最低价","最低指数","low"):
            mapping[c] = "low"
        elif s in ("成交量","volume","vol"):
            mapping[c] = "volume"
        elif s in ("成交额","amount","turnover"):
            mapping[c] = "amount"
    x = x.rename(columns=mapping)
    if "date" not in x.columns or "close" not in x.columns:
        return pd.DataFrame()
    x["date"] = pd.to_datetime(x["date"], errors="coerce")
    for c in ("open","close","high","low","volume","amount"):
        if c in x.columns:
            x[c] = pd.to_numeric(x[c], errors="coerce")
    if "amount" not in x.columns and "volume" in x.columns:
        x["amount"] = x["volume"]
    x = x.dropna(subset=["date","close"]).sort_values("date").drop_duplicates("date")
    return x.reset_index(drop=True)

def rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0)
    dn = -d.clip(upper=0)
    au = up.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    ad = dn.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    rs = au / ad.replace(0, np.nan)
    return (100 - 100/(1+rs)).fillna(50)

def pos(close, n):
    s = close.dropna().tail(n)
    if len(s) < min(10, n):
        return np.nan
    lo, hi, cur = s.min(), s.max(), s.iloc[-1]
    return 50.0 if hi == lo else float((cur-lo)/(hi-lo)*100)

def ret(close, n):
    s = close.dropna()
    if len(s) <= n: return np.nan
    return float((s.iloc[-1]/s.iloc[-1-n]-1)*100)

def vol(close, n=20):
    r = close.pct_change().dropna().tail(n)
    return np.nan if len(r) < 5 else float(r.std()*np.sqrt(252)*100)

def mdd(close, n=126):
    s = close.dropna().tail(n)
    if len(s) < 5: return np.nan
    return float((s/s.cummax()-1).min()*100)

def cur_dd(close, n=126):
    s = close.dropna().tail(n)
    if len(s) < 5: return np.nan
    return float((s.iloc[-1]/s.max()-1)*100)

def rel_return(df, bench, n):
    if bench is None or bench.empty: return np.nan
    a = df[["date","close"]].rename(columns={"close":"a"})
    b = bench[["date","close"]].rename(columns={"close":"b"})
    x = a.merge(b, on="date").dropna().sort_values("date")
    if len(x) <= n: return np.nan
    return float(((x["a"].iloc[-1]/x["a"].iloc[-1-n]-1) -
                  (x["b"].iloc[-1]/x["b"].iloc[-1-n]-1))*100)

def age_signal(df):
    c = df["close"]
    if len(c) < 25: return 0
    ma5 = c.rolling(5).mean()
    ma10 = c.rolling(10).mean()
    ma20 = c.rolling(20).mean()
    cond = (c > ma20) & (ma5 > ma10)
    if not bool(cond.iloc[-1]): return 0
    n = 0
    for v in reversed(cond.tail(30).tolist()):
        if bool(v): n += 1
        else: break
    return n

def state_of(df, p6, r15, r21):
    c = df["close"]
    if len(c) < 65: return "数据不足"
    ma5 = c.rolling(5).mean().iloc[-1]
    ma10 = c.rolling(10).mean().iloc[-1]
    ma20s = c.rolling(20).mean()
    ma20 = ma20s.iloc[-1]
    ma60 = c.rolling(60).mean().iloc[-1]
    ma20old = ma20s.iloc[-6]
    slope20 = (ma20/ma20old-1)*100 if ma20old else 0
    rr = rsi(c).iloc[-1]
    cur = c.iloc[-1]
    if not np.isnan(p6) and p6 >= 85:
        return "高位强势" if ma5 > ma10 > ma20 else "高位"
    down = cur < ma20 and ma5 < ma10 and slope20 < -0.4
    if not np.isnan(p6) and p6 <= 20 and rr < 35 and down:
        return "超跌"
    if down:
        return "下跌"
    flat = -0.8 <= slope20 <= 0.8
    near20 = abs(cur/ma20-1) <= 0.035 if ma20 else False
    if not np.isnan(p6) and p6 <= 40 and flat and near20 and 30 <= rr <= 60:
        return "筑底"
    relok = (np.isnan(r15) or r15 > 0) and (np.isnan(r21) or r21 > -0.5)
    if not np.isnan(p6) and p6 <= 50 and cur > ma20 and ma5 > ma10 and slope20 >= -0.2 and relok:
        return "初步转强"
    if cur > ma20 and ma5 > ma10 > ma20 and slope20 > 0 and (np.isnan(r15) or r15 > 0):
        return "强趋势" if ma20 > ma60 and (np.isnan(p6) or p6 >= 55) else "趋势确认"
    return "震荡"

def group_of(state, positions, age, rsi_value):
    """
    V1.0 A类拆分：
    A1 低位刚转强 ★★★★★
      - 6个月位置 <= 35%
      - 初步转强
      - 信号年龄 <= 5天
      - 15天位置 35%~80%
      - 1个月位置 <= 80%
      - RSI 40~60
    A3 低位启动后已加速 ★★★
      - 仍属于低位启动候选（6个月 <= 50%）
      - 但短期已经明显加速：15天>=90 / 1月>=90 / 2月>=95 /
        RSI>=65 / 信号年龄>10，任一满足
    A2 低位转强 ★★★★
      - 其余满足低位转强条件的板块
    """
    p15 = positions.get("15天", np.nan)
    p1 = positions.get("1个月", np.nan)
    p2 = positions.get("2个月", np.nan)
    p6 = positions.get("6个月", np.nan)

    if not np.isnan(p6) and p6 >= 80:
        return "D 高位"

    is_low_turn = state in ("初步转强", "趋势确认") and (np.isnan(p6) or p6 <= 50)

    if is_low_turn:
        accelerated = (
            (not np.isnan(p15) and p15 >= 90) or
            (not np.isnan(p1) and p1 >= 90) or
            (not np.isnan(p2) and p2 >= 95) or
            (not np.isnan(rsi_value) and rsi_value >= 65) or
            age > 10
        )
        if accelerated:
            return "A3 低位启动后已加速 ★★★"

        a1 = (
            state == "初步转强" and
            (np.isnan(p6) or p6 <= 35) and
            age <= 5 and
            (np.isnan(p15) or 35 <= p15 <= 80) and
            (np.isnan(p1) or p1 <= 80) and
            (np.isnan(rsi_value) or 40 <= rsi_value <= 60)
        )
        if a1:
            return "A1 低位刚转强 ★★★★★"

        return "A2 低位转强 ★★★★"

    if not np.isnan(p6) and p6 <= 40 and state in ("下跌","超跌","筑底","震荡"):
        return "B 低位等待"
    if state in ("趋势确认","强趋势","高位强势") and (np.isnan(p6) or p6 < 80):
        return "C 趋势机会"
    return "观察"

def clip(v,a,b): return max(a,min(b,v))

def opp_score(df,p6,r15,r21,age):
    c=df["close"]; cur=c.iloc[-1]
    ma5=c.rolling(5).mean().iloc[-1]
    ma10=c.rolling(10).mean().iloc[-1]
    ma20s=c.rolling(20).mean(); ma20=ma20s.iloc[-1]
    ma60=c.rolling(60).mean().iloc[-1]
    rr=rsi(c).iloc[-1]
    low=10 if np.isnan(p6) else clip((65-p6)/65*30,0,30)
    tr=0
    tr += 6 if cur>ma20 else 0
    tr += 6 if ma5>ma10 else 0
    tr += 6 if ma10>ma20 else 0
    tr += 4 if ma20s.iloc[-1]>=ma20s.iloc[-6] else 0
    tr += 3 if ma20>ma60 else 0
    rs=0
    if not np.isnan(r15): rs += clip((r15+2)/6*8,0,8)
    if not np.isnan(r21): rs += clip((r21+2)/8*7,0,7)
    vs=5
    if "amount" in df.columns:
        a5=df["amount"].tail(5).mean(); a20=df["amount"].tail(20).mean()
        if a20 and np.isfinite(a5) and np.isfinite(a20):
            vs=clip((a5/a20-0.7)/0.8*10,0,10)
    if 40<=rr<=60: rsis=10
    elif 35<=rr<40 or 60<rr<=65: rsis=7
    elif 30<=rr<35 or 65<rr<=70: rsis=4
    else: rsis=1
    fresh=10 if 1<=age<=5 else 7 if 6<=age<=10 else 4 if 11<=age<=15 else 2 if age>15 else 3
    return round(clip(low+tr+rs+vs+rsis+fresh,0,100),1)

def risk_score(df,p6,state):
    c=df["close"]; score=0
    vv=vol(c); dd=abs(mdd(c)); rr=rsi(c).iloc[-1]; r5=ret(c,5)
    if not np.isnan(vv): score+=clip(vv/60*30,0,30)
    if not np.isnan(dd): score+=clip(dd/35*25,0,25)
    if state in ("下跌","超跌"): score+=20
    elif state=="筑底": score+=10
    if not np.isnan(p6) and p6>=85: score+=15
    if rr>=72: score+=10
    if not np.isnan(r5) and r5>=10: score+=10
    return round(clip(score,0,100),1)


def macd_values(close):
    """标准 MACD(12,26,9)，柱值采用 2*(DIF-DEA)。"""
    c=pd.to_numeric(close,errors="coerce").astype(float)
    dif=c.ewm(span=12,adjust=False).mean()-c.ewm(span=26,adjust=False).mean()
    dea=dif.ewm(span=9,adjust=False).mean()
    hist=2*(dif-dea)
    return dif,dea,hist

def kdj_values(df,n=9):
    """标准 KDJ(9,3,3)，K/D 初始平滑值按 50 处理。"""
    d=norm(df)
    low=d["low"] if "low" in d.columns else d["close"]
    high=d["high"] if "high" in d.columns else d["close"]
    close=d["close"]
    ll=low.rolling(n,min_periods=1).min()
    hh=high.rolling(n,min_periods=1).max()
    den=(hh-ll).replace(0,np.nan)
    rsv=((close-ll)/den*100).fillna(50).clip(0,100)
    k=pd.Series(index=rsv.index,dtype=float)
    dd=pd.Series(index=rsv.index,dtype=float)
    kp=50.0; dp=50.0
    for i,v in enumerate(rsv):
        kp=2/3*kp+1/3*float(v)
        dp=2/3*dp+1/3*kp
        k.iloc[i]=kp
        dd.iloc[i]=dp
    j=3*k-2*dd
    return k,dd,j

def cross_age(a,b,cross_type="gold",max_lookback=30):
    """
    返回当前关系下，距离最近一次金叉/死叉的交易日数。
    当天交叉=0；若当前关系与目标交叉不一致，返回 -1。
    """
    if len(a)<2 or len(b)<2:
        return -1
    if cross_type=="gold":
        if not (a.iloc[-1] > b.iloc[-1]):
            return -1
        event=(a>b) & (a.shift(1)<=b.shift(1))
    else:
        if not (a.iloc[-1] < b.iloc[-1]):
            return -1
        event=(a<b) & (a.shift(1)>=b.shift(1))
    vals=event.tail(max_lookback+1).tolist()
    for age,v in enumerate(reversed(vals)):
        if bool(v):
            return age
    return max_lookback+1

def macd_signal_text(close):
    dif,dea,hist=macd_values(close)
    if len(dif)<3:
        return "数据不足","—","—",-1
    gold_age=cross_age(dif,dea,"gold")
    dead_age=cross_age(dif,dea,"dead")
    axis="零轴上" if dif.iloc[-1]>=0 else "零轴下"

    if hist.iloc[-1]>=0:
        hist_state="红柱放大" if hist.iloc[-1]>hist.iloc[-2] else "红柱缩短"
    else:
        hist_state="绿柱缩短" if hist.iloc[-1]>hist.iloc[-2] else "绿柱放大"

    if gold_age>=0:
        if gold_age==0:
            sig=f"{axis}金叉（今日）"
        elif gold_age<=5:
            sig=f"{axis}金叉后{gold_age}天"
        else:
            sig=f"{axis}多头"
        age=gold_age
    elif dead_age>=0:
        if dead_age==0:
            sig=f"{axis}死叉（今日）"
        elif dead_age<=5:
            sig=f"{axis}死叉后{dead_age}天"
        else:
            sig=f"{axis}空头"
        age=dead_age
    else:
        sig="多头" if dif.iloc[-1]>=dea.iloc[-1] else "空头"
        age=-1
    return sig,axis,hist_state,age

def kdj_signal_text(df):
    k,d,j=kdj_values(df)
    if len(k)<3:
        return "数据不足","—",-1,50.0,50.0,50.0
    gold_age=cross_age(k,d,"gold")
    dead_age=cross_age(k,d,"dead")
    kv=float(k.iloc[-1]); dv=float(d.iloc[-1]); jv=float(j.iloc[-1])

    if kv<30 and dv<30:
        area="低位"
    elif kv>80 and dv>80:
        area="高位"
    else:
        area="中位"

    if gold_age>=0:
        cross_k=float(k.iloc[-1-gold_age]) if gold_age < len(k) else kv
        cross_d=float(d.iloc[-1-gold_age]) if gold_age < len(d) else dv
        cross_area="低位" if cross_k<30 and cross_d<30 else ("高位" if cross_k>80 and cross_d>80 else "中位")
        if gold_age==0:
            sig=f"{cross_area}金叉（今日）"
        elif gold_age<=5:
            sig=f"{cross_area}金叉后{gold_age}天"
        else:
            sig=f"{area}多头"
        age=gold_age
    elif dead_age>=0:
        cross_k=float(k.iloc[-1-dead_age]) if dead_age < len(k) else kv
        cross_d=float(d.iloc[-1-dead_age]) if dead_age < len(d) else dv
        cross_area="高位" if cross_k>80 and cross_d>80 else ("低位" if cross_k<30 and cross_d<30 else "中位")
        if dead_age==0:
            sig=f"{cross_area}死叉（今日）"
        elif dead_age<=5:
            sig=f"{cross_area}死叉后{dead_age}天"
        else:
            sig=f"{area}空头"
        age=dead_age
    else:
        sig=f"{area}多头" if kv>=dv else f"{area}空头"
        age=-1
    return sig,area,age,kv,dv,jv

def timing_confirmation(df, macd_sig, macd_hist_state, kdj_sig, rsi_value, volume_ratio):
    """
    择时确认分 0~20。
    位置分类(A1/A2/A3)不由本分数改变，本分数仅用于排序辅助和最终建议。
    """
    score=0
    reasons=[]

    # MACD
    if "零轴下金叉" in macd_sig:
        score+=6; reasons.append("MACD零轴下金叉")
    elif "金叉" in macd_sig:
        score+=4; reasons.append("MACD金叉")
    elif "多头" in macd_sig:
        score+=2

    if macd_hist_state=="红柱放大":
        score+=3; reasons.append("MACD动能增强")
    elif macd_hist_state=="绿柱缩短":
        score+=2; reasons.append("MACD空头动能衰减")
    elif macd_hist_state=="红柱缩短":
        score-=2
    elif macd_hist_state=="绿柱放大":
        score-=3

    if "零轴上死叉" in macd_sig:
        score-=6; reasons.append("MACD高位死叉")

    # KDJ
    if "低位金叉" in kdj_sig:
        score+=5; reasons.append("KDJ低位金叉")
    elif "金叉" in kdj_sig:
        score+=3; reasons.append("KDJ金叉")
    elif "多头" in kdj_sig:
        score+=1

    if "高位死叉" in kdj_sig:
        score-=5; reasons.append("KDJ高位死叉")
    elif "死叉" in kdj_sig:
        score-=2

    # RSI 与量能确认
    rr=rsi(df["close"])
    recent_min=float(rr.tail(6).min()) if len(rr)>=6 else float(rsi_value)
    if 40<=rsi_value<=62 and recent_min<50:
        score+=3; reasons.append("RSI回升")
    elif 42<=rsi_value<=60:
        score+=2

    if np.isfinite(volume_ratio):
        if volume_ratio>=1.15:
            score+=3; reasons.append("量能改善")
        elif volume_ratio>=1.02:
            score+=1
        elif volume_ratio<0.8:
            score-=1

    return int(round(clip(score,0,20))), "、".join(reasons[:4]) if reasons else "暂无明显共振"


def boll_values(df, n=20, k=2.0):
    """
    标准 BOLL(20,2):
    mid = MA20
    upper/lower = mid ± 2 * rolling std
    """
    d=norm(df)
    c=d["close"].astype(float)
    mid=c.rolling(n).mean()
    std=c.rolling(n).std(ddof=0)
    upper=mid+k*std
    lower=mid-k*std
    width=((upper-lower)/mid.replace(0,np.nan)*100)
    return mid,upper,lower,width

def atr_values(df,n=14):
    """ATR14，用于动态判断回踩区间与失效缓冲。"""
    d=norm(df)
    c=d["close"].astype(float)
    h=d["high"].astype(float) if "high" in d.columns else c
    l=d["low"].astype(float) if "low" in d.columns else c
    pc=c.shift(1)
    tr=pd.concat([(h-l).abs(),(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/n,adjust=False,min_periods=n).mean()

def boll_signal_text(df):
    d=norm(df)
    if len(d)<25:
        return "数据不足","—","—",np.nan,np.nan,np.nan,np.nan
    c=d["close"]
    mid,up,lo,width=boll_values(d)
    cur=float(c.iloc[-1]); prev=float(c.iloc[-2])
    m=float(mid.iloc[-1]); u=float(up.iloc[-1]); l=float(lo.iloc[-1])
    if not all(np.isfinite(x) for x in [m,u,l]):
        return "数据不足","—","—",np.nan,np.nan,np.nan,np.nan

    # 位置
    if cur>=u:
        pos="上轨上方"
    elif cur>=m:
        pos="中轨上方"
    elif cur>=l:
        pos="中轨下方"
    else:
        pos="下轨下方"

    # 中轨方向
    m5=float(mid.iloc[-6]) if len(mid)>=6 and np.isfinite(mid.iloc[-6]) else m
    if m > m5*1.003:
        mid_dir="中轨向上"
    elif m < m5*0.997:
        mid_dir="中轨向下"
    else:
        mid_dir="中轨走平"

    # 带宽方向
    w=float(width.iloc[-1]) if np.isfinite(width.iloc[-1]) else np.nan
    w5=float(width.iloc[-6]) if len(width)>=6 and np.isfinite(width.iloc[-6]) else w
    if np.isfinite(w) and np.isfinite(w5):
        if w > w5*1.12:
            width_state="带宽扩大"
        elif w < w5*0.88:
            width_state="带宽收窄"
        else:
            width_state="带宽稳定"
    else:
        width_state="带宽未知"

    # 关键信号
    prev_mid=float(mid.iloc[-2]) if np.isfinite(mid.iloc[-2]) else m
    prev_low=float(lo.iloc[-2]) if np.isfinite(lo.iloc[-2]) else l
    prev_up=float(up.iloc[-2]) if np.isfinite(up.iloc[-2]) else u

    if prev < prev_low and cur >= l:
        sig="下轨反弹"
    elif prev <= prev_mid and cur > m:
        sig="重新站上中轨"
    elif prev >= prev_mid and cur < m:
        sig="跌破中轨"
    elif prev <= prev_up and cur > u:
        sig="突破上轨"
    elif prev >= prev_low and cur < l:
        sig="跌破下轨"
    elif cur>=m and abs(cur-m)/m<=0.02:
        sig="中轨支撑"
    elif cur>m:
        sig="中轨上方运行"
    else:
        sig="中轨下方运行"

    dist_mid=(cur/m-1)*100
    dist_up=(cur/u-1)*100
    dist_low=(cur/l-1)*100
    return sig,pos,f"{mid_dir}/{width_state}",round(dist_mid,2),round(dist_up,2),round(dist_low,2),round(w,2) if np.isfinite(w) else np.nan

def observation_stage(age):
    age=int(age) if pd.notna(age) else 0
    if age<=3:
        return "新信号 0~3日"
    if age<=10:
        return "短期验证 4~10日"
    if age<=20:
        return "中期验证 11~20日"
    if age<=40:
        return "完整验证 21~40日"
    return "长期跟踪 >40日"

def lifecycle_text(group, age):
    g=str(group)
    stage=observation_stage(age)
    if g.startswith("A1"):
        return f"A1｜{stage}"
    if g.startswith("A2"):
        return f"A2｜{stage}"
    if g.startswith("A3"):
        return f"A3｜已加速"
    if g.startswith("B"):
        return f"B｜{stage}"
    if g.startswith("C"):
        return "C｜趋势跟踪"
    if g.startswith("D"):
        return "D｜高位阶段"
    return f"观察｜{stage}"

def position_judgement(df, group, boll_sig, timing):
    """
    当前位置：理想 / 合理 / 偏高 / 过热 / 信号失效
    使用 MA10/MA20/BOLL/ATR 动态判断，不采用固定百分比。
    """
    d=norm(df)
    c=d["close"]
    if len(d)<25:
        return "数据不足","—","—","—"

    cur=float(c.iloc[-1])
    ma10=float(c.rolling(10).mean().iloc[-1])
    ma20=float(c.rolling(20).mean().iloc[-1])
    mid,up,lo,width=boll_values(d)
    atr=atr_values(d)
    m=float(mid.iloc[-1]); u=float(up.iloc[-1]); l=float(lo.iloc[-1])
    av=float(atr.iloc[-1]) if np.isfinite(atr.iloc[-1]) else cur*0.02
    atrp=av/cur*100 if cur else np.nan

    # 最近启动低点：近10个交易日低点；失效留0.5 ATR缓冲
    low_series=d["low"] if "low" in d.columns else c
    recent_low=float(low_series.tail(10).min())
    invalid=recent_low-0.5*av

    # 动态理想区：MA20/BOLL中轨附近，宽度取 0.6 ATR
    center=(ma20+m)/2
    ideal_low=min(ma20,m)-0.6*av
    ideal_high=max(ma20,m)+0.6*av

    # 合理区：MA10 到 BOLL中轨/MA20 上方 1ATR
    reasonable_low=min(ma10,ma20,m)-0.5*av
    reasonable_high=max(ma10,ma20,m)+1.0*av

    if cur < invalid or boll_sig=="跌破下轨":
        pos="信号失效"
    elif cur <= ideal_high and cur >= ideal_low:
        pos="理想区"
    elif cur <= reasonable_high and cur >= reasonable_low:
        pos="合理区"
    elif cur >= u+0.5*av:
        pos="过热"
    elif cur > reasonable_high:
        pos="偏高"
    else:
        pos="偏低等待确认"

    dist_ideal=(cur-center)/center*100 if center else np.nan
    ideal_text=f"{ideal_low:.2f} ~ {ideal_high:.2f}"
    invalid_text=f"< {invalid:.2f}"
    return pos,ideal_text,invalid_text,round(dist_ideal,2) if np.isfinite(dist_ideal) else np.nan

def timing_confirmation_v19(df, macd_sig, macd_hist_state, kdj_sig, boll_sig, boll_state, rsi_value, volume_ratio):
    """
    V1.0 择时确认分继续维持 0~20，但把 BOLL 纳入。
    为避免总分膨胀，MACD/KDJ/RSI/量能/BOLL共同归一到20。
    """
    raw=0
    reasons=[]

    # MACD
    if "零轴下金叉" in macd_sig:
        raw+=6; reasons.append("MACD零轴下金叉")
    elif "金叉" in macd_sig:
        raw+=4; reasons.append("MACD金叉")
    elif "多头" in macd_sig:
        raw+=2

    if macd_hist_state=="红柱放大":
        raw+=3; reasons.append("MACD动能增强")
    elif macd_hist_state=="绿柱缩短":
        raw+=2; reasons.append("空头动能衰减")
    elif macd_hist_state=="红柱缩短":
        raw-=2
    elif macd_hist_state=="绿柱放大":
        raw-=3

    if "零轴上死叉" in macd_sig:
        raw-=6; reasons.append("MACD高位死叉")

    # KDJ
    if "低位金叉" in kdj_sig:
        raw+=5; reasons.append("KDJ低位金叉")
    elif "金叉" in kdj_sig:
        raw+=3; reasons.append("KDJ金叉")
    elif "多头" in kdj_sig:
        raw+=1

    if "高位死叉" in kdj_sig:
        raw-=5; reasons.append("KDJ高位死叉")
    elif "死叉" in kdj_sig:
        raw-=2

    # BOLL
    if boll_sig=="下轨反弹":
        raw+=3; reasons.append("BOLL下轨反弹")
    elif boll_sig=="重新站上中轨":
        raw+=4; reasons.append("BOLL站上中轨")
    elif boll_sig=="中轨支撑":
        raw+=2; reasons.append("BOLL中轨支撑")
    elif boll_sig=="突破上轨":
        raw+=1; reasons.append("BOLL突破上轨")
    elif boll_sig=="跌破中轨":
        raw-=3; reasons.append("BOLL跌破中轨")
    elif boll_sig=="跌破下轨":
        raw-=5; reasons.append("BOLL跌破下轨")

    if "中轨向上" in boll_state and "带宽扩大" in boll_state:
        raw+=3; reasons.append("BOLL向上开口")
    elif "中轨向上" in boll_state:
        raw+=2

    # RSI
    rr=rsi(df["close"])
    recent_min=float(rr.tail(6).min()) if len(rr)>=6 else float(rsi_value)
    if 40<=rsi_value<=62 and recent_min<50:
        raw+=3; reasons.append("RSI回升")
    elif 42<=rsi_value<=60:
        raw+=2

    # 量能
    if np.isfinite(volume_ratio):
        if volume_ratio>=1.15:
            raw+=3; reasons.append("量能改善")
        elif volume_ratio>=1.02:
            raw+=1
        elif volume_ratio<0.8:
            raw-=1

    # raw 理论范围大于20，映射到0~20
    score=int(round(clip(raw,0,26)/26*20))
    return score, "、".join(reasons[:5]) if reasons else "暂无明显共振"

def final_advice_v19(group,state,timing,risk,macd_sig,kdj_sig,boll_sig,position,stage):
    g=str(group)
    bearish=(("死叉" in macd_sig and "死叉" in kdj_sig) or boll_sig in ("跌破中轨","跌破下轨"))
    high_risk=risk>=52

    if position=="信号失效":
        return "信号失效｜等待重新形成转强结构"
    if g.startswith("A1"):
        if high_risk:
            return f"谨慎观察｜{stage}｜A1成立但风险偏高"
        if position=="理想区" and timing>=14 and not bearish:
            return f"优先研究｜{stage}｜理想区，多指标共振"
        if position=="合理区" and timing>=12 and not bearish:
            return f"重点观察｜{stage}｜当前位置合理"
        if position in ("偏高","过热"):
            return f"等待回踩｜{stage}｜A1成立但当前位置偏高"
        return f"观察｜{stage}｜A1成立，等待更强确认"

    if g.startswith("A2"):
        if position=="理想区" and timing>=13 and not high_risk:
            return f"重点观察｜{stage}｜回踩至较优位置"
        if position in ("偏高","过热"):
            return f"不追｜{stage}｜等待MA20/BOLL中轨附近"
        return f"观察｜{stage}｜转强确认中"

    if g.startswith("A3"):
        return "不追高｜已加速｜等待回踩重新形成择时信号"

    if g.startswith("B"):
        if state=="筑底" and timing>=12 and not high_risk and position in ("理想区","合理区"):
            return f"潜在候选｜{stage}｜等待升级A1/A2"
        return f"继续等待｜{stage}｜尚未确认转强"

    if g.startswith("C"):
        return "趋势跟踪｜不属于低位策略" if not bearish else "趋势降温｜注意回撤"
    if g.startswith("D"):
        return "高位谨慎｜不追高"
    return "观察｜等待更清晰信号"

def analyze(name, df, bench=None, level=""):
    df=norm(df)
    if df.empty or len(df)<65: raise ValueError("历史数据不足")
    c=df["close"]
    ps={k:round(pos(c,n),1) for k,n in PERIODS.items()}
    p6=ps["6个月"]; r15=rel_return(df,bench,15); r21=rel_return(df,bench,21)
    age=age_signal(df)
    rsi_value=float(rsi(c).iloc[-1])
    st=state_of(df,p6,r15,r21)
    gp=group_of(st,ps,age,rsi_value)
    ma5s=c.rolling(5).mean(); ma10s=c.rolling(10).mean(); ma20s=c.rolling(20).mean(); ma60s=c.rolling(60).mean()
    ratio=np.nan
    if "amount" in df.columns:
        a5=df["amount"].tail(5).mean(); a20=df["amount"].tail(20).mean()
        if a20: ratio=a5/a20

    macd_sig,macd_axis,macd_hist_state,macd_age=macd_signal_text(c)
    kdj_sig,kdj_area,kdj_age,kv,dv,jv=kdj_signal_text(df)
    boll_sig,boll_pos,boll_state,boll_mid_dist,boll_up_dist,boll_low_dist,boll_width=boll_signal_text(df)
    timing,timing_reason=timing_confirmation_v19(df,macd_sig,macd_hist_state,kdj_sig,boll_sig,boll_state,rsi_value,ratio)
    stage=observation_stage(age)
    lifecycle=lifecycle_text(gp,age)
    position,ideal_zone,invalid_zone,dist_ideal=position_judgement(df,gp,boll_sig,timing)
    advice=final_advice_v19(gp,st,timing,risk_score(df,p6,st),macd_sig,kdj_sig,boll_sig,position,stage)

    return {
        "名称":name,"层级":level,"最新日期":df["date"].iloc[-1].strftime("%Y-%m-%d"),
        "最新值":round(float(c.iloc[-1]),3),**ps,"状态":st,"分类":gp,
        "机会分":opp_score(df,p6,r15,r21,age),"风险分":risk_score(df,p6,st),"信号年龄":age,
        "择时确认分":timing,
        "观察阶段":stage,
        "生命周期":lifecycle,
        "当前位置":position,
        "理想观察区":ideal_zone,
        "信号失效区":invalid_zone,
        "距理想区中心%":dist_ideal,
        "MACD信号":macd_sig,
        "MACD位置":macd_axis,
        "MACD柱":macd_hist_state,
        "MACD交叉年龄":macd_age,
        "KDJ信号":kdj_sig,
        "KDJ区域":kdj_area,
        "K值":round(kv,1),"D值":round(dv,1),"J值":round(jv,1),
        "BOLL信号":boll_sig,
        "BOLL位置":boll_pos,
        "BOLL状态":boll_state,
        "距BOLL中轨%":boll_mid_dist,
        "距BOLL上轨%":boll_up_dist,
        "距BOLL下轨%":boll_low_dist,
        "BOLL带宽%":boll_width,
        "择时依据":timing_reason,
        "最终建议":advice,
        "RSI14":round(rsi_value,1),
        "MA5方向":"↑" if ma5s.iloc[-1]>=ma5s.iloc[-2] else "↓",
        "MA10方向":"↑" if ma10s.iloc[-1]>=ma10s.iloc[-2] else "↓",
        "MA20方向":"↑" if ma20s.iloc[-1]>=ma20s.iloc[-6] else "↓",
        "MA60方向":"↑" if ma60s.iloc[-1]>=ma60s.iloc[-6] else "↓",
        "15日相对沪深300":round(r15,2) if np.isfinite(r15) else np.nan,
        "1月相对沪深300":round(r21,2) if np.isfinite(r21) else np.nan,
        "5日成交额/20日均值":round(ratio,2) if np.isfinite(ratio) else np.nan,
        "20日年化波动率%":round(vol(c),1) if np.isfinite(vol(c)) else np.nan,
        "6月最大回撤%":round(mdd(c),1) if np.isfinite(mdd(c)) else np.nan,
        "距6月高点%":round(cur_dd(c),1) if np.isfinite(cur_dd(c)) else np.nan,
        "5日涨跌%":round(ret(c,5),2) if np.isfinite(ret(c,5)) else np.nan,
        "15日涨跌%":round(ret(c,15),2) if np.isfinite(ret(c,15)) else np.nan,
        "1月涨跌%":round(ret(c,21),2) if np.isfinite(ret(c,21)) else np.nan,
    }

def call_retry(fn, label, tries=3):
    last=None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            last=e
            if i<tries-1:
                log(f"{label} 第{i+1}次失败，稍后重试：{e}")
                time.sleep(1.5*(i+1))
    raise last

def set_cn_direct():
    # 只让中国公开行情源尽量直连；不影响后面的 Yahoo
    domains = ["swsresearch.com","www.swsresearch.com","gu.qq.com","qt.gtimg.cn",
               "finance.sina.com.cn","hq.sinajs.cn","vip.stock.finance.sina.com.cn"]
    cur=os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    parts=[x.strip() for x in cur.split(",") if x.strip()]
    for d in domains:
        if d not in parts: parts.append(d)
    v=",".join(parts)
    os.environ["NO_PROXY"]=v; os.environ["no_proxy"]=v

def benchmark():
    f=CACHE/f"{CACHE_TAG}_hs300.csv"
    if f.exists():
        d=norm(pd.read_csv(f))
        if not d.empty: return d
    set_cn_direct()
    # 腾讯优先，新浪兜底；彻底不再调用东方财富
    errors=[]
    for label, func in [
        ("腾讯沪深300", lambda: ak.stock_zh_index_daily_tx(symbol="sh000300")),
        ("新浪沪深300", lambda: ak.stock_zh_index_daily(symbol="sh000300")),
    ]:
        try:
            d=norm(call_retry(func,label,2))
            if not d.empty:
                d.tail(400).to_csv(f,index=False)
                log(f"沪深300基准来源：{label}")
                return d.tail(400).reset_index(drop=True)
        except Exception as e:
            errors.append(f"{label}: {e}")
    raise RuntimeError("沪深300两个备用源都失败："+" | ".join(errors))

def sw_list():
    global SW_REALTIME
    SW_REALTIME = {}
    set_cn_direct()
    rows=[]
    errors=[]
    # 一级优先；二级失败不影响整个报告
    for level in ("一级行业","二级行业"):
        try:
            df=call_retry(lambda lv=level: ak.index_realtime_sw(symbol=lv),f"申万{level}",2)
            code_col=next((c for c in df.columns if "指数代码" in str(c) or str(c)=="代码"),None)
            name_col=next((c for c in df.columns if "指数名称" in str(c) or str(c)=="名称"),None)
            if not code_col or not name_col:
                raise RuntimeError(f"无法识别列：{list(df.columns)}")
            def pick_col(candidates):
                for cand in candidates:
                    for col in df.columns:
                        if str(col).strip() == cand or cand in str(col):
                            return col
                return None

            open_col=pick_col(["今开盘","开盘价","开盘"])
            high_col=pick_col(["最高价","最高"])
            low_col=pick_col(["最低价","最低"])
            close_col=pick_col(["最新价","最新","收盘价","收盘"])
            amount_col=pick_col(["成交额"])
            volume_col=pick_col(["成交量"])

            for _,r in df.iterrows():
                code=str(r[code_col]).split(".")[0].strip()
                name=str(r[name_col]).strip()
                if code and name and code!="nan" and name!="nan":
                    rows.append((code,name,level))

                    snap={"date":TODAY}
                    for key,col in [
                        ("open",open_col),("high",high_col),("low",low_col),
                        ("close",close_col),("amount",amount_col),("volume",volume_col)
                    ]:
                        if col is not None:
                            try:
                                snap[key]=float(pd.to_numeric(r[col],errors="coerce"))
                            except Exception:
                                pass
                    if np.isfinite(snap.get("close",np.nan)):
                        SW_REALTIME[code]=snap
        except Exception as e:
            errors.append(f"{level}: {e}")
            log(f"申万{level}列表获取失败，跳过：{e}")
    if not rows:
        # 一级行业静态兜底，保证接口列表失败时仍能尝试历史行情
        static = [
            ("801010","农林牧渔"),("801030","基础化工"),("801040","钢铁"),("801050","有色金属"),
            ("801080","电子"),("801110","家用电器"),("801120","食品饮料"),("801130","纺织服饰"),
            ("801140","轻工制造"),("801150","医药生物"),("801160","公用事业"),("801170","交通运输"),
            ("801180","房地产"),("801200","商贸零售"),("801210","社会服务"),("801230","综合"),
            ("801710","建筑材料"),("801720","建筑装饰"),("801730","电力设备"),("801740","国防军工"),
            ("801750","计算机"),("801760","传媒"),("801770","通信"),("801780","银行"),
            ("801790","非银金融"),("801880","汽车"),("801890","机械设备"),("801950","煤炭"),
            ("801960","石油石化"),("801970","环保"),("801980","美容护理"),
        ]
        rows=[(c,n,"一级行业") for c,n in static]
        log("申万实时列表不可用，已启用内置一级行业代码表。")
    # 去重
    seen=set(); out=[]
    for x in rows:
        if x[0] not in seen:
            seen.add(x[0]); out.append(x)
    return out, errors

def sw_hist(code):
    f=CACHE/f"{CACHE_TAG}_sw_{code}.csv"
    if f.exists():
        d=norm(pd.read_csv(f))
        if len(d)>=65:
            return d

    set_cn_direct()
    d=norm(call_retry(lambda: ak.index_hist_sw(symbol=code,period="day"),f"申万{code}",2))
    if d.empty:
        raise RuntimeError("返回空数据")
    d=d.tail(420).reset_index(drop=True)

    # 午盘/盘中/收盘：用 index_realtime_sw 的当前快照更新/补入今天这一根日K。
    # 这样三次运行不会只是重复昨天收盘数据。
    if SCAN_SLOT != "盘前":
        snap=SW_REALTIME.get(str(code))
        if snap and np.isfinite(snap.get("close",np.nan)):
            row={"date":pd.to_datetime(TODAY)}
            close=float(snap["close"])
            row["close"]=close
            for k in ("open","high","low","amount","volume"):
                v=snap.get(k,np.nan)
                row[k]=float(v) if np.isfinite(v) else np.nan

            # 若实时接口缺少OHLC，用最新价兜底，确保技术指标可计算
            for k in ("open","high","low"):
                if not np.isfinite(row.get(k,np.nan)) or row[k] <= 0:
                    row[k]=close

            today_dt=pd.to_datetime(TODAY)
            d=d[d["date"]!=today_dt].copy()
            d=pd.concat([d,pd.DataFrame([row])],ignore_index=True)
            d=norm(d).tail(420).reset_index(drop=True)

    d.to_csv(f,index=False)
    return d

def set_global_direct():
    domains = [
        "finance.sina.com.cn",
        "stock.finance.sina.com.cn",
        "gi.finance.sina.com.cn",
        "fred.stlouisfed.org",
        "api.stlouisfed.org",
    ]
    cur = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    parts = [x.strip() for x in cur.split(",") if x.strip()]
    for d in domains:
        if d not in parts:
            parts.append(d)
    v = ",".join(parts)
    os.environ["NO_PROXY"] = v
    os.environ["no_proxy"] = v

def fred_series(series_id: str) -> pd.DataFrame:
    """
    FRED 免费 CSV，不需要 API Key。
    只取 date + close，足够用于位置、MA、RSI、趋势和风险分析。
    """
    import requests
    set_global_direct()
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    df = pd.read_csv(StringIO(r.text))
    if df.empty or len(df.columns) < 2:
        raise RuntimeError(f"FRED {series_id} 返回空数据")
    date_col = df.columns[0]
    value_col = df.columns[1]
    df = df.rename(columns={date_col: "date", value_col: "close"})
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df.dropna(subset=["date", "close"]).tail(420).reset_index(drop=True)

def global_cached(key: str, fetcher, label: str) -> pd.DataFrame:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in key)
    f = CACHE / f"{CACHE_TAG}_global_{safe}.csv"
    if f.exists():
        d = norm(pd.read_csv(f))
        if len(d) >= 65:
            return d
    d = norm(call_retry(fetcher, label, 2))
    if len(d) < 65:
        raise RuntimeError(f"{label} 历史数据不足：{len(d)}")
    d = d.tail(420).reset_index(drop=True)
    d.to_csv(f, index=False)
    return d

def fetch_with_fallback(name, candidates):
    """
    candidates: [(数据源名称, callable), ...]
    返回 (df, source)
    """
    errors = []
    for source, fn in candidates:
        try:
            df = global_cached(name + "_" + source, fn, f"{name}/{source}")
            return df, source
        except Exception as e:
            errors.append(f"{source}: {e}")
            log(f"{name} 数据源 {source} 失败，尝试备用源：{e}")
    raise RuntimeError(" | ".join(errors))


def global_asset_comment(row):
    name=str(row.get("名称",""))
    state=str(row.get("状态",""))
    p15=pd.to_numeric(pd.Series([row.get("15天",np.nan)]),errors="coerce").iloc[0]
    p1=pd.to_numeric(pd.Series([row.get("1个月",np.nan)]),errors="coerce").iloc[0]
    p3=pd.to_numeric(pd.Series([row.get("3个月",np.nan)]),errors="coerce").iloc[0]
    p6=pd.to_numeric(pd.Series([row.get("6个月",np.nan)]),errors="coerce").iloc[0]
    risk=float(row.get("风险分",0) or 0)

    def hi(x,t): return np.isfinite(x) and x>=t
    def lo(x,t): return np.isfinite(x) and x<=t

    if name=="黄金":
        if state in ("趋势确认","强趋势","高位强势"):
            view="偏强"
            desc="黄金趋势较强，通常意味着避险/通胀交易存在支撑。"
            amap="关注黄金、有色贵金属；若美元和美债收益率同时走强，要警惕黄金承压。"
        elif lo(p6,30) and state in ("筑底","震荡","初步转强"):
            view="低位观察"
            desc="黄金中期位置偏低，处于震荡或筑底阶段。"
            amap="若后续美元走弱、实际利率回落，黄金方向更容易转强。"
        elif hi(p6,85):
            view="高位谨慎"
            desc="黄金已处于中期高位，继续追涨性价比下降。"
            amap="贵金属方向更适合等回踩，而非单看趋势追高。"
        else:
            view="中性"
            desc="黄金暂未出现特别明确的趋势优势。"
            amap="对A股贵金属的指引偏中性。"

    elif name in ("WTI原油","Brent原油"):
        if state in ("趋势确认","强趋势","高位强势") or hi(p15,90):
            view="强势"
            desc="原油短期明显偏强，能源价格处在强势阶段。"
            amap="偏利好油服、石油石化、炼化；但若已连续快速上涨，也要防地缘缓和后的回撤。"
        elif lo(p6,30) and state in ("筑底","初步转强"):
            view="低位转强"
            desc="原油仍在中低位，但已有转强迹象。"
            amap="油服和上游资源股通常比下游更受益。"
        elif state in ("下跌","超跌"):
            view="偏弱"
            desc="原油趋势偏弱。"
            amap="对油服、石油石化偏压制；对航空、化工下游成本端可能相对友好。"
        else:
            view="震荡"
            desc="原油缺乏明确趋势。"
            amap="能源板块更依赖国内基本面和事件催化。"

    elif name in ("标普500","纳斯达克100","纳斯达克综合","道琼斯","罗素2000","费城半导体SOX"):
        if state in ("下跌","超跌"):
            view="偏弱"
            desc="海外对应风险资产处于下跌/弱势阶段。"
            amap="若是SOX/纳指偏弱，对A股半导体、AI、电子的情绪映射通常偏负面。"
        elif hi(p6,85):
            view="高位"
            desc="指数仍强，但中期位置偏高。"
            amap="风险偏好尚可，但高位环境下要防海外回撤传导。"
        elif state in ("趋势确认","强趋势"):
            view="偏强"
            desc="海外风险资产趋势较强。"
            amap="对A股成长、科技、券商等风险偏好方向通常更友好。"
        elif lo(p6,30):
            view="低位观察"
            desc="海外指数处于中期相对低位。"
            amap="若开始转强，可能改善A股成长风格外部环境。"
        else:
            view="中性"
            desc="海外股指处于震荡或中性状态。"
            amap="对A股更多是背景变量，而非单独催化。"

    elif name=="美国10年期收益率":
        if hi(p6,90) or state in ("高位","高位强势"):
            view="高利率压力"
            desc="美国长端收益率位于高位，对全球估值形成压力。"
            amap="相对压制高估值成长/科技；价值、金融、资源风格相对占优。"
        elif lo(p6,25):
            view="利率回落"
            desc="美债收益率处于低位或明显回落。"
            amap="通常更利于成长股、科技股和黄金估值修复。"
        else:
            view="中性"
            desc="美国长端利率处于中间区域。"
            amap="对A股风格影响偏中性。"

    elif name=="VIX":
        if hi(p6,80) or state in ("强趋势","高位","高位强势"):
            view="风险升温"
            desc="VIX处于高位，海外避险情绪明显升温。"
            amap="通常不利于A股高波动成长和题材，防御/红利相对占优。"
        elif lo(p6,20):
            view="风险情绪平稳"
            desc="VIX处于低位，海外市场恐慌程度较低。"
            amap="风险偏好背景较友好，但极低VIX也意味着市场可能对风险过于乐观。"
        else:
            view="中性"
            desc="VIX处于正常区间。"
            amap="海外风险情绪暂未形成明显压制。"

    elif "美元" in name:
        if state in ("趋势确认","强趋势","高位强势") or hi(p6,80):
            view="美元偏强"
            desc="美元处于偏强阶段。"
            amap="通常对黄金、有色、新兴市场风险偏好形成一定压力。"
        elif state in ("下跌","超跌") or lo(p6,25):
            view="美元偏弱"
            desc="美元处于偏弱阶段。"
            amap="通常更有利于黄金、有色和全球风险资产。"
        else:
            view="震荡"
            desc="美元指数处于震荡状态。"
            amap="对A股影响偏中性。"
    else:
        view="观察"
        desc=f"{state}。"
        amap="作为全球环境辅助变量观察。"

    return view, desc, amap

def global_environment_summary(glob):
    if glob is None or glob.empty:
        return {
            "总览":"全球数据不足",
            "能源":"—",
            "美股":"—",
            "科技":"—",
            "利率美元":"—",
            "风险情绪":"—"
        }

    def row(name):
        x=glob[glob["名称"]==name]
        return None if x.empty else x.iloc[0]

    oil=row("Brent原油")
    if oil is None:
        oil=row("WTI原油")
    sp=row("标普500")
    sox=row("费城半导体SOX")
    y10=row("美国10年期收益率")
    vix=row("VIX")
    usd=None
    for n in ["美元广义指数","美元指数DXY"]:
        t=row(n)
        if t is not None:
            usd=t; break

    def st(r): return "—" if r is None else str(r.get("状态","—"))
    def p6v(r):
        if r is None: return np.nan
        return pd.to_numeric(pd.Series([r.get("6个月",np.nan)]),errors="coerce").iloc[0]

    energy = "偏强" if oil is not None and (st(oil) in ("趋势确认","强趋势","高位强势") or p6v(oil)>=70) else "中性/偏弱"
    equity = "高位偏强" if sp is not None and p6v(sp)>=80 else ("偏弱" if sp is not None and st(sp) in ("下跌","超跌") else "中性")
    tech = "偏弱" if sox is not None and st(sox) in ("下跌","超跌") else ("偏强" if sox is not None and st(sox) in ("趋势确认","强趋势") else "中性")
    rates = "偏紧" if y10 is not None and p6v(y10)>=85 else ("偏松" if y10 is not None and p6v(y10)<=25 else "中性")
    if usd is not None:
        if st(usd) in ("趋势确认","强趋势","高位强势") or p6v(usd)>=80:
            rates += " / 美元偏强"
        elif st(usd) in ("下跌","超跌") or p6v(usd)<=25:
            rates += " / 美元偏弱"
        else:
            rates += " / 美元震荡"
    risk = "恐慌偏低" if vix is not None and p6v(vix)<=20 else ("风险升温" if vix is not None and p6v(vix)>=80 else "中性")

    parts=[]
    if energy=="偏强": parts.append("能源强")
    if equity=="高位偏强": parts.append("美股高位")
    if tech=="偏弱": parts.append("海外科技偏弱")
    if rates.startswith("偏紧"): parts.append("利率偏紧")
    if risk=="恐慌偏低": parts.append("VIX低位")
    overview=" + ".join(parts) if parts else "全球环境中性"

    return {
        "总览":overview,
        "能源":energy,
        "美股":equity,
        "科技":tech,
        "利率美元":rates,
        "风险情绪":risk
    }

def enrich_global_analysis(glob):
    if glob is None or glob.empty:
        return pd.DataFrame()
    x=glob.copy()
    views=[]; comments=[]; maps=[]
    for _,r in x.iterrows():
        v,c,m=global_asset_comment(r)
        views.append(v); comments.append(c); maps.append(m)
    x["机会判断"]=views
    x["解读"]=comments
    x["A股映射"]=maps
    return x


def global_data():
    """
    V1.0:
    - 不再使用 ，避免 YFRateLimitError
    - 黄金/原油：新浪外盘期货；FRED 现货数据兜底
    - 美股核心指数：新浪美股指数
    - Russell/SOX/VIX：新浪指数优先，ETF/FRED 兜底
    - 美国10Y：新浪债券，FRED 兜底
    - 美元：FRED 广义美元指数（不是 DXY，报告中明确标注）
    """
    set_global_direct()
    rows = []
    log("获取全球资产（新浪 / FRED，已移除 ）...")

    specs = [
        (
            "黄金",
            [
                ("新浪COMEX黄金", lambda: ak.futures_foreign_hist(symbol="GC")),
                ("FRED伦敦金", lambda: fred_series("GOLDAMGBD228NLBM")),
            ],
        ),
        (
            "WTI原油",
            [
                ("新浪NYMEX原油", lambda: ak.futures_foreign_hist(symbol="CL")),
                ("FRED-WTI现货", lambda: fred_series("DCOILWTICO")),
            ],
        ),
        (
            "Brent原油",
            [
                ("新浪Brent原油", lambda: ak.futures_foreign_hist(symbol="OIL")),
                ("FRED-Brent现货", lambda: fred_series("DCOILBRENTE")),
            ],
        ),
        (
            "标普500",
            [
                ("新浪美股指数", lambda: ak.index_us_stock_sina(symbol=".INX")),
                ("FRED-SP500", lambda: fred_series("SP500")),
            ],
        ),
        (
            "纳斯达克100",
            [
                ("新浪美股指数", lambda: ak.index_us_stock_sina(symbol=".NDX")),
                ("FRED-NASDAQ100", lambda: fred_series("NASDAQ100")),
            ],
        ),
        (
            "纳斯达克综合",
            [
                ("新浪美股指数", lambda: ak.index_us_stock_sina(symbol=".IXIC")),
                ("FRED-NASDAQCOM", lambda: fred_series("NASDAQCOM")),
            ],
        ),
        (
            "道琼斯",
            [
                ("新浪美股指数", lambda: ak.index_us_stock_sina(symbol=".DJI")),
                ("FRED-DJIA", lambda: fred_series("DJIA")),
            ],
        ),
        (
            "罗素2000",
            [
                ("新浪Russell指数", lambda: ak.index_us_stock_sina(symbol=".RUT")),
                ("IWM ETF代理", lambda: ak.stock_us_daily(symbol="IWM", adjust="")),
            ],
        ),
        (
            "费城半导体SOX",
            [
                ("新浪SOX指数", lambda: ak.index_us_stock_sina(symbol=".SOX")),
                ("SOXX ETF代理", lambda: ak.stock_us_daily(symbol="SOXX", adjust="")),
            ],
        ),
        (
            "美国10年期收益率",
            [
                ("新浪美国国债", lambda: ak.bond_gb_us_sina(symbol="美国10年期国债")),
                ("FRED-DGS10", lambda: fred_series("DGS10")),
            ],
        ),
        (
            "VIX",
            [
                ("新浪VIX指数", lambda: ak.index_us_stock_sina(symbol=".VIX")),
                ("FRED-VIXCLS", lambda: fred_series("VIXCLS")),
                ("VIXY ETF代理", lambda: ak.stock_us_daily(symbol="VIXY", adjust="")),
            ],
        ),
        (
            "美元广义指数",
            [
                ("FRED-DTWEXBGS", lambda: fred_series("DTWEXBGS")),
                ("UUP ETF代理", lambda: ak.stock_us_daily(symbol="UUP", adjust="")),
            ],
        ),
    ]

    for name, candidates in specs:
        try:
            df, source = fetch_with_fallback(name, candidates)
            r = analyze(name, df, None, "全球资产")
            r["数据源"] = source
            rows.append(r)
            log(f"全球资产成功：{name} <- {source}")
        except Exception as e:
            log(f"全球资产跳过 {name}: {e}")

    return pd.DataFrame(rows)

def load_hist():
    if not HISTORY.exists(): return pd.DataFrame()
    try: return pd.read_csv(HISTORY)
    except: return pd.DataFrame()

def save_hist(ind):
    cols=[
        "扫描日期","扫描时间","扫描时段",
        "名称","层级","状态","分类","观察阶段","当前位置",
        "机会分","择时确认分","风险分",
        "15天","1个月","2个月","3个月","4个月","5个月","6个月",
        "信号年龄","MACD信号","KDJ信号","BOLL信号","BOLL状态",
        "理想观察区","信号失效区","最终建议"
    ]
    x=ind.copy()
    x["扫描日期"]=TODAY
    x["扫描时间"]=SCAN_TIME
    x["扫描时段"]=SCAN_SLOT
    x=x[cols]

    old=load_hist()
    if not old.empty:
        # 兼容旧列（本正式版从零开始，但这里防止CSV结构异常）
        if "扫描时段" not in old.columns:
            old["扫描时段"]="历史"
        if "扫描时间" not in old.columns:
            old["扫描时间"]="00:00:00"

        # 同一天 + 同一时段 + 同一板块只保留最新一次；
        # 盘前/午盘/收盘互不覆盖。
        mask=(
            (old["扫描日期"].astype(str)==TODAY) &
            (old["扫描时段"].astype(str)==SCAN_SLOT) &
            old["名称"].astype(str).isin(x["名称"].astype(str))
        )
        old=old[~mask]
        x=pd.concat([old,x],ignore_index=True)

    x.to_csv(HISTORY,index=False,encoding="utf-8-sig")


SIGNAL_COLUMNS = [
    "信号日期","记录日期","名称","层级","信号分类",
    "信号机会分","信号风险分","信号价格","沪深300信号值",
    "观察交易日",
    "5日收益%","5日超额%",
    "10日收益%","10日超额%",
    "20日收益%","20日超额%",
    "40日收益%","40日超额%",
    "当前最大回撤%","40日最大回撤%",
    "验证状态"
]

def load_signals():
    if not SIGNALS.exists():
        return pd.DataFrame(columns=SIGNAL_COLUMNS)
    try:
        x=pd.read_csv(SIGNALS)
        for c in SIGNAL_COLUMNS:
            if c not in x.columns:
                x[c]=np.nan
        return x[SIGNAL_COLUMNS]
    except Exception:
        return pd.DataFrame(columns=SIGNAL_COLUMNS)

def save_signals(x):
    if x is None or x.empty:
        pd.DataFrame(columns=SIGNAL_COLUMNS).to_csv(SIGNALS,index=False,encoding="utf-8-sig")
        return
    y=x.copy()
    for c in SIGNAL_COLUMNS:
        if c not in y.columns:
            y[c]=np.nan
    y[SIGNAL_COLUMNS].to_csv(SIGNALS,index=False,encoding="utf-8-sig")

def benchmark_value_on(bm, date_value):
    if bm is None or bm.empty:
        return np.nan
    d=norm(bm)
    target=pd.to_datetime(date_value,errors="coerce")
    if pd.isna(target):
        return np.nan
    q=d[d["date"]<=target]
    if q.empty:
        return np.nan
    return float(q.iloc[-1]["close"])

def previous_scan_class(old_hist, name, level):
    """
    正式A1历史验证只看今天之前最近一次扫描记录。
    盘前/午盘属于观察样本，不阻止今天收盘登记正式A1信号。
    """
    if old_hist is None or old_hist.empty:
        return None
    x=old_hist.copy()
    if "扫描日期" not in x.columns or "名称" not in x.columns:
        return None
    x["_d"]=pd.to_datetime(x["扫描日期"],errors="coerce")
    cutoff=pd.to_datetime(TODAY)
    x=x[(x["名称"].astype(str)==str(name)) & (x["_d"]<cutoff)]
    if "层级" in x.columns:
        y=x[x["层级"].astype(str)==str(level)]
        if not y.empty:
            x=y
    if x.empty:
        return None
    return str(x.sort_values("_d").iloc[-1].get("分类",""))

def register_new_a1_signals(ind, old_hist, hist_map, bm):
    """
    正式A1历史验证只在“收盘”时段登记。
    盘前/午盘/盘中只用于观察，不污染 +5/+10/+20/+40 交易日验证样本。
    """
    sig=load_signals()

    if SCAN_SLOT != "收盘":
        log(f"当前为{SCAN_SLOT}时段：只记录观察数据，不登记A1正式历史验证信号。")
        return sig
    rows=[]

    current=ind[ind["分类"].astype(str).str.startswith("A1")]
    for _,r in current.iterrows():
        name=str(r["名称"])
        level=str(r["层级"])
        key=(name,level)
        df=hist_map.get(key)
        if df is None or df.empty:
            continue

        signal_date=str(r.get("最新日期",TODAY))
        signal_price=float(r.get("最新值",df["close"].iloc[-1]))

        # 同一个交易日、同一个行业，只记录一次
        if not sig.empty:
            same=(
                (sig["信号日期"].astype(str)==signal_date) &
                (sig["名称"].astype(str)==name) &
                (sig["层级"].astype(str)==level)
            )
            if same.any():
                continue

        prev=previous_scan_class(old_hist,name,level)
        # 上次扫描已经是 A1，表示仍在同一段连续 A1 信号中
        if prev and prev.startswith("A1"):
            continue

        rows.append({
            "信号日期":signal_date,
            "记录日期":TODAY,
            "名称":name,
            "层级":level,
            "信号分类":str(r["分类"]),
            "信号机会分":float(r["机会分"]),
            "信号风险分":float(r["风险分"]),
            "信号价格":signal_price,
            "沪深300信号值":benchmark_value_on(bm,signal_date),
            "观察交易日":0,
            "5日收益%":np.nan,"5日超额%":np.nan,
            "10日收益%":np.nan,"10日超额%":np.nan,
            "20日收益%":np.nan,"20日超额%":np.nan,
            "40日收益%":np.nan,"40日超额%":np.nan,
            "当前最大回撤%":0.0,
            "40日最大回撤%":np.nan,
            "验证状态":"等待5日"
        })

    if rows:
        sig=pd.concat([sig,pd.DataFrame(rows)],ignore_index=True)
        log(f"新增 A1 历史验证信号 {len(rows)} 条："+"、".join(x["名称"] for x in rows))
    return sig

def _standard_max_drawdown(close_values):
    s=pd.Series(close_values,dtype=float).dropna()
    if s.empty:
        return np.nan
    peak=s.cummax()
    dd=s/peak-1
    return float(dd.min()*100)

def update_a1_signal_performance(sig, hist_map, bm):
    """
    +N日 = 信号收盘后的第 N 个交易日。
    超额 = 行业同期收益 - 沪深300同期收益。
    当前最大回撤 = 从信号日开始，到当前最多40个交易日内的标准最大回撤。
    """
    if sig is None or sig.empty:
        return pd.DataFrame(columns=SIGNAL_COLUMNS)

    out=sig.copy()
    bench=norm(bm)

    for idx,row in out.iterrows():
        key=(str(row["名称"]),str(row["层级"]))
        df=hist_map.get(key)
        if df is None or df.empty:
            continue
        d=norm(df)
        signal_date=pd.to_datetime(row["信号日期"],errors="coerce")
        if pd.isna(signal_date):
            continue

        # 从信号日开始；若日期存在微小不一致，取第一个 >= 信号日期的交易日
        after=d[d["date"]>=signal_date].reset_index(drop=True)
        if after.empty:
            continue

        base=float(after.iloc[0]["close"])
        actual_signal_date=after.iloc[0]["date"]
        observed=max(0,len(after)-1)
        out.at[idx,"观察交易日"]=observed

        # 沪深300与行业交易日对齐
        b=bench[["date","close"]].rename(columns={"close":"bm_close"}) if not bench.empty else pd.DataFrame()
        aligned=after[["date","close"]]
        if not b.empty:
            aligned=aligned.merge(b,on="date",how="left")
        else:
            aligned["bm_close"]=np.nan

        bm0=np.nan
        if "bm_close" in aligned.columns and len(aligned):
            bm0=aligned.iloc[0]["bm_close"]
        if not np.isfinite(bm0):
            bm0=benchmark_value_on(bench,actual_signal_date)

        for h in SIGNAL_HORIZONS:
            rc=f"{h}日收益%"
            ec=f"{h}日超额%"
            if len(aligned)>h:
                sector_ret=(float(aligned.iloc[h]["close"])/base-1)*100
                out.at[idx,rc]=round(sector_ret,3)

                bmh=aligned.iloc[h].get("bm_close",np.nan)
                if np.isfinite(bm0) and np.isfinite(bmh) and bm0!=0:
                    bm_ret=(float(bmh)/float(bm0)-1)*100
                    out.at[idx,ec]=round(sector_ret-bm_ret,3)

        # 当前可观察窗口最大40个交易日
        end=min(len(after),41)
        current_mdd=_standard_max_drawdown(after["close"].iloc[:end])
        out.at[idx,"当前最大回撤%"]=round(current_mdd,3) if np.isfinite(current_mdd) else np.nan

        if len(after)>40:
            mdd40=_standard_max_drawdown(after["close"].iloc[:41])
            out.at[idx,"40日最大回撤%"]=round(mdd40,3) if np.isfinite(mdd40) else np.nan

        if observed>=40:
            status="已完成40日"
        elif observed>=20:
            status="已有20日"
        elif observed>=10:
            status="已有10日"
        elif observed>=5:
            status="已有5日"
        else:
            status="等待5日"
        out.at[idx,"验证状态"]=status

    # 新信号放在最上面
    out["_date"]=pd.to_datetime(out["信号日期"],errors="coerce")
    out=out.sort_values(["_date","信号机会分"],ascending=[False,False]).drop(columns="_date").reset_index(drop=True)
    return out

def a1_signal_stats(sig):
    rows=[]
    if sig is None:
        sig=pd.DataFrame()
    for h in SIGNAL_HORIZONS:
        rc=f"{h}日收益%"
        ec=f"{h}日超额%"
        if sig.empty or rc not in sig.columns:
            valid=pd.DataFrame()
        else:
            valid=sig[pd.to_numeric(sig[rc],errors="coerce").notna()].copy()

        if valid.empty:
            rows.append({
                "周期":f"{h}日","样本数":0,"胜率%":np.nan,
                "平均收益%":np.nan,"平均超额%":np.nan,"超额胜率%":np.nan
            })
            continue

        rv=pd.to_numeric(valid[rc],errors="coerce")
        ev=pd.to_numeric(valid[ec],errors="coerce")
        rows.append({
            "周期":f"{h}日",
            "样本数":int(len(valid)),
            "胜率%":round(float((rv>0).mean()*100),1),
            "平均收益%":round(float(rv.mean()),2),
            "平均超额%":round(float(ev.mean()),2) if ev.notna().any() else np.nan,
            "超额胜率%":round(float((ev.dropna()>0).mean()*100),1) if ev.notna().any() else np.nan
        })
    return pd.DataFrame(rows)

def stats_sentence(stats, h):
    if stats is None or stats.empty:
        return f"{h}日：暂无样本"
    x=stats[stats["周期"]==f"{h}日"]
    if x.empty or int(x.iloc[0]["样本数"])==0:
        return f"{h}日：暂无成熟样本"
    r=x.iloc[0]
    return (
        f"{h}日：样本 {int(r['样本数'])}；胜率 {fmt(r['胜率%'])}%；"
        f"平均收益 {fmt(r['平均收益%'],2)}%；平均超额 {fmt(r['平均超额%'],2)}%"
    )

def fmt(v,d=1):
    if pd.isna(v): return "—"
    if isinstance(v,(float,np.floating)): return f"{v:.{d}f}"
    return str(v)


def safe_read_csv(path):
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()

def fmt_pct(v, digits=1):
    try:
        if pd.isna(v):
            return "—"
        return f"{float(v):.{digits}f}%"
    except Exception:
        return str(v)

def decision_priority(row):
    """
    给 ChatGPT 的跨日比较辅助排序。
    不替代最终投资判断。
    """
    g=str(row.get("分类",""))
    base=0
    if g.startswith("A1"): base=100
    elif g.startswith("A2"): base=80
    elif g.startswith("A3"): base=60
    elif g.startswith("B"): base=40
    elif g.startswith("C"): base=30
    else: base=10

    opp=float(row.get("机会分",0) or 0)
    timing=float(row.get("择时确认分",0) or 0)
    risk=float(row.get("风险分",50) or 50)
    pos=str(row.get("当前位置",""))
    pos_bonus={"理想区":8,"合理区":5,"偏低等待确认":2,"偏高":-4,"过热":-8,"信号失效":-20}.get(pos,0)
    return round(base + opp*0.25 + timing*0.8 - risk*0.15 + pos_bonus,2)

def compact_rows(df, limit=15):
    if df is None or df.empty:
        return []
    x=df.copy()
    if "决策优先分" not in x.columns:
        x["决策优先分"]=x.apply(decision_priority,axis=1)
    return x.sort_values(["决策优先分","机会分"],ascending=[False,False]).head(limit).to_dict("records")

def decision_pack_markdown(ind, glob, signals, stats, history):
    """
    单日完整决策包：
    用户可以直接把多个日期的这个文件上传给 ChatGPT 做跨日比较。
    """
    ind=ind.copy()
    ind["决策优先分"]=ind.apply(decision_priority,axis=1)

    a1=ind[ind["分类"].astype(str).str.startswith("A1")].copy()
    a2=ind[ind["分类"].astype(str).str.startswith("A2")].copy()
    a3=ind[ind["分类"].astype(str).str.startswith("A3")].copy()
    b=ind[ind["分类"].astype(str).str.startswith("B")].copy()

    env=global_environment_summary(glob)
    ga=enrich_global_analysis(glob)

    out=[]
    out += [
        "# ChatGPT 投资决策数据包",
        "",
        f"数据日期：{TODAY}",
        f"扫描时段：{SCAN_SLOT}",
        f"扫描时间：{SCAN_TIME}",
        f"生成时间：{NOW}",
        "",
        "## 一、使用说明",
        "",
        "这是本地量化扫描结果，不是投资建议。请将本文件与前几天同类文件一起交给 ChatGPT，",
        "让 ChatGPT 比较板块信号迁移、技术指标变化、全球环境变化，并联网核实最新行业催化和基金信息。",
        "",
        "重点不是只看某一天分数，而是比较盘前 / 午盘 / 收盘以及跨日变化：",
        "- B → A1 / A2 的升级",
        "- A1 是否连续确认",
        "- A1 → A3 是否已经加速",
        "- MACD / KDJ / BOLL 是否继续共振",
        "- 当前是否回到理想区 / 合理区",
        "- 信号是否触及失效条件",
        "",
        "## 二、今日摘要",
        "",
        f"- 成功扫描行业：{len(ind)}",
        f"- A1 低位刚转强：{len(a1)}",
        f"- A2 低位转强：{len(a2)}",
        f"- A3 已加速：{len(a3)}",
        f"- B 低位等待：{len(b)}",
        f"- 全球资产：{len(glob)}",
        "",
        "## 三、今日优先候选",
        ""
    ]

    top=ind.sort_values(["决策优先分","机会分"],ascending=[False,False]).head(15)
    for i,(_,r) in enumerate(top.iterrows(),1):
        out += [
            f"### {i}. {r['名称']}（{r['层级']}）",
            f"- 分类：{r['分类']}；观察阶段：{r['观察阶段']}；状态：{r['状态']}",
            f"- 机会分：{r['机会分']}；择时确认：{r['择时确认分']}/20；风险分：{r['风险分']}；决策优先分：{r['决策优先分']}",
            f"- 七周期位置：15天 {r['15天']}%；1月 {r['1个月']}%；2月 {r['2个月']}%；3月 {r['3个月']}%；4月 {r['4个月']}%；5月 {r['5个月']}%；6月 {r['6个月']}%",
            f"- 相对沪深300：15日 {fmt(r['15日相对沪深300'],2)}%；1月 {fmt(r['1月相对沪深300'],2)}%",
            f"- MACD：{r['MACD信号']} / {r['MACD柱']}",
            f"- KDJ：{r['KDJ信号']}（K {fmt(r['K值'],1)} / D {fmt(r['D值'],1)} / J {fmt(r['J值'],1)}）",
            f"- BOLL：{r['BOLL信号']} / {r['BOLL状态']}；距中轨 {fmt(r['距BOLL中轨%'],2)}%",
            f"- RSI14：{r['RSI14']}；成交额5日/20日：{fmt(r['5日成交额/20日均值'],2)}",
            f"- 当前位置：{r['当前位置']}",
            f"- 理想观察区：{r['理想观察区']}",
            f"- 信号失效区：{r['信号失效区']}",
            f"- 当前规则建议：{r['最终建议']}",
            ""
        ]

    out += [
        "## 四、A1 / A2 / A3 分类清单",
        "",
        "### A1 低位刚转强 ★★★★★",
        ""
    ]
    if a1.empty:
        out.append("暂无。")
    else:
        for _,r in a1.iterrows():
            out.append(f"- {r['名称']}｜{r['观察阶段']}｜择时 {r['择时确认分']}/20｜{r['当前位置']}｜{r['最终建议']}")

    out += ["", "### A2 低位转强 ★★★★", ""]
    if a2.empty:
        out.append("暂无。")
    else:
        for _,r in a2.head(20).iterrows():
            out.append(f"- {r['名称']}｜{r['观察阶段']}｜择时 {r['择时确认分']}/20｜{r['当前位置']}｜{r['最终建议']}")

    out += ["", "### A3 低位启动后已加速 ★★★", ""]
    if a3.empty:
        out.append("暂无。")
    else:
        for _,r in a3.head(20).iterrows():
            out.append(f"- {r['名称']}｜{r['当前位置']}｜{r['最终建议']}")

    out += ["", "## 五、B类潜在升级候选", ""]
    if b.empty:
        out.append("暂无。")
    else:
        bx=b.sort_values(["择时确认分","机会分"],ascending=[False,False]).head(15)
        for _,r in bx.iterrows():
            out.append(
                f"- {r['名称']}｜状态 {r['状态']}｜择时 {r['择时确认分']}/20｜"
                f"15天 {r['15天']}%｜6月 {r['6个月']}%｜{r['当前位置']}｜{r['最终建议']}"
            )

    out += [
        "",
        "## 六、全球资产环境",
        "",
        f"- 总览：{env['总览']}",
        f"- 能源：{env['能源']}",
        f"- 美股：{env['美股']}",
        f"- 科技：{env['科技']}",
        f"- 利率/美元：{env['利率美元']}",
        f"- 风险情绪：{env['风险情绪']}",
        ""
    ]
    if ga is not None and not ga.empty:
        for _,r in ga.iterrows():
            out.append(
                f"- {r['名称']}｜{r['机会判断']}｜{r['状态']}｜"
                f"15天 {r['15天']}%｜1月 {r['1个月']}%｜6月 {r['6个月']}%｜"
                f"A股映射：{r['A股映射']}"
            )

    out += ["", "## 七、A1 历史验证", ""]
    out.append(f"- 已登记 A1 信号：{0 if signals is None else len(signals)} 条")
    for h in SIGNAL_HORIZONS:
        out.append("- " + stats_sentence(stats,h))

    if signals is not None and not signals.empty:
        out += ["", "最近 A1 信号：", ""]
        for _,s in signals.head(15).iterrows():
            out.append(
                f"- {s['信号日期']} {s['名称']}｜{s['验证状态']}｜"
                f"+5日 {fmt(s['5日收益%'],2)}%｜+10日 {fmt(s['10日收益%'],2)}%｜"
                f"+20日 {fmt(s['20日收益%'],2)}%｜+40日 {fmt(s['40日收益%'],2)}%｜"
                f"当前最大回撤 {fmt(s['当前最大回撤%'],2)}%"
            )

    out += [
        "",
        "## 八、给 ChatGPT 的最终分析任务",
        "",
        "请把我上传的多个日期《ChatGPT投资决策数据包》按时间顺序比较，并联网核实最新公开信息。",
        "",
        "请完成以下任务：",
        "",
        "1. 找出最近几天真正持续改善的板块，而不是只看今天分数最高的板块。",
        "2. 重点识别 B→A1、A1持续确认、A1→A2，以及A3加速后的回踩机会。",
        "3. 判断 MACD、KDJ、BOLL、RSI、量能、相对沪深300是否形成持续共振。",
        "4. 结合黄金、原油、美股、SOX、美元、美债、VIX判断外部环境是否支持该板块。",
        "5. 联网搜索最新行业政策、产业催化、商品价格、海外联动和主要风险。",
        "6. 最终只保留 3~5 个最值得研究的板块，并说明为什么其他候选被淘汰。",
        "7. 对每个最终板块，联网筛选当前可交易基金：",
        "   - 场内 ETF：优先跟踪指数纯度高、规模较大、成交活跃、价差较小、费率合理的产品，给 1~3 只。",
        "   - 场外基金：优先 ETF 联接 / 指数基金，其次才考虑主动行业基金，给 1~3 只。",
        "   - 必须核实基金代码、名称、跟踪指数、规模/流动性/费率等当前信息，不要凭记忆编造。",
        "8. 给基金做 S / A / B / C 分级。",
        "9. 结合本文件中的“当前位置、理想观察区、信号失效区”和最新基金价格/NAV，给出：",
        "   - 现在适合：开始观察 / 小仓试探 / 等回踩 / 暂不参与",
        "   - 大致的观察或分批区域",
        "   - 明确的失效条件",
        "10. 不要给确定性收益承诺；如果样本太少或信号冲突，要明确写“证据不足”。",
        "",
        "最终输出格式：",
        "",
        "### 最终候选 1",
        "- 板块：",
        "- 综合评级：S/A/B/C",
        "- 最近几天信号变化：",
        "- 当前阶段：",
        "- 当前是否适合参与：",
        "- 理想观察/分批区域：",
        "- 失效条件：",
        "- 场内 ETF 1~3只：",
        "- 场外基金 1~3只：",
        "- 核心催化：",
        "- 主要风险：",
        "",
        "最后再给一个总表：",
        "板块｜评级｜场内首选｜场外首选｜当前动作｜理想位置｜主要风险",
        ""
    ]
    return "\n".join(out)

def build_rolling_summary(history, days=7):
    """
    最近 N 个扫描日汇总。
    每天可同时包含：盘前 / 午盘 / 收盘 / 盘中。
    """
    if history is None or history.empty or "扫描日期" not in history.columns:
        return "# 最近%d日决策汇总\n\n暂无足够历史数据。" % days

    h=history.copy()
    if "扫描时段" not in h.columns:
        h["扫描时段"]="历史"
    if "扫描时间" not in h.columns:
        h["扫描时间"]="00:00:00"

    h["_d"]=pd.to_datetime(h["扫描日期"],errors="coerce")
    h=h.dropna(subset=["_d"])
    dates=sorted(h["_d"].drop_duplicates().tolist())
    if not dates:
        return "# 最近%d日决策汇总\n\n暂无足够历史数据。" % days

    keep=dates[-days:]
    x=h[h["_d"].isin(keep)].copy()

    slot_order={"盘前":0,"午盘":1,"盘中":2,"收盘":3,"历史":9}
    x["_slot_order"]=x["扫描时段"].map(slot_order).fillna(8)
    x["_time"]=pd.to_datetime(
        x["扫描日期"].astype(str)+" "+x["扫描时间"].astype(str),
        errors="coerce"
    )

    out=[
        f"# 最近{days}个扫描日板块迁移汇总",
        "",
        f"覆盖日期：{keep[0].strftime('%Y-%m-%d')} ~ {keep[-1].strftime('%Y-%m-%d')}",
        f"实际扫描日数：{len(keep)}",
        "",
        "## 分时段 A1/A2/A3 变化",
        ""
    ]

    for d in keep:
        day=x[x["_d"]==d].copy()
        slots=day[["扫描时段","_slot_order"]].drop_duplicates().sort_values("_slot_order")
        for _,sr in slots.iterrows():
            slot=str(sr["扫描时段"])
            z=day[day["扫描时段"].astype(str)==slot]
            scan_time=str(z["扫描时间"].iloc[-1]) if not z.empty else ""
            a1=z[z["分类"].astype(str).str.startswith("A1")]["名称"].tolist()
            a2=z[z["分类"].astype(str).str.startswith("A2")]["名称"].tolist()
            a3=z[z["分类"].astype(str).str.startswith("A3")]["名称"].tolist()
            out += [
                f"### {d.strftime('%Y-%m-%d')}｜{slot}｜{scan_time}",
                f"- A1：{'、'.join(a1) if a1 else '无'}",
                f"- A2：{'、'.join(a2[:20]) if a2 else '无'}",
                f"- A3：{'、'.join(a3[:20]) if a3 else '无'}",
                ""
            ]

    out += ["## 板块分时迁移轨迹", ""]
    names=x["名称"].astype(str).unique().tolist()
    tracks=[]
    for name in names:
        z=x[x["名称"].astype(str)==name].copy()
        z=z.sort_values(["_d","_slot_order","_time"],na_position="last")
        cats=[str(v) for v in z["分类"].tolist()]
        important=any(c.startswith(("A1","A2","A3")) for c in cats)
        if not important and "择时确认分" in z.columns:
            try:
                important=float(z.iloc[-1]["择时确认分"])>=10
            except Exception:
                pass
        if important:
            tracks.append((name,z))

    for name,z in tracks[:100]:
        route=[]
        for _,r in z.iterrows():
            route.append(
                f"{str(r.get('扫描日期',''))[-5:]}{r.get('扫描时段','')}:{r.get('分类','')}"
            )
        latest=z.iloc[-1]
        out.append(
            f"- {name}："+" → ".join(route)+
            f"｜最新择时 {latest.get('择时确认分','—')}/20"
            f"｜最新位置 {latest.get('当前位置','—')}"
            f"｜最新建议 {latest.get('最终建议','—')}"
        )

    out += [
        "",
        "## 分析提示",
        "",
        "- 盘前：基准观察，A股价格主要反映上一交易日收盘；全球资产可更新。",
        "- 午盘：观察上午走势是否把板块推入/退出 A1/A2/A3。",
        "- 收盘：作为当天最重要的确认时点；A1正式历史验证只在收盘登记。",
        "- 重点看“午盘转强但收盘失败”与“连续多个时段持续增强”的区别。",
        "",
        "把本汇总与 ChatGPT分析包 整包一起上传给 ChatGPT 即可。",
        ""
    ]
    return "\n".join(out)

def make_md(ind,glob,signals,stats):
    top=ind.head(12)
    a1=ind[ind["分类"].str.startswith("A1")].head(10)
    a2=ind[ind["分类"].str.startswith("A2")].head(10)
    a3=ind[ind["分类"].str.startswith("A3")].head(10)
    out=[
        "# 给 ChatGPT 的板块分析数据","",f"扫描时间：{NOW}","",
        "请联网研究以下量化候选的最新行业新闻、政策、产业催化、海外联动与风险。",
        "重点判断哪些属于真正的低位转强，哪些可能只是技术性反弹；关注未来 2～8 周催化持续性。",
        "量化分数不是上涨概率，不要直接据此给出确定性买入结论。","",
        "## A1：低位刚转强 ★★★★★"
    ]
    if a1.empty:
        out.append("暂无 A1 信号。")
    for _,r in a1.iterrows():
        out += [
            f"### {r['名称']}（{r['层级']}）",
            f"- 状态 {r['状态']}；机会 {r['机会分']}；风险 {r['风险分']}；信号年龄 {r['信号年龄']}天",
            f"- 位置：15天 {r['15天']}%，1月 {r['1个月']}%，2月 {r['2个月']}%，3月 {r['3个月']}%，4月 {r['4个月']}%，5月 {r['5个月']}%，6月 {r['6个月']}%",
            f"- 相对沪深300：15日 {fmt(r['15日相对沪深300'],2)}%，1月 {fmt(r['1月相对沪深300'],2)}%",
            f"- RSI {r['RSI14']}；成交额5日/20日 {fmt(r['5日成交额/20日均值'],2)}",
            f"- MACD：{r['MACD信号']} / {r['MACD柱']}；KDJ：{r['KDJ信号']}；BOLL：{r['BOLL信号']} / {r['BOLL状态']}；择时确认 {r['择时确认分']}/20",
            f"- 生命周期：{r['生命周期']}；当前位置：{r['当前位置']}；理想观察区：{r['理想观察区']}；失效区：{r['信号失效区']}",
            f"- 最终建议：{r['最终建议']}",""
        ]
    out += ["", "## A2：低位转强 ★★★★", ""]
    if a2.empty:
        out.append("暂无 A2 信号。")
    for _,r in a2.iterrows():
        out += [
            f"### {r['名称']}（{r['层级']}）",
            f"- 状态 {r['状态']}；机会 {r['机会分']}；风险 {r['风险分']}；信号年龄 {r['信号年龄']}天",
            f"- 位置：15天 {r['15天']}%，1月 {r['1个月']}%，2月 {r['2个月']}%，3月 {r['3个月']}%，4月 {r['4个月']}%，5月 {r['5个月']}%，6月 {r['6个月']}%",
            f"- 相对沪深300：15日 {fmt(r['15日相对沪深300'],2)}%，1月 {fmt(r['1月相对沪深300'],2)}%",
            f"- RSI {r['RSI14']}；成交额5日/20日 {fmt(r['5日成交额/20日均值'],2)}",
            f"- MACD：{r['MACD信号']} / {r['MACD柱']}；KDJ：{r['KDJ信号']}；BOLL：{r['BOLL信号']} / {r['BOLL状态']}；择时确认 {r['择时确认分']}/20",
            f"- 生命周期：{r['生命周期']}；当前位置：{r['当前位置']}；理想观察区：{r['理想观察区']}；失效区：{r['信号失效区']}",
            f"- 最终建议：{r['最终建议']}",""
        ]

    out += ["", "## A3：低位启动后已加速 ★★★", ""]
    if a3.empty:
        out.append("暂无 A3 信号。")
    for _,r in a3.iterrows():
        out += [
            f"### {r['名称']}（{r['层级']}）",
            f"- 状态 {r['状态']}；机会 {r['机会分']}；风险 {r['风险分']}；信号年龄 {r['信号年龄']}天",
            f"- 位置：15天 {r['15天']}%，1月 {r['1个月']}%，2月 {r['2个月']}%，3月 {r['3个月']}%，4月 {r['4个月']}%，5月 {r['5个月']}%，6月 {r['6个月']}%",
            f"- 相对沪深300：15日 {fmt(r['15日相对沪深300'],2)}%，1月 {fmt(r['1月相对沪深300'],2)}%",
            f"- RSI {r['RSI14']}；成交额5日/20日 {fmt(r['5日成交额/20日均值'],2)}",
            "- 提示：该板块中长期位置仍不高，但短周期已经明显加速，优先等待回踩而不是追高。",""
        ]

    out += ["", "## A1 历史信号验证", ""]
    out.append(f"- 已登记 A1 信号：{0 if signals is None else len(signals)} 条")
    for _h in SIGNAL_HORIZONS:
        out.append("- " + stats_sentence(stats,_h))
    if signals is not None and not signals.empty:
        _recent=signals.head(10)
        out += ["", "### 最近 A1 信号", ""]
        for _,_s in _recent.iterrows():
            out.append(
                f"- {_s['信号日期']} {_s['名称']}｜{_s['验证状态']}｜"
                f"+5日 {fmt(_s['5日收益%'],2)}%｜+10日 {fmt(_s['10日收益%'],2)}%｜"
                f"+20日 {fmt(_s['20日收益%'],2)}%｜+40日 {fmt(_s['40日收益%'],2)}%｜"
                f"当前最大回撤 {fmt(_s['当前最大回撤%'],2)}%"
            )
    out += ["", "说明：历史验证从 V1.0 开始按实际扫描信号持续积累；样本很少时不要据此判断策略有效。", ""]

    out += ["## TOP12",""]
    for i,(_,r) in enumerate(top.iterrows(),1):
        out.append(f"{i}. {r['名称']}｜{r['层级']}｜{r['分类']}｜{r['观察阶段']}｜机会{r['机会分']}｜择时{r['择时确认分']}/20｜当前位置{r['当前位置']}｜MACD {r['MACD信号']}｜KDJ {r['KDJ信号']}｜BOLL {r['BOLL信号']}｜建议：{r['最终建议']}")
    out += ["","## 全球资产机会分析",""]
    if glob.empty:
        out.append("全球行情本次获取失败或无数据。")
    else:
        _env=global_environment_summary(glob)
        out += [
            f"- 全球环境：{_env['总览']}",
            f"- 能源：{_env['能源']}",
            f"- 美股：{_env['美股']}",
            f"- 科技：{_env['科技']}",
            f"- 利率/美元：{_env['利率美元']}",
            f"- 风险情绪：{_env['风险情绪']}",
            ""
        ]
        _g=enrich_global_analysis(glob)
        for _,r in _g.iterrows():
            out.append(
                f"- {r['名称']}｜{r['机会判断']}｜{r['状态']}｜"
                f"15天 {r['15天']}%｜1月 {r['1个月']}%｜3月 {r['3个月']}%｜6月 {r['6个月']}%｜"
                f"{r['解读']} A股映射：{r['A股映射']}"
            )
    return "\n".join(out)

def table_rows(df,cols):
    if df is None or df.empty:
        return '<tr><td colspan="%d">暂无数据</td></tr>' % max(1,len(cols))
    rows=[]
    wrap_cols={"BOLL状态","BOLL信号","MACD信号","KDJ信号","观察阶段","理想观察区","信号失效区"}
    advice_cols={"最终建议"}
    for _,r in df.iterrows():
        cells=[]
        for c in cols:
            v=r.get(c,"—")
            if pd.isna(v):
                v="—"
            if isinstance(v,float):
                v=fmt(v,1)
            cls=""
            if c in advice_cols:
                cls=' class="advice"'
            elif c in wrap_cols:
                cls=' class="wrap"'
            cells.append(f"<td{cls}>{v}</td>")
        rows.append("<tr>"+"".join(cells)+"</tr>")
    return "\n".join(rows)

def make_html(ind,glob,source_errors,failures,signals,stats):
    top=ind.head(12)
    a1=ind[ind["分类"].str.startswith("A1")]
    a2=ind[ind["分类"].str.startswith("A2")]
    a3=ind[ind["分类"].str.startswith("A3")]
    b=ind[ind["分类"].str.startswith("B")]
    c=ind[ind["分类"].str.startswith("C")]
    d=ind[ind["分类"].str.startswith("D")]
    cols=["名称","层级","分类","观察阶段","机会分","风险分","MACD信号","KDJ信号","BOLL信号","择时确认分","当前位置","最终建议"]
    pcols=["名称","层级","15天","1个月","2个月","3个月","4个月","5个月","6个月","状态","分类","观察阶段","机会分","风险分","MACD信号","KDJ信号","BOLL信号","择时确认分","当前位置","理想观察区","信号失效区","最终建议"]
    gcols=["名称","数据源","15天","1个月","3个月","6个月","状态","机会分","风险分"]
    scols=["信号日期","名称","层级","验证状态","观察交易日","5日收益%","5日超额%","10日收益%","10日超额%","20日收益%","20日超额%","40日收益%","40日超额%","当前最大回撤%"]
    def names(x): return "、".join(x["名称"].head(20).tolist()) if not x.empty else "暂无"
    warnings=[]
    if source_errors: warnings += source_errors
    if failures: warnings.append(f"有 {len(failures)} 个行业历史行情失败，报告按成功数据生成。")
    warn_html="<br>".join(warnings) if warnings else "数据源运行正常。"

    stat_cards=[]
    if stats is not None and not stats.empty:
        for _,sr in stats.iterrows():
            n=int(sr["样本数"])
            if n==0:
                detail="暂无成熟样本"
            else:
                detail=(
                    f"胜率 {fmt(sr['胜率%'])}%<br>"
                    f"平均收益 {fmt(sr['平均收益%'],2)}%<br>"
                    f"平均超额 {fmt(sr['平均超额%'],2)}%"
                )
            stat_cards.append(
                f'<div class="card"><div class="k">{sr["周期"]}验证 · 样本{n}</div>'
                f'<div style="font-size:14px;font-weight:600;line-height:1.7;margin-top:6px">{detail}</div></div>'
            )
    signal_count=0 if signals is None else len(signals)
    recent_signals=pd.DataFrame() if signals is None else signals.head(20)

    global_analysis=enrich_global_analysis(glob)
    env=global_environment_summary(glob)
    gacols=["名称","机会判断","状态","15天","1个月","3个月","6个月","解读","A股映射"]

    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>基金投资板块分析 {TODAY} {SCAN_SLOT}</title>
<style>
body{{margin:0;background:#f5f6f8;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;color:#17191f}}
.wrap{{max-width:1400px;margin:auto;padding:26px}}h1{{margin:0}}.sub{{color:#757b87;margin:6px 0 20px}}
.cards{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}}.card,section{{background:#fff;border:1px solid #e6e8ed;border-radius:15px;padding:17px;margin:14px 0;overflow-x:auto;overflow-y:hidden}}
.k{{color:#777;font-size:13px}}.v{{font-size:25px;font-weight:700;margin-top:5px}}
table{{border-collapse:collapse;width:max-content;min-width:100%;font-size:13px}}
th,td{{padding:9px;border-bottom:1px solid #eceef2;text-align:right;white-space:nowrap;vertical-align:middle}}
th:first-child,td:first-child{{text-align:left;position:sticky;left:0;background:#fff;z-index:1}}
th{{color:#707680;background:#fafbfc;position:sticky;top:0;z-index:2}}
th:first-child{{background:#fafbfc;z-index:3}}
td.wrap,th.wrap{{white-space:normal;min-width:160px;max-width:260px;line-height:1.45}}
td.advice,th.advice{{white-space:normal;min-width:240px;max-width:360px;text-align:left;line-height:1.45}}
section::-webkit-scrollbar{{height:10px}}
section::-webkit-scrollbar-thumb{{background:#cfd3da;border-radius:999px}}
section::-webkit-scrollbar-track{{background:#f3f4f6;border-radius:999px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}.pool{{border:1px solid #eceef2;border-radius:10px;padding:13px;line-height:1.7}}
.note{{background:#f8f9fb;border-radius:10px;padding:12px;line-height:1.6;color:#4c525e}}.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:12px 0}}footer{{color:#777;font-size:12px;line-height:1.7;margin:22px 0}}
@media(max-width:800px){{.cards,.grid,.stats{{grid-template-columns:1fr 1fr}}.wrap{{padding:12px}}}}
</style></head><body><div class="wrap">
<h1>基金投资板块分析 V1.0</h1><div class="sub">{NOW} ｜ <b>{SCAN_SLOT}</b> ｜ A股：申万行业｜全球：新浪/FRED/ETF兜底</div>
<div class="cards">
<div class="card"><div class="k">成功扫描行业</div><div class="v">{len(ind)}</div></div>
<div class="card"><div class="k">A1 刚转强</div><div class="v">{len(a1)}</div></div>
<div class="card"><div class="k">A2 转强</div><div class="v">{len(a2)}</div></div>
<div class="card"><div class="k">A3 已加速</div><div class="v">{len(a3)}</div></div>
<div class="card"><div class="k">全球资产数</div><div class="v">{len(glob)}</div></div>
</div>
<section><h2>V1.0 使用方式</h2>
<div class="note">
每天运行后，<b>基金报告</b> 文件夹会自动分类保存全部结果：<br>
<b>01_每日归档/日期_盘前/午盘/收盘_ChatGPT决策包.md</b>：每个时段独立留档；<br>
<b>02_滚动汇总/最近7日_决策汇总.md</b>：最近7个扫描日的板块迁移；<br>
<b>02_滚动汇总/最近20日_决策汇总.md</b>：中期迁移汇总；<br><b>03_最新文件/最新_ChatGPT决策包.md</b>：始终保留最新一天。<br><br>
最省事的方式：把“02_滚动汇总/最近7日_决策汇总.md + 03_最新文件/最新_ChatGPT决策包.md”直接上传给 ChatGPT，
让它联网分析行业催化、筛选场内ETF/场外基金，并结合当前位置给最终建议。
</div></section>
<section><h2>观察周期与买入位置</h2>
<div class="note">
<b>观察阶段：</b>0~3交易日=新信号；4~10日=短期验证；11~20日=中期验证；21~40日=完整验证。<br>
<b>当前位置：</b>理想区 / 合理区 / 偏高 / 过热 / 信号失效。理想观察区由 MA20、BOLL中轨和 ATR14 动态计算，不使用固定“-5%”规则。<br>
<b>原则：</b>A1/A2负责判断“值不值得看”，MACD/KDJ/BOLL负责判断“现在是不是更合适的时点”。A3默认不追高。
</div></section>
<section><h2>今日机会 TOP12</h2><div class="note">首页只展示决策核心字段；详细七周期位置、观察区和失效区请看下方“七周期位置”。</div><table><thead><tr>{''.join(f'<th>{x}</th>' for x in cols)}</tr></thead><tbody>{table_rows(top,cols)}</tbody></table></section>
<section><h2>机会分类</h2><div class="grid">
<div class="pool"><b>🟢 A1 低位刚转强 ★★★★★</b><br><span style="color:#666">优先研究</span><br>{names(a1)}</div>
<div class="pool"><b>🟢 A2 低位转强 ★★★★</b><br><span style="color:#666">重点观察</span><br>{names(a2)}</div>
<div class="pool"><b>🟠 A3 低位启动后已加速 ★★★</b><br><span style="color:#666">不追，等回踩</span><br>{names(a3)}</div>
<div class="pool"><b>🟡 B 低位等待</b><br>{names(b)}</div>
<div class="pool"><b>🔵 C 趋势机会</b><br>{names(c)}</div>
<div class="pool"><b>🔴 D 高位</b><br>{names(d)}</div>
</div></section>
<section><h2>A1 历史信号验证</h2>
<div class="note">
已登记 A1 信号 <b>{signal_count}</b> 条。+5 / +10 / +20 / +40 均按<b>交易日</b>计算；
超额收益 = 行业收益 - 同期沪深300收益。<br>
第一天不会凭空生成未来收益，后续每天运行会自动回填。
<b>样本数很少时不要据此判断策略是否有效。</b>
</div>
<div class="stats">{''.join(stat_cards)}</div>
<table><thead><tr>{''.join(f'<th>{x}</th>' for x in scols)}</tr></thead>
<tbody>{table_rows(recent_signals,scols)}</tbody></table>
</section>
<section><h2>七周期位置</h2><div class="note">此表字段较多，可在表格区域内左右滑动；第一列名称会固定，不会再溢出卡片。</div><div class="note">0% 接近周期低点，100% 接近周期高点。重点看“6个月位置仍低，但15天/1个月明显抬升”。MACD/KDJ用于择时确认，不单独决定A1/A2/A3分类。</div>
<table><thead><tr>{''.join(f'<th>{x}</th>' for x in pcols)}</tr></thead><tbody>{table_rows(ind,pcols)}</tbody></table></section>
<section><h2>全球资产机会分析</h2>
<div class="note">
<b>全球环境总览：</b>{env['总览']}<br>
<b>能源：</b>{env['能源']} ｜ 
<b>美股：</b>{env['美股']} ｜ 
<b>科技：</b>{env['科技']} ｜ 
<b>利率/美元：</b>{env['利率美元']} ｜ 
<b>风险情绪：</b>{env['风险情绪']}
</div>
<table><thead><tr>{''.join(f'<th>{x}</th>' for x in gacols)}</tr></thead>
<tbody>{table_rows(global_analysis,gacols)}</tbody></table>
</section>
<section><h2>黄金 / 原油 / 美股 / 美元 / 美债 / VIX 原始量化数据</h2>
<table><thead><tr>{''.join(f'<th>{x}</th>' for x in gcols)}</tr></thead><tbody>{table_rows(glob,gcols)}</tbody></table></section>
<section><h2>数据源状态</h2><div class="note">{warn_html}</div></section>
<footer><b>说明：</b>这是研究筛选工具，不构成投资建议；机会分不是上涨概率。V1.0 已加入全球资产机会分析；V1.0 已加入 A1 信号 +5/+10/+20/+40 日收益、超额收益和最大回撤跟踪；A类已拆分为 A1/A2/A3；A股采用申万行业，沪深300优先腾讯、备用新浪；全球资产优先新浪/FRED，必要时使用 ETF 代理。美元项使用 FRED 广义美元指数，并非 ICE DXY。Russell2000 / SOX / VIX 在原指数源不可用时可分别使用 IWM / SOXX / VIXY ETF 作为代理。公开接口可能存在延迟或临时不可用。</footer>
</div></body></html>"""


def _copy_if_exists(src: Path, dst: Path):
    try:
        if src.exists() and src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    except Exception as e:
        log(f"整理 ChatGPT 分析文件失败：{src.name} -> {e}")

def refresh_chatgpt_folder():
    """
    自动整理“直接给 ChatGPT”的分析文件夹。

    01_全部扫描记录：
    永久累计，不限制7天/20天/1个月，不主动删除旧记录。

    02_滚动汇总：
    最近7日、最近20日快速摘要。

    03_最新数据：
    始终刷新为最近一次。

    04_历史验证：
    history.csv、a1_signals.csv 永久同步。
    """
    for p in (CHATGPT_DAILY, CHATGPT_SUMMARY, CHATGPT_LATEST, CHATGPT_HISTORY):
        p.mkdir(parents=True, exist_ok=True)

    # 兼容旧目录：如果曾经存在“01_最近7个扫描日”，把已有文件迁入新目录
    old_daily = CHATGPT_FOLDER / "01_最近7个扫描日"
    if old_daily.exists() and old_daily.is_dir():
        for f in old_daily.iterdir():
            if f.is_file() and f.name != ".gitkeep":
                _copy_if_exists(f, CHATGPT_DAILY / f.name)

    # 01_全部扫描记录：永久累计，不清空
    # 每次从每日归档同步全部历史核心文件
    keep_suffixes = (
        "_ChatGPT决策包.md",
        "_量化结果.csv",
        "_全球资产.csv",
        "_A1信号验证.csv",
        "_A1验证统计.csv",
        "_给ChatGPT分析.md",
        "_基金投资板块分析.html",
    )
    for f in sorted(DAILY_REPORTS.iterdir()):
        if f.is_file() and f.name.endswith(keep_suffixes):
            _copy_if_exists(f, CHATGPT_DAILY / f.name)

    # 02_滚动汇总：摘要文件可刷新
    for f in CHATGPT_SUMMARY.iterdir():
        if f.is_file() and f.name != ".gitkeep":
            f.unlink()
    _copy_if_exists(
        ROLLING_REPORTS / "最近7日_决策汇总.md",
        CHATGPT_SUMMARY / "最近7日_决策汇总.md"
    )
    _copy_if_exists(
        ROLLING_REPORTS / "最近20日_决策汇总.md",
        CHATGPT_SUMMARY / "最近20日_决策汇总.md"
    )

    # 03_最新数据：只保留最近一次
    for f in CHATGPT_LATEST.iterdir():
        if f.is_file() and f.name != ".gitkeep":
            f.unlink()
    latest_names = [
        "最新报告.html",
        "最新_ChatGPT决策包.md",
        "最新_量化结果.csv",
        "最新_全球资产.csv",
        "最新_A1信号验证.csv",
    ]
    for name in latest_names:
        _copy_if_exists(LATEST_REPORTS / name, CHATGPT_LATEST / name)

    # 04_历史验证：同步最新完整数据库
    for f in CHATGPT_HISTORY.iterdir():
        if f.is_file() and f.name != ".gitkeep":
            f.unlink()
    _copy_if_exists(HISTORY, CHATGPT_HISTORY / "history.csv")
    _copy_if_exists(SIGNALS, CHATGPT_HISTORY / "a1_signals.csv")

    record_count = len([
        f for f in CHATGPT_DAILY.iterdir()
        if f.is_file() and f.name != ".gitkeep"
    ])

    note = f"""基金投资板块分析 V1.0 — ChatGPT分析包

更新时间：{NOW}
最新扫描时段：{SCAN_SLOT}

这个文件夹可以整体压缩后直接上传给 ChatGPT。

01_全部扫描记录/
- 永久累计全部盘前 / 午盘 / 收盘扫描文件
- 不限制7天、20天、1个月
- 程序不会主动删除旧历史
- 当前文件数：{record_count}

02_滚动汇总/
- 最近7日_决策汇总.md
- 最近20日_决策汇总.md
这些只是快速摘要，不影响完整历史保存。

03_最新数据/
- 始终保留最近一次扫描结果

04_历史验证/
- history.csv
- a1_signals.csv
这两个文件永久累计。

正式规则：
- 盘前 / 午盘 / 收盘分别留档
- 同一时段重复运行只保留该时段最新记录
- A1 +5/+10/+20/+40 日正式验证只在收盘登记
- 完整历史永久累计

以后无论运行2周、1个月、3个月还是半年，
都可以直接把整个 ChatGPT分析包 文件夹压缩后上传。

建议对 ChatGPT 说：
“分析这个文件夹里的全部历史数据。比较短期、中期、长期板块迁移，识别持续增强、假突破、A1/A2/A3演化和技术共振；再联网核实最新政策、行业催化、全球资产和基金信息，最终给出3~5个板块、场内基金、场外基金、S/A/B/C评级、当前动作、理想位置和失效条件。”
"""
    (CHATGPT_FOLDER / "00_直接把整个文件夹给ChatGPT.txt").write_text(
        note, encoding="utf-8"
    )

def main():
    log(f"启动 V1.0：{SCAN_SLOT}扫描（{SCAN_TIME}） + 多时段留档 + ChatGPT决策包")
    old=load_hist()

    log("获取沪深300基准...")
    bm=benchmark()

    log("获取申万一级 / 二级行业列表...")
    items,source_errors=sw_list()
    log(f"共 {len(items)} 个申万行业，开始扫描。首次运行会较慢。")

    results=[]; failures=[]; hist_map={}
    # 申万官网接口不做高并发，稳定优先
    for i,(code,name,level) in enumerate(items,1):
        try:
            df=sw_hist(code)
            hist_map[(name,level)]=df
            results.append(analyze(name,df,bm,level))
        except Exception as e:
            failures.append((code,name,str(e)))
        if i%10==0 or i==len(items):
            log(f"进度 {i}/{len(items)}，成功 {len(results)}，失败 {len(failures)}")
        time.sleep(0.08)

    if len(results)<10:
        raise RuntimeError(f"申万行业成功数量过少：{len(results)}。请把本次运行错误文件发给我。")

    ind=pd.DataFrame(results)
    order={
        "A1 低位刚转强 ★★★★★":0,
        "A2 低位转强 ★★★★":1,
        "A3 低位启动后已加速 ★★★":2,
        "B 低位等待":3,
        "C 趋势机会":4,
        "D 高位":5,
        "观察":6
    }
    ind["_o"]=ind["分类"].map(order).fillna(9)
    ind=ind.sort_values(["_o","机会分","择时确认分","风险分"],ascending=[True,False,False,True]).drop(columns="_o").reset_index(drop=True)

    log("登记 / 更新 A1 历史验证信号...")
    signals=register_new_a1_signals(ind,old,hist_map,bm)
    signals=update_a1_signal_performance(signals,hist_map,bm)
    save_signals(signals)
    stats=a1_signal_stats(signals)

    glob=global_data()

    csv=DAILY_REPORTS/f"{RUN_TAG}_量化结果.csv"
    ind.to_csv(csv,index=False,encoding="utf-8-sig")
    glob.to_csv(DAILY_REPORTS/f"{RUN_TAG}_全球资产.csv",index=False,encoding="utf-8-sig")
    signals.to_csv(DAILY_REPORTS/f"{RUN_TAG}_A1信号验证.csv",index=False,encoding="utf-8-sig")
    stats.to_csv(DAILY_REPORTS/f"{RUN_TAG}_A1验证统计.csv",index=False,encoding="utf-8-sig")
    (DAILY_REPORTS/f"{RUN_TAG}_给ChatGPT分析.md").write_text(make_md(ind,glob,signals,stats),encoding="utf-8")

    html=make_html(ind,glob,source_errors,failures,signals,stats)
    hp=DAILY_REPORTS/f"{RUN_TAG}_基金投资板块分析.html"; hp.write_text(html,encoding="utf-8")
    (LATEST_REPORTS/"最新报告.html").write_text(html,encoding="utf-8")

    save_hist(ind)

    # V1.0：生成给 ChatGPT 的完整决策包和滚动多日汇总
    history_now=load_hist()
    decision_md=decision_pack_markdown(ind,glob,signals,stats,history_now)
    (DAILY_REPORTS/f"{RUN_TAG}_ChatGPT决策包.md").write_text(decision_md,encoding="utf-8")
    (LATEST_REPORTS/"最新_ChatGPT决策包.md").write_text(decision_md,encoding="utf-8")

    rolling7=build_rolling_summary(history_now,7)
    rolling20=build_rolling_summary(history_now,20)
    (ROLLING_REPORTS/"最近7日_决策汇总.md").write_text(rolling7,encoding="utf-8")
    (ROLLING_REPORTS/"最近20日_决策汇总.md").write_text(rolling20,encoding="utf-8")

    # 固定名称“最新”文件：增加扫描时间/时段，单独上传也能识别
    latest_ind=ind.copy()
    latest_ind.insert(0,"扫描时段",SCAN_SLOT)
    latest_ind.insert(0,"扫描时间",SCAN_TIME)
    latest_ind.insert(0,"扫描日期",TODAY)
    latest_ind.to_csv(LATEST_REPORTS/"最新_量化结果.csv",index=False,encoding="utf-8-sig")

    latest_glob=glob.copy()
    latest_glob.insert(0,"扫描时段",SCAN_SLOT)
    latest_glob.insert(0,"扫描时间",SCAN_TIME)
    latest_glob.insert(0,"扫描日期",TODAY)
    latest_glob.to_csv(LATEST_REPORTS/"最新_全球资产.csv",index=False,encoding="utf-8-sig")
    signals.to_csv(LATEST_REPORTS/"最新_A1信号验证.csv",index=False,encoding="utf-8-sig")

    if failures:
        (LOG_REPORTS/f"{RUN_TAG}_失败列表.txt").write_text("\n".join(f"{c} {n}: {e}" for c,n,e in failures),encoding="utf-8")

    refresh_chatgpt_folder()
    log(f"ChatGPT分析包 已自动刷新：本次 {SCAN_SLOT} 数据已归档，完整历史永久保留")
    log(f"V1.0 决策包已生成：{LATEST_REPORTS} + {ROLLING_REPORTS}")
    log("扫描完成")
    print(f"REPORT_PATH={hp}")

    return LATEST_REPORTS / "最新报告.html"

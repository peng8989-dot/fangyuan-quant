#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
方圆量化 - 多数据源自动更新 data.js (v4.0)
支持：东方财富 / 腾讯 / 网易，自动切换
"""

import requests
import json
import time
import random
import os
from datetime import datetime

# ================== 配置 ==================
ETF = {
    "300": {"sym": "510300", "idx": "000300", "name": "沪深300ETF"},
    "500": {"sym": "510500", "idx": "000905", "name": "中证500ETF"},
    "Med": {"sym": "512010", "idx": "000991", "name": "医药ETF"},
    "Tech":{"sym": "515000", "idx": "931087", "name": "科技ETF"},
    "Bond":{"sym": "511260", "idx": None, "name": "国债ETF"}
}
OUTPUT = "data.js"

# 如果你有稳定的HTTP代理，在此填写（例如 'http://127.0.0.1:10809'）
PROXY = os.environ.get("HTTP_PROXY", None)
session = requests.Session()
if PROXY:
    session.proxies = {"http": PROXY, "https": PROXY}
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://quote.eastmoney.com/",
})

def safe_get(url, params=None, retry=2, timeout=8):
    for i in range(retry):
        try:
            resp = session.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp
        except:
            time.sleep(1.5)
    return None

# ---------- PE分位（多源） ----------
def pe_eastmoney(idx):
    """东方财富直接返回分位"""
    r = safe_get("https://push2.eastmoney.com/api/qt/stock/get",
                 {"secid": f"1.{idx}", "fields": "f134"})
    if r:
        try:
            pct = r.json()["data"]["f134"]
            if pct is not None:
                return round(float(pct), 1)
        except: pass
    return None

def pe_tencent(idx):
    """腾讯不支持分位，跳过"""
    return None

def pe_netease(idx):
    """网易历史PE，计算近5年分位"""
    try:
        url = f"http://quotes.money.163.com/service/chddata.html?code=1{idx}&start=20200101&end=20301231&fields=TCLOSE;PE"
        r = safe_get(url, retry=2, timeout=12)
        if not r: return None
        lines = r.text.strip().split('\n')
        pe_vals = []
        for line in lines[1:]:
            parts = line.split(',')
            if len(parts) >= 9:
                try:
                    pe = float(parts[8])
                    if pe > 0: pe_vals.append(pe)
                except: pass
        if len(pe_vals) < 100: return None
        recent = pe_vals[-1250:] if len(pe_vals) > 1250 else pe_vals
        cur = recent[-1]
        pct = sum(1 for x in recent if x < cur) / len(recent) * 100
        return round(pct, 1)
    except: return None

def get_pe(key, idx):
    """按优先级尝试多个源"""
    for func, name in [(pe_eastmoney, "东方财富"), (pe_netease, "网易")]:
        val = func(idx)
        if val is not None:
            print(f"  PE分位({name}): {val}%")
            return val
    print("  PE分位全部失败，使用默认50%")
    return 50

# ---------- K线（日/周） ----------
def kline_eastmoney(sym, period="daily"):
    klt = 101 if period == "daily" else 102
    r = safe_get("https://push2his.eastmoney.com/api/qt/stock/kline/get",
                 {"secid": f"1.{sym}", "klt": klt, "fqt": 1, "lmt": 1250,
                  "fields1": "f1,f2,f3,f4,f5,f6",
                  "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"})
    if not r: return None
    try:
        lines = r.json()["data"]["klines"]
        recs = []
        for line in lines:
            p = line.split(",")
            recs.append({"high": float(p[3]), "close": float(p[2])})
        return recs
    except: return None

def kline_tencent(sym, period="daily"):
    ktype = "day" if period == "daily" else "week"
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh{sym},{ktype},,,1250,qfq"
    r = safe_get(url, timeout=10)
    if not r: return None
    try:
        data = r.json()["data"]["sh"+sym]
        kls = data.get(ktype, []) or data.get("day", [])
        recs = [{"high": float(k[3]), "close": float(k[2])} for k in kls[-1250:]]
        return recs
    except: return None

def get_kline(sym, period="daily"):
    for func, name in [(kline_eastmoney, "东方财富"), (kline_tencent, "腾讯")]:
        val = func(sym, period)
        if val:
            return val
    return None

# ---------- 实时价格 ----------
def price_tencent(sym):
    r = safe_get(f"http://qt.gtimg.cn/q=sh{sym}", timeout=5)
    if r:
        parts = r.text.split('~')
        if len(parts) > 3:
            try: return float(parts[3])
            except: pass
    return None

def price_eastmoney(sym):
    r = safe_get("https://push2.eastmoney.com/api/qt/stock/get",
                 {"secid": f"1.{sym}", "fields": "f43"})
    if r:
        try:
            return r.json()["data"]["f43"] / 1000
        except: pass
    return None

def get_price(sym):
    for func, name in [(price_tencent, "腾讯"), (price_eastmoney, "东方财富")]:
        val = func(sym)
        if val: return round(val, 3)
    return None

# ---------- 计算 ----------
def calc_trend(weekly):
    if not weekly or len(weekly) < 20: return "above"
    closes = [k["close"] for k in weekly[-20:]]
    ma20 = sum(closes) / 20
    if closes[-1] > ma20: return "above"
    if len(closes) >= 2 and closes[-2] > ma20: return "below1"
    return "below2"

def main():
    result = {}
    for key, cfg in ETF.items():
        print(f"\n处理 {cfg['name']} ...")
        # PE
        if cfg["idx"]:
            result[f"pe{key}"] = get_pe(key, cfg["idx"])
        else:
            result[f"pe{key}"] = 0
        # 日线最高价
        daily = get_kline(cfg["sym"], "daily")
        high = round(max(k["high"] for k in daily), 3) if daily else 0
        result[f"high{key}"] = high
        print(f"  最高价: {high}")
        # 周线趋势
        weekly = get_kline(cfg["sym"], "weekly")
        trend = calc_trend(weekly)
        result[f"trend{key}"] = trend
        print(f"  周线趋势: {trend}")
        # 价格
        price = get_price(cfg["sym"])
        if price:
            result[f"price{key}"] = price
            print(f"  当前价: {price}")
        time.sleep(random.uniform(1.5, 3))

    result["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write("const AUTO_DATA = " + json.dumps(result, ensure_ascii=False, indent=2) + ";")
    print(f"\n✅ 已生成 {OUTPUT}")

if __name__ == "__main__":
    main()
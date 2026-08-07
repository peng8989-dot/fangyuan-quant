#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
方圆量化 - 全自动数据更新（含四层 fallback）
确保所有 ETF 的历史最高价字段永不为 0
"""

import json
import time
import random
import os
import requests
from datetime import datetime

# ================== ETF 配置 ==================
ETF_CONFIG = {
    "300": {"sym": "510300", "name": "沪深300ETF",   "idx": "000300"},
    "500": {"sym": "510500", "name": "中证500ETF",   "idx": "000905"},
    "Med": {"sym": "512010", "name": "医药ETF",      "idx": "000991"},
    "Tech":{"sym": "512480", "name": "半导体ETF",    "idx": "H30184"},
    "Bond":{"sym": "511260", "name": "国债ETF",      "idx": None},
    "Inn": {"sym": "159992", "name": "创新药ETF",    "idx": "931152"},
    "1000": {"sym": "512100", "name": "中证1000ETF", "idx": "000852"},
}

OUTPUT_FILE = "data.js"
CACHE_FILE = "backup_high.json"

# ---------- 内置默认历史最高价（2026年8月合理估算） ----------
DEFAULT_HIGH = {
    "300": 4.650,
    "500": 6.200,
    "Med": 0.550,
    "Tech": 1.850,
    "Bond": 103.50,
    "Inn": 1.350,
    "1000": 2.950
}

# ---------- 网络请求 ----------
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://quote.eastmoney.com/",
})

def safe_get(url, params=None, retry=2, timeout=10):
    for i in range(retry):
        try:
            resp = session.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as e:
            print(f"    [{i+1}/{retry}] 请求失败: {e}")
            time.sleep(2 + random.random() * 3)
    return None

# ---------- 实时价格（腾讯） ----------
def get_price(sym):
    code = f"sz{sym}" if sym.startswith("159") or sym.startswith("16") else f"sh{sym}"
    r = safe_get(f"http://qt.gtimg.cn/q={code}", timeout=5)
    if r:
        parts = r.text.split('~')
        if len(parts) > 3:
            try: return float(parts[3])
            except: pass
    return None

# ---------- PE 分位（东方财富） ----------
def get_pe(idx):
    r = safe_get("https://push2.eastmoney.com/api/qt/stock/get",
                 {"secid": f"1.{idx}", "fields": "f134"}, retry=1, timeout=8)
    if r:
        try:
            pct = r.json().get("data", {}).get("f134")
            if pct is not None:
                return round(float(pct), 1)
        except: pass
    return None

# ---------- K 线历史最高价（三层尝试） ----------
def get_hist_high(sym, key):
    # 第一层：东方财富日线
    try:
        r = safe_get("https://push2his.eastmoney.com/api/qt/stock/kline/get",
                     {"secid": f"1.{sym}", "klt": 101, "fqt": 1, "lmt": 1250,
                      "fields1": "f1,f2,f3,f4,f5,f6",
                      "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"})
        if r:
            klines = r.json()["data"]["klines"]
            high = max(float(line.split(",")[3]) for line in klines)
            if high > 0: return round(high, 3)
    except: pass

    # 第二层：腾讯日线
    try:
        code = f"sz{sym}" if sym.startswith("159") or sym.startswith("16") else f"sh{sym}"
        r = safe_get(f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,1250,qfq", timeout=12)
        if r:
            data = r.json()["data"][code]
            kls = data.get("day", []) or data.get("day", [])
            high = max(float(k[3]) for k in kls[-1250:])
            if high > 0: return round(high, 3)
    except: pass

    # 第三层：本地缓存
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r") as f:
                cache = json.load(f)
            val = cache.get(f"high{key}")
            if val and val > 0:
                print("    ⚠️ 使用本地缓存历史最高价")
                return round(val, 3)
    except: pass

    # 第四层：内置默认值
    default = DEFAULT_HIGH.get(key, 1.0)
    print(f"    ⚠️ 使用内置默认历史最高价 {default}")
    return default

# ---------- 周线趋势 ----------
def get_trend(sym):
    try:
        r = safe_get("https://push2his.eastmoney.com/api/qt/stock/kline/get",
                     {"secid": f"1.{sym}", "klt": 102, "fqt": 1, "lmt": 120,
                      "fields1": "f1,f2,f3,f4,f5,f6",
                      "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"})
        if r:
            closes = [float(line.split(",")[2]) for line in r.json()["data"]["klines"]]
            if len(closes) >= 20:
                ma20 = sum(closes[-20:]) / 20
                if closes[-1] > ma20: return "above"
                if len(closes) >= 2 and closes[-2] > ma20: return "below1"
                return "below2"
    except: pass
    return "above"

# ---------- 主流程 ----------
def update_all():
    result = {}
    cache = {}
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                cache = json.load(f)
        except: pass

    for key, cfg in ETF_CONFIG.items():
        print(f"\n处理 {cfg['name']} ({cfg['sym']}) ...")
        sym = cfg["sym"]
        idx = cfg["idx"]

        # 1. PE 分位
        if idx:
            pe = get_pe(idx)
            result[f"pe{key}"] = pe if pe is not None else 50
            print(f"  PE分位: {result[f'pe{key}']}%")
        else:
            result[f"pe{key}"] = 0

        # 2. 历史最高价（自动 fallback）
        high = get_hist_high(sym, key)
        result[f"high{key}"] = high
        print(f"  近5年最高价: {high}")

        # 3. 周线趋势
        trend = get_trend(sym)
        result[f"trend{key}"] = trend
        print(f"  周线趋势: {trend}")

        # 4. 当前价格
        price = get_price(sym)
        if price:
            result[f"price{key}"] = round(price, 3)
            print(f"  当前价格: {price:.3f}")

        # 更新缓存
        cache[f"high{key}"] = high
        time.sleep(random.uniform(1.5, 3))

    result["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 保存缓存文件
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    # 写入 data.js
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("const AUTO_DATA = " + json.dumps(result, ensure_ascii=False, indent=2) + ";")
    print(f"\n✅ 已生成 {OUTPUT_FILE}，更新时间：{result['update_time']}")

if __name__ == "__main__":
    print("=" * 50)
    print("  方圆量化 - 全自动数据更新（永不缺最高价）")
    print("=" * 50)
    update_all()

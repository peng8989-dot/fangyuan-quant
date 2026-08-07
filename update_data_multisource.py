#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
方圆量化 - 全自动数据更新（PE缓存+多源备选）
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
HIGH_CACHE_FILE = "backup_high.json"
PE_CACHE_FILE = "pe_cache.json"          # 新增：PE缓存文件

# ---------- 内置默认历史最高价 ----------
DEFAULT_HIGH = {
    "300": 4.650,
    "500": 6.200,
    "Med": 0.550,
    "Tech": 1.850,
    "Bond": 103.50,
    "Inn": 1.350,
    "1000": 2.950
}

# ---------- 请求会话 ----------
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://quote.eastmoney.com/",
})

def safe_get(url, params=None, retry=3, timeout=12):
    """增加重试次数与超时时间"""
    for i in range(retry):
        try:
            resp = session.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as e:
            print(f"    [{i+1}/{retry}] 请求失败: {e}")
            time.sleep(2 + random.random() * 4)
    return None

# ---------- 实时价格 ----------
def get_price(sym):
    code = f"sz{sym}" if sym.startswith("159") or sym.startswith("16") else f"sh{sym}"
    r = safe_get(f"http://qt.gtimg.cn/q={code}", timeout=5)
    if r:
        parts = r.text.split('~')
        if len(parts) > 3:
            try: return float(parts[3])
            except: pass
    return None

# ---------- PE 分位（增强版：三源+缓存） ----------
def get_pe_from_eastmoney(idx):
    """东方财富接口，返回分位值"""
    try:
        r = safe_get("https://push2.eastmoney.com/api/qt/stock/get",
                     {"secid": f"1.{idx}", "fields": "f134"}, retry=2, timeout=10)
        if r:
            pct = r.json().get("data", {}).get("f134")
            if pct is not None:
                return round(float(pct), 1)
    except: pass
    return None

def get_pe_from_netease(idx):
    """网易历史PE，自行计算近5年分位（备用）"""
    try:
        url = f"http://quotes.money.163.com/service/chddata.html?code=1{idx}&start=20200101&end=20301231&fields=TCLOSE;PE"
        r = safe_get(url, retry=1, timeout=15)
        if not r:
            return None
        lines = r.text.strip().split('\n')
        pe_vals = []
        for line in lines[1:]:
            parts = line.split(',')
            if len(parts) >= 9:
                try:
                    pe = float(parts[8])
                    if pe > 0: pe_vals.append(pe)
                except: pass
        if len(pe_vals) < 100:
            return None
        recent = pe_vals[-1250:] if len(pe_vals) > 1250 else pe_vals
        cur = recent[-1]
        pct = sum(1 for x in recent if x < cur) / len(recent) * 100
        return round(pct, 1)
    except: pass
    return None

def load_pe_cache():
    """加载PE缓存字典"""
    if os.path.exists(PE_CACHE_FILE):
        try:
            with open(PE_CACHE_FILE, "r") as f:
                return json.load(f)
        except: pass
    return {}

def save_pe_cache(cache_dict):
    """保存PE缓存"""
    with open(PE_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache_dict, f, ensure_ascii=False, indent=2)

def get_pe(key, idx, cache):
    """
    获取PE分位：
    1. 尝试东方财富
    2. 尝试网易
    3. 使用本地缓存（上次成功值）
    4. 返回 None（外部将用 50 兜底）
    """
    # 在线获取
    for func, name in [(get_pe_from_eastmoney, "东方财富"), (get_pe_from_netease, "网易")]:
        val = func(idx)
        if val is not None:
            print(f"  PE分位({name}): {val}%")
            # 更新缓存
            cache[key] = val
            save_pe_cache(cache)
            return val

    # 使用缓存
    cached_val = cache.get(key)
    if cached_val is not None:
        print(f"  ⚠️ 使用PE缓存值: {cached_val}%")
        return cached_val

    # 完全失败
    return None

# ---------- 历史最高价（原逻辑不变） ----------
def get_hist_high(sym, key):
    # 略，同之前脚本...
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
    try:
        code = f"sz{sym}" if sym.startswith("159") or sym.startswith("16") else f"sh{sym}"
        r = safe_get(f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,1250,qfq", timeout=12)
        if r:
            data = r.json()["data"][code]
            kls = data.get("day", [])
            high = max(float(k[3]) for k in kls[-1250:])
            if high > 0: return round(high, 3)
    except: pass
    try:
        if os.path.exists(HIGH_CACHE_FILE):
            with open(HIGH_CACHE_FILE, "r") as f:
                high_cache = json.load(f)
            val = high_cache.get(f"high{key}")
            if val and val > 0:
                print("    ⚠️ 使用本地缓存历史最高价")
                return round(val, 3)
    except: pass
    return DEFAULT_HIGH.get(key, 1.0)

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
    high_cache = {}
    if os.path.exists(HIGH_CACHE_FILE):
        try:
            with open(HIGH_CACHE_FILE, "r") as f:
                high_cache = json.load(f)
        except: pass

    # 加载PE缓存
    pe_cache = load_pe_cache()

    for key, cfg in ETF_CONFIG.items():
        print(f"\n处理 {cfg['name']} ({cfg['sym']}) ...")
        sym = cfg["sym"]
        idx = cfg["idx"]

        # 1. PE 分位
        if idx:
            pe = get_pe(key, idx, pe_cache)
            result[f"pe{key}"] = pe if pe is not None else 50
        else:
            result[f"pe{key}"] = 0

        # 2. 历史最高价
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

        # 更新历史最高价缓存
        high_cache[f"high{key}"] = high
        time.sleep(random.uniform(2, 4))

    result["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 保存所有缓存
    with open(HIGH_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(high_cache, f, ensure_ascii=False, indent=2)
    # PE缓存已在 get_pe 中自动保存

    # 写入 data.js
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("const AUTO_DATA = " + json.dumps(result, ensure_ascii=False, indent=2) + ";")
    print(f"\n✅ 已生成 {OUTPUT_FILE}，更新时间：{result['update_time']}")

if __name__ == "__main__":
    print("=" * 50)
    print("  方圆量化 - PE缓存增强版")
    print("=" * 50)
    update_all()

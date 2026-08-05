#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
方圆量化 - 全自动数据更新（防崩溃版）
即使全部接口失败，也能正常生成 data.js
"""

import json
import time
import random
import traceback
from datetime import datetime

try:
    import requests
except ImportError:
    # 万一没有 requests 库，也不会让程序崩溃
    requests = None

# ================== 配置 ==================
ETF = {
    "300": {"sym": "510300", "idx": "000300", "name": "沪深300ETF"},
    "500": {"sym": "510500", "idx": "000905", "name": "中证500ETF"},
    "Med": {"sym": "512010", "idx": "000991", "name": "医药ETF"},
    "Tech":{"sym": "515000", "idx": "931087", "name": "科技ETF"},
    "Bond":{"sym": "511260", "idx": None, "name": "国债ETF"}
}

OUTPUT = "data.js"

def safe_get(url, params=None, retry=2, timeout=8):
    """绝对安全的请求，失败返回 None"""
    if not requests:
        return None
    try:
        for i in range(retry):
            try:
                resp = requests.get(url, params=params, timeout=timeout,
                                    headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                return resp
            except:
                time.sleep(1.5)
    except:
        pass
    return None

# ---------- PE分位（多源）----------
def pe_eastmoney(idx):
    try:
        r = safe_get("https://push2.eastmoney.com/api/qt/stock/get",
                     {"secid": f"1.{idx}", "fields": "f134"})
        if r:
            pct = r.json().get("data", {}).get("f134")
            if pct is not None:
                return round(float(pct), 1)
    except:
        pass
    return None

def pe_netease(idx):
    try:
        url = f"http://quotes.money.163.com/service/chddata.html?code=1{idx}&start=20200101&end=20301231&fields=TCLOSE;PE"
        r = safe_get(url, retry=2, timeout=12)
        if not r:
            return None
        lines = r.text.strip().split('\n')
        pe_vals = []
        for line in lines[1:]:
            parts = line.split(',')
            if len(parts) >= 9:
                try:
                    pe = float(parts[8])
                    if pe > 0:
                        pe_vals.append(pe)
                except:
                    pass
        if len(pe_vals) < 100:
            return None
        recent = pe_vals[-1250:] if len(pe_vals) > 1250 else pe_vals
        cur = recent[-1]
        pct = sum(1 for x in recent if x < cur) / len(recent) * 100
        return round(pct, 1)
    except:
        return None

def get_pe(idx):
    for func in [pe_eastmoney, pe_netease]:
        try:
            val = func(idx)
            if val is not None:
                return val
        except:
            pass
    return 50

# ---------- K线 ----------
def kline_eastmoney(sym, period="daily"):
    try:
        klt = 101 if period == "daily" else 102
        params = {
            "secid": f"1.{sym}",
            "klt": klt,
            "fqt": 1,
            "lmt": 1250,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
        }
        r = safe_get("https://push2his.eastmoney.com/api/qt/stock/kline/get", params=params)
        if not r:
            return None
        lines = r.json()["data"]["klines"]
        return [{"high": float(p[3]), "close": float(p[2])} for p in [l.split(",") for l in lines]]
    except:
        return None

def kline_tencent(sym, period="daily"):
    try:
        ktype = "day" if period == "daily" else "week"
        url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh{sym},{ktype},,,1250,qfq"
        r = safe_get(url, timeout=10)
        if not r:
            return None
        data = r.json()["data"]["sh"+sym]
        kls = data.get(ktype, []) or data.get("day", [])
        return [{"high": float(k[3]), "close": float(k[2])} for k in kls[-1250:]]
    except:
        return None

def get_kline(sym, period="daily"):
    for func in [kline_eastmoney, kline_tencent]:
        try:
            val = func(sym, period)
            if val:
                return val
        except:
            pass
    return []

# ---------- 实时价格 ----------
def price_tencent(sym):
    try:
        r = safe_get(f"http://qt.gtimg.cn/q=sh{sym}", timeout=5)
        if r:
            parts = r.text.split('~')
            if len(parts) > 3:
                return float(parts[3])
    except:
        pass
    return None

def price_eastmoney(sym):
    try:
        r = safe_get("https://push2.eastmoney.com/api/qt/stock/get",
                     {"secid": f"1.{sym}", "fields": "f43"})
        if r:
            return r.json()["data"]["f43"] / 1000
    except:
        pass
    return None

def get_price(sym):
    for func in [price_tencent, price_eastmoney]:
        try:
            val = func(sym)
            if val:
                return round(val, 3)
        except:
            pass
    return None

# ---------- 计算趋势 ----------
def calc_trend(weekly):
    try:
        if len(weekly) >= 20:
            closes = [k["close"] for k in weekly[-20:]]
            ma20 = sum(closes) / 20
            if closes[-1] > ma20:
                return "above"
            if closes[-2] > ma20:
                return "below1"
            return "below2"
    except:
        pass
    return "above"

# ---------- 主流程 ----------
def main():
    result = {}
    for key, cfg in ETF.items():
        print(f"\n处理 {cfg['name']} ...")
        try:
            if cfg["idx"]:
                result[f"pe{key}"] = get_pe(cfg["idx"])
            else:
                result[f"pe{key}"] = 0

            daily = get_kline(cfg["sym"], "daily")
            high = round(max(k["high"] for k in daily), 3) if daily else 0
            result[f"high{key}"] = high

            weekly = get_kline(cfg["sym"], "weekly")
            result[f"trend{key}"] = calc_trend(weekly)

            price = get_price(cfg["sym"])
            if price:
                result[f"price{key}"] = price

            print(f"  PE: {result[f'pe{key}']}%  最高: {high}  趋势: {result[f'trend{key}']}  现价: {price}")
        except Exception as e:
            print(f"  处理 {cfg['name']} 时出错，使用默认值")
            traceback.print_exc()
            # 为该 ETF 填入绝对安全的默认值
            result[f"pe{key}"] = 50 if cfg["idx"] else 0
            result[f"high{key}"] = 0
            result[f"trend{key}"] = "above"
        time.sleep(random.uniform(1, 2))

    result["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write("const AUTO_DATA = " + json.dumps(result, ensure_ascii=False, indent=2) + ";")
    print(f"\n✅ 已生成 {OUTPUT}")

if __name__ == "__main__":
    main()

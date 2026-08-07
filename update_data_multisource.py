#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
方圆量化 - 全自动数据更新（科技→半导体版）
适配 512480 半导体 ETF，指数代码 H30184
"""

import json
import time
import random
import traceback
from datetime import datetime

try:
    import requests
except ImportError:
    requests = None

# ================== ETF 配置（已替换科技→半导体） ==================
ETF_CONFIG = {
    "300": {
        "symbol": "510300",
        "name": "沪深300ETF",
        "index_code": "000300",        # 沪深300指数
    },
    "500": {
        "symbol": "510500",
        "name": "中证500ETF",
        "index_code": "000905",        # 中证500指数
    },
    "Med": {
        "symbol": "512010",
        "name": "医药ETF",
        "index_code": "000991",        # 医药100指数
    },
    "Tech": {
        "symbol": "512480",            # 改为半导体ETF
        "name": "半导体ETF",
        "index_code": "H30184",        # 中证全指半导体指数
    },
    "Inn": {
    "symbol": "159992",
    "name": "创新药ETF",
    "index_code": "931152",        # 创新药产业指数
    "pe_needed": True,
    },
    "1000": {
    "symbol": "512100",
    "name": "中证1000ETF",
    "index_code": "000852",        # 中证1000指数
    "pe_needed": True,
    },
    "Bond": {
        "symbol": "511260",
        "name": "国债ETF",
        "index_code": None,
    }
}

OUTPUT_FILE = "data.js"

# ================== 网络请求（防崩溃） ==================
def safe_get(url, params=None, retry=2, timeout=8):
    """绝对安全的GET请求，失败返回None"""
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

# ================== PE 分位（东方财富优先） ==================
def pe_eastmoney(idx):
    """东方财富直接返回市盈率分位（f134）"""
    try:
        # 指数代码格式：沪市指数加前缀 1.
        secid = f"1.{idx}"
        r = safe_get("https://push2.eastmoney.com/api/qt/stock/get",
                     {"secid": secid, "fields": "f134"})
        if r:
            pct = r.json().get("data", {}).get("f134")
            if pct is not None:
                return round(float(pct), 1)
    except:
        pass
    return None

def pe_netease(idx):
    """网易历史PE，计算近5年分位（备用）"""
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
    """依次尝试东方财富、网易，均失败返回50"""
    for func in [pe_eastmoney, pe_netease]:
        try:
            val = func(idx)
            if val is not None:
                return val
        except:
            pass
    return 50

# ================== K线数据（东方财富优先） ==================
def kline_eastmoney(sym, period="daily"):
    """东方财富K线，返回 [{high, close}]"""
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
    """腾讯K线，返回 [{high, close}]"""
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
    """获取K线，优先东方财富，失败则腾讯"""
    for func in [kline_eastmoney, kline_tencent]:
        try:
            val = func(sym, period)
            if val:
                return val
        except:
            pass
    return []

# ================== 实时价格（腾讯优先） ==================
def price_tencent(sym):
    """腾讯实时行情"""
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
    """东方财富实时价格"""
    try:
        r = safe_get("https://push2.eastmoney.com/api/qt/stock/get",
                     {"secid": f"1.{sym}", "fields": "f43"})
        if r:
            return r.json()["data"]["f43"] / 1000
    except:
        pass
    return None

def get_price(sym):
    """获取实时价格，优先腾讯，失败则东方财富"""
    for func in [price_tencent, price_eastmoney]:
        try:
            val = func(sym)
            if val:
                return round(val, 3)
        except:
            pass
    return None

# ================== 趋势计算 ==================
def calc_trend(weekly):
    """根据周线计算趋势：above / below1 / below2"""
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

# ================== 主流程 ==================
def update_all():
    result = {}
    for key, cfg in ETF_CONFIG.items():
        print(f"\n处理 {cfg['name']} ({cfg['symbol']}) ...")
        try:
            # 1. PE 分位
            if cfg["index_code"]:
                pe = get_pe(cfg["index_code"])
                result[f"pe{key}"] = pe if pe is not None else 50
            else:
                result[f"pe{key}"] = 0
            print(f"  PE分位: {result[f'pe{key}']}%")

            # 2. 日线最高价
            daily = get_kline(cfg["symbol"], "daily")
            high = round(max(k["high"] for k in daily), 3) if daily else 0
            result[f"high{key}"] = high
            print(f"  近5年最高价: {high}")

            # 3. 周线趋势
            weekly = get_kline(cfg["symbol"], "weekly")
            trend = calc_trend(weekly)
            result[f"trend{key}"] = trend
            print(f"  周线趋势: {trend}")

            # 4. 实时价格
            price = get_price(cfg["symbol"])
            if price:
                result[f"price{key}"] = price
                print(f"  当前价格: {price}")
            else:
                print("  当前价格获取失败")

        except Exception as e:
            print(f"  处理 {cfg['name']} 时出错，使用默认值")
            traceback.print_exc()
            # 填入默认值防止崩溃
            result[f"pe{key}"] = 50 if cfg["index_code"] else 0
            result[f"high{key}"] = 0
            result[f"trend{key}"] = "above"

        # 随机延迟，避免请求过快
        time.sleep(random.uniform(1.5, 3))

    result["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 写入 data.js
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("const AUTO_DATA = " + json.dumps(result, ensure_ascii=False, indent=2) + ";")
    print(f"\n✅ 已生成 {OUTPUT_FILE}，更新时间：{result['update_time']}")

if __name__ == "__main__":
    print("=" * 50)
    print("  方圆量化系统 - 数据自动更新（半导体版）")
    print("=" * 50)
    update_all()

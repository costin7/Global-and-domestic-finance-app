#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取主要指数/商品/汇率行情（Yahoo Finance 公开接口，无需密钥）。
输出 data/market_raw.json；单个品种失败不影响整体。"""
import json, os, sys, time
from datetime import datetime, timezone, timedelta
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "market_raw.json")
BJT = timezone(timedelta(hours=8))

# key: (候选代码列表, 中文名, 类型)  类型: index/rate/commodity/fx/crypto
SYMBOLS = {
    "spx":    (["^GSPC"], "标普500", "index"),
    "ixic":   (["^IXIC"], "纳斯达克综合", "index"),
    "dji":    (["^DJI"], "道琼斯", "index"),
    "ust10":  (["^TNX"], "10Y美债收益率", "rate"),      # 值需 /10
    "dxy":    (["DX-Y.NYB", "DX=F"], "美元指数 DXY", "index"),
    "gold":   (["GC=F"], "COMEX黄金", "commodity"),
    "brent":  (["BZ=F"], "布伦特原油", "commodity"),
    "btc":    (["BTC-USD"], "比特币", "crypto"),
    "sse":    (["000001.SS"], "上证指数", "index"),
    "csi300": (["000300.SS"], "沪深300", "index"),
    "chinext":(["399006.SZ"], "创业板指", "index"),
    "star50": (["000688.SS"], "科创50", "index"),
    "hsi":    (["^HSI"], "恒生指数", "index"),
    "hstech": (["^HSTECH", "3032.HK", "513180.SS"], "恒生科技", "index"),
    "n225":   (["^N225"], "日经225", "index"),
    "usdcny": (["CNY=X"], "美元兑人民币", "fx"),
    "csi_div":(["515080.SS"], "中证红利ETF(红利类代理)", "index"),
}

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}


def fetch_chart(symbol: str):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(symbol)}"
    r = requests.get(url, params={"range": "1y", "interval": "1d"}, headers=UA, timeout=20)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    ts = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]
    pts = [(t, c) for t, c in zip(ts, closes) if c is not None]
    if len(pts) < 5:
        raise ValueError("数据点过少")
    meta = res.get("meta", {})
    return pts, meta.get("currency", "")


def calc(key, pts, currency):
    scale = 0.1 if key == "ust10" else 1.0
    last_ts, last = pts[-1]
    prev = pts[-2][1]
    year = datetime.fromtimestamp(last_ts, BJT).year
    year_pts = [p for p in pts if datetime.fromtimestamp(p[0], BJT).year == year]
    base = year_pts[0][1] if year_pts else None  # 今年首个交易日收盘
    item = {
        "last": round(last * scale, 4),
        "dayChgPct": round((last / prev - 1) * 100, 2),
        "currency": currency,
        "asOf": datetime.fromtimestamp(last_ts, BJT).strftime("%Y-%m-%d"),
    }
    if key == "ust10":
        # 利率类：给年内变动 bp 而不是百分比
        if base:
            item["ytdBp"] = round((last - base) * scale * 100, 0)
    elif base:
        item["ytdPct"] = round((last / base - 1) * 100, 2)
    return item


def main():
    out = {"fetchedAt": datetime.now(BJT).strftime("%Y-%m-%d %H:%M"), "items": {}, "warnings": []}
    for key, (cands, name, kind) in SYMBOLS.items():
        ok = False
        for sym in cands:
            try:
                pts, cur = fetch_chart(sym)
                item = calc(key, pts, cur)
                item.update({"name": name, "symbol": sym, "kind": kind})
                out["items"][key] = item
                ok = True
                break
            except Exception as e:  # noqa: BLE001
                out["warnings"].append(f"{name}({sym}): {e}")
                time.sleep(1)
        if not ok:
            out["warnings"].append(f"{name}: 全部候选代码失败，将沿用旧数据")
        time.sleep(0.6)  # 温和限速
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"行情抓取完成：{len(out['items'])}/{len(SYMBOLS)} 成功；警告 {len(out['warnings'])} 条")
    for w in out["warnings"][:8]:
        print("  -", w)


if __name__ == "__main__":
    sys.exit(main())

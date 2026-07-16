#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取财经新闻标题（RSS，无需密钥），供 AI 分析选材。
输出 data/news_raw.json。任何单一源失败不影响整体。"""
import html
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "news_raw.json")
BJT = timezone(timedelta(hours=8))
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}

def gnews(query: str, lang="zh-CN", gl="CN", ceid="CN:zh-Hans"):
    from urllib.parse import quote
    return f"https://news.google.com/rss/search?q={quote(query)}&hl={lang}&gl={gl}&ceid={ceid}"

FEEDS = [
    ("谷歌新闻·中国宏观", gnews("中国经济 OR 央行 OR 国家统计局 when:2d")),
    ("谷歌新闻·A股港股", gnews("A股 OR 上证指数 OR 港股 OR 恒生指数 when:2d")),
    ("谷歌新闻·基金ETF", gnews("基金 OR ETF OR 公募 when:2d")),
    ("谷歌新闻·政策楼市", gnews("政策 OR 房地产 OR 人民币 汇率 when:2d")),
    ("谷歌新闻·美联储", gnews("美联储 OR 美国CPI OR 美股 when:2d")),
    ("谷歌新闻·全球市场", gnews("federal reserve OR inflation OR stock market when:2d", lang="en-US", gl="US", ceid="US:en")),
    ("谷歌新闻·大宗地缘", gnews("oil price OR gold price OR geopolitics markets when:2d", lang="en-US", gl="US", ceid="US:en")),
    ("CNBC·经济", "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
    ("CNBC·市场", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("MarketWatch·头条", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
]

TAG_RE = re.compile(r"<[^>]+>")


def clean(s: str, limit=220) -> str:
    s = html.unescape(TAG_RE.sub(" ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit]


def parse_feed(name: str, url: str):
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    items = []
    for it in root.iter("item"):
        title = clean(it.findtext("title", ""), 160)
        link = (it.findtext("link") or "").strip()
        desc = clean(it.findtext("description", ""))
        pub = it.findtext("pubDate", "")
        src = it.findtext("source") or name
        try:
            dt = parsedate_to_datetime(pub).astimezone(BJT)
            date = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:  # noqa: BLE001
            date = ""
        if title and link:
            items.append({"title": title, "link": link, "summary": desc,
                          "source": clean(str(src), 40) or name, "published": date, "feed": name})
    return items


def main():
    all_items, errors = [], []
    for name, url in FEEDS:
        try:
            got = parse_feed(name, url)[:15]
            all_items.extend(got)
            print(f"  {name}: {len(got)} 条")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")
    # 按标题去重（前18字符归一化）
    seen, dedup = set(), []
    for it in sorted(all_items, key=lambda x: x["published"], reverse=True):
        key = re.sub(r"\W", "", it["title"])[:18]
        if key and key not in seen:
            seen.add(key)
            dedup.append(it)
    dedup = dedup[:80]
    out = {"fetchedAt": datetime.now(BJT).strftime("%Y-%m-%d %H:%M"), "count": len(dedup),
           "items": dedup, "errors": errors}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"新闻抓取完成：{len(dedup)} 条（源错误 {len(errors)} 个）")
    for e in errors:
        print("  -", e)


if __name__ == "__main__":
    sys.exit(main())

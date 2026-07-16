#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 分析引擎：读取行情与新闻原料，调用 OpenAI 兼容接口生成 data/data.json。

模型可随时更换 —— 只需改环境变量（GitHub 仓库 Settings → Secrets and variables → Actions）：
  AI_API_KEY   必填（Secrets）      各家平台的 API Key
  AI_BASE_URL  选填（Variables）    默认 https://api.deepseek.com
  AI_MODEL     选填（Variables）    默认 deepseek-chat

任何环节失败都会沿用上一版 data.json，站点永不因更新失败而挂掉。"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "data.json")
MARKET = os.path.join(ROOT, "data", "market_raw.json")
NEWS = os.path.join(ROOT, "data", "news_raw.json")
BJT = timezone(timedelta(hours=8))
DRY = "--dry-run" in sys.argv

AI_BASE = (os.environ.get("AI_BASE_URL") or "https://api.deepseek.com").rstrip("/")
AI_MODEL = os.environ.get("AI_MODEL") or "deepseek-chat"
AI_KEY = os.environ.get("AI_API_KEY", "")


# ---------------- 基础工具 ----------------
def load(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return default


def chat(system: str, user: str, max_tokens=6000, retries=2) -> dict:
    """调用 OpenAI 兼容 /chat/completions，强制 JSON 输出并解析。"""
    url = AI_BASE + ("/chat/completions" if not AI_BASE.endswith("/v1") else "/chat/completions")
    payload = {
        "model": AI_MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.4,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    last_err = None
    for i in range(retries + 1):
        try:
            r = requests.post(url, json=payload, timeout=300,
                              headers={"Authorization": f"Bearer {AI_KEY}"})
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            m = re.search(r"\{[\s\S]*\}", content)
            return json.loads(m.group(0) if m else content)
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"::warning::AI 调用失败(第{i + 1}次): {e}")
            time.sleep(5 * (i + 1))
    raise RuntimeError(f"AI 调用最终失败: {last_err}")


def fnum(v, digits=2):
    s = f"{v:,.{digits}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def sgn(p, unit="%"):
    if p is None:
        return "—"
    return ("+" if p >= 0 else "") + f"{p:.1f}{unit}" if abs(p) < 100 else ("+" if p >= 0 else "") + f"{p:.0f}{unit}"


def tile(label, value, delta, delta_label, direction):
    return {"label": label, "value": value, "delta": delta, "deltaLabel": delta_label, "dir": direction}


def dir_of(p):
    return "flat" if p is None else ("up" if p > 0 else "down" if p < 0 else "flat")


def prev_tile(prev_list, label, alts=()):
    for want in (label, *alts):
        for t in prev_list or []:
            if t.get("label") == want:
                return t
    return None


# ---------------- 确定性构建（数字不经过 AI，杜绝幻觉） ----------------
def build_global_kpis(mk, prev):
    out, p = [], (prev.get("global", {}).get("kpis") or [])
    spec = [
        ("spx", "标普500", (), lambda it: fnum(it["last"])),
        ("ixic", "纳斯达克综合", (), lambda it: fnum(it["last"])),
        ("dji", "道琼斯", (), lambda it: fnum(it["last"])),
        ("ust10", "10Y美债收益率", (), lambda it: f"{it['last']:.2f}%"),
        ("dxy", "美元指数 DXY", (), lambda it: fnum(it["last"], 1)),
        ("gold", "COMEX黄金", ("现货黄金", "黄金"), lambda it: "$" + fnum(it["last"], 0)),
        ("brent", "布伦特原油", (), lambda it: "$" + fnum(it["last"], 2)),
        ("btc", "比特币", (), lambda it: "$" + fnum(it["last"], 0)),
    ]
    for key, label, alts, fmt in spec:
        it = (mk.get("items") or {}).get(key)
        if it:
            if key == "ust10":
                bp = it.get("ytdBp")
                out.append(tile(label, fmt(it), (f"{'+' if bp >= 0 else ''}{bp:.0f}bp" if bp is not None else "—"),
                                "年内", dir_of(bp)))
            else:
                y = it.get("ytdPct")
                out.append(tile(label, fmt(it), sgn(y), "年内", dir_of(y)))
        else:
            old = prev_tile(p, label, alts)
            if old:
                out.append(old)
    return out or p


def build_china_kpis(mk, prev, rate_tiles):
    out, p = [], (prev.get("china", {}).get("kpis") or [])
    spec = [
        ("sse", "上证指数"), ("csi300", "沪深300"), ("chinext", "创业板指"), ("star50", "科创50"),
        ("hsi", "恒生指数"), ("hstech", "恒生科技"),
    ]
    for key, label in spec:
        it = (mk.get("items") or {}).get(key)
        if it:
            y = it.get("ytdPct")
            out.append(tile(label, fnum(it["last"]), sgn(y), "年内", dir_of(y)))
        else:
            old = prev_tile(p, label)
            if old:
                out.append(old)
    # 10Y国债 与 LPR：无免费行情源，默认沿用上一版，AI 可依据官方新闻覆盖
    for label in ["10Y国债收益率", "LPR (1Y/5Y+)"]:
        override = next((t for t in (rate_tiles or []) if isinstance(t, dict) and t.get("label") == label), None)
        old = override or prev_tile(p, label)
        if old:
            out.append(old)
    it = (mk.get("items") or {}).get("usdcny")
    if it:
        y = it.get("ytdPct")
        lbl = "人民币年内贬值" if (y or 0) > 0 else "人民币年内升值"
        out.append(tile("美元兑人民币", fnum(it["last"], 4), sgn(y), lbl, dir_of(y)))
    else:
        old = prev_tile(p, "美元兑人民币")
        if old:
            out.append(old)
    return out or p


def build_asset_ytd(mk, prev):
    label_map = [
        ("star50", "科创50"), ("n225", "日经225"), ("chinext", "创业板指"), ("csi300", "沪深300"),
        ("ixic", "纳斯达克综合"), ("spx", "标普500"), ("sse", "上证指数"), ("hsi", "恒生指数"),
        ("hstech", "恒生科技"), ("gold", "COMEX黄金"), ("csi_div", "红利类(515080代理)"),
    ]
    rows = []
    for key, label in label_map:
        it = (mk.get("items") or {}).get(key)
        if it and it.get("ytdPct") is not None:
            rows.append({"label": label, "value": it["ytdPct"], "note": f"截至{it.get('asOf', '')}"})
    if len(rows) < 6:
        return prev.get("trend", {}).get("assetYTD") or rows
    rows.sort(key=lambda r: r["value"], reverse=True)
    return rows


# ---------------- AI 三段式分析 ----------------
def market_digest(mk):
    lines = []
    for key, it in (mk.get("items") or {}).items():
        y = it.get("ytdPct")
        extra = f" 年内{sgn(y)}" if y is not None else (f" 年内{it.get('ytdBp', 0):+.0f}bp" if "ytdBp" in it else "")
        lines.append(f"{it['name']}: {it['last']}（日{it.get('dayChgPct', 0):+.2f}%,{extra}, 截至{it.get('asOf')}）")
    return "\n".join(lines)


def news_digest(nw, limit=70):
    lines = []
    for it in (nw.get("items") or [])[:limit]:
        lines.append(f"- [{it.get('published', '')[:10]}] {it['title']}｜{it.get('source', '')}｜{it['link']}"
                     + (f"｜{it['summary'][:90]}" if it.get("summary") else ""))
    return "\n".join(lines)


SYS = ("你是严谨的中文财经研究助手，为一个名为「财经罗盘」的公开仪表盘生成内容。"
       "必须输出合法 JSON（UTF-8，无注释无多余文本）。所有文字用简体中文。"
       "语气为研究梳理而非指令式推荐，不承诺收益；数字只能来自输入材料，不得编造；"
       "涉及基金品种时仅使用广为人知的真实代码，不确定就写类别不写代码。")


def call_news(nw, today):
    user = f"""今天是{today}（北京时间）。以下是最新抓取的新闻标题池（含链接）：
{news_digest(nw)}

任务：从中挑选并改写为仪表盘新闻卡片。输出 JSON：
{{"globalNews":[10条全球财经热点],"chinaNews":[10条中国财经热点]}}
每条格式：{{"date":"MM-DD","tag":"2-4字分类（如 货币政策/通胀/A股/港股/地缘/房地产/产业政策/汇率/大宗商品/科技）","title":"≤40字标题","summary":"80-130字摘要（可综合多条相关标题）","implication":"一句话市场含义","sourceName":"来源媒体名","sourceUrl":"必须原样使用输入里的链接"}}
要求：全球条目覆盖货币政策/通胀或就业/美股/欧洲或日本/大宗商品/地缘中至少5类；中国条目覆盖宏观数据/政策/A股/港股/汇率或楼市中至少5类；不要重复同一事件；sourceUrl 必须来自输入链接列表。"""
    return chat(SYS, user, max_tokens=6000)


def call_trend(mk, nw, prev, today):
    pt = prev.get("trend", {})
    user = f"""今天是{today}（北京时间）。

【最新行情（程序抓取，可信）】
{market_digest(mk)}

【最新新闻标题池（节选）】
{news_digest(nw, 45)}

【上一版宏观序列（若新闻中没有新公布的官方数据，必须原样沿用）】
中国: months={json.dumps(pt.get('chinaMacro', {}).get('months', []), ensure_ascii=False)} cpi={pt.get('chinaMacro', {}).get('cpi')} ppi={pt.get('chinaMacro', {}).get('ppi')} pmi={pt.get('chinaMacro', {}).get('pmi')}
美国: months={json.dumps(pt.get('usMacro', {}).get('months', []), ensure_ascii=False)} cpi={pt.get('usMacro', {}).get('cpi')} ffr={pt.get('usMacro', {}).get('ffr')}

【上一版中国利率磁贴（若新闻无 LPR/国债新信息则沿用）】
{json.dumps([t for t in prev.get('china', {}).get('kpis', []) if t.get('label') in ['10Y国债收益率', 'LPR (1Y/5Y+)']], ensure_ascii=False)}

任务：输出走向分析 JSON：
{{"heroTitle":"总览页今日焦点大标题（≤12字，突出当天最大变化）",
"heroDesc":"120-180字：概括今天全球+中国最重要变化",
"judgments":[3条 {{"title":"≤14字判断","desc":"60-110字论据"}}],
"globalAnalysis":[4段字符串，每段90-200字：货币政策/增长与通胀/资产分化/地缘与机构观点],
"chinaAnalysis":[4段字符串：物价与景气/政策取向/市场结构/汇率与机构共识],
"scenarios":[3个 {{"name":"基准|乐观|悲观：≤12字副题","prob":"如55%","desc":"70-120字"}}],
"chinaMacro":{{"months":[...],"cpi":[...],"ppi":[...],"pmi":[...]}},
"usMacro":{{"months":[...],"cpi":[数字或null...],"ffr":[...]}},
"rateTiles":[可选：若新闻公布了新 LPR 或 10Y 国债水平，给出 {{"label":"LPR (1Y/5Y+)","value":"x% / x%","delta":"...","deltaLabel":"...","dir":"flat"}} 等，否则给 []]}}
序列规则：只有当新闻明确包含新一期官方数据时才在序列末尾追加新月份并保持 6-9 个点（多则去头），否则原样返回上一版；数值必须与来源一致。"""
    return chat(SYS, user, max_tokens=5000)


def call_funds(mk, prev, today):
    pf = prev.get("funds", {})
    ps = prev.get("spec", {})
    user = f"""今天是{today}（北京时间）。用户风险偏好：平衡型；覆盖国内+海外基金。

【最新行情】
{market_digest(mk)}

【上一版基金建议（作为基础，按最新行情微调而非推倒重来；配置颜色 color 字段必须原样保留）】
{json.dumps({'allocation': pf.get('allocation'), 'longTermCategories': [c.get('category') for c in pf.get('longTerm', [])], 'shortTermCategories': [c.get('category') for c in pf.get('shortTerm', [])]}, ensure_ascii=False)}

【上一版长期/短期卡片与投机观察全文】
{json.dumps({'longTerm': pf.get('longTerm'), 'shortTerm': pf.get('shortTerm'), 'notes': pf.get('notes'), 'spec': ps}, ensure_ascii=False)[:6000]}

任务：输出基金与投机模块 JSON：
{{"allocation":[6项 {{"label","pct":整数,"color":"沿用上一版的 --s1 等","note"}}，pct 合计=100],
"longTerm":[5-6张 {{"category","tickers":["名称 (代码)"...],"role":"核心|卫星","risk":1-5整数,"logic":"90-180字","risks":"50-120字","horizon","weight"}}],
"shortTerm":[3-4张 同上结构],
"notes":[4-5条操作要点字符串，第一条必须是未来两周关键财经日历],
"specRules":[3-4条投机纪律字符串],
"specItems":[4-5个 {{"theme","heat":"如 极高热度/中热度","drivers","catalysts","vehicles","risks","discipline"}}]}}
要求：基于最新行情更新逻辑与风险描述（点位、涨跌幅要与输入行情一致）；建议持有期与仓位保持克制；投机模块必须强调风险与止损；所有内容是研究参考而非推荐。"""
    return chat(SYS, user, max_tokens=6000)


# ---------------- 校验 ----------------
def v_news(d):
    for k in ["globalNews", "chinaNews"]:
        arr = d.get(k)
        assert isinstance(arr, list) and len(arr) >= 6, f"{k} 数量不足"
        for it in arr:
            for f in ["date", "tag", "title", "summary", "implication", "sourceName", "sourceUrl"]:
                assert isinstance(it.get(f), str) and it[f], f"{k} 缺字段 {f}"
    return d


def v_series(s, months_key="months"):
    assert isinstance(s, dict) and isinstance(s.get(months_key), list) and 4 <= len(s[months_key]) <= 12
    n = len(s[months_key])
    for k, v in s.items():
        if k == months_key:
            continue
        assert isinstance(v, list) and len(v) == n, f"序列 {k} 长度不一致"
        assert all(x is None or isinstance(x, (int, float)) for x in v), f"序列 {k} 含非法值"
    return s


def v_trend(d):
    assert isinstance(d.get("heroTitle"), str) and d["heroTitle"]
    assert isinstance(d.get("heroDesc"), str) and len(d["heroDesc"]) > 40
    assert isinstance(d.get("judgments"), list) and len(d["judgments"]) == 3
    for k in ["globalAnalysis", "chinaAnalysis"]:
        assert isinstance(d.get(k), list) and 2 <= len(d[k]) <= 6
    assert isinstance(d.get("scenarios"), list) and len(d["scenarios"]) == 3
    v_series(d.get("chinaMacro", {}))
    v_series(d.get("usMacro", {}))
    return d


def v_funds(d):
    alloc = d.get("allocation")
    assert isinstance(alloc, list) and 4 <= len(alloc) <= 8
    total = sum(int(a.get("pct", 0)) for a in alloc)
    assert 97 <= total <= 103, f"配置合计 {total} 异常"
    for k, lo in [("longTerm", 4), ("shortTerm", 2)]:
        arr = d.get(k)
        assert isinstance(arr, list) and len(arr) >= lo
        for c in arr:
            assert c.get("category") and isinstance(c.get("tickers"), list)
            assert isinstance(c.get("risk"), int) and 1 <= c["risk"] <= 5
    assert isinstance(d.get("notes"), list) and len(d["notes"]) >= 3
    assert isinstance(d.get("specRules"), list) and len(d["specRules"]) >= 3
    arr = d.get("specItems")
    assert isinstance(arr, list) and len(arr) >= 3
    for it in arr:
        for f in ["theme", "heat", "drivers", "catalysts", "vehicles", "risks", "discipline"]:
            assert isinstance(it.get(f), str) and it[f], f"specItems 缺 {f}"
    return d


# ---------------- 干跑（无 API 时自测管线） ----------------
def dry_results(prev, today):
    g = [{"date": today[5:], "tag": n["tag"], "title": n["title"], "summary": n["summary"],
          "implication": n["implication"], "sourceName": n["source"]["name"], "sourceUrl": n["source"]["url"]}
         for n in prev["global"]["news"]]
    c = [{"date": today[5:], "tag": n["tag"], "title": n["title"], "summary": n["summary"],
          "implication": n["implication"], "sourceName": n["source"]["name"], "sourceUrl": n["source"]["url"]}
         for n in prev["china"]["news"]]
    t = {"heroTitle": prev["overview"]["heroTitle"], "heroDesc": prev["overview"]["heroDesc"],
         "judgments": prev["overview"]["judgments"], "globalAnalysis": prev["trend"]["globalAnalysis"],
         "chinaAnalysis": prev["trend"]["chinaAnalysis"], "scenarios": prev["trend"]["scenarios"],
         "chinaMacro": prev["trend"]["chinaMacro"], "usMacro": prev["trend"]["usMacro"], "rateTiles": []}
    f = {"allocation": prev["funds"]["allocation"], "longTerm": prev["funds"]["longTerm"],
         "shortTerm": prev["funds"]["shortTerm"], "notes": prev["funds"]["notes"],
         "specRules": prev["spec"]["rules"], "specItems": prev["spec"]["items"]}
    return {"globalNews": g, "chinaNews": c}, t, f


def main():
    prev = load(DATA)
    if not prev:
        print("::error::缺少上一版 data/data.json，无法运行")
        return 1
    mk = load(MARKET, {"items": {}})
    nw = load(NEWS, {"items": []})
    now = datetime.now(BJT)
    today = now.strftime("%Y-%m-%d")

    if not DRY and not AI_KEY:
        print("::warning::未配置 AI_API_KEY，跳过 AI 分析，仅用最新行情刷新数字部分")

    try:
        if DRY:
            news_r, trend_r, funds_r = dry_results(prev, today)
        elif AI_KEY:
            news_r = v_news(call_news(nw, today))
            trend_r = v_trend(call_trend(mk, nw, prev, today))
            funds_r = v_funds(call_funds(mk, prev, today))
        else:
            news_r, trend_r, funds_r = dry_results(prev, today)
    except Exception as e:  # noqa: BLE001
        print(f"::warning::AI 分析失败，本次沿用上一版分析文字，仅刷新行情数字。原因: {e}")
        news_r, trend_r, funds_r = dry_results(prev, today)

    def news_map(items):
        return [{"date": it["date"], "tag": it["tag"], "title": it["title"], "summary": it["summary"],
                 "implication": it["implication"],
                 "source": {"name": it["sourceName"], "url": it["sourceUrl"]}} for it in items]

    data = json.loads(json.dumps(prev, ensure_ascii=False))  # 深拷贝
    data["meta"]["generatedAt"] = now.strftime("%Y-%m-%d %H:%M（北京时间）")
    data["overview"].update({"heroTitle": trend_r["heroTitle"], "heroDesc": trend_r["heroDesc"],
                             "judgments": trend_r["judgments"]})
    data["global"]["kpis"] = build_global_kpis(mk, prev)
    data["global"]["news"] = news_map(news_r["globalNews"]) or prev["global"]["news"]
    data["china"]["kpis"] = build_china_kpis(mk, prev, trend_r.get("rateTiles"))
    data["china"]["news"] = news_map(news_r["chinaNews"]) or prev["china"]["news"]
    data["trend"].update({
        "assetYTD": build_asset_ytd(mk, prev),
        "chinaMacro": trend_r["chinaMacro"], "usMacro": trend_r["usMacro"],
        "globalAnalysis": trend_r["globalAnalysis"], "chinaAnalysis": trend_r["chinaAnalysis"],
        "scenarios": trend_r["scenarios"],
    })
    data["funds"] = {"allocation": funds_r["allocation"], "longTerm": funds_r["longTerm"],
                     "shortTerm": funds_r["shortTerm"], "notes": funds_r["notes"]}
    data["spec"] = {"rules": funds_r["specRules"], "items": funds_r["specItems"]}

    # 数据来源：固定官方源 + 今日新闻来源去重
    fixed = prev.get("sources", [])[:10]
    seen = {s["url"] for s in fixed}
    for n in data["global"]["news"] + data["china"]["news"]:
        u = n["source"]["url"]
        if u not in seen and len(fixed) < 24:
            seen.add(u)
            fixed.append({"name": n["source"]["name"], "url": u})
    data["sources"] = fixed

    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    mode = AI_MODEL if AI_KEY and not DRY else "未启用/干跑"
    print(f"::notice::data.json 已更新（{data['meta']['generatedAt']}，AI: {mode}，行情品种: {len((mk.get('items') or {}))}）")
    print(f"data.json 已更新（{data['meta']['generatedAt']}，模型: {mode}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

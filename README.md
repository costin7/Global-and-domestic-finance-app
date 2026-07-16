# 🧭 财经罗盘

AI 每日自动更新的「全球 × 中国」财经热点、经济走向分析与基金策略仪表盘。

纯静态网站 + GitHub Actions 自动化：每天早上 8 点（北京时间）自动抓取行情与新闻 → AI 分析 → 更新数据 → 发布到 GitHub Pages / Vercel。**分析模型可随时更换**（DeepSeek / Kimi / 智谱 / OpenAI / Claude 等任意 OpenAI 兼容接口）。

## 工作原理

```
GitHub Actions（每天 UTC 00:00 = 北京 08:00）
 ├─ scripts/fetch_market.py   Yahoo 行情：中美港日主要指数、金油、美元、比特币、汇率（免费无密钥）
 ├─ scripts/fetch_news.py     新闻标题池：Google News（中英多主题）+ CNBC + MarketWatch RSS
 ├─ scripts/analyze.py        调用 AI（OpenAI 兼容接口）三段式生成：
 │                              ① 新闻精选与市场含义  ② 走向研判/情景推演/宏观序列
 │                              ③ 基金长短期建议与投机观察
 │                            关键数字（点位、涨跌幅）由程序计算注入，不经过 AI，避免幻觉
 ├─ 提交 data/data.json
 └─ 部署 GitHub Pages（推送到 main 也会触发纯部署）
```

前端 `index.html` 运行时加载 `data/data.json`（带内置快照兜底，双击本地文件也能看）。任何更新环节失败都会沿用上一版数据，**站点永不因更新失败而挂掉**。

## 首次配置（约 5 分钟）

1. **添加 AI Key**：仓库 `Settings → Secrets and variables → Actions → Secrets → New repository secret`
   - 名称 `AI_API_KEY`，值为你的 DeepSeek API Key（在 <https://platform.deepseek.com> 创建）
2. **（可选）指定模型**：同页面 `Variables` 标签
   - `AI_BASE_URL`（默认 `https://api.deepseek.com`）
   - `AI_MODEL`（默认 `deepseek-chat`）
3. **启用 Pages**：`Settings → Pages → Build and deployment → Source` 选 **GitHub Actions**
4. **手动跑一次**：`Actions → 每日更新并部署 → Run workflow`，两三分钟后 Pages 地址即上线最新数据

## 🔄 更换 AI 模型

只改两个 Variables（`AI_BASE_URL` + `AI_MODEL`），Key 换成对应平台的即可：

| 平台 | AI_BASE_URL | AI_MODEL 示例 |
|---|---|---|
| DeepSeek（默认） | `https://api.deepseek.com` | `deepseek-chat`（V3）/ `deepseek-reasoner`（R1） |
| 月之暗面 Kimi | `https://api.moonshot.cn/v1` | `moonshot-v1-32k` 等 |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-air` 等 |
| 阿里通义 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` 等 |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` 等 |
| Anthropic Claude | `https://api.anthropic.com/v1`（OpenAI 兼容层） | `claude-sonnet-4-5` 等 |

> 模型名与接口以各平台最新文档为准；只要提供 OpenAI 兼容的 `/chat/completions` 且支持 JSON 输出即可接入。

## Vercel 同步部署

Vercel 控制台 → `Add New → Project` → 导入本仓库 → 直接 Deploy（纯静态，无需构建配置）。之后每次 Actions 提交数据，Vercel 会自动重新部署，两边始终同步。

## 本地开发

```bash
python -m http.server 8000        # 打开 http://localhost:8000
python scripts/fetch_market.py    # 测试行情抓取
python scripts/fetch_news.py      # 测试新闻抓取
python scripts/analyze.py --dry-run   # 不调 AI，测试数据管线
AI_API_KEY=sk-xxx python scripts/analyze.py   # 真实生成
```

## 自定义

- **更新时间**：改 `.github/workflows/update-and-deploy.yml` 里的 cron（UTC，北京时间减 8 小时）
- **监控品种**：改 `scripts/fetch_market.py` 的 `SYMBOLS`
- **新闻来源**：改 `scripts/fetch_news.py` 的 `FEEDS`
- **风险偏好 / 免责声明**：改 `data/data.json` 的 `meta`（AI 更新时会保留）

## ⚠️ 免责声明

本项目全部内容由 AI 自动搜集公开信息生成，仅供参考与学习交流，**不构成任何投资建议**。数据可能存在错漏或时滞；基金有风险，投资需谨慎，请独立决策并自行核实。

# htlb-dataset · 高性价比人生指南结构化数据集

《高性价比人生指南》全书正文解析成**机器可读的结构化数据**，每天自动同步上游。

上游 [eternity4719/HowToLiveBetter](https://github.com/eternity4719/HowToLiveBetter) 只发布 Markdown，不发布数据。于是每个衍生工具——微信小程序、Android App、各语言翻译、各本地化版本——都得自己写一遍 Markdown 解析器，结果是同一本书在不同地方条数对不上（528 / 612 / 672 三个数字同时在流传）。

本仓库只做一件事：把正文解析好，**当所有衍生工具的公共数据源**。

## 现状数字（每次同步自动更新，以 `meta.synced_at` 为准）

| 指标 | 值 |
|---|---|
| 条目 | 672 |
| 节 | 34 |
| 证据等级 | A 438 · B 179 · C 55 |
| 性价比 | 极高 114 · 高 304 · 一般 254 |
| 争议标注 | 70 条 |
| 出处链接 | 1690 |
| 交叉引用 | 343 |

## 快速开始

**直接用数据**（不用跑脚本）：

```
data/htlb.json     全量，含 meta / sections / items
data/htlb.csv      扁平表，Excel 直接打开（UTF-8 BOM）
data/htlb.sqlite   SQLite，字段同 JSON，建了 section / evidence / ratio 索引
data/stats.json    统计与校验数字
data/schema.json   字段说明
```

`htlb.sqlite` 不入库（二进制，每天全量会撑爆仓库），本地跑一次 `python build.py` 即可生成。

**自己生成**：

```bash
git clone --depth 1 https://github.com/eternity4719/HowToLiveBetter.git _upstream
python build.py --repo _upstream          # 解析并写出 data/
python build.py --repo _upstream --check  # 只校验不写（CI 用）
```

零第三方依赖，Python 3.8+ 标准库即可。

## 一条数据长什么样

```json
{
  "id": "23-1",
  "section": 23,
  "section_title": "学什么技能划算",
  "no": 1,
  "title": "不满 16 周岁没有「去打工」这个选项：招你的单位每月被罚 5000 元",
  "cost_money": "0", "cost_time": "少", "cost_willpower": "否",
  "benefit_level": "大", "metric": "自由",
  "cost_score": 0, "ratio": "极高",
  "evidence": "A", "evidence_raw": "A", "evidence_flags": [],
  "disputed": false, "todo": false,
  "plain": "初中毕业一般 15 到 16 岁…每用一名童工每月罚 5000 元。",
  "cost_text": "不花钱。花一分钟算一下自己多大。",
  "benefit_text": "《义务教育法》第十一条…",
  "sources": ["http://www.moe.gov.cn/...", "http://www.gov.cn/..."],
  "note": "受益人是自己。满 16 岁以后打工是合法的…",
  "refs": []
}
```

完整字段见 `data/schema.json`。

## 口径：与上游逐字对齐，不对齐就报错

抄自上游 `tools/sync-stats.mjs` 文件头注释与 `index.html` 的 `COST_W` / `e.ratio` 两行：

- 条目数 = `book/*.md` 里的 `###` 标题数；节数 = `book/*.md` 文件数
- **A/B/C = 证据等级行的首字母**，带 `（争议）` 后缀的照样算
- 争议 = 备注以「争议」开头的条数；TODO = 正文含「待核实」或 `TODO`
- 链接 = 「来源」「备注」两行里的 http(s) 总数
- 性价比 = `COST_W` 加权求和后按 `e.ratio` 分档

**防漂移**：`build.py` 启动时比对上游 `index.html` 里的那两行，上游一旦改权重或分档规则，脚本直接报错退出，不会静默算出对不上的数。

**自检**：解析完逐条校验 6 个字段与成本标签是否齐全，缺任何一项就中止输出。当前上游 672 条全部字段齐全，零缺失。

### 已知数据质量点（别踩）

**证据等级有 5 条带括号后缀**，直接按 `A/B/C` 硬切会漏掉或分错：

| id | 原文 | 归一化 | 括号标记 |
|---|---|---|---|
| 5-14 | `C（争议）` | C | 争议 |
| 10-8 | `A（争议）` | A | 争议 |
| 10-20 | `A（争议）` | A | 争议 |
| 13-15 | `B（指南强推荐，但底层证据等级低）` | B | 指南强推荐，但底层证据等级低 |
| 23-2 | `A（争议）` | A | 争议 |

所以数据里同时给了三个字段：`evidence`（首字母，方便分组）、`evidence_raw`（原文）、`evidence_flags`（括号内容列表）。**要筛"有争议的"，用 `evidence_flags` 或 `disputed`，不要只看 `evidence`。**

## 许可

- **正文数据**：源自《高性价比人生指南》，CC BY 4.0。已做到的三件事——写明出处、附上 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) 链接、标注本数据集为解析后的结构化改写版。每条数据的同步版本见 `data/htlb.json` 的 `meta.upstream_commit` 与 `meta.synced_at`。
- **代码**（`build.py`、workflows）：MIT，见 `LICENSE-CODE`。
- `data/NOTICE.md` 随数据一起分发，单独取用 `data/` 时也带着声明。

## 边界

- 不改写、不增删、不评价正文任何一字，只做格式转换。内容纠错请去上游仓库提 issue。
- 不提供阅读页面、App、翻译——那些已有他人维护，需要数据直接取这里的 JSON。
- 上游日更，快照会过期：请按 `meta.synced_at` 判断新鲜度，或直接订阅本仓库的每日同步。

### 快照过期有多快：一个上午的实测

2026-10-08 这一天，上游同一个仓库的条数变化：

| 时间（UTC） | 上游 commit | 条数 |
|---|---|---|
| 01:04 | `b9034f0` | 670 |
| 02:48 | `54ac922` 按 issue #94 补第 1 节第 43 条 | 671 |
| 05:07 | `0cec2b3` 补第 20 节第 14 条 | 672 |

**四个小时，涨了 2 条。** 所以别把任何一份快照当成"最新版"到处转——要看同步时间。这也是本仓库每天自动跑一次的原因。

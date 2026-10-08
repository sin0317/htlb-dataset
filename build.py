# -*- coding: utf-8 -*-
"""把《高性价比人生指南》book/*.md 解析成结构化数据（JSON / CSV / SQLite）。

用法：
    python build.py --repo _upstream            解析并写出 data/
    python build.py --repo _upstream --check    只校验不写（CI 用）

零第三方依赖，Python 3.8+。

口径与上游 eternity4719/HowToLiveBetter 的 tools/sync-stats.mjs 完全一致，
抄自该文件头注释与 index.html 的 COST_W / e.ratio 两行：
  条目数 = book/*.md 里的 ### 标题数
  节数   = book/*.md 的文件数
  A/B/C  = 证据等级行的首字母（带（争议）后缀的照样算）
  争议   = 备注以「争议」开头的条数
  TODO   = 正文里含「待核实」或「TODO」的行数
  链接   = 「- 来源：」和「- 备注：」行里的 http(s) 总数
  性价比 = index.html 的 COST_W 权重与 e.ratio 分档

上游若改了那两行，本脚本启动即报错退出，避免静默漂移。
"""

import argparse
import csv
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))

UPSTREAM_REPO = "https://github.com/eternity4719/HowToLiveBetter"
UPSTREAM_NAME = "高性价比人生指南"

# 上游 index.html 里的两行，改了就必须同步本文件（防漂移）
COST_W_LINE = "const COST_W = { money:{'0':0,'少':1,'多':2}, time:{'少':0,'中':1,'多':2}, will:{'否':0,'些':1,'是':2} };"
RATIO_LINE = "e.ratio = e.level === '大' ? (e.cs === 0 ? '极高' : (e.cs <= 2 ? '高' : '一般'))"

W_MONEY = {"0": 0, "少": 1, "多": 2}
W_TIME = {"少": 0, "中": 1, "多": 2}
W_WILL = {"否": 0, "些": 1, "是": 2}

FIELDS = ["成本", "说人话", "收益", "证据等级", "来源", "备注"]
FIELD_KEY = {
    "成本": "cost_text",
    "说人话": "plain",
    "收益": "benefit_text",
    "证据等级": "evidence_raw",
    "来源": "source_text",
    "备注": "note",
}

RE_ITEM = re.compile(r"^###\s+(\d+)\.\s*(.+?)\s*$")
RE_TAG = re.compile(
    r"<!--\s*成本标签:\s*钱=(\S+)\s+时间=(\S+)\s+毅力=(\S+)\s+收益=(\S+)\s+口径=(\S+?)\s*-->"
)
RE_FIELD = re.compile(r"^-\s*(成本|说人话|收益|证据等级|来源|备注)\s*[：:]\s*(.*)$")
RE_SEC_TITLE = re.compile(r"^#\s+(\d+)\.\s*(.+?)\s*$", re.M)
RE_XREF_SEC = re.compile(r"见第\s*(\d+)\s*节第\s*(\d+)\s*条")
RE_XREF_LOCAL = re.compile(r"见第\s*(\d+)\s*条")
RE_URL = re.compile(r"https?://[^\s<>()（）]+")


def die(msg):
    print("[build] 失败：%s" % msg, file=sys.stderr)
    sys.exit(1)


def check_algorithm(repo):
    """上游改了权重或分档规则就退出，不要静默算出对不上的数。"""
    p = os.path.join(repo, "index.html")
    if not os.path.exists(p):
        print("[build] 警告：找不到 index.html，跳过算法一致性校验")
        return
    text = open(p, encoding="utf-8").read()
    if COST_W_LINE not in text:
        die("index.html 的 COST_W 行变了，请同步 build.py 里的权重")
    if RATIO_LINE not in text:
        die("index.html 的 e.ratio 行变了，请同步 build.py 里的分档规则")


def ratio_of(cost, level):
    """与上游 ratioOf() 逐字对应。"""
    if level == "大":
        return "极高" if cost == 0 else ("高" if cost <= 2 else "一般")
    return "高" if (level == "中" and cost == 0) else "一般"


def split_fields(lines):
    """把条目块按 `- 字段：` 切成 dict，值含续行。"""
    found = {}
    order = []
    cur = None
    buf = []
    for ln in lines:
        m = RE_FIELD.match(ln)
        if m:
            if cur:
                found[cur] = "\n".join(buf).strip()
            cur = m.group(1)
            order.append(cur)
            buf = [m.group(2)]
        elif cur:
            buf.append(ln)
    if cur:
        found[cur] = "\n".join(buf).strip()
    return found, order


def norm_evidence(raw):
    """官方口径：取首字母；括号后缀原样保留在 evidence_flags。"""
    if not raw:
        return None, []
    s = raw.strip()
    flags = re.findall(r"[（(]([^（）()]+)[）)]", s)
    return s[0] if s and s[0] in "ABC" else None, flags


def parse_book(repo):
    book_dir = os.path.join(repo, "book")
    if not os.path.isdir(book_dir):
        die("找不到 %s，先克隆上游仓库" % book_dir)

    files = sorted(f for f in os.listdir(book_dir) if f.endswith(".md"))
    items = []
    sections = []
    problems = []

    for fn in files:
        path = os.path.join(book_dir, fn)
        text = open(path, encoding="utf-8").read()
        lines = text.split("\n")

        m = RE_SEC_TITLE.search(text, re.M)
        if m:
            sec_no, sec_title = int(m.group(1)), m.group(2)
        else:
            fm = re.match(r"^(\d+)-", fn)
            sec_no = int(fm.group(1)) if fm else 0
            sec_title = ""
            problems.append("%s 缺 # 节标题" % fn)

        sections.append({"no": sec_no, "title": sec_title, "file": fn})

        # 按 ### 切块
        starts = [i for i, ln in enumerate(lines) if RE_ITEM.match(ln)]
        for idx, s in enumerate(starts):
            e = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
            block = lines[s:e]
            m = RE_ITEM.match(block[0])
            no, title = int(m.group(1)), m.group(2)

            tag = None
            for ln in block[:4]:
                tag = RE_TAG.search(ln) or tag
            if not tag:
                problems.append("%s 第 %d 条缺成本标签" % (fn, no))

            fields, _ = split_fields(block)
            for f in FIELDS:
                if f not in fields:
                    problems.append("%s 第 %d 条缺「%s」字段" % (fn, no, f))

            raw_ev = fields.get("证据等级", "")
            ev, flags = norm_evidence(raw_ev)

            cm = tag.group(1) if tag else None
            ct = tag.group(2) if tag else None
            cw = tag.group(3) if tag else None
            lv = tag.group(4) if tag else None
            metric = tag.group(5) if tag else None

            cost = None
            ratio = None
            if tag:
                try:
                    cost = W_MONEY[cm] + W_TIME[ct] + W_WILL[cw]
                    ratio = ratio_of(cost, lv)
                except KeyError as ex:
                    problems.append("%s 第 %d 条成本标签取值异常：%s" % (fn, no, ex))

            note = fields.get("备注", "")
            full = "\n".join(block)

            xrefs = []
            seen = set()
            for a, b in RE_XREF_SEC.findall(full):
                k = (int(a), int(b))
                if k not in seen:
                    seen.add(k)
                    xrefs.append({"section": k[0], "no": k[1]})
            for b in RE_XREF_LOCAL.findall(full):
                k = (sec_no, int(b))
                if k not in seen:
                    seen.add(k)
                    xrefs.append({"section": k[0], "no": k[1]})

            src_text = fields.get("来源", "")
            links = len(RE_URL.findall(src_text)) + len(RE_URL.findall(note))

            items.append({
                "id": "%d-%d" % (sec_no, no),
                "seq": len(items) + 1,
                "section": sec_no,
                "section_title": sec_title,
                "no": no,
                "title": title,
                "cost_money": cm,
                "cost_time": ct,
                "cost_willpower": cw,
                "benefit_level": lv,
                "metric": metric,
                "cost_score": cost,
                "ratio": ratio,
                "evidence": ev,
                "evidence_raw": raw_ev.strip(),
                "evidence_flags": flags,
                "disputed": note.startswith("争议"),
                "todo": ("待核实" in full) or ("TODO" in full),
                "cost_text": fields.get("成本", ""),
                "plain": fields.get("说人话", ""),
                "benefit_text": fields.get("收益", ""),
                "source_text": src_text,
                "sources": RE_URL.findall(src_text),
                "link_count": links,
                "note": note,
                "refs": xrefs,
                "source_file": fn,
            })

    return items, sections, problems


def git_commit(repo):
    try:
        out = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=20)
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None


def build_stats(items, sections):
    grade = {"A": 0, "B": 0, "C": 0}
    ratio = {"极高": 0, "高": 0, "一般": 0}
    for it in items:
        if it["evidence"] in grade:
            grade[it["evidence"]] += 1
        if it["ratio"] in ratio:
            ratio[it["ratio"]] += 1
    per_section = []
    for s in sections:
        sub = [i for i in items if i["section"] == s["no"]]
        per_section.append({
            "no": s["no"],
            "title": s["title"],
            "entries": len(sub),
            "A": sum(1 for i in sub if i["evidence"] == "A"),
            "B": sum(1 for i in sub if i["evidence"] == "B"),
            "C": sum(1 for i in sub if i["evidence"] == "C"),
            "极高": sum(1 for i in sub if i["ratio"] == "极高"),
            "高": sum(1 for i in sub if i["ratio"] == "高"),
            "一般": sum(1 for i in sub if i["ratio"] == "一般"),
        })
    return {
        "entries": len(items),
        "sections": len(sections),
        "grade": grade,
        "disputed": sum(1 for i in items if i["disputed"]),
        "evidence_flagged": sum(1 for i in items if i["evidence_flags"]),
        "todo": sum(1 for i in items if i["todo"]),
        "links": sum(i["link_count"] for i in items),
        "refs": sum(len(i["refs"]) for i in items),
        "ratio": ratio,
        "per_section": per_section,
    }


CSV_COLS = ["id", "seq", "section", "section_title", "no", "title",
            "cost_money", "cost_time", "cost_willpower", "benefit_level",
            "metric", "cost_score", "ratio", "evidence", "evidence_raw",
            "disputed", "todo", "link_count", "plain", "cost_text",
            "benefit_text", "source_text", "note", "sources", "refs", "source_file"]


def write_outputs(items, sections, stats, meta, out_dir):
    os.makedirs(out_dir, exist_ok=True)

    payload = {"meta": meta, "sections": sections, "items": items}
    with open(os.path.join(out_dir, "htlb.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    with open(os.path.join(out_dir, "htlb.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS, extrasaction="ignore")
        w.writeheader()
        for it in items:
            row = dict(it)
            row["sources"] = " | ".join(it["sources"])
            row["refs"] = " | ".join("%d-%d" % (r["section"], r["no"]) for r in it["refs"])
            row["evidence_flags"] = " | ".join(it["evidence_flags"])
            w.writerow(row)

    db = os.path.join(out_dir, "htlb.sqlite")
    if os.path.exists(db):
        os.remove(db)
    con = sqlite3.connect(db)
    con.execute("""
        CREATE TABLE items (
            id TEXT PRIMARY KEY, seq INTEGER, section INTEGER, section_title TEXT,
            no INTEGER, title TEXT, cost_money TEXT, cost_time TEXT,
            cost_willpower TEXT, benefit_level TEXT, metric TEXT,
            cost_score INTEGER, ratio TEXT, evidence TEXT, evidence_raw TEXT,
            disputed INTEGER, todo INTEGER, link_count INTEGER,
            plain TEXT, cost_text TEXT, benefit_text TEXT, source_text TEXT,
            note TEXT, sources TEXT, refs TEXT, source_file TEXT)
    """)
    con.executemany(
        "INSERT INTO items VALUES (%s)" % ",".join("?" * 26),
        [[
            it["id"], it["seq"], it["section"], it["section_title"], it["no"],
            it["title"], it["cost_money"], it["cost_time"], it["cost_willpower"],
            it["benefit_level"], it["metric"], it["cost_score"], it["ratio"],
            it["evidence"], it["evidence_raw"], int(it["disputed"]), int(it["todo"]),
            it["link_count"], it["plain"], it["cost_text"], it["benefit_text"],
            it["source_text"], it["note"], " | ".join(it["sources"]),
            " | ".join("%d-%d" % (r["section"], r["no"]) for r in it["refs"]),
            it["source_file"],
        ] for it in items])
    con.execute("CREATE INDEX idx_section ON items(section)")
    con.execute("CREATE INDEX idx_evidence ON items(evidence)")
    con.execute("CREATE INDEX idx_ratio ON items(ratio)")
    con.commit()
    con.close()

    with open(os.path.join(out_dir, "stats.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "stats": stats}, f, ensure_ascii=False, indent=1)

    schema = {
        "note": "字段口径与上游 tools/sync-stats.mjs 一致。空值表示上游该条缺对应内容。",
        "fields": {
            "id": "节号-条号，如 23-1",
            "seq": "全书顺序号，1 起",
            "section": "节号", "section_title": "节标题", "no": "节内条号",
            "title": "条目标题",
            "cost_money": "花钱：0 / 少 / 多",
            "cost_time": "花时间：少 / 中 / 多",
            "cost_willpower": "要毅力：否 / 些 / 是",
            "benefit_level": "收益档：小 / 中 / 大",
            "metric": "口径：死亡率 / 金钱 / 时间 / 自由",
            "cost_score": "成本加权分 0-6，权重抄自上游 COST_W",
            "ratio": "性价比：极高 / 高 / 一般，算法抄自上游 e.ratio",
            "evidence": "证据等级首字母 A/B/C",
            "evidence_raw": "证据等级原文，可能带（争议）等后缀",
            "evidence_flags": "证据等级括号内的标记，如 ['争议']",
            "disputed": "备注是否以「争议」开头（上游口径）",
            "todo": "正文是否含「待核实」或 TODO",
            "link_count": "来源+备注行里的 http(s) 数",
            "plain": "说人话", "cost_text": "成本", "benefit_text": "收益",
            "source_text": "来源原文", "sources": "来源里的 URL 列表",
            "note": "备注", "refs": "交叉引用到的 [节号, 条号]",
            "source_file": "出处文件",
        },
    }
    with open(os.path.join(out_dir, "schema.json"), "w", encoding="utf-8") as f:
        json.dump(schema, f, ensure_ascii=False, indent=1)


def main():
    ap = argparse.ArgumentParser(description="解析《高性价比人生指南》为结构化数据")
    ap.add_argument("--repo", default="_upstream", help="上游仓库本地路径")
    ap.add_argument("--out", default="data", help="输出目录")
    ap.add_argument("--check", action="store_true", help="只校验不写文件")
    a = ap.parse_args()

    check_algorithm(a.repo)
    items, sections, problems = parse_book(a.repo)
    stats = build_stats(items, sections)

    meta = {
        "source": UPSTREAM_NAME,
        "source_repo": UPSTREAM_REPO,
        "upstream_commit": git_commit(a.repo),
        "synced_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "license": "CC BY 4.0（正文）",
        "generated_by": "build.py",
    }

    print("[build] 条目 %d ｜ 节 %d ｜ A %d B %d C %d ｜ 争议 %d ｜ 证据带标记 %d ｜ TODO %d ｜ 链接 %d ｜ 交叉引用 %d"
          % (stats["entries"], stats["sections"], stats["grade"]["A"], stats["grade"]["B"],
             stats["grade"]["C"], stats["disputed"], stats["evidence_flagged"],
             stats["todo"], stats["links"], stats["refs"]))
    print("[build] 性价比 极高 %d / 高 %d / 一般 %d"
          % (stats["ratio"]["极高"], stats["ratio"]["高"], stats["ratio"]["一般"]))

    if problems:
        print("[build] 异常 %d 处：" % len(problems))
        for p in problems[:20]:
            print("   - %s" % p)
        if not a.check:
            die("存在解析异常，已中止输出（确认无误后移除该校验）")
    else:
        print("[build] 结构校验通过：全部条目字段齐全")

    if a.check:
        return

    out_dir = a.out if os.path.isabs(a.out) else os.path.join(HERE, a.out)
    write_outputs(items, sections, stats, meta, out_dir)
    print("[build] 已写出 %s/htlb.json htlb.csv htlb.sqlite stats.json schema.json" % out_dir)


if __name__ == "__main__":
    main()

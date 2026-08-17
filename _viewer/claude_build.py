# -*- coding: utf-8 -*-
"""把 Claude 的匯出檔轉成檢視器用的資料。

輸出格式和 build.py（ChatGPT）完全一樣，所以分支切換、分支圖、
全文搜尋、各種匯出都不用改就能用。

兩邊的差異：
  ChatGPT                       Claude
  mapping 字典                  chat_messages 陣列
  parent 欄位                   parent_message_uuid（根是全 0 的 uuid）
  role user/assistant           sender human/assistant
  思考是獨立節點                 思考是同一則訊息裡的 thinking 區塊
  current_node 指出使用中分支     沒有，用時間最新的葉節點推定
"""
import json, os, sys, glob, datetime, collections

import paths

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

ROOT_UUID = "00000000-0000-4000-8000-000000000000"
FT_SHARD_BYTES = 2 * 1024 * 1024

# 這些工具的輸出很長又不是對話內容，收成一行就好
TOOL_LABELS = {
    "artifacts": "Artifact",
    "web_search": "網路搜尋",
    "web_fetch": "讀取網頁",
    "bash_tool": "執行指令",
    "view": "檢視檔案",
    "create_file": "建立檔案",
    "str_replace": "編輯檔案",
    "present_files": "提供檔案",
    "conversation_search": "搜尋對話",
}


def iso_epoch(s):
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def parse_json_field(v):
    """attachments / files 在匯出檔裡是 JSON 字串，不是陣列。"""
    if isinstance(v, list):
        return v
    if isinstance(v, str) and v.strip():
        try:
            return json.loads(v)
        except Exception:
            return []
    return []


def flatten(msg):
    """把一則訊息的 content 區塊攤平成 (內文, 思考, 工具)。"""
    texts, thinks, tools = [], [], []
    for b in msg.get("content") or []:
        t = b.get("type")
        if t == "text":
            if b.get("text"):
                texts.append(b["text"])
        elif t == "thinking":
            if b.get("thinking"):
                thinks.append({"s": "", "c": b["thinking"]})
        elif t == "tool_use":
            inp = b.get("input") or {}
            rec = {"n": TOOL_LABELS.get(b.get("name"), b.get("name") or "工具"),
                   "raw": b.get("name") or ""}
            if b.get("name") == "artifacts":
                rec["title"] = inp.get("title") or inp.get("id") or ""
                rec["lang"] = (inp.get("language")
                               or (inp.get("type") or "").split("/")[-1] or "")
                if inp.get("content"):
                    rec["body"] = inp["content"]
                rec["cmd"] = inp.get("command") or ""
            else:
                # 只留最能看出在做什麼的欄位，不然 tool 輸入會塞爆資料
                for k in ("command", "query", "path", "file_path", "url", "id"):
                    if inp.get(k):
                        rec["arg"] = str(inp[k])[:300]
                        break
            tools.append(rec)
        elif t == "tool_result":
            if tools and not tools[-1].get("err"):
                tools[-1]["err"] = bool(b.get("is_error"))
        # token_budget / flag 不顯示
    # 有些訊息的 text 欄位比 content 完整（舊資料），取比較長的那個
    plain = (msg.get("text") or "").strip()
    joined = "\n\n".join(texts).strip()
    body = plain if len(plain) > len(joined) else joined
    return body, thinks, tools


def build_one(conv):
    msgs = conv.get("chat_messages") or []
    nodes = {"root": {"c": []}}
    kids = collections.defaultdict(list)
    order = {}
    for i, m in enumerate(msgs):
        order[m["uuid"]] = i

    for m in msgs:
        uid = m["uuid"]
        par = m.get("parent_message_uuid") or ROOT_UUID
        if par == ROOT_UUID or par not in order:
            par = "root"
        body, thinks, tools = flatten(m)
        n = {
            "p": par,
            "r": "user" if m.get("sender") == "human" else "assistant",
            "k": "text",
        }
        t = iso_epoch(m.get("created_at"))
        if t:
            n["t"] = t
        if body:
            n["x"] = body
        if thinks:
            n["th"] = thinks
        if tools:
            n["tool"] = tools

        att = []
        for a in parse_json_field(m.get("attachments")):
            rec = {"n": a.get("file_name") or "附件", "f": "",
                   "s": a.get("file_size") or 0,
                   "mt": a.get("file_type") or ""}
            if a.get("extracted_content"):
                rec["x"] = a["extracted_content"]     # 匯出檔有附件的文字內容
            att.append(rec)
        for f in parse_json_field(m.get("files")):
            att.append({"n": f.get("file_name") or "檔案", "f": "", "s": 0, "mt": ""})
        if att:
            n["att"] = att

        nodes[uid] = n
        kids[par].append(uid)

    # 子節點依原始順序（匯出檔本身就是時間序）排好，分支切換才穩定
    for par, ch in kids.items():
        ch.sort(key=lambda x: (order.get(x, 0)))
        nodes[par]["c"] = ch

    # Claude 沒有 current_node，用時間最新的葉節點當使用中的分支
    leaves = [k for k, v in nodes.items() if not v.get("c") and k != "root"]
    cur = max(leaves, key=lambda k: (nodes[k].get("t") or 0, order.get(k, 0)),
              default="root")
    return nodes, cur, leaves


def main():
    out = paths.data_dir()
    srcs = paths.claude_sources()
    if not srcs:
        print("找不到 Claude 的 conversations.json")
        return 1

    # 多份備份：由舊到新讀，同一個對話 uuid 留最後（最新）那版
    convs = {}
    order = []
    for src in srcs:
        print("  讀取 %s…" % os.path.basename(os.path.dirname(src)) or "conversations.json")
        for c in json.load(open(src, encoding="utf-8")):
            u = c.get("uuid")
            if not u:
                continue
            if u not in convs:
                order.append(u)
            convs[u] = c
    convs = [convs[u] for u in order]
    if len(srcs) > 1:
        print("  來源 %d 份備份，去重後 %d 個對話" % (len(srcs), len(convs)))

    os.makedirs(os.path.join(out, "conv"), exist_ok=True)
    os.makedirs(os.path.join(out, "ft"), exist_ok=True)
    for old in (glob.glob(os.path.join(out, "conv", "*.json"))
                + glob.glob(os.path.join(out, "ft", "*.json"))):
        os.remove(old)

    index = []
    ft_buf, ft_size, ft_n = {}, 0, 0

    def flush_ft():
        nonlocal ft_buf, ft_size, ft_n
        if not ft_buf:
            return
        with open(os.path.join(out, "ft", "ft-%03d.json" % ft_n), "w",
                  encoding="utf-8") as fh:
            json.dump(ft_buf, fh, ensure_ascii=False)
        ft_n += 1
        ft_buf, ft_size = {}, 0

    total = 0
    for c in convs:
        cid = c.get("uuid")
        if not cid:
            continue
        nodes, cur, leaves = build_one(c)
        conv = {
            "id": cid,
            "title": c.get("name") or "(無標題)",
            "create_time": iso_epoch(c.get("created_at")),
            "update_time": iso_epoch(c.get("updated_at")),
            "current_node": cur,
            "root": "root",
            "model": "",
            "starred": False,
            "archived": False,
            "service": "claude",
            "nodes": nodes,
        }
        with open(os.path.join(out, "conv", cid + ".json"), "w", encoding="utf-8") as fh:
            json.dump(conv, fh, ensure_ascii=False)

        flat = [n["x"] for n in nodes.values() if n.get("x")]
        nmsg = len(flat)
        maxfan = max((len(v.get("c") or []) for v in nodes.values()), default=0)
        index.append({
            "id": cid,
            "title": conv["title"],
            "pj": None, "gz": None,
            "ct": conv["create_time"],
            "ut": conv["update_time"],
            "n": nmsg,
            "br": len(leaves) or 1,
            "mf": maxfan,
            "st": False, "ar": False,
            "md": [],
            "src": "",
            "svc": "claude",
        })

        body = "\n".join(flat).lower()
        ft_buf[cid] = body
        ft_size += len(body.encode("utf-8"))
        if ft_size > FT_SHARD_BYTES:
            flush_ft()

        total += 1
        if total % 50 == 0:
            print("  已處理 %d 個對話..." % total)

    flush_ft()

    # 專案知識庫：docs 裡是你上傳到專案的檔案，content 就是完整原文。
    # 內容另外存成一個檔一份，知識庫頁面才不用一次載入好幾 MB。
    kdir = os.path.join(out, "kdoc")
    os.makedirs(kdir, exist_ok=True)
    for old in glob.glob(os.path.join(kdir, "*.txt")):
        os.remove(old)
    knowledge = []

    # Claude 的專案有名字，但匯出檔沒有記對話屬於哪個專案，所以只能列出來
    groups = []
    seen = set()
    i = 0
    for src in srcs:
        pdir = os.path.join(os.path.dirname(src), "projects")
        if not os.path.isdir(pdir):
            continue
        for f in sorted(os.listdir(pdir)):
            try:
                p = json.load(open(os.path.join(pdir, f), encoding="utf-8"))
            except Exception:
                continue
            pid = p.get("uuid") or f
            if pid in seen:
                continue
            seen.add(pid)
            i += 1
            docs = p.get("docs") or []
            groups.append({"id": pid, "kind": "project", "no": i,
                           "n": 0, "titles": [], "files": len(docs),
                           "name": p.get("name") or "", "note": p.get("description") or ""})

            items = []
            for d in docs:
                body = d.get("content") or ""
                duid = d.get("uuid") or ("%s-%d" % (pid, len(items)))
                with open(os.path.join(kdir, duid + ".txt"), "w", encoding="utf-8") as fh:
                    fh.write(body)
                items.append({"id": duid, "n": d.get("filename") or "(未命名)",
                              "len": len(body), "ct": d.get("created_at") or ""})
            knowledge.append({
                "id": pid,
                "name": p.get("name") or "(未命名專案)",
                "note": p.get("description") or "",
                "prompt": p.get("prompt_template") or "",
                "ct": p.get("created_at") or "",
                "ut": p.get("updated_at") or "",
                "docs": items,
            })
    with open(os.path.join(out, "groups.json"), "w", encoding="utf-8") as fh:
        json.dump(groups, fh, ensure_ascii=False)
    with open(os.path.join(out, "files.json"), "w", encoding="utf-8") as fh:
        json.dump([], fh)
    with open(os.path.join(out, "knowledge.json"), "w", encoding="utf-8") as fh:
        json.dump(knowledge, fh, ensure_ascii=False)

    index.sort(key=lambda x: x["ut"] or x["ct"] or 0, reverse=True)
    with open(os.path.join(out, "index.json"), "w", encoding="utf-8") as fh:
        json.dump({"convs": index, "ft_shards": ft_n, "service": "claude",
                   "built": __import__("time").time(),
                   "latest": "",
                   "imports": sorted(paths.current_imports())}, fh, ensure_ascii=False)

    branched = sum(1 for c in index if c["br"] > 1)
    nd = sum(len(k["docs"]) for k in knowledge)
    nc = sum(d["len"] for k in knowledge for d in k["docs"])
    print("  專案 %d 個（匯出檔沒有記對話歸屬，只能列出名稱）" % len(groups))
    if nd:
        print("  專案知識庫：%d 個檔案／%s 字" % (nd, format(nc, ",")))
    print("完成：%d 個對話（%d 個有分支），全文分片 %d 個" % (total, branched, ft_n))
    print("輸出目錄：%s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

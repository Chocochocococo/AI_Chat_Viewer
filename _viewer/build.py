# -*- coding: utf-8 -*-
"""把 ChatGPT 匯出檔轉成檢視器用的資料。

讀取上層目錄的 conversations-*.json，輸出到 _viewer/data/：
  index.json      對話清單（標題、時間、訊息數、分支數）
  conv/<id>.json  每個對話的完整節點樹
  ft/ft-###.json  全文搜尋用的純文字分片
"""
import json, glob, os, sys, datetime

import paths

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass


HERE = paths.work_dir()
BASE = paths.export_dir()
OUT = paths.data_dir()

# 全文分片大小（實際位元組）。分片小一點，瀏覽器抓大檔容易中斷，
# 而且進度顯示比較細。
FT_SHARD_BYTES = 2 * 1024 * 1024


def iso_epoch(s):
    """'2026-08-11T08:07:09.251637+00:00' -> epoch 秒；解析不了就回 None"""
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s).timestamp()
    except Exception:
        return None


def text_of(content):
    """把一則訊息的 content 攤平成 (kind, text, thoughts, images)。"""
    ct = (content or {}).get("content_type")
    if ct == "text":
        parts = [p for p in (content.get("parts") or []) if isinstance(p, str)]
        return "text", "\n\n".join(parts), None, None
    if ct == "thoughts":
        th = []
        for t in content.get("thoughts") or []:
            th.append({"s": t.get("summary") or "", "c": t.get("content") or ""})
        return "thoughts", "", th, None
    if ct == "reasoning_recap":
        return "recap", content.get("content") or "", None, None
    if ct == "multimodal_text":
        txt, imgs = [], []
        for p in content.get("parts") or []:
            if isinstance(p, str):
                txt.append(p)
            elif isinstance(p, dict) and p.get("content_type") == "image_asset_pointer":
                ptr = p.get("asset_pointer") or ""
                fid = ptr.rsplit("/", 1)[-1]
                imgs.append({"f": fid, "w": p.get("width"), "h": p.get("height")})
        return "multimodal", "\n\n".join(txt), None, imgs
    # 其他型別（code / execution_output 等）盡量保留原始文字
    raw = content.get("text") or content.get("content") or ""
    return ct or "unknown", raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False), None, None


def main():
    global HERE, BASE, OUT
    HERE, BASE, OUT = paths.work_dir(), paths.export_dir(), paths.data_dir()
    asset_names = {}
    p = paths.meta_file("conversation_asset_file_names.json")
    if p:
        asset_names = json.load(open(p, encoding="utf-8"))
    # file-XXXX -> 實際存在的檔名
    asset_by_id = {}
    for fname in asset_names:
        fid = fname.rsplit(".", 1)[0]
        asset_by_id[fid] = fname
    # 使用者上傳的是 file-XXXX，ChatGPT 產生的是 file_0000XXXX，兩種都要收
    for fname in os.listdir(BASE):
        if fname.startswith("file-") or fname.startswith("file_"):
            asset_by_id.setdefault(fname.rsplit(".", 1)[0], fname)

    # GPT 產生的圖片 / canvas 文件不在 conversations-*.json 裡，
    # 而是記在 library_files.json，用 origination_message_id 接回訊息節點。
    lib_all = []
    p = paths.meta_file("library_files.json")
    if p:
        try:
            lib_all = json.load(open(p, encoding="utf-8"))
        except Exception:
            lib_all = []
    lib_meta = {e["file_id"]: e for e in lib_all if e.get("file_id")}
    lib_by_msg = {}
    lib_by_thread = {}
    for e in lib_all:
        fid = e.get("file_id")
        if not fid:
            continue
        fname = asset_by_id.get(fid)
        if not fname or not os.path.exists(os.path.join(BASE, fname)):
            continue
        rec = {
            "f": fname,
            "n": e.get("file_name") or fname,
            "mt": e.get("mime_type") or "",
            "s": e.get("file_size_bytes") or 0,
            "gen": bool(e.get("image_gen_generation_id")),
        }
        mid = e.get("origination_message_id")
        if mid:
            lib_by_msg.setdefault(mid, []).append(rec)
        # 有些檔案的 origination_message_id 對不上任何節點（大部分是圖片），
        # 但 origination_thread_id 指得出是哪個對話 —— 留著等一下用時間戳補位
        tid = e.get("origination_thread_id")
        if tid:
            r2 = dict(rec)
            r2["ts"] = iso_epoch(e.get("created_at"))
            r2["mid"] = mid
            lib_by_thread.setdefault(tid, []).append(r2)

    os.makedirs(os.path.join(OUT, "conv"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "ft"), exist_ok=True)
    for old in glob.glob(os.path.join(OUT, "conv", "*.json")) + glob.glob(os.path.join(OUT, "ft", "*.json")):
        os.remove(old)

    files = paths.conversation_sources()
    if not files:
        print("找不到 ChatGPT 的 conversations-*.json")
        return 1
    newest = paths.latest_import()
    if len(files) > 1:
        print("  來源：%d 個對話檔（含 %d 次匯入）"
              % (len(files), len(set(os.path.basename(os.path.dirname(f)) for f in files))))

    index = []
    by_id = {}                   # 對話 id -> 在 index 裡的位置（用來去重）
    dup = 0
    used_assets = set()          # 有被對話引用到的檔案 id
    ft_buf, ft_size, ft_n = {}, 0, 0
    ft_map = {}   # conv id -> 分片編號

    def flush_ft():
        nonlocal ft_buf, ft_size, ft_n
        if not ft_buf:
            return
        name = "ft-%03d.json" % ft_n
        with open(os.path.join(OUT, "ft", name), "w", encoding="utf-8") as fh:
            json.dump(ft_buf, fh, ensure_ascii=False)
        ft_n += 1
        ft_buf, ft_size = {}, 0

    total = 0
    for f in files:
        src = os.path.basename(os.path.dirname(f))
        if src == os.path.basename(paths.export_dir()):
            src = ""                      # 舊版擺法，沒有匯入時間戳
        data = json.load(open(f, encoding="utf-8"))
        for c in data:
            cid = c.get("id") or c.get("conversation_id")
            mapping = c.get("mapping") or {}
            nodes = {}
            kids = {}
            root = None
            models = set()
            nmsg = 0
            flat = []

            for k, v in mapping.items():
                par = v.get("parent")
                if par:
                    kids.setdefault(par, []).append(k)
                else:
                    root = root or k

            for k, v in mapping.items():
                msg = v.get("message")
                n = {"p": v.get("parent")}
                if msg:
                    role = (msg.get("author") or {}).get("role")
                    meta = msg.get("metadata") or {}
                    kind, txt, th, imgs = text_of(msg.get("content"))
                    n["r"] = role
                    n["k"] = kind
                    if txt:
                        n["x"] = txt
                    if th:
                        n["th"] = th
                    if imgs:
                        for im in imgs:
                            used_assets.add(im["f"])
                            im["n"] = asset_names.get(asset_by_id.get(im["f"], ""), "")
                            im["f"] = asset_by_id.get(im["f"], im["f"])
                        n["img"] = imgs
                    if msg.get("create_time"):
                        n["t"] = msg["create_time"]
                    ms = meta.get("model_slug")
                    if ms:
                        n["m"] = ms
                        models.add(ms)
                    att = meta.get("attachments")
                    if att:
                        for a in att:
                            if a.get("id"):
                                used_assets.add(a["id"])
                        n["att"] = [{
                            "n": a.get("name"),
                            "f": asset_by_id.get(a.get("id"), ""),
                            "s": a.get("size"),
                            "mt": a.get("mime_type"),
                        } for a in att]
                    out_files = lib_by_msg.get(k)
                    if out_files:
                        n["out"] = out_files
                        for o in out_files:
                            used_assets.add(o["f"].rsplit(".", 1)[0])
                    if kind in ("text", "multimodal") and txt:
                        nmsg += 1
                        flat.append(txt)
                nodes[k] = n

            # 子節點依時間排序，確保分支順序穩定
            for k, ch in kids.items():
                ch.sort(key=lambda x: (nodes.get(x, {}).get("t") or 0, x))
                nodes[k]["c"] = ch

            leaves = [k for k in nodes if not nodes[k].get("c")]
            maxfan = max((len(v.get("c") or []) for v in nodes.values()), default=0)

            conv = {
                "id": cid,
                "title": c.get("title") or "(無標題)",
                "create_time": c.get("create_time"),
                "update_time": c.get("update_time"),
                "current_node": c.get("current_node"),
                "root": root,
                "model": c.get("default_model_slug"),
                "starred": bool(c.get("is_starred")),
                "archived": bool(c.get("is_archived")),
                "nodes": nodes,
            }
            with open(os.path.join(OUT, "conv", cid + ".json"), "w", encoding="utf-8") as fh:
                json.dump(conv, fh, ensure_ascii=False)

            # conversation_template_id：g-p-… 是專案，g-… 是自訂 GPT
            tmpl = c.get("conversation_template_id") or ""
            entry = {
                "id": cid,
                "title": conv["title"],
                "pj": tmpl if tmpl.startswith("g-p-") else None,
                "gz": tmpl if tmpl and not tmpl.startswith("g-p-") else None,
                "ct": conv["create_time"],
                "ut": conv["update_time"],
                "n": nmsg,
                "br": len(leaves),          # 分支（葉節點）數
                "mf": maxfan,               # 單一節點最多分出幾條
                "st": conv["starred"],
                "ar": conv["archived"],
                "md": sorted(models),
                "src": src,
                "svc": "chatgpt",
            }
            # 同一個對話出現在多次匯入時，留 update_time 比較新的那版。
            # files 已經由舊排到新，正常情況直接覆蓋即可。
            if cid in by_id:
                dup += 1
                prev = index[by_id[cid]]
                if (entry["ut"] or 0) >= (prev["ut"] or 0):
                    index[by_id[cid]] = entry
            else:
                by_id[cid] = len(index)
                index.append(entry)

            body = "\n".join(flat).lower()
            ft_buf[cid] = body
            ft_size += len(body.encode("utf-8"))
            ft_map[cid] = ft_n
            if ft_size > FT_SHARD_BYTES:
                flush_ft()

            total += 1
            if total % 200 == 0:
                print("  已處理 %d 個對話..." % total)

    flush_ft()

    # ---- 補位：只知道屬於哪個對話、不知道屬於哪則訊息的檔案 ----
    # ChatGPT 產生的圖片有一部分 origination_message_id 對不上任何節點，
    # 只剩 origination_thread_id。用建立時間找最接近的那則助理訊息掛上去，
    # 並標記成 approx，UI 會註明位置是推定的。
    n_approx = 0
    for cid, cand in lib_by_thread.items():
        path = os.path.join(OUT, "conv", cid + ".json")
        if not os.path.exists(path):
            continue
        conv = json.load(open(path, encoding="utf-8"))
        nodes = conv["nodes"]
        todo = [r for r in cand if r["mid"] not in nodes]
        if not todo:
            continue
        # 助理訊息依時間排序，用來找落點。優先掛在有內文的回覆上；
        # 整則只有 recap（「已思考 N 秒」）的對話才退而求其次用 recap 節點。
        def slots_of(kinds):
            return sorted((n["t"], k) for k, n in nodes.items()
                          if n.get("t") and n.get("r") == "assistant"
                          and n.get("k") in kinds)

        slots = slots_of(("text", "multimodal")) or slots_of(("recap", "thoughts"))
        if not slots:
            continue
        for r in todo:
            ts = r.get("ts")
            if ts is None:
                target = slots[-1][1]
            else:
                # 取「時間 <= 圖片建立時間」裡最晚的那則，都沒有就取第一則
                target = slots[0][1]
                for t, k in slots:
                    if t <= ts + 5:
                        target = k
                    else:
                        break
            rec = {"f": r["f"], "n": r["n"], "mt": r["mt"], "s": r["s"],
                   "gen": r["gen"], "approx": True}
            nodes[target].setdefault("out", []).append(rec)
            used_assets.add(r["f"].rsplit(".", 1)[0])
            n_approx += 1
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(conv, fh, ensure_ascii=False)
    print("  依時間補位的產出檔案：%d 個" % n_approx)

    # ---- 檔案庫：把實際存在的附件 / 圖片列成一份清單 ----
    titles = {c["id"]: c["title"] for c in index}
    files_out = []
    for fname in sorted(os.listdir(BASE)):
        if not (fname.startswith("file-") or fname.startswith("file_")):
            continue
        fid = fname.rsplit(".", 1)[0]
        e = lib_meta.get(fid, {})
        full = os.path.join(BASE, fname)
        cid = e.get("initiating_conversation_id") or e.get("origination_thread_id")
        files_out.append({
            "f": fname,
            "n": asset_names.get(fname) or e.get("file_name") or fname,
            "mt": e.get("mime_type") or "",
            "s": os.path.getsize(full),
            "ct": e.get("created_at") or "",
            "cid": cid if cid in titles else None,
            "cti": titles.get(cid, ""),
            "used": fid in used_assets,
            "gen": bool(e.get("image_gen_generation_id")),
        })
    with open(os.path.join(OUT, "files.json"), "w", encoding="utf-8") as fh:
        json.dump(files_out, fh, ensure_ascii=False)

    # ---- 專案 / 自訂 GPT ----
    # 匯出檔只有 id，沒有專案名稱。使用者可以自己命名，存成 project-names.json
    # 放在 _viewer/ 裡，重跑 build.py 就會寫進來。
    names = {}
    np = paths.names_file()
    if os.path.exists(np):
        try:
            names = json.load(open(np, encoding="utf-8"))
        except Exception:
            names = {}

    groups = {}
    for c in index:
        gid = c["pj"] or c["gz"]
        if not gid:
            continue
        g = groups.setdefault(gid, {"id": gid, "kind": "project" if c["pj"] else "gpt",
                                    "n": 0, "titles": [], "files": 0,
                                    "name": names.get(gid, "")})
        g["n"] += 1
        if len(g["titles"]) < 4:
            g["titles"].append(c["title"])
    for e in lib_all:
        gid = e.get("gizmo_id")
        if gid in groups:
            groups[gid]["files"] += 1
    groups_out = sorted(groups.values(), key=lambda g: (g["kind"] != "project", -g["n"]))
    # 沒命名的給一個穩定的預設編號
    seq = {"project": 0, "gpt": 0}
    for g in groups_out:
        seq[g["kind"]] += 1
        g["no"] = seq[g["kind"]]
    with open(os.path.join(OUT, "groups.json"), "w", encoding="utf-8") as fh:
        json.dump(groups_out, fh, ensure_ascii=False)
    npj = sum(1 for g in groups_out if g["kind"] == "project")
    print("  專案 %d 個（%d 個對話）／自訂 GPT %d 個（%d 個對話）" % (
        npj, sum(g["n"] for g in groups_out if g["kind"] == "project"),
        len(groups_out) - npj, sum(g["n"] for g in groups_out if g["kind"] == "gpt")))

    index.sort(key=lambda x: x["ut"] or x["ct"] or 0, reverse=True)
    with open(os.path.join(OUT, "index.json"), "w", encoding="utf-8") as fh:
        json.dump({"convs": index, "ft_shards": ft_n,
                   "built": __import__("time").time(),
                   "latest": newest,
                   "imports": sorted(paths.current_imports())},
                  fh, ensure_ascii=False)

    if dup:
        print("  跨備份重複的對話 %d 筆，已保留最新版本" % dup)
    only_old = [c for c in index if newest and c.get("src") and c["src"] != newest]
    if only_old:
        print("  只存在於舊備份的對話 %d 筆（可能已在 ChatGPT 上刪除）" % len(only_old))
    print("完成：%d 個對話，全文分片 %d 個" % (len(index), ft_n))
    print("輸出目錄：%s" % OUT)


if __name__ == "__main__":
    main()

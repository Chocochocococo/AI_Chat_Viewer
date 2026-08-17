# -*- coding: utf-8 -*-
"""依資料夾裡有什麼備份，決定要跑哪個轉檔程式。

只有一家 → 直接轉進 data/。
兩家都有 → 各自轉進暫存區，再合併成同一份 data/：
  conv/<id>.json   兩邊的 id 都是 uuid，不會撞
  ft/ft-###.json   重新編號串在一起
  index.json       兩邊的清單接起來，每筆帶 svc 標記來源
"""
import json, os, shutil, sys

import paths

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass


def _run(mod, stage):
    paths.set_data_dir(stage)
    try:
        rc = mod.main()
    finally:
        paths.set_data_dir(None)
    return rc


def _read(stage, name, default):
    p = os.path.join(stage, name)
    if not os.path.exists(p):
        return default
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def merge(stages, out):
    """把幾個暫存區合併成一份 data/。"""
    for sub in ("conv", "ft", "kdoc"):
        d = os.path.join(out, sub)
        if os.path.isdir(d):
            shutil.rmtree(d)
        os.makedirs(d)

    convs, groups, files_all, knowledge = [], [], [], []
    ft_n = 0
    for stage in stages:
        idx = _read(stage, "index.json", {"convs": [], "ft_shards": 0})
        convs += idx.get("convs") or []
        groups += _read(stage, "groups.json", [])
        files_all += _read(stage, "files.json", [])
        knowledge += _read(stage, "knowledge.json", [])

        src_k = os.path.join(stage, "kdoc")
        if os.path.isdir(src_k):
            for f in os.listdir(src_k):
                shutil.move(os.path.join(src_k, f), os.path.join(out, "kdoc", f))

        src_conv = os.path.join(stage, "conv")
        if os.path.isdir(src_conv):
            for f in os.listdir(src_conv):
                shutil.move(os.path.join(src_conv, f), os.path.join(out, "conv", f))
        src_ft = os.path.join(stage, "ft")
        if os.path.isdir(src_ft):
            for f in sorted(os.listdir(src_ft)):
                shutil.move(os.path.join(src_ft, f),
                            os.path.join(out, "ft", "ft-%03d.json" % ft_n))
                ft_n += 1

    convs.sort(key=lambda c: c.get("ut") or c.get("ct") or 0, reverse=True)
    with open(os.path.join(out, "index.json"), "w", encoding="utf-8") as fh:
        json.dump({"convs": convs, "ft_shards": ft_n, "service": "both",
                   "built": __import__("time").time(),
                   "latest": "", "imports": [""]}, fh, ensure_ascii=False)
    with open(os.path.join(out, "groups.json"), "w", encoding="utf-8") as fh:
        json.dump(groups, fh, ensure_ascii=False)
    with open(os.path.join(out, "files.json"), "w", encoding="utf-8") as fh:
        json.dump(files_all, fh, ensure_ascii=False)
    with open(os.path.join(out, "knowledge.json"), "w", encoding="utf-8") as fh:
        json.dump(knowledge, fh, ensure_ascii=False)

    for stage in stages:
        shutil.rmtree(stage, ignore_errors=True)
    return len(convs), ft_n


def main():
    import build
    import claude_build

    svcs = paths.services_present()
    if not svcs:
        print("找不到任何對話資料")
        return 1

    out = paths.data_dir()
    if len(svcs) == 1:
        mod = claude_build if svcs[0] == "claude" else build
        return mod.main()

    print("這個資料夾同時有 ChatGPT 和 Claude 的備份，兩份都會轉。\n")
    stages = []
    for svc, mod in (("chatgpt", build), ("claude", claude_build)):
        stage = os.path.join(out, "_stage_" + svc)
        shutil.rmtree(stage, ignore_errors=True)
        os.makedirs(stage, exist_ok=True)
        print("── %s ──" % ("ChatGPT" if svc == "chatgpt" else "Claude"))
        rc = _run(mod, stage)
        if rc:
            print("  （這一份轉檔沒有成功，跳過）")
            shutil.rmtree(stage, ignore_errors=True)
            continue
        stages.append(stage)
        print()

    if not stages:
        return 1
    n, ft = merge(stages, out)
    print("合併完成：共 %d 個對話，全文分片 %d 個" % (n, ft))
    print("輸出目錄：%s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

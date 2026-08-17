# -*- coding: utf-8 -*-
"""一鍵啟動：需要的話先轉檔，然後開伺服器。

.py 和 exe 兩種模式共用這個進入點。轉檔是直接呼叫 build.main()，
不是另外開一個 python 行程 —— 打包成 exe 之後 sys.executable 就是 exe 本身，
再去 subprocess 它只會無限重開。
"""
import os, sys, json

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

import paths
import importer
import build
import claude_build
import build_all
import serve


def main():
    print("AI 對話備份檢視器")

    # 資料夾裡有沒匯入過的備份 zip 就先解進 export/。
    # 先解再印狀態，不然第一次執行時還看不出裡面有哪幾家的備份。
    try:
        imported = importer.auto_import()
    except Exception as e:
        print("解壓縮失敗：%s" % e)
        imported = False
    if imported:
        print()
    print(paths.describe())
    print()

    has_src = bool(paths.services_present())
    has_data = paths.has_data()
    if not has_src and not has_data:
        print("找不到對話資料。")
        print("請把 ChatGPT 或 Claude 匯出的 zip 放進這個資料夾，再執行一次；")
        print("（或是把 zip 解壓縮後，把這個程式放進解開後的資料夾裡）")
        return 1

    if has_data and not imported:
        # 資料是不是用現在這些匯入建出來的？不是就要重建
        try:
            idx = json.load(open(os.path.join(paths.data_dir(False), "index.json"),
                                 encoding="utf-8"))
            built_from = set(idx.get("imports") or [])
            now = set([""]) if paths.is_legacy_layout() else set(
                os.path.basename(d) for d in
                __import__("glob").glob(os.path.join(paths.imports_dir(), "*")))
            if now and built_from and not now <= built_from:
                print("偵測到新的備份，重新轉檔…")
                print()
                imported = True
        except Exception:
            pass

    if not has_data or imported:
        print("正在轉換備份資料，大約需要 1-3 分鐘…" if has_data
              else "第一次使用，正在轉換備份資料，大約需要 1-3 分鐘…\n")
        try:
            build_all.main()
        except SystemExit as e:
            if e.code:
                return e.code
        except Exception as e:
            print("\n轉檔失敗：%s" % e)
            return 1
        print()

    port = serve._arg_port(8777)
    for _ in range(20):
        rc = serve.serve(port)
        if rc != 2:          # 2 = 連接埠被佔用，換一個再試
            return rc
        port += 1
        print("換用連接埠 %d…" % port)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)

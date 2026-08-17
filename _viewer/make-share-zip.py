# -*- coding: utf-8 -*-
"""打包一份可以分享給別人的檢視器。

白名單只收程式碼，不會放進 data/、project-names.json、settings.json——
那些是使用者自己的對話內容。
"""
import os, sys, zipfile, datetime

HERE = os.path.dirname(os.path.abspath(__file__))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 白名單：只有列在這裡的檔案會被打包
CODE_FILES = [
    "paths.py", "importer.py", "build.py", "claude_build.py", "build_all.py",
    "serve.py", "launch.py",
    "make-share-zip.py", "build-exe.py",
    "index.html", "files.html", "knowledge.html", "export-template.html",
    "core.js", "app.js", "style.css",
    "README.md", "啟動檢視器.cmd", "start.sh",
]

# 有打包好的 exe 就一起帶上（對方連 Python 都不用裝）
EXE = os.path.join("dist", "AI備份檢視器.exe")

README_FOR_SHARING = '# AI 對話備份檢視器\n\n瀏覽 ChatGPT 與 Claude 匯出備份的本機網頁工具，重點是看得到每則訊息的所有分支（重新生成過的回覆、編輯過的提問）。\n\n純本機執行，不連外網，資料不會離開你的電腦。\n\n## 怎麼用\n\n1. 下載你的備份，會收到一封信，裡面有 zip：\n\n   | 服務 | 位置 |\n   |---|---|\n   | ChatGPT | 設定 → 資料控制 → 匯出資料 |\n   | Claude | Settings → Privacy → Export data |\n\n2. 解開這個壓縮檔，把下載到的備份 zip 直接丟進同一個資料夾（不用自己解壓）：\n\n       任意資料夾/\n         AI備份檢視器.exe\n         某某備份.zip\n         _viewer/\n\n3. 雙擊 AI備份檢視器.exe\n\n第一次會自動解壓並轉檔（約 1～3 分鐘，畫面有進度），然後開瀏覽器；之後直接進畫面。備份 zip 解完可以移走，整個資料夾可壓縮帶到別台電腦。\n\n## 幾個重點\n\n| 情況 | 結果 |\n|---|---|\n| 兩家的 zip 放同一個資料夾 | 合併成一份清單，可切換只看某一家 |\n| 之後丟入新的備份 zip | 自動匯入、依對話合併，不會重複 |\n| 對話已在新備份中消失 | 保留舊備份那版，標示「舊備份」 |\n| 已解壓好的匯出資料夾 | 把 _viewer 和 exe 放進去即可 |\n\n## 需要安裝什麼\n\n| 方式 | 需求 |\n|---|---|\n| exe | 什麼都不用裝 |\n| Python | 3.8 以上，不需要 pip install 任何套件 |\n\n用 Python 跑：Windows 雙擊 `_viewer\\啟動檢視器.cmd`，Mac / Linux 執行 `sh start.sh`。\n\nexe 沒有數位簽章，Windows 可能跳「不明發行者」或防毒誤判，這是 PyInstaller 打包的通病。介意的話改用 Python 版，或自己執行 `python build-exe.py` 重新打包。\n\n## 主要功能\n\n- 分支：訊息上方的 `‹ 2/3 ›` 切換版本，右上角「分支圖」看整棵樹\n- 搜尋：搜標題，或全文搜尋所有訊息內容（涵蓋所有分支）\n- 匯出：單一對話存成獨立 HTML、Markdown，或 SillyTavern 的 JSONL\n- 名稱：可把「你 / ChatGPT」換成自訂名字，只改顯示不動原始文本\n- 檔案：GPT檔案庫（圖片與附件）、Claude專案知識庫（專案上傳的檔案）\n- 版面：側欄可收合（左上角 « 或 Ctrl+B），小螢幕預設收起\n\n詳細說明見 `_viewer/README.md`。\n'


def main():
    stamp = datetime.date.today().strftime("%Y%m%d")
    out = os.path.join(os.path.dirname(HERE), "ai-chat-viewer-%s.zip" % stamp)

    missing = [f for f in CODE_FILES if not os.path.exists(os.path.join(HERE, f))]
    included = [f for f in CODE_FILES if os.path.exists(os.path.join(HERE, f))]

    exe_path = os.path.join(HERE, EXE)
    has_exe = os.path.exists(exe_path)

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in included:
            z.write(os.path.join(HERE, f), "_viewer/" + f)
        if has_exe:
            z.write(exe_path, "AI備份檢視器.exe")
        z.writestr("使用說明.md", README_FOR_SHARING)

    print("已產生：%s" % out)
    print("  收錄 %d 個程式檔%s" % (len(included), "，含 exe" if has_exe else "（沒有 exe，先跑 build-exe.py 可以一起打包）"))
    if missing:
        print("  找不到（略過）：%s" % "、".join(missing))
    print()
    print("沒有放進去的東西（都是你自己的資料）：")
    for name, desc in (("data/", "全部對話內容"),
                       ("project-names.json", "你替專案取的名字"),
                       ("settings.json", "顯示名稱設定")):
        p = os.path.join(HERE, name.rstrip("/"))
        if os.path.exists(p):
            print("  - %-20s %s" % (name, desc))
    # 保險起見，掃一遍 zip 裡有沒有混到不該有的東西
    with zipfile.ZipFile(out) as z:
        leaked = [n for n in z.namelist()
                  if "/data/" in n or n.endswith("project-names.json")
                  or n.endswith("settings.json")]
    print()
    print("檢查結果：%s" % ("有東西不該在裡面 → " + str(leaked) if leaked else "乾淨，沒有夾帶對話資料"))


if __name__ == "__main__":
    main()

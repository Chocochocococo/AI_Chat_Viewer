# -*- coding: utf-8 -*-
"""把檢視器打包成單一個 Windows exe，對方就不用裝 Python。

需要先安裝 PyInstaller：

    python -m pip install pyinstaller

然後：

    python build-exe.py

產出 dist/AI備份檢視器.exe，把它放進 ChatGPT 匯出檔的資料夾裡雙擊即可。
前端檔案（html/js/css）會被塞進 exe 內部，轉出來的 data/ 則寫在 exe 旁邊的
_viewer/ 資料夾，所以 exe 版和 .py 版可以共用同一份資料。
"""
import os, sys, shutil, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "AI備份檢視器"

# 要打包進 exe 的前端檔案
ASSETS = ["index.html", "files.html", "knowledge.html", "export-template.html",
          "core.js", "app.js", "style.css"]

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main():
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("找不到 PyInstaller，請先執行：")
        print("    python -m pip install pyinstaller")
        return 1

    missing = [a for a in ASSETS if not os.path.exists(os.path.join(HERE, a))]
    if missing:
        print("缺少檔案：%s" % "、".join(missing))
        return 1

    cmd = [sys.executable, "-m", "PyInstaller",
           "--onefile", "--console", "--clean", "--noconfirm",
           "--name", NAME,
           "--distpath", os.path.join(HERE, "dist"),
           "--workpath", os.path.join(HERE, "build_tmp"),
           "--specpath", os.path.join(HERE, "build_tmp")]
    for a in ASSETS:
        # PyInstaller 的分隔符號在 Windows 是 ;，其他平台是 :
        cmd += ["--add-data", "%s%s." % (os.path.join(HERE, a), os.pathsep)]
    # 排除用不到的大套件讓 exe 小一點。
    # 注意 email / xml / ssl 不能排除：http.server 會用到 email，
    # 排掉會變成 exe 一啟動就 ModuleNotFoundError。
    for mod in ("tkinter", "unittest", "doctest", "pydoc", "lib2to3",
                "sqlite3", "multiprocessing", "pdb"):
        cmd += ["--exclude-module", mod]
    for m in ("build", "claude_build", "build_all", "importer", "paths", "serve"):
        cmd += ["--hidden-import", m]
    cmd.append(os.path.join(HERE, "launch.py"))

    print("開始打包…（第一次會比較久）\n")
    r = subprocess.run(cmd)
    if r.returncode != 0:
        print("\n打包失敗")
        return r.returncode

    exe = os.path.join(HERE, "dist", NAME + ".exe")
    if not os.path.exists(exe):
        print("\n找不到產出的 exe")
        return 1
    size = os.path.getsize(exe) / 1048576
    print("\n完成：%s（%.1f MB）" % (exe, size))
    print("把它複製到備份資料夾裡雙擊即可。")

    # 清掉中間檔
    shutil.rmtree(os.path.join(HERE, "build_tmp"), ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

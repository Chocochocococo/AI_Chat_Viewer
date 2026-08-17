# -*- coding: utf-8 -*-
"""路徑解析。程式要能用兩種方式跑、資料夾也有兩種擺法。

執行方式：
  .py  —— 程式碼在 <app>/_viewer/
  exe  —— html/js/css 打包在 exe 內部（PyInstaller 解壓到暫存目錄）

資料夾擺法：
  新版（自帶）  <app>/export/ 放匯出檔，整個 <app> 資料夾可以直接搬走
      ChatGPT_viewer/
        ChatGPT檢視器.exe
        某某備份.zip          ← 丟進來就會自動匯入
        export/               ← 解出來的匯出檔
          file-*.dat  file_*.dat  library_files.json …
          _imports/<時間戳>/conversations-*.json
        _viewer/
          (程式碼) data/ project-names.json imported.json

  舊版（相容）  匯出檔和 _viewer/ 平放在同一層
      你的匯出資料夾/
        conversations-*.json  file-*.dat …
        _viewer/

三種目錄要分清楚：
  asset_dir()   html / js / css —— exe 模式下在暫存目錄，不能寫入
  export_dir()  file-*.dat 之類的附件所在位置
  work_dir()    data/、project-names.json —— 一定要可寫、可保留
"""
import os, sys, glob

IMPORTS = "_imports"


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def asset_dir():
    if is_frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    return os.path.dirname(os.path.abspath(__file__))


def app_dir():
    """使用者實際操作的資料夾：exe 所在處，或 _viewer/ 的上一層。"""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _has_conv(d):
    return bool(glob.glob(os.path.join(d, "conversations-*.json")))


def _has_claude(d):
    """Claude 的匯出：單一個 conversations.json，每筆帶 chat_messages。"""
    p = os.path.join(d, "conversations.json")
    if not os.path.exists(p):
        return False
    try:
        with open(p, encoding="utf-8") as fh:
            head = fh.read(4000)
        return '"chat_messages"' in head or '"parent_message_uuid"' in head
    except Exception:
        return False


def claude_sources():
    """所有 Claude 的 conversations.json，由舊到新排序。"""
    out = []
    app = app_dir()
    for d in (app, os.path.join(app, "export")):
        p = os.path.join(d, "conversations.json")
        if _has_claude(d) and p not in out:
            out.append(p)
    for d in sorted(glob.glob(os.path.join(export_dir(), IMPORTS, "*"))):
        p = os.path.join(d, "conversations.json")
        if os.path.exists(p) and p not in out:
            out.append(p)
    return out


def services_present():
    """這個資料夾裡有哪幾家的備份。"""
    out = []
    if conversation_sources():
        out.append("chatgpt")
    if claude_sources():
        out.append("claude")
    return out


def service():
    """單一來源時回傳那一家；兩家都有時回傳 'both'。"""
    svcs = services_present()
    if len(svcs) > 1:
        return "both"
    return svcs[0] if svcs else "chatgpt"


def _has_imports(d):
    return bool(glob.glob(os.path.join(d, IMPORTS, "*", "conversations-*.json")))


def is_legacy_layout():
    """匯出檔直接放在 app 資料夾裡（我們最早的擺法）。"""
    app = app_dir()
    if _has_conv(app) or _has_claude(app):
        return True
    # 已經轉過檔、原始 json 被刪掉的情況
    return (os.path.exists(os.path.join(app, "_viewer", "data", "index.json"))
            and not os.path.isdir(os.path.join(app, "export")))


def export_dir(create=False):
    app = app_dir()
    if is_legacy_layout():
        return app
    d = os.path.join(app, "export")
    if create:
        os.makedirs(d, exist_ok=True)
    return d


def imports_dir(create=False):
    d = os.path.join(export_dir(create), IMPORTS)
    if create:
        os.makedirs(d, exist_ok=True)
    return d


def conversation_sources():
    """所有 conversations-*.json，由舊到新排序。

    轉檔時後面的會蓋掉前面的，所以同一個對話會留下最新那一版。
    """
    exp = export_dir()
    out = sorted(glob.glob(os.path.join(exp, "conversations-*.json")))   # 舊版擺法
    for d in sorted(glob.glob(os.path.join(exp, IMPORTS, "*"))):         # 時間戳排序
        out += sorted(glob.glob(os.path.join(d, "conversations-*.json")))
    return out


def latest_import():
    """最新一次 ChatGPT 匯入的時間戳。

    只看含 conversations-*.json 的資料夾 —— 混放時 Claude 的匯入資料夾
    可能排在後面，拿它當「最新」會把整批 ChatGPT 對話誤標成「舊備份」。
    """
    ds = [d for d in sorted(glob.glob(os.path.join(export_dir(), IMPORTS, "*")))
          if glob.glob(os.path.join(d, "conversations-*.json"))]
    return os.path.basename(ds[-1]) if ds else ""


def current_imports():
    """目前實際存在的匯入批次名稱。

    轉檔程式把這組寫進 index.json，啟動時再拿來比對：一樣就不用重轉。
    三個轉檔程式都用同一個函式，避免各寫各的而對不上、每次都重轉。
    """
    if is_legacy_layout():
        return {""}
    return {os.path.basename(d)
            for d in glob.glob(os.path.join(imports_dir(), "*")) if os.path.isdir(d)}


def meta_file(name):
    """library_files.json 之類的：優先用最新一次匯入的，再退回 export/ 根目錄。"""
    exp = export_dir()
    for d in sorted(glob.glob(os.path.join(exp, IMPORTS, "*")), reverse=True):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    p = os.path.join(exp, name)
    return p if os.path.exists(p) else None


def work_dir(create=True):
    w = os.path.join(app_dir(), "_viewer")
    if create:
        os.makedirs(w, exist_ok=True)
    return w


_DATA_OVERRIDE = None


def set_data_dir(p):
    """讓轉檔程式先寫進暫存區，之後再合併成一份 data/。"""
    global _DATA_OVERRIDE
    _DATA_OVERRIDE = p


def data_dir(create=True):
    d = _DATA_OVERRIDE or os.path.join(work_dir(create), "data")
    if create:
        os.makedirs(d, exist_ok=True)
    return d


def names_file():
    return os.path.join(work_dir(), "project-names.json")


def imported_file():
    return os.path.join(work_dir(), "imported.json")


def has_data():
    return os.path.exists(os.path.join(data_dir(create=False), "index.json"))


def describe():
    svc = service()
    n = len(conversation_sources()) + len(claude_sources())
    return ("模式：%s／%s／%s 備份\n  資料夾：%s\n  匯出檔：%s（%d 個對話檔）\n  產生的資料：%s"
            % ("exe" if is_frozen() else "python 腳本",
               "舊版擺法" if is_legacy_layout() else "自帶資料夾",
               {"claude": "Claude", "both": "ChatGPT + Claude"}.get(svc, "ChatGPT"),
               app_dir(), export_dir(), n, data_dir(create=False)))

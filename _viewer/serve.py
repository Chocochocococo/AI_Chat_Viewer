# -*- coding: utf-8 -*-
"""啟動本機伺服器並開啟檢視器。

從匯出資料夾根目錄提供檔案，所以 file-XXXX.dat 附件可以直接被網頁讀到。
.dat 檔會依檔頭判斷真正的類型（png/jpeg/pdf/...），讓圖片能正常顯示。
"""
import http.server, socketserver, os, sys, json, webbrowser, threading

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

import paths

ASSETS = paths.asset_dir()      # html/js/css（exe 模式下唯讀）
ROOT = paths.export_dir()       # conversations-*.json、file-*.dat
WORK = paths.work_dir()         # data/、project-names.json
HERE = WORK                     # 相容舊名稱
def _arg_port(default=8777):
    for a in sys.argv[1:]:
        if a.isdigit():
            return int(a)
    return default


PORT = _arg_port()

# 這些是使用者資料，永遠從 work_dir 讀寫，不能跟打包在 exe 裡的程式檔混在一起
USER_DATA = {"settings.json", "project-names.json", "imported.json"}

MAGIC = [
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"%PDF-", "application/pdf"),
    (b"PK\x03\x04", "application/zip"),
    (b"RIFF", "image/webp"),
]


class Handler(http.server.SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    # HTTP/1.1 會保持連線，閒置的連線不設 timeout 會一直佔著執行緒
    timeout = 60

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def translate_path(self, path):
        """一個 URL 空間對應三個實體目錄。

        /_viewer/data/...          -> WORK/data      （轉出來的資料）
        /_viewer/project-names.json-> WORK           （使用者取的名字）
        /_viewer/<其他>            -> ASSETS         （打包進 exe 的前端檔案）
        /<其他>                    -> ROOT           （匯出檔與附件）
        """
        clean = path.split("?", 1)[0].split("#", 1)[0]
        if clean.startswith("/_viewer/"):
            rel = clean[len("/_viewer/"):]
            safe = []
            for part in rel.split("/"):
                if part in ("", ".", "..") or os.sep in part or (os.altsep and os.altsep in part):
                    continue
                safe.append(part)
            if not safe:
                return os.path.join(ASSETS, "index.html")
            # 使用者資料一律在 WORK。exe 模式下 ASSETS 是 exe 內部解壓出來的
            # 唯讀暫存目錄，把設定檔導去那裡就會永遠讀不到自己寫的東西。
            if safe[0] in USER_DATA or safe[0] == "data":
                return os.path.join(WORK, *safe)
            hit = os.path.join(ASSETS, *safe)
            if os.path.exists(hit):
                return hit
            return os.path.join(WORK, *safe)      # .py 模式下兩者是同一個資料夾
        return super().translate_path(path)

    def guess_type(self, path):
        if path.lower().endswith(".dat"):
            try:
                with open(path, "rb") as fh:
                    head = fh.read(16)
                for sig, mime in MAGIC:
                    if head.startswith(sig):
                        if mime == "image/webp" and head[8:12] != b"WEBP":
                            continue
                        return mime
                head.decode("utf-8")
                return "text/plain; charset=utf-8"
            except Exception:
                pass
            return "application/octet-stream"
        t = super().guess_type(path)
        if t == "application/json":
            return "application/json; charset=utf-8"
        return t

    # 只有這幾個路徑可以寫檔，各自對應一個固定的檔名
    WRITABLE = {
        "/_viewer/api/project-names": "project-names.json",
        "/_viewer/api/settings": "settings.json",
    }

    def do_POST(self):
        """把設定寫成檔案。

        存成檔案而不是只放在瀏覽器 localStorage，這樣換連接埠、
        清瀏覽器資料、甚至日後重新匯出備份都不會弄丟。
        """
        target = self.WRITABLE.get(self.path.split("?")[0])
        if not target:
            self.send_error(404)
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > 1_000_000:
                raise ValueError("body 大小不合理")
            data = json.loads(self.rfile.read(n).decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("格式必須是物件")
            if target == "project-names.json":
                if not all(isinstance(k, str) and isinstance(v, str)
                           for k, v in data.items()):
                    raise ValueError("格式必須是 {id: 名稱}")
                clean = {k: v for k, v in data.items() if v.strip()}
            else:
                clean = data
            path = os.path.join(paths.work_dir(), target)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(clean, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception as e:
            self.send_error(400, str(e))
            return
        body = json.dumps({"ok": True, "n": len(clean)}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        # 改過的 js/css/資料要馬上生效，不然瀏覽器會拿舊的快取。
        # no-cache 是「每次回來驗證」，沒改的檔案照樣回 304，不會變慢。
        p = self.path.split("?")[0].lower()
        if not p.endswith(".dat"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve(port=PORT, open_browser=True):
    """回傳 0 表示正常結束，2 表示連接埠不能用（呼叫端可以換一個再試）。"""
    if not os.path.exists(os.path.join(paths.data_dir(create=False), "index.json")):
        print("尚未建立資料，請先執行 build.py")
        return 1
    url = "http://127.0.0.1:%d/_viewer/index.html" % port
    try:
        httpd = Server(("127.0.0.1", port), Handler)
    except OSError as e:
        print("連接埠 %d 無法使用（%s）" % (port, e))
        return 2
    with httpd:
        print("檢視器已啟動")
        print("  " + url)
        print("  按 Ctrl+C 結束")
        if open_browser:
            threading.Timer(0.8, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print('\n已結束')
    return 0


if __name__ == "__main__":
    sys.exit(serve(PORT))

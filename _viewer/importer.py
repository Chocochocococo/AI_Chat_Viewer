# -*- coding: utf-8 -*-
"""把 ChatGPT 匯出的 zip 解進 export/。

規則：
  conversations-*.json  每次匯入各自放在 _imports/<時間戳>/ 底下。
      不是覆蓋 —— 新舊備份的分片數可能不一樣，直接覆蓋會殘留舊分片造成
      對話重複；整組刪掉又會弄丟「你已經在 ChatGPT 刪掉、但舊備份還有」
      的對話。分開存，轉檔時再用對話 id 去重取最新的那版。
  file-*.dat / file_*.dat  直接解到 export/，同名同大小就跳過。
      不同次匯出的附件不完全一樣，全部留下來才是最完整的。
  其他 json（library_files.json 等）兩邊都放一份，讀取時以最新的為準。

匯入過的 zip 記在 _viewer/imported.json，不會重複解。
"""
import os, re, json, glob, zipfile, datetime, shutil

import paths

CONV_RE = re.compile(r"(^|/)conversations-\d+\.json$")        # ChatGPT
CLAUDE_RE = re.compile(r"(^|/)conversations\.json$")           # Claude


def _load_record():
    p = paths.imported_file()
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_record(rec):
    with open(paths.imported_file(), "w", encoding="utf-8") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=2)


def _key(path):
    st = os.stat(path)
    return "%s|%d" % (os.path.basename(path), st.st_size)


def zip_kind(zpath):
    """這個 zip 是誰的備份：'chatgpt'、'claude'，或 None（不是備份）。"""
    try:
        with zipfile.ZipFile(zpath) as z:
            names = z.namelist()
            if any(CONV_RE.search(n) for n in names):
                return "chatgpt"
            for n in names:
                if CLAUDE_RE.search(n):
                    # Claude 的 conversations.json 才有 chat_messages
                    with z.open(n) as fh:
                        head = fh.read(4000).decode("utf-8", "replace")
                    if '"chat_messages"' in head or '"parent_message_uuid"' in head:
                        return "claude"
    except Exception:
        pass
    return None


def looks_like_export(zpath):
    return zip_kind(zpath) is not None


def find_zips(folder):
    """資料夾裡看起來像 ChatGPT 匯出的 zip。"""
    out = []
    for f in sorted(os.listdir(folder)):
        if not f.lower().endswith(".zip"):
            continue
        p = os.path.join(folder, f)
        if os.path.isfile(p) and looks_like_export(p):
            out.append(p)
    return out


def _stamp_from(zpath):
    """優先用檔名裡的日期（ChatGPT 的檔名帶時間），否則用檔案時間。"""
    m = re.search(r"(20\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})",
                  os.path.basename(zpath))
    if m:
        return "%s%s%s-%s%s%s" % m.groups()
    t = datetime.datetime.fromtimestamp(os.path.getmtime(zpath))
    return t.strftime("%Y%m%d-%H%M%S")


def _unique_stamp(base, taken):
    """兩個 zip 可能算出同一個時間戳（檔名沒日期、又同一秒複製進來的）。
    共用同一個 _imports 資料夾會讓後解的蓋掉先解的分片，對話會憑空消失，
    所以撞到就加序號。"""
    imports = paths.imports_dir(create=True)
    s, i = base, 2
    while s in taken or os.path.isdir(os.path.join(imports, s)):
        s = "%s-%d" % (base, i)
        i += 1
    return s


def import_zip(zpath, log=print, taken=()):
    """解一個 zip 進 export/，回傳 (新增檔案數, 跳過數, 時間戳)。"""
    exp = paths.export_dir(create=True)
    kind = zip_kind(zpath) or "chatgpt"
    base = _stamp_from(zpath)
    if kind == "claude":
        base += "-claude"     # 資料夾名字就看得出是誰的備份
    stamp = _unique_stamp(base, set(taken))
    conv_dir = os.path.join(paths.imports_dir(create=True), stamp)
    os.makedirs(conv_dir, exist_ok=True)

    added = skipped = 0
    with zipfile.ZipFile(zpath) as z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        total = len(infos)
        for n, info in enumerate(infos, 1):
            name = os.path.basename(info.filename)
            if not name:
                continue
            if kind == "claude":
                # Claude 的匯出全是 json，整份放進這次匯入的資料夾，
                # 保留 projects/ 的子目錄結構
                rel = info.filename.lstrip("/")
                if rel.startswith("projects/"):
                    targets = [os.path.join(conv_dir, "projects", name)]
                else:
                    targets = [os.path.join(conv_dir, name)]
                is_conv = True          # 不做「同名同大小就跳過」，每份備份各留各的
            else:
                is_conv = bool(CONV_RE.search(info.filename))
                # conversations 每次分開放；其他中繼資料兩邊都放一份
                targets = [os.path.join(conv_dir, name)] if is_conv else [os.path.join(exp, name)]
                if not is_conv and info.filename.lower().endswith(".json"):
                    targets.append(os.path.join(conv_dir, name))

            for dst in targets:
                if (os.path.exists(dst) and os.path.getsize(dst) == info.file_size
                        and not is_conv):
                    skipped += 1
                    continue
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with z.open(info) as src, open(dst, "wb") as out:
                    shutil.copyfileobj(src, out, 1024 * 256)
                added += 1
            if n % 200 == 0 or n == total:
                log("    解壓中… %d/%d" % (n, total))
    return added, skipped, stamp


def auto_import(log=print):
    """把 app 資料夾裡沒匯入過的 zip 都解進來。回傳有沒有新東西。"""
    folder = paths.app_dir()

    # 舊版擺法（匯出檔已經解壓在同一層）就不要自動匯入。
    # 那裡放的 zip 通常就是旁邊這些檔案的原始封存，解進來只會把
    # conversations-*.json 再複製一份，白白多佔一倍空間。
    if paths.is_legacy_layout() and (
            glob.glob(os.path.join(folder, "conversations-*.json"))
            or os.path.exists(os.path.join(folder, "conversations.json"))):
        if find_zips(folder):
            log("（偵測到 zip，但這個資料夾已經有解壓好的匯出檔，略過自動匯入）")
        return False

    zips = find_zips(folder)
    if not zips:
        return False

    rec = _load_record()
    changed = False
    for zp in zips:
        k = _key(zp)
        if k in rec:
            continue
        kind = zip_kind(zp) or "chatgpt"
        log("發現 %s 備份壓縮檔：%s（%.2f GB）"
            % ("Claude" if kind == "claude" else "ChatGPT",
               os.path.basename(zp), os.path.getsize(zp) / 1073741824))
        log("  正在解壓縮到 export/…（只需要做一次）")
        taken = {v.get("stamp") for v in rec.values() if v.get("stamp")}
        added, skipped, stamp = import_zip(zp, log=log, taken=taken)
        rec[k] = {"file": os.path.basename(zp), "stamp": stamp,
                  "added": added, "skipped": skipped,
                  "when": datetime.datetime.now().isoformat(timespec="seconds")}
        _save_record(rec)
        log("  完成：新增 %d 個檔案，跳過 %d 個已存在的" % (added, skipped))
        log("  這個 zip 已經解完，之後可以移走或刪掉。")
        changed = True
    return changed

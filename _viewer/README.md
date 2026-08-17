# AI 對話備份檢視器

瀏覽 ChatGPT 與 Claude 匯出備份的本機網頁工具。重點是看得到每則訊息的所有分支——你重新生成過的回覆、編輯過的提問，官方的 `chat.html` 都不會顯示，Claude 的匯出更是完全沒附檢視工具。

純本機執行，不連外網，資料不會離開這台電腦。

## 使用方式

開一個資料夾，把 `AI備份檢視器.exe` 和下載的備份 zip 丟進去，雙擊 exe。不用自己解壓縮。

```
任意資料夾/
  AI備份檢視器.exe
  某某備份.zip          ← 丟進來就會自動匯入（解完可移走）
  export/               ← 自動解出來的匯出檔
  _viewer/              ← 程式碼、data/、設定
```

- 第一次會轉檔（約 1～3 分鐘），完成後自動開瀏覽器
- 整個資料夾可以直接壓縮帶走
- 用 Python 跑：Windows 雙擊 `_viewer\啟動檢視器.cmd`，Mac / Linux 執行 `sh start.sh`，或 `python launch.py`
- 已解壓好的匯出資料夾也支援：把 `_viewer` 放進去（和 `conversations*.json` 同一層）

## 支援的備份

| | ChatGPT | Claude |
|---|---|---|
| 來源檔 | `conversations-*.json` | `conversations.json` |
| 分支 | 支援 | 支援 |
| 圖片 / 附件 | 有實體檔案 | 匯出檔沒有檔案本體 |
| 專案 | 只有 id，名稱要自己補 | 有名稱，但對不上對話 |
| 專案知識庫 | 無 | 有，含完整原文 |

兩家的 zip 可以放在同一個資料夾，會合併成一份清單，側欄可切換只看某一家。全文搜尋一次搜完兩家，助理名稱與匯出格式跟著每個對話自己的來源走。

## 多份備份

同一個資料夾丟入多份備份 zip（不論新舊、不論哪一家）都可以：

- 依對話 id 去重，保留 `update_time` 最新的那版
- 只存在於舊備份的對話會保留下來，並標示「舊備份」
- 附件取所有備份的聯集，越留越完整
- 匯入過的 zip 記在 `_viewer/imported.json`，不會重複解

## 功能

分支

- 訊息上方的 `‹ 2/3 ›` 切換版本，切到非預設版本時變橘色
- 右上角「分支圖」看整棵樹，`⑂3` 表示分岔點，點任一節點跳到經過它的路徑
- 節點多時自動勾「只看目前路徑」，有多版本的訊息可點開「▸ 其他 N 個版本」
- 切換分支後畫面停在原位，不會跳走

搜尋

- 直接打字搜標題；按 Enter 或「全文」搜所有訊息內容
- 全文搜尋涵蓋所有分支，點結果會切到含關鍵字的那條分支並標記

匯出

| 格式 | 內容 |
|---|---|
| HTML | 單一對話存成獨立檔案，含整棵分支樹，圖片內嵌，可單獨帶走 |
| Markdown | 目前顯示的那條路徑 |
| JSONL | SillyTavern 格式，多版本收成 swipes，`swipe_id` 指向目前這版 |

顯示名稱

- 「✎ 名稱」可把「你 / ChatGPT」換成自訂名字，只改顯示與匯出，原始文本不動
- 每個對話各記一組，也可設為所有對話的預設
- 存在 `_viewer/settings.json`，重開程式或清瀏覽器資料都不會不見

檔案

- GPT檔案庫：ChatGPT 備份裡的所有檔案，可依類型篩選、連回來源對話
- Claude專案知識庫：專案上傳的檔案，完整原文可展開，可搜檔名與內容
- 兩頁的頂端列都釘住，捲到哪都能用搜尋與篩選
- 側欄只顯示這份備份實際有的入口

其他

- 側欄可收合（左上角 « 或 Ctrl+B），視窗小於 900px 時預設收起，狀態會記住
- 思考過程、Claude 的 Artifact 與工具呼叫收在可展開區塊
- 深色 / 淺色跟隨系統
- 快捷鍵：`/` 搜尋、`Ctrl+B` 收合側欄、`Esc` 關分支圖

## 匯出檔的已知缺漏

ChatGPT

- 產生的圖片不在對話檔裡，記在 `library_files.json`，本工具會接回對應訊息（官方 `chat.html` 不顯示）
- 附件不齊全，找不到檔案的顯示成灰色虛線標籤
- 專案沒有名稱，只有 id。自己命名後存進 `project-names.json`，id 不隨匯出改變，重新匯出後會自動接回

Claude

- 沒有任何檔案本體。附件只有抽出的純文字，`files` 只有檔名
- 專案與對話之間沒有關聯欄位，無法分類
- 沒有 `current_node`，使用中的分支以時間最新的葉節點推定

共通

- 數學公式維持原文顯示，沒有排版成數學符號

## 轉檔後原始檔還要留著嗎

轉檔只把文字寫進 `data/`，圖片和附件每次顯示都是即時從 `export/` 讀。

| 檔案 | 是否要留 |
|---|---|
| `file-*` / `file_*` | 要，全部的圖片和附件 |
| `_viewer/data/` | 要 |
| `conversations*.json`、`library_files.json` | 看的時候不用，重新轉檔要用 |
| `chat.html` | 用不到，可刪 |
| 匯入完的 zip | 可移到別處封存 |

刪掉來源 json 後檢視器照樣能開，但無法重新轉檔。

## 分享給別人

```bash
python make-share-zip.py
```

在上層資料夾產生 `ai-chat-viewer-<日期>.zip`。白名單只收程式碼，不會放進 `data/`、`project-names.json`、`settings.json`，打包完會再掃一次確認。

不要直接壓縮整個 `_viewer` 資料夾，`data/` 在裡面，等於把聊天紀錄送出去。

打包成 exe：

```bash
python -m pip install pyinstaller
python build-exe.py
```

產出 `dist/AI備份檢視器.exe`（約 8 MB）。前端檔案打包在 exe 內部，`data/` 寫在 exe 旁邊，所以 exe 版和 Python 版共用同一份資料。

## 檔案結構

```
_viewer/
  啟動檢視器.cmd   Windows 一鍵啟動（純 ASCII，中文訊息交給 launch.py 印）
  start.sh         Mac / Linux 啟動
  launch.py        匯入 zip → 需要時轉檔 → 開伺服器
  paths.py         路徑解析（Python/exe 兩種執行方式、兩種資料夾擺法）
  importer.py      把備份 zip 解進 export/
  build.py         轉 ChatGPT 的備份
  claude_build.py  轉 Claude 的備份
  build_all.py     判斷有哪幾家，必要時合併
  serve.py         本機伺服器
  index.html       主畫面
  files.html       GPT檔案庫
  knowledge.html   Claude專案知識庫
  core.js          Markdown、樹走訪、訊息與分支圖（主畫面與匯出單檔共用）
  app.js           主畫面邏輯
  export-template.html  匯出單檔 HTML 的模板
  style.css
  build-exe.py     打包成單一 exe
  make-share-zip.py 打包可分享的版本
  project-names.json  專案名稱，不要刪
  settings.json    顯示名稱等設定
  data/            轉出來的資料，可刪除後重建
```

## 改了程式卻沒生效

`index.html` 引用 js / css 時帶了版本參數（`core.js?v=…`），改完程式要一起換掉版本字串，瀏覽器才會重抓。`serve.py` 也送 `Cache-Control: no-cache`，但只對之後才進快取的檔案有效，更早的仍需靠版本參數或 Ctrl+Shift+R。

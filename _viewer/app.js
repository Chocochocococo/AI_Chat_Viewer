/* ChatGPT 備份檢視器 —— 純前端，無外部相依。共用邏輯在 core.js */
'use strict';

const $ = s => document.querySelector(s);

const state = {
  index: [],          // 對話清單
  view: [],           // 目前顯示的清單
  conv: null,         // 開啟中的對話
  path: [],           // 目前路徑（root → leaf）
  defaultPath: [],    // ChatGPT 原本的路徑（依 current_node）
  highlight: '',
  ftShards: 0,
  mode: 'title',      // title | full
  query: '',
  hits: null,         // 全文搜尋命中 [{id, snips, count}]
  latest: '',         // 最新一次匯入的時間戳
  multiImport: false, // 是否匯入過多份備份
  groups: [],         // 專案 / 自訂 GPT
  names: {},          // 專案 id -> 自訂名稱
  settings: {},       // 顯示名稱等設定（存成 _viewer/settings.json）
  treeExpanded: new Set(),  // 分支圖「只看目前路徑」模式下展開的節點
  service: 'chatgpt',  // 這份備份是 chatgpt 還是 claude
};

/* 助理的預設顯示名稱，跟著備份來源走 */
const svcName = (svc) => ((svc || convSvc()) === 'claude' ? 'Claude' : 'ChatGPT');

/* 目前這個對話屬於哪一家。混放時看 index 每筆的 svc，否則看整份備份 */
function convSvc(id) {
  const cid = id || (state.conv && state.conv.id);
  const it = cid && state.index.find(c => c.id === cid);
  return (it && it.svc) || (state.service === 'both' ? 'chatgpt' : state.service);
}

/* ===================== 顯示名稱 =====================
   把「你 / ChatGPT」換成自訂的名字。只改顯示與匯出，原始文本完全不動。
   設定分兩層：全域預設，加上每個對話各自的覆寫（角色扮演每室不同人）。*/
const SET_URL = 'settings.json';
const SET_API = 'api/settings';

async function initSettings() {
  try {
    const r = await fetch(SET_URL + '?t=' + Date.now());
    if (r.ok) state.settings = await r.json();
  } catch (e) { /* 還沒有設定檔很正常 */ }
  if (!state.settings || typeof state.settings !== 'object') state.settings = {};
  state.settings.names = state.settings.names || {};
}

async function saveSettings() {
  try {
    const r = await fetch(SET_API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(state.settings),
    });
    return r.ok;
  } catch (e) { return false; }
}

/* 目前這個對話該用什麼名字：先看該對話的覆寫，再退回全域預設 */
function nameFor(convId) {
  const m = state.settings.names || {};
  const d = m._default || {};
  const own = (convId && m[convId]) || {};
  return { u: own.u || d.u || '', a: own.a || d.a || '' };
}

/* 開關關閉時回傳空物件，core.js 就會用原本的「你 / ChatGPT」 */
function activeNames() {
  if (!state.settings.applyNames) return {};
  return nameFor(state.conv && state.conv.id);
}

/* ===================== 專案 =====================
   匯出檔只有專案 id（conversation_template_id 的 g-p-… 前綴），沒有名稱。
   自己取的名字存成 _viewer/project-names.json（由 serve.py 寫檔），
   key 是專案 id —— 那個 id 是專案本身的識別碼，重新匯出備份還是同一組，
   所以名稱可以一直沿用下去。
   localStorage 只是伺服器寫檔失敗時的備援。*/
const NAMES_KEY = 'chatgpt-viewer.groupNames';
const NAMES_URL = 'project-names.json';
const NAMES_API = 'api/project-names';

function lsNames() {
  try { return JSON.parse(localStorage.getItem(NAMES_KEY) || '{}'); }
  catch (e) { return {}; }
}
function loadNames() {
  return state.names;
}
async function initNames() {
  let fromFile = {};
  try {
    const r = await fetch(NAMES_URL + '?t=' + Date.now());
    if (r.ok) fromFile = await r.json();
  } catch (e) { /* 檔案還不存在很正常 */ }
  // 檔案優先，localStorage 補上檔案裡沒有的（例如舊版留下來的）
  state.names = Object.assign({}, lsNames(), fromFile);
}
async function saveNames(m) {
  state.names = m;
  try { localStorage.setItem(NAMES_KEY, JSON.stringify(m)); } catch (e) { }
  try {
    const r = await fetch(NAMES_API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(m),
    });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return true;
  } catch (e) {
    return false;   // 寫檔失敗就只留 localStorage，並提示可以手動下載
  }
}
function groupLabel(g) {
  const custom = state.names[g.id] || g.name;
  const base = custom || (g.kind === 'project' ? '專案 ' + g.no : 'GPT ' + g.no);
  return `${base}（${g.n}）`;
}

function fillProjects() {
  const sel = $('#proj');
  const cur = sel.value;
  sel.textContent = '';
  const add = (v, t) => { const o = document.createElement('option'); o.value = v; o.textContent = t; sel.appendChild(o); };
  const nPj = state.groups.filter(g => g.kind === 'project').length;
  add('', `全部對話（${state.index.length}）`);
  if (state.service === 'both') {
    const g = state.index.filter(c => (c.svc || 'chatgpt') === 'chatgpt').length;
    add('__gpt__', `🟢 只看 ChatGPT（${g}）`);
    add('__claude__', `🟣 只看 Claude（${state.index.length - g}）`);
  }
  add('__none__', `不屬於任何專案（${state.index.filter(c => !c.pj && !c.gz).length}）`);
  for (const g of state.groups) {
    if (g.kind !== 'project' || !g.n) continue;   // 對不上任何對話就不列
    add(g.id, '📁 ' + groupLabel(g));
  }
  for (const g of state.groups) {
    if (g.kind !== 'gpt' || !g.n) continue;
    add(g.id, '🤖 ' + groupLabel(g));
  }
  sel.value = cur && [...sel.options].some(o => o.value === cur) ? cur : '';
  $('#proj-name').disabled = !sel.value || sel.value.startsWith('__');
  // 「存成檔案」平常隱藏 —— 名稱會直接寫進 project-names.json，
  // 只有寫檔失敗（唯讀資料夾之類）時 renameGroup() 才把它顯示出來
  return nPj;
}

async function renameGroup() {
  const id = $('#proj').value;
  if (!id || id === '__none__') return;
  const g = state.groups.find(x => x.id === id);
  const names = Object.assign({}, state.names);
  const now = names[id] || (g && g.name) || '';
  const v = prompt('幫這個' + (g && g.kind === 'gpt' ? '自訂 GPT' : '專案') + '取個名字：\n'
    + '（' + (g ? g.titles.slice(0, 3).join('、') : '') + '…）', now);
  if (v === null) return;
  if (v.trim()) names[id] = v.trim(); else delete names[id];
  const ok = await saveNames(names);
  fillProjects();
  renderList();
  if (state.conv) renderConv();
  $('#proj-save').hidden = ok;      // 有寫進檔案就不用再手動下載
}

/* 備援：伺服器寫不了檔時，讓使用者自己下載後放進 _viewer/ */
function exportNames() {
  const names = Object.assign({}, state.names);
  for (const g of state.groups) if (g.name && !names[g.id]) names[g.id] = g.name;
  download(new Blob([JSON.stringify(names, null, 2)], { type: 'application/json' }),
    'project-names.json');
}

/* ===================== 側欄清單 ===================== */

function applyFilters() {
  const q = $('#q').value.trim().toLowerCase();
  const onlyBranch = $('#f-branch').checked;
  const onlyStar = $('#f-star').checked;
  const sort = $('#sort').value;
  let v = state.index;

  if (state.mode === 'full' && state.hits) {
    const ids = new Set(state.hits.map(h => h.id));
    v = v.filter(c => ids.has(c.id));
  } else if (q) {
    v = v.filter(c => c.title.toLowerCase().includes(q));
  }
  if (onlyBranch) v = v.filter(c => c.br > 1);
  if (onlyStar) v = v.filter(c => c.st);
  const pj = $('#proj').value;
  if (pj === '__gpt__') v = v.filter(c => (c.svc || 'chatgpt') === 'chatgpt');
  else if (pj === '__claude__') v = v.filter(c => c.svc === 'claude');
  else if (pj === '__none__') v = v.filter(c => !c.pj && !c.gz);
  else if (pj) v = v.filter(c => c.pj === pj || c.gz === pj);

  v = v.slice();
  if (sort === 'title') v.sort((a, b) => a.title.localeCompare(b.title, 'zh-Hant'));
  else if (sort === 'n') v.sort((a, b) => b.n - a.n);
  else if (sort === 'br') v.sort((a, b) => (b.br - a.br) || (b.mf - a.mf));
  else if (sort === 'ct') v.sort((a, b) => (b.ct || 0) - (a.ct || 0));
  else v.sort((a, b) => (b.ut || b.ct || 0) - (a.ut || a.ct || 0));

  state.view = v;
  renderList();
}

function renderList() {
  const wrap = $('#list');
  wrap.textContent = '';
  const hits = state.hits ? new Map(state.hits.map(h => [h.id, h])) : null;
  const branched = state.index.filter(c => c.br > 1).length;
  $('#counts').textContent =
    `顯示 ${state.view.length} / 共 ${state.index.length} 個對話 · ${branched} 個有分支`
    + (state.mode === 'full' ? ' · 全文搜尋' : '');

  const frag = document.createDocumentFragment();
  for (const c of state.view) {
    const it = el('div', 'item' + (state.conv && state.conv.id === c.id ? ' on' : ''));
    it.dataset.id = c.id;
    it.appendChild(el('div', 't', c.title));
    const s = el('div', 's');
    s.appendChild(el('span', null, fmtDate(c.ut || c.ct)));
    s.appendChild(el('span', 'badge', c.n + ' 則'));
    if (c.br > 1) s.appendChild(el('span', 'badge br', c.br + ' 分支'));
    if (c.st) s.appendChild(el('span', 'badge', '★'));
    if (state.service === 'both') {
      s.appendChild(el('span', 'badge svc ' + (c.svc || 'chatgpt'),
        c.svc === 'claude' ? 'Claude' : 'ChatGPT'));
    }
    // 匯入過多份備份時，標出只存在於舊備份的對話
    if (state.multiImport && c.src && state.latest && c.src !== state.latest) {
      const b = el('span', 'badge old', '舊備份');
      b.title = '這個對話只出現在較舊的備份裡，可能已經在 ChatGPT 上刪除';
      s.appendChild(b);
    }
    it.appendChild(s);
    const h = hits && hits.get(c.id);
    if (h && h.snips.length) {
      const sn = el('div', 'snip');
      sn.innerHTML = h.snips.slice(0, 2).join(' … ');
      it.appendChild(sn);
    }
    it.onclick = () => openConv(c.id, state.mode === 'full' ? state.query : '');
    frag.appendChild(it);
  }
  wrap.appendChild(frag);
}

/* ===================== 對話顯示 ===================== */

async function openConv(id, highlight) {
  const r = await fetch('data/conv/' + encodeURIComponent(id) + '.json');
  const conv = await r.json();
  state.conv = conv;
  state.defaultPath = pathToRoot(conv, conv.current_node || conv.root);
  state.path = state.defaultPath.slice();
  state.highlight = (highlight || '').trim().toLowerCase();
  state.treeExpanded = new Set();

  // 從全文搜尋點進來時，走到「含有關鍵字」的那個節點（可能在別條分支上）
  if (state.highlight) {
    const hit = findNode(conv, state.highlight);
    if (hit) state.path = pathThrough(conv, hit);
  }
  $('#empty').hidden = true;
  $('#results').hidden = true;
  $('#conv').hidden = false;
  history.replaceState(null, '', '#conv=' + encodeURIComponent(id));
  renderConv();
  renderList();
  if (!$('#namebox').hidden) fillNameBox();
  if (!$('#treepanel').hidden) renderTree(true);
  $('#main').scrollTop = 0;
  if (state.highlight) {
    const m = $('#thread mark');
    if (m) m.scrollIntoView({ block: 'center' });
  }
}

function findNode(conv, q) {
  for (const k in conv.nodes) {
    const n = conv.nodes[k];
    if (n.x && n.x.toLowerCase().includes(q)) return k;
  }
  return null;
}

function renderConv() {
  const conv = state.conv;
  $('#ctitle').textContent = conv.title;
  const meta = $('#cmeta');
  meta.textContent = '';
  const add = t => meta.appendChild(el('span', null, t));
  add('建立 ' + fmtTime(conv.create_time));
  add('更新 ' + fmtTime(conv.update_time));
  add(Object.keys(conv.nodes).length + ' 個節點');
  add(leafCount(conv) + ' 條分支');
  if (conv.model) add(conv.model);
  if (conv.archived) add('已封存');
  const ic = state.index.find(c => c.id === conv.id);
  const g = ic && state.groups.find(x => x.id === (ic.pj || ic.gz));
  if (g) {
    const s = el('span', 'in-group', (g.kind === 'project' ? '📁 ' : '🤖 ') + groupLabel(g));
    s.title = '點一下只看這個' + (g.kind === 'project' ? '專案' : '自訂 GPT') + '的對話';
    s.onclick = () => { $('#proj').value = g.id; fillProjects(); applyFilters(); };
    meta.appendChild(s);
  }

  const thread = $('#thread');
  thread.textContent = '';
  thread.appendChild(renderThread(conv, state.path, {
    asset: f => '../' + f,
    defaultPath: state.defaultPath,
    highlight: state.highlight,
    onSwitch: switchTo,
    names: activeNames(),
    svc: convSvc(),
  }));
}

/* 切換分支後，把「剛剛那一則」留在畫面上原本的位置。

   本來是重繪後去找第一個切換器來對齊，切回主線時沒有橘色標記，
   就退回到整串的第一個切換器 —— 畫面於是跳回頂端。*/
function switchTo(pathIdx, nodeId) {
  const main = $('#main');
  const oldEl = $(`#thread [data-node="${state.path[pathIdx]}"]`);
  const keepY = oldEl ? oldEl.getBoundingClientRect().top : null;

  state.path = state.path.slice(0, pathIdx).concat(descend(state.conv, nodeId));
  renderConv();
  if (!$('#treepanel').hidden) renderTree();

  const newEl = $(`#thread [data-node="${nodeId}"]`);
  if (newEl && keepY !== null) {
    main.scrollTop += newEl.getBoundingClientRect().top - keepY;
  } else if (newEl) {
    newEl.scrollIntoView({ block: 'center' });
  }
}

function renderTree(recenter) {
  const conv = state.conv;
  if (!conv) { $('#tp-body').textContent = ''; $('#tp-info').textContent = ''; return; }
  $('#tp-info').textContent = `${Object.keys(conv.nodes).length} 節點 · ${leafCount(conv)} 條分支`;
  renderTreeInto($('#tp-body'), conv, state.path, id => {
    state.path = pathThrough(conv, id);
    renderConv();
    renderTree();                 // 不 recenter，維持樹的捲動位置
    const m = $('#thread .brs.other') || $('#thread');
    if (m) m.scrollIntoView({ block: 'center' });
  }, {
    pathOnly: $('#tp-forks').checked,
    expanded: state.treeExpanded,
    onToggle: id => {
      state.treeExpanded.has(id) ? state.treeExpanded.delete(id) : state.treeExpanded.add(id);
      renderTree();
    },
    recenter: !!recenter,
  });
}

/* 樹很大時預設收起直線段，不然 1000 多個節點根本翻不完 */
function openTree() {
  $('#treepanel').hidden = false;
  if (state.conv && !state.treeTouched) {
    $('#tp-forks').checked = Object.keys(state.conv.nodes).length > 200;
  }
  renderTree(true);
}

/* ===================== 全文搜尋 ===================== */

let ftToken = 0;

async function fullSearch(q) {
  q = q.trim().toLowerCase();
  if (!q) return;
  const token = ++ftToken;          // 新的搜尋會取消掉還在跑的舊搜尋
  state.query = q;
  state.mode = 'full';
  state.hits = [];
  $('#btn-full').classList.add('on');
  const counts = $('#counts');
  const hits = [];

  try {
    // 逐片載入、掃完就丟，不把 70MB 全文留在記憶體裡
    for (let i = 0; i < state.ftShards; i++) {
      counts.textContent = `搜尋中… ${i + 1}/${state.ftShards}（已命中 ${hits.length}）`;
      const r = await fetch(`data/ft/ft-${String(i).padStart(3, '0')}.json`);
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const shard = await r.json();
      if (token !== ftToken) return;   // 已被新的搜尋取代
      for (const id in shard) {
        const body = shard[id];
        let pos = body.indexOf(q);
        if (pos < 0) continue;
        const snips = [];
        let count = 0;
        while (pos >= 0) {
          if (snips.length < 3) {
            const a = Math.max(0, pos - 40), b = Math.min(body.length, pos + q.length + 60);
            snips.push((a > 0 ? '…' : '') + esc(body.slice(a, pos)) + '<mark>'
              + esc(body.slice(pos, pos + q.length)) + '</mark>'
              + esc(body.slice(pos + q.length, b)) + (b < body.length ? '…' : ''));
          }
          count++;
          pos = body.indexOf(q, pos + q.length);
        }
        hits.push({ id, snips, count });
      }
      state.hits = hits.slice().sort((a, b) => b.count - a.count);
      applyFilters();                 // 邊搜邊出結果
    }
    counts.textContent = `全文命中 ${hits.length} 個對話（關鍵字「${q}」）`;
  } catch (e) {
    if (token === ftToken) counts.textContent = '搜尋失敗：' + e.message + '（請重試）';
  }
}

function clearFull() {
  ftToken++;
  state.mode = 'title';
  state.hits = null;
  state.query = '';
  $('#btn-full').classList.remove('on');
  applyFilters();
}

/* ===================== 匯出 ===================== */

function download(blob, name) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 8000);
}
function safeName(s) {
  return (s || 'conversation').replace(/[\\/:*?"<>|]/g, '_').slice(0, 60);
}

function exportMd() {
  const conv = state.conv;
  if (!conv) return;
  const nm = nameFor(conv.id);
  const uName = nm.u || '你';
  const aName = nm.a || svcName();
  const out = [`# ${conv.title}`, '',
    `建立：${fmtTime(conv.create_time)}　更新：${fmtTime(conv.update_time)}`, ''];
  for (let i = 1; i < state.path.length; i++) {
    const n = conv.nodes[state.path[i]];
    if (!n || !n.x || n.k === 'recap') continue;
    out.push(`## ${n.r === 'user' ? uName : aName}${n.m ? '（' + n.m + '）' : ''}　${fmtTime(n.t)}`,
      '', n.x, '');
  }
  download(new Blob([out.join('\n')], { type: 'text/markdown;charset=utf-8' }),
    safeName(conv.title) + '.md');
}

/* 把目前這條路徑攤成 SillyTavern 訊息，並沿路收集 swipes。

   逐則對齊，不是「有分岔就切開」：
   每個位置把還活著的各分支拿出同一則來比，
     - 內容全都一樣 → 只輸出一次、不做 swipes，全部分支繼續往下
       （ChatGPT 重新生成時會連使用者訊息一起複製，這樣才不會出現
        ["問A","問A"] 這種重複的 swipes）
     - 內容有不同 → 收成 swipes（去重），只有和使用中版本相同的分支繼續往下

   這樣巢狀情形才對：改過提問、又在改過的那版重新生成，
   使用者訊息和助理回覆會各自都有自己的 swipes。

   思考節點（thoughts / recap）沒有內文，會直接跨過去，
   所以會思考的模型分岔在思考層也抓得到。*/
const ST_MAX_LIVE = 40;   // 分支爆炸時的保險，避免一個位置比對上百個版本

function isContentNode(n) {
  return !!(n && n.x && n.k !== 'recap' && n.k !== 'thoughts');
}

/* 從 id 的子節點往下找「下一批有內文的節點」，中間的思考節點跨過去 */
function nextContent(conv, id) {
  const out = [];
  const stack = ((conv.nodes[id] || {}).c || []).slice();
  let guard = 0;
  while (stack.length && guard++ < 500) {
    const k = stack.shift();
    const n = conv.nodes[k];
    if (!n) continue;
    if (isContentNode(n)) out.push(k);
    else stack.push(...(n.c || []));
  }
  return out;
}

function rootContent(conv) {
  return nextContent(conv, conv.root);
}

function stMessages(conv, path) {
  const seq = path.filter(id => isContentNode(conv.nodes[id]));   // 使用中的那條
  const out = [];
  let live = rootContent(conv);

  for (const cur of seq) {
    const n = conv.nodes[cur];
    const curText = (n.x || '').trim();
    if (!live.includes(cur)) live = [cur];          // 保險：對不上就只跟著路徑走

    // 只跟同角色的版本比，避免把使用者訊息和助理回覆混成同一則的 swipes
    const same = live.filter(k => (conv.nodes[k] || {}).r === n.r).slice(0, ST_MAX_LIVE);
    const texts = same.map(k => (conv.nodes[k].x || '').trim());
    const distinct = [];
    for (const t of texts) if (!distinct.includes(t)) distinct.push(t);

    const rec = { id: cur, node: n, text: curText };
    if (distinct.length > 1) {
      rec.swipes = distinct;
      rec.swipeId = Math.max(0, distinct.indexOf(curText));
    }
    out.push(rec);

    // 只有和使用中版本內容相同的分支能繼續往下
    const keep = same.filter(k => (conv.nodes[k].x || '').trim() === curText);
    const nxt = [];
    for (const k of (keep.length ? keep : [cur])) {
      for (const c of nextContent(conv, k)) if (!nxt.includes(c)) nxt.push(c);
    }
    live = nxt;
  }
  return out;
}

/* SillyTavern 的 .jsonl：第一行是 metadata 標頭，之後每行一則訊息。
   ChatGPT 的分支剛好對應 SillyTavern 的 swipes（同一則訊息的多個版本），
   所以有分支的回覆會把所有版本一起帶進去，在 ST 裡可以左右滑。*/
function stDate(d) {
  const M = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
    'August', 'September', 'October', 'November', 'December'];
  let h = d.getHours();
  const ap = h >= 12 ? 'PM' : 'AM';
  h = h % 12 || 12;
  return `${M[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()} ${h}:${String(d.getMinutes()).padStart(2, '0')}${ap}`;
}

function exportJsonl() {
  const conv = state.conv;
  if (!conv) return;
  const nm = nameFor(conv.id);
  const uName = nm.u || '你';
  const aName = nm.a || svcName();

  const lines = [JSON.stringify({
    user_name: uName,
    character_name: aName,
    create_date: stDate(new Date((conv.create_time || Date.now() / 1000) * 1000)),
    chat_metadata: { chatgpt_conversation_id: conv.id, title: conv.title },
  })];

  for (const rec of stMessages(conv, state.path)) {
    const n = rec.node;
    const isUser = n.r === 'user';
    const e = {
      name: isUser ? uName : aName,
      is_user: isUser,
      is_system: false,
      send_date: stDate(new Date((n.t || conv.create_time || 0) * 1000)),
      mes: rec.text,
      extra: {},
    };
    if (rec.swipes) {
      e.swipes = rec.swipes;
      e.swipe_id = rec.swipeId;
      e.mes = rec.swipes[rec.swipeId];
    }
    lines.push(JSON.stringify(e));
  }

  download(new Blob([lines.join('\n') + '\n'], { type: 'application/json;charset=utf-8' }),
    safeName(conv.title) + '.jsonl');
}

/* 匯出成一個獨立的 HTML：含整棵分支樹、分支切換器、分支圖，
   圖片與附件直接內嵌成 data URI，檔案本身就能單獨拿去別台電腦開。*/
async function exportHtml(withAssets) {
  const conv = state.conv;
  if (!conv) return;
  const btn = $('#btn-html');
  const label = btn.textContent;
  btn.disabled = true;

  try {
    // 收集這個對話用到的圖片（所有分支，不只目前這條）。
    // 只內嵌圖片：zip / 文件內嵌進去會讓單檔暴增到幾十 MB，
    // 而那些檔案在備份資料夾裡本來就拿得到。
    const wanted = new Set();
    for (const k in conv.nodes) {
      const n = conv.nodes[k];
      for (const im of n.img || []) if (im.f) wanted.add(im.f);
      for (const f of n.att || []) if (f.f && (f.mt || '').startsWith('image/')) wanted.add(f.f);
      for (const f of n.out || []) if (f.f && (f.mt || '').startsWith('image/')) wanted.add(f.f);
    }

    const assets = {};
    if (withAssets) {
      let i = 0;
      for (const f of wanted) {
        i++;
        btn.textContent = `內嵌檔案 ${i}/${wanted.size}…`;
        try {
          const r = await fetch('../' + f);
          if (!r.ok) continue;
          const blob = await r.blob();
          assets[f] = await new Promise((res, rej) => {
            const fr = new FileReader();
            fr.onload = () => res(fr.result);
            fr.onerror = rej;
            fr.readAsDataURL(blob);
          });
        } catch (e) { /* 檔案不在就跳過 */ }
      }
    }

    btn.textContent = '產生 HTML…';
    const [css, core, tpl] = await Promise.all([
      fetch('style.css?v=20260817k').then(r => r.text()),
      fetch('core.js?v=20260817k').then(r => r.text()),
      fetch('export-template.html?v=20260817k').then(r => r.text()),
    ]);

    // 對話內容裡可能有 "</script>"，直接塞進 <script> 會把標籤提早關掉，
    // 所以把 < 跳脫掉（JSON 裡的 < 只會出現在字串值中，改成 < 仍然合法）
    const forScript = o => JSON.stringify(o)
      .replace(/</g, '\\u003c')
      .replace(/\u2028/g, '\\u2028')
      .replace(/\u2029/g, '\\u2029');

    const html = tpl
      .replace('/*__CSS__*/', () => css)
      .replace('/*__CORE__*/', () => core.replace(/<\/script/gi, '<\\/script'))
      .replace('"__CONV__"', () => forScript(conv))
      .replace('"__ASSETS__"', () => forScript(assets))
      .replace('"__NAMES__"', () => forScript(nameFor(conv.id)))
      .replace(/__TITLE__/g, () => esc(conv.title));

    download(new Blob([html], { type: 'text/html;charset=utf-8' }),
      safeName(conv.title) + '.html');
  } catch (e) {
    alert('匯出失敗：' + e.message);
  } finally {
    btn.textContent = label;
    btn.disabled = false;
  }
}

/* ===================== 名稱面板 ===================== */

function fillNameBox() {
  const lbl = [...document.querySelectorAll('#namebox label')][1];
  if (lbl) lbl.childNodes[0].nodeValue = svcName() + ' 顯示為';
  const own = ((state.settings.names || {})[state.conv ? state.conv.id : ''] || {});
  const d = (state.settings.names || {})._default || {};
  $('#nm-user').value = own.u || '';
  $('#nm-asst').value = own.a || '';
  $('#nm-user').placeholder = d.u || '你';
  $('#nm-asst').placeholder = d.a || svcName();
  $('#nm-apply').checked = !!state.settings.applyNames;
  const eff = nameFor(state.conv && state.conv.id);
  $('#nm-hint').textContent = (eff.u || eff.a)
    ? `目前會顯示成「${eff.u || '你'} / ${eff.a || svcName()}」`
    : '留白就是用預設值。這裡只改顯示與匯出，原始文本不動。';
}

async function saveNameBox() {
  if (!state.conv) return;
  const m = state.settings.names || (state.settings.names = {});
  const u = $('#nm-user').value.trim();
  const a = $('#nm-asst').value.trim();
  if (u || a) m[state.conv.id] = { u, a };
  else delete m[state.conv.id];
  state.settings.applyNames = $('#nm-apply').checked;
  fillNameBox();
  renderConv();
  await saveSettings();
}

async function setAsDefault() {
  const m = state.settings.names || (state.settings.names = {});
  const u = $('#nm-user').value.trim();
  const a = $('#nm-asst').value.trim();
  m._default = { u, a };
  // 設成預設之後，這個對話就不用再存一份一樣的
  if (state.conv && m[state.conv.id]
      && m[state.conv.id].u === u && m[state.conv.id].a === a) {
    delete m[state.conv.id];
  }
  fillNameBox();
  renderConv();
  const ok = await saveSettings();
  $('#nm-hint').textContent = ok ? '已設為所有對話的預設名稱' : '存檔失敗（設定只留在這次瀏覽）';
}

/* ===================== 側欄收合 =====================
   小螢幕上側欄佔掉一大塊，收起來看對話比較舒服。
   狀態存在 settings.json，下次開啟維持原樣。*/
function setSidebar(off, save) {
  document.querySelector('#app').classList.toggle('side-off', off);
  $('#side-show').hidden = !off;
  if (save) {
    state.settings.sidebarOff = off;
    saveSettings();
  }
}

function initSidebar() {
  // 沒設定過時，視窗窄就預設收起來
  const off = state.settings.sidebarOff === undefined
    ? window.innerWidth < 900
    : !!state.settings.sidebarOff;
  setSidebar(off, false);
  $('#side-hide').onclick = () => setSidebar(true, true);
  $('#side-show').onclick = () => setSidebar(false, true);
  document.addEventListener('keydown', e => {
    if (e.key === 'b' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      setSidebar(!document.querySelector('#app').classList.contains('side-off'), true);
    }
  });
}

/* ===================== 啟動 ===================== */

async function init() {
  const [d, groups] = await Promise.all([
    fetch('data/index.json').then(r => r.json()),
    fetch('data/groups.json').then(r => r.ok ? r.json() : []).catch(() => []),
    initNames(),
    initSettings(),
  ]);
  state.index = d.convs;
  state.ftShards = d.ft_shards;
  state.service = d.service || 'chatgpt';
  state.latest = d.latest || '';
  state.multiImport = (d.imports || []).filter(Boolean).length > 1;
  state.groups = groups;
  // 入口連結：哪一家的資料存在就顯示哪一個
  const nKnow = (await fetch('data/knowledge.json')
    .then(r => r.ok ? r.json() : []).catch(() => [])).length;
  const nFiles = (state.service !== 'claude');
  $('#link-files').hidden = !nFiles;
  $('#link-know').hidden = !nKnow;

  if (state.service === 'both') {
    document.title = 'AI 對話備份檢視器';
    const brand = $('#brand-text');
    if (brand) brand.textContent = 'AI 對話備份';
    const h = document.querySelector('#empty h1');
    if (h) h.textContent = 'AI 對話備份檢視器';
  } else if (state.service === 'claude') {
    document.title = 'Claude 備份檢視器';
    const brand = $('#brand-text');
    if (brand) brand.textContent = 'Claude 備份';
    const h = document.querySelector('#empty h1');
    if (h) h.textContent = 'Claude 備份檢視器';
    const lbl = [...document.querySelectorAll('#namebox label')][1];
    if (lbl) lbl.childNodes[0].nodeValue = 'Claude 顯示為';
  }
  initSidebar();
  fillProjects();
  applyFilters();

  const m = location.hash.match(/conv=([^&]+)/);
  if (m) {
    const id = decodeURIComponent(m[1]);
    if (state.index.some(c => c.id === id)) openConv(id, '');
  }

  let timer;
  $('#q').addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(() => { if (state.mode === 'full') clearFull(); else applyFilters(); }, 120);
  });
  $('#q').addEventListener('keydown', e => {
    if (e.key === 'Enter') fullSearch($('#q').value);
    if (e.key === 'Escape') { $('#q').value = ''; clearFull(); }
  });
  $('#btn-full').onclick = () => {
    if (state.mode === 'full') clearFull(); else fullSearch($('#q').value);
  };
  $('#proj').onchange = () => { fillProjects(); applyFilters(); };
  $('#proj-name').onclick = renameGroup;
  $('#proj-save').onclick = e => { e.preventDefault(); exportNames(); };
  $('#f-branch').onchange = applyFilters;
  $('#f-star').onchange = applyFilters;
  $('#sort').onchange = applyFilters;
  $('#btn-tree').onclick = () => {
    if ($('#treepanel').hidden) openTree();
    else $('#treepanel').hidden = true;
  };
  $('#tp-close').onclick = () => { $('#treepanel').hidden = true; };
  $('#tp-forks').onchange = () => { state.treeTouched = true; renderTree(true); };
  $('#btn-md').onclick = exportMd;
  $('#btn-html').onclick = () => exportHtml($('#embed-assets').checked);
  $('#btn-jsonl').onclick = exportJsonl;
  $('#btn-names').onclick = () => {
    const b = $('#namebox');
    b.hidden = !b.hidden;
    if (!b.hidden) { fillNameBox(); $('#nm-user').focus(); }
  };
  let nmTimer;
  for (const id of ['#nm-user', '#nm-asst']) {
    $(id).addEventListener('input', () => {
      clearTimeout(nmTimer);
      nmTimer = setTimeout(saveNameBox, 400);
    });
  }
  $('#nm-apply').onchange = saveNameBox;
  $('#nm-default').onclick = setAsDefault;
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && !$('#treepanel').hidden) $('#treepanel').hidden = true;
    if (e.key === '/' && document.activeElement !== $('#q')) { e.preventDefault(); $('#q').focus(); }
  });
}
init();

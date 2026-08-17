/* 共用核心：Markdown、樹的走訪、訊息與分支圖的繪製。
   index.html 與「匯出 HTML」產生的單檔都用這一份，不重複實作。 */
'use strict';

function el(tag, cls, txt) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
}
function esc(s) {
  return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}
function fmtTime(t) {
  if (!t) return '';
  const d = new Date(t * 1000);
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
function fmtDate(t) {
  if (!t) return '';
  const d = new Date(t * 1000);
  return `${d.getFullYear()}/${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')}`;
}
function firstLine(s, n = 60) {
  if (!s) return '';
  const t = s.replace(/\s+/g, ' ').trim();
  return t.length > n ? t.slice(0, n) + '…' : t;
}

/* ===================== 極簡 Markdown ===================== */

function md(src) {
  if (!src) return '';
  const blocks = [];
  let s = src.replace(/```([^\n`]*)\n([\s\S]*?)```/g, (m, lang, code) => {
    blocks.push(`<pre><code data-lang="${esc(lang.trim())}">${esc(code.replace(/\n$/, ''))}</code></pre>`);
    return ` B${blocks.length - 1} `;
  });
  s = esc(s);

  const inline = t => t
    .replace(/`([^`\n]+)`/g, (m, c) => `<code>${c}</code>`)
    .replace(/\*\*\*([^*\n]+)\*\*\*/g, '<strong><em>$1</em></strong>')
    .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*\w])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/~~([^~\n]+)~~/g, '<del>$1</del>')
    .replace(/\[([^\]\n]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');

  const lines = s.split('\n');
  const out = [];
  let i = 0, para = [];
  const flush = () => { if (para.length) { out.push('<p>' + inline(para.join('<br>')) + '</p>'); para = []; } };

  while (i < lines.length) {
    const ln = lines[i];
    if (/^ B\d+ $/.test(ln.trim())) { flush(); out.push(ln.trim()); i++; continue; }
    if (!ln.trim()) { flush(); i++; continue; }
    let m;
    if ((m = ln.match(/^(#{1,6})\s+(.*)$/))) {
      flush(); const lv = Math.min(m[1].length, 4);
      out.push(`<h${lv}>${inline(m[2])}</h${lv}>`); i++; continue;
    }
    if (/^\s*([-*_])\s*\1\s*\1[\s\-*_]*$/.test(ln)) { flush(); out.push('<hr>'); i++; continue; }
    if (/^\s*&gt;\s?/.test(ln)) {
      flush(); const buf = [];
      while (i < lines.length && /^\s*&gt;\s?/.test(lines[i])) { buf.push(lines[i].replace(/^\s*&gt;\s?/, '')); i++; }
      out.push('<blockquote>' + md(buf.join('\n')) + '</blockquote>'); continue;
    }
    if (ln.includes('|') && i + 1 < lines.length && /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lines[i + 1])) {
      flush();
      const row = r => r.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|').map(c => c.trim());
      const head = row(ln); i += 2;
      let t = '<table><thead><tr>' + head.map(c => `<th>${inline(c)}</th>`).join('') + '</tr></thead><tbody>';
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) {
        t += '<tr>' + row(lines[i]).map(c => `<td>${inline(c)}</td>`).join('') + '</tr>'; i++;
      }
      out.push(t + '</tbody></table>'); continue;
    }
    if (/^\s*([-*+]|\d+[.)])\s+/.test(ln)) {
      flush();
      const ordered = /^\s*\d+[.)]\s+/.test(ln);
      let html = ordered ? '<ol>' : '<ul>';
      let depth = 0;
      while (i < lines.length && /^\s*([-*+]|\d+[.)])\s+/.test(lines[i])) {
        const ind = (lines[i].match(/^\s*/)[0].length >= 2) ? 1 : 0;
        const txt = lines[i].replace(/^\s*([-*+]|\d+[.)])\s+/, '');
        if (ind > depth) { html += (ordered ? '<ol>' : '<ul>'); depth = 1; }
        else if (ind < depth) { html += (ordered ? '</ol>' : '</ul>'); depth = 0; }
        html += `<li>${inline(txt)}</li>`; i++;
      }
      if (depth) html += ordered ? '</ol>' : '</ul>';
      out.push(html + (ordered ? '</ol>' : '</ul>')); continue;
    }
    para.push(ln); i++;
  }
  flush();
  return out.join('\n').replace(/ B(\d+) /g, (m, n) => blocks[+n]);
}

/* ===================== 樹的走訪 ===================== */

function latestTime(conv, id, memo) {
  if (memo.has(id)) return memo.get(id);
  const n = conv.nodes[id] || {};
  let best = n.t || 0;
  for (const c of n.c || []) best = Math.max(best, latestTime(conv, c, memo));
  memo.set(id, best);
  return best;
}
/* 從 id 往下走到葉節點，每一步選最新的那條分支 */
function descend(conv, id) {
  const memo = conv._memo || (conv._memo = new Map());
  const out = [id];
  let cur = id;
  for (;;) {
    const ch = (conv.nodes[cur] || {}).c || [];
    if (!ch.length) break;
    let best = ch[0], bt = -1;
    for (const c of ch) { const t = latestTime(conv, c, memo); if (t >= bt) { bt = t; best = c; } }
    out.push(best); cur = best;
  }
  return out;
}
function pathToRoot(conv, id) {
  const out = [];
  let cur = id;
  while (cur) { out.unshift(cur); cur = (conv.nodes[cur] || {}).p; }
  return out;
}
function pathThrough(conv, id) {
  return pathToRoot(conv, id).slice(0, -1).concat(descend(conv, id));
}
function leafCount(conv) {
  let n = 0;
  for (const k in conv.nodes) if (!(conv.nodes[k].c || []).length) n++;
  return n;
}
function markIn(root, q) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const targets = [];
  while (walker.nextNode()) {
    if (walker.currentNode.nodeValue.toLowerCase().includes(q)) targets.push(walker.currentNode);
  }
  const re = new RegExp('(' + q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'ig');
  for (const t of targets) {
    const frag = document.createDocumentFragment();
    for (const p of t.nodeValue.split(re)) {
      if (p.toLowerCase() === q) frag.appendChild(el('mark', null, p));
      else frag.appendChild(document.createTextNode(p));
    }
    t.parentNode.replaceChild(frag, t);
  }
}

/* ===================== 繪製訊息 =====================
   opts:
     asset(f)      檔名 -> 可用的網址
     defaultPath   ChatGPT 原本選中的路徑（用來標示「你正在看別條分支」）
     highlight     要標記的關鍵字
     onSwitch(i,id) 按下分支切換器時呼叫
     names         {u, a} 顯示用的替換名稱（只改顯示，原始文本不動）
*/
function renderThread(conv, path, opts) {
  const frag = document.createDocumentFragment();
  const asset = opts.asset || (f => f);
  const dflt = new Set(opts.defaultPath || []);
  const nm = opts.names || {};
  const svcName = opts.svc === 'claude' ? 'Claude' : 'ChatGPT';
  const uName = nm.u || '你';
  const aName = nm.a || svcName;

  const brSwitch = (pathIdx, sibs, curId) => {
    const idx = sibs.indexOf(curId);
    const onDefault = dflt.has(curId);
    const w = el('span', 'brs' + (onDefault ? '' : ' other'));
    w.title = onDefault ? '這個節點有多個版本'
      : '目前顯示的不是預設選中的那個版本';
    const prev = el('button', null, '‹');
    const next = el('button', null, '›');
    prev.disabled = idx <= 0;
    next.disabled = idx >= sibs.length - 1;
    prev.onclick = () => opts.onSwitch(pathIdx, sibs[idx - 1]);
    next.onclick = () => opts.onSwitch(pathIdx, sibs[idx + 1]);
    w.append(prev, el('span', 'n', `${idx + 1}/${sibs.length}`), next);
    return w;
  };

  /* Claude 的思考寫在同一則訊息裡（ChatGPT 是獨立節點），畫成可展開區塊 */
  const thinkBlock = (list, n) => {
    const det = document.createElement('details');
    det.className = 'think';
    det.appendChild(el('summary', null, `💭 思考過程（${list.length} 段）`));
    const tb = el('div', 'tb');
    tb.innerHTML = list.map(t =>
      (t.s ? `<strong>${esc(t.s)}</strong><br>` : '') + md(t.c)).join('<hr>');
    det.appendChild(tb);
    return det;
  };

  /* Claude 的工具呼叫。Artifact 有內容就展開成程式碼，其他收成一行。*/
  const toolBlock = list => {
    const w = el('div', 'tools');
    for (const t of list) {
      if (t.body) {
        const det = document.createElement('details');
        det.className = 'artifact';
        det.appendChild(el('summary', null,
          '📦 ' + (t.title || 'Artifact') + (t.lang ? '（' + t.lang + '）' : '')));
        const body = el('div', 'tb');
        body.innerHTML = md('```' + (t.lang || '') + '\n' + t.body + '\n```');
        det.appendChild(body);
        w.appendChild(det);
      } else {
        const row = el('div', 'toolrow' + (t.err ? ' err' : ''));
        row.appendChild(el('span', 'tn', '🔧 ' + t.n));
        if (t.title || t.arg) row.appendChild(el('span', 'ta', t.title || t.arg));
        w.appendChild(row);
      }
    }
    return w;
  };

  // 檔案取不到（不在匯出檔裡，或單檔 HTML 沒內嵌）時的灰色標示
  const missing = txt => {
    const s = el('a', 'gone', txt);
    s.title = '這個檔案沒有內嵌在這份 HTML 裡，請到備份資料夾取用';
    return s;
  };
  const imgLink = (url, alt) => {
    const a = document.createElement('a');
    a.href = url; a.target = '_blank';
    const img = document.createElement('img');
    img.className = 'asset'; img.loading = 'lazy';
    img.src = url; img.alt = alt;
    a.appendChild(img);
    return a;
  };

  const outputBlock = list => {
    const w = el('div', 'out');
    const anyImg = list.some(f => (f.mt || '').startsWith('image/'));
    const lbl = el('div', 'lbl', anyImg ? '🖼 ChatGPT 產生的圖片' : '📤 ChatGPT 產生的檔案');
    if (list.every(f => f.approx)) {
      const tip = el('span', 'approx', '（位置依時間推定）');
      tip.title = '這個檔案的匯出資料只記到屬於哪個對話，沒記到屬於哪則訊息，'
        + '所以是用建立時間找最接近的回覆掛上去的';
      lbl.appendChild(tip);
    }
    w.appendChild(lbl);
    const chips = el('div', 'att');
    for (const f of list) {
      const url = asset(f.f);
      if ((f.mt || '').startsWith('image/')) {
        if (url) w.appendChild(imgLink(url, f.n || f.f));
        else chips.appendChild(missing('🖼 ' + (f.n || f.f)));
      } else if (url) {
        const link = el('a', null, '📄 ' + (f.n || f.f));
        link.href = url; link.target = '_blank';
        chips.appendChild(link);
      } else {
        chips.appendChild(missing('📄 ' + (f.n || f.f)));
      }
    }
    if (chips.children.length) w.appendChild(chips);
    return w;
  };

  for (let i = 1; i < path.length; i++) {
    const id = path[i];
    const n = conv.nodes[id];
    if (!n) continue;
    const parent = conv.nodes[path[i - 1]];
    const sibs = (parent && parent.c) || [];
    const hasBranch = sibs.length > 1;

    // 有些回覆整則就只有一個 recap 節點（「已思考 N 秒」），內容是圖片。
    // 這種情況要畫成正常的助理訊息，否則掛在上面的圖片會消失。
    if (n.k === 'recap' && n.out && n.out.length) {
      const box = el('div', 'msg asst');
      box.dataset.node = id;
      const who = el('div', 'who');
      who.appendChild(el('span', null, n.m ? aName + ' · ' + n.m : aName));
      if (n.t) who.appendChild(el('span', null, fmtTime(n.t)));
      if (hasBranch) who.appendChild(brSwitch(i, sibs, id));
      box.appendChild(who);
      const body = el('div', 'body');
      body.appendChild(el('div', 'recap-inline', '💭 ' + (n.x || '已思考')));
      body.appendChild(outputBlock(n.out));
      box.appendChild(body);
      frag.appendChild(box);
      continue;
    }
    if (n.k === 'recap' && !hasBranch) {
      frag.appendChild(el('div', 'recap', '💭 ' + (n.x || '已思考')));
      continue;
    }
    if (n.k === 'thoughts') {
      const det = document.createElement('details');
      det.className = 'think';
      det.appendChild(el('summary', null, `💭 思考過程（${(n.th || []).length} 段）`));
      const tb = el('div', 'tb');
      tb.innerHTML = (n.th || []).map(t =>
        (t.s ? `<strong>${esc(t.s)}</strong><br>` : '') + md(t.c)).join('<hr>');
      det.appendChild(tb);
      if (hasBranch || (n.out && n.out.length)) {
        const w = el('div');
        w.dataset.node = id;
        if (hasBranch) w.appendChild(brSwitch(i, sibs, id));
        w.appendChild(det);
        if (n.out && n.out.length) w.appendChild(outputBlock(n.out));
        frag.appendChild(w);
      } else frag.appendChild(det);
      continue;
    }

    const isUser = n.r === 'user';
    const box = el('div', 'msg ' + (isUser ? 'user' : 'asst'));
    box.dataset.node = id;
    const who = el('div', 'who');
    who.appendChild(el('span', null, isUser ? uName : (n.m ? aName + ' · ' + n.m : aName)));
    if (n.t) who.appendChild(el('span', null, fmtTime(n.t)));
    if (hasBranch) who.appendChild(brSwitch(i, sibs, id));
    box.appendChild(who);

    const body = el('div', 'body');
    body.innerHTML = n.x ? md(n.x)
      : (n.img || n.att || n.out ? '' : '<em style="color:var(--fg2)">（空白訊息）</em>');
    if (opts.highlight) markIn(body, opts.highlight);
    if (n.th && n.th.length) body.insertBefore(thinkBlock(n.th, n), body.firstChild);
    if (n.tool && n.tool.length) body.appendChild(toolBlock(n.tool));

    for (const im of n.img || []) {
      const url = im.f && asset(im.f);
      if (url) body.appendChild(imgLink(url, im.n || im.f));
      else {
        const a = el('div', 'att');
        a.appendChild(missing('🖼 ' + (im.n || im.f || '圖片')));
        body.appendChild(a);
      }
    }
    if (n.att && n.att.length) {
      const a = el('div', 'att');
      for (const f of n.att) {
        const url = f.f && asset(f.f);
        if (url) {
          const link = el('a', null, '📎 ' + (f.n || f.f));
          link.href = url; link.target = '_blank';
          a.appendChild(link);
        } else if (f.x) {
          // Claude 的匯出把附件的文字內容直接放在 json 裡，沒有原始檔案
          const det = document.createElement('details');
          det.className = 'think att-text';
          det.appendChild(el('summary', null, '📎 ' + (f.n || '附件') + '（純文字內容）'));
          const tb = el('div', 'tb');
          tb.innerHTML = md(f.x);
          det.appendChild(tb);
          body.appendChild(det);
        } else {
          const chip = missing('📎 ' + (f.n || f.f));
          if (!f.f) chip.title = '這個附件的檔案本體不在匯出檔裡';
          a.appendChild(chip);
        }
      }
      body.appendChild(a);
    }
    if (n.out && n.out.length) body.appendChild(outputBlock(n.out));
    box.appendChild(body);
    frag.appendChild(box);
  }
  return frag;
}

/* ===================== 繪製分支圖 ===================== */

/* 用扁平清單畫，縮排靠 padding 而且有上限。
   原本用巢狀 div，一層套一層的分岔會把文字欄壓到寬度歸零，只剩點點。

   opts.pathOnly：只列出目前路徑，並在每個有多版本的訊息後面放一列
   「⑂ 其他 N 個版本」，點開才展開。分岔多的對話（幾乎每則都重生成過）
   用整棵樹翻不完，這個模式可以把上千列縮到跟對話一樣長。
   opts.expanded：pathOnly 模式下已經展開的節點 id（Set）*/
function renderTreeInto(container, conv, path, onPick, opts) {
  opts = opts || {};
  const active = new Set(path);
  const MAX_INDENT = 8, STEP = 12;
  const keepScroll = container.scrollTop;

  const mainChild = kids => {
    for (const k of kids) if (active.has(k)) return k;
    return kids[kids.length - 1];
  };

  const label = n => n.k === 'thoughts' ? '（思考）'
    : n.k === 'recap' ? '（已思考）'
    : (firstLine(n.x, 48) || '（空白）');

  const makeRow = (id, n, depth, opt) => {
    opt = opt || {};
    const row = el('div', 'tnode ' + (n.r === 'user' ? 'u' : n.r === 'assistant' ? 'a' : '')
      + (active.has(id) ? ' active' : '') + (opt.cls ? ' ' + opt.cls : ''));
    row.style.paddingLeft = Math.min(depth, MAX_INDENT) * STEP + 'px';
    row.appendChild(el('span', 'dot'));
    row.appendChild(el('span', 'tx', opt.text || label(n)));
    const kids = n.c || [];
    if (opt.fork == null ? kids.length > 1 : opt.fork) {
      row.appendChild(el('span', 'fk', '⑂' + (opt.forkN || kids.length)));
    }
    row.onclick = opt.onClick || (() => onPick(id));
    return row;
  };

  container.textContent = '';
  const frag = document.createDocumentFragment();

  if (opts.pathOnly) {
    const expanded = opts.expanded || new Set();
    let run = [];
    const flushRun = () => {
      if (!run.length) return;
      if (run.length <= 3) {
        for (const r of run) frag.appendChild(makeRow(r.id, r.n, 0));
      } else {
        const last = run[run.length - 1];
        const row = el('div', 'tnode skip active');
        row.appendChild(el('span', 'dot'));
        row.appendChild(el('span', 'tx', `⋯ 中間 ${run.length} 則沒有其他版本 ⋯`));
        row.onclick = () => onPick(last.id);
        frag.appendChild(row);
      }
      run = [];
    };

    for (let i = 1; i < path.length; i++) {
      const id = path[i];
      const n = conv.nodes[id];
      if (!n) continue;
      const sibs = (conv.nodes[path[i - 1]] || {}).c || [];
      if (sibs.length < 2) { run.push({ id, n }); continue; }

      flushRun();
      frag.appendChild(makeRow(id, n, 0));

      const others = sibs.filter(k => k !== id);
      const open = expanded.has(id);
      const more = el('div', 'tnode alt' + (open ? ' open' : ''));
      more.style.paddingLeft = STEP + 'px';
      more.appendChild(el('span', 'dot'));
      more.appendChild(el('span', 'tx',
        (open ? '▾ ' : '▸ ') + `其他 ${others.length} 個版本`));
      more.title = '點開看這則訊息的其他版本';
      more.onclick = () => opts.onToggle && opts.onToggle(id);
      frag.appendChild(more);

      if (open) {
        for (const k of others) {
          const sn = conv.nodes[k];
          if (!sn) continue;
          frag.appendChild(makeRow(k, sn, 2, { cls: 'altitem' }));
        }
      }
    }
    flushRun();
  } else {
    // 整棵樹：前序走訪，只有非主線的分支才縮排
    const rows = [];
    const stack = [];
    const pushKids = (kids, depth) => {
      const main = kids.length > 1 ? mainChild(kids) : kids[0];
      for (let i = kids.length - 1; i >= 0; i--) {
        const k = kids[i];
        stack.push([k, k === main ? depth : depth + 1]);
      }
    };
    pushKids((conv.nodes[conv.root] || {}).c || [], 0);
    while (stack.length) {
      const [id, depth] = stack.pop();
      const n = conv.nodes[id];
      if (!n) continue;
      rows.push({ id, n, depth });
      pushKids(n.c || [], depth);
    }
    for (const r of rows) frag.appendChild(makeRow(r.id, r.n, r.depth));
  }

  container.appendChild(frag);
  if (opts.recenter) {
    const a = container.querySelector('.tnode.active');
    if (a) a.scrollIntoView({ block: 'center' });
  } else {
    container.scrollTop = keepScroll;
  }
}

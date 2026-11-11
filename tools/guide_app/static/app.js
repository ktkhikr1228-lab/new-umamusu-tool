"use strict";
// ガイド確認アプリの画面。ビルド不要の素のJavaScript。

const TIERS = { super_recommended: "超おすすめ", recommended: "おすすめ" };
const STRATEGIES = ["逃げ", "先行", "差し", "追込"];
const $app = document.getElementById("app");
const state = {
  group: null, params: null, cur: 0, filter: "all",
  selected: new Set(), anchor: null, focus: 0, editing: null, busy: false,
};

// ---------- 共通 ----------
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const qs = (o) => new URLSearchParams(o).toString();

async function api(path, body) {
  const opts = body === undefined ? {} : {
    method: "POST", body: JSON.stringify(body),
    headers: { "Content-Type": "application/json", "X-Guide-App": "1" },
  };
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({ error: `通信エラー (${res.status})` }));
  if (!res.ok) throw new Error(data.error || `エラー (${res.status})`);
  return data;
}

let toastTimer;
function toast(msg, isError = false) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = "toast" + (isError ? " err" : "");
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), isError ? 6000 : 2500);
}

function remember(key, value) { try { localStorage.setItem(key, value); } catch (_) { /* 保存できなくても動く */ } }
function recall(key) { try { return localStorage.getItem(key); } catch (_) { return null; } }

function parseHash() {
  const [path, query] = location.hash.replace(/^#/, "").split("?");
  return { view: (path || "/").replace(/^\//, "") || "home", params: Object.fromEntries(new URLSearchParams(query || "")) };
}

async function route() {
  const { view, params } = parseHash();
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("on", a.dataset.nav === view));
  try {
    if (view === "review") return await showReview(params);
    if (view === "publish") return await showPublish();
    return await showHome();
  } catch (e) {
    $app.innerHTML = `<div class="card"><strong>読み込めませんでした</strong><p class="muted">${esc(e.message)}</p><a href="#/">ホームへ</a></div>`;
  }
}

function reviewLink(event, race, strategy) {
  return "#/review?" + qs({ event, race, strategy });
}

// ---------- ホーム ----------
async function showHome() {
  const { events, last_import } = await api("/api/overview");
  const imp = last_import
    ? `最終取り込み ${esc(last_import.at)}(追加 ${last_import.added}行)` +
      (last_import.problems.length ? `<ul class="problems">${last_import.problems.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>` : "")
    : "まだ自動取り込みは動いていません";
  $app.innerHTML = `
    <div class="card small muted">${imp}
      <button class="btn sm" data-act="import-now" style="margin-left:8px">今すぐ取り込む</button>
    </div>
    ${events.length ? events.map(eventCard).join("") : `<div class="card">まだデータがありません。抽出CSVを取り込むとここに表示されます。</div>`}`;
}

function eventCard(ev) {
  const pct = (n) => (ev.total ? (n / ev.total) * 100 : 0).toFixed(1) + "%";
  const first = ev.races[0] && ev.races[0].strategies.find((s) => s.draft > 0);
  const next = first ? reviewLink(ev.event, ev.races[0].race, first.strategy) : null;
  return `
  <div class="card">
    <div class="evhead">
      <div>
        <h2>${esc(ev.event)}</h2>
        <div class="muted small">${ev.races.map((r) => esc(r.race)).join("・")} ・ 画像 ${ev.images}枚(確認済み ${ev.images_reviewed})・ ${ev.total}行</div>
      </div>
      ${next ? `<a class="btn primary" href="${next}">続きを確認する</a>` : `<span class="chip ok">未確認なし</span>`}
    </div>
    <div class="bar"><i style="width:${pct(ev.ready)};background:var(--ok)"></i><i style="width:${pct(ev.rejected)};background:var(--ng)"></i></div>
    <div class="chips"><span class="chip">未確認 ${ev.draft}</span><span class="chip ok">OK ${ev.ready}</span><span class="chip">却下 ${ev.rejected}</span></div>
    <table class="grid">
      <tr><th>コース</th><th>脚質</th><th class="n">画像(確認済み)</th><th class="n">未確認</th><th class="n">OK</th><th class="n">却下</th></tr>
      ${ev.races.map((race) => race.strategies.map((s) => `
        <tr>
          <td>${esc(race.race)}</td>
          <td><a href="${reviewLink(ev.event, race.race, s.strategy)}">${esc(s.strategy)}</a></td>
          <td class="n">${s.images}(${s.images_reviewed})</td>
          <td class="n">${s.draft}</td><td class="n">${s.ready}</td><td class="n">${s.rejected}</td>
        </tr>`).join("")).join("")}
    </table>
  </div>`;
}

// ---------- 確認画面 ----------
async function showReview(params) {
  if (!params.event) {
    const last = recall("guide.lastReview");
    if (last) { location.hash = last; return; }
    $app.innerHTML = `<div class="card">ホームからコースと脚質を選んでください。<a href="#/">ホームへ</a></div>`;
    return;
  }
  const changed = !state.params || ["event", "race", "strategy"].some((k) => state.params[k] !== params[k]);
  state.params = params;
  remember("guide.lastReview", location.hash);
  document.getElementById("nav-review").href = location.hash;
  if (changed) Object.assign(state, { cur: 0, selected: new Set(), anchor: null, focus: 0, editing: null });
  await loadGroup();
}

async function loadGroup(keepFile) {
  const p = state.params;
  const data = await api("/api/group?" + qs({ event: p.event, race: p.race, strategy: p.strategy }));
  state.group = data;
  const list = visibleImages();
  if (keepFile) {
    const i = list.findIndex((im) => im.file === keepFile);
    state.cur = i >= 0 ? i : Math.min(state.cur, list.length - 1);
  }
  state.cur = Math.max(0, Math.min(state.cur, list.length - 1));
  renderReview();
}

const isMain = (r) => !r.known || r.attention.length > 0;
const needsWork = (im) => im.rows.some((r) => isMain(r) && r.status === "draft") || !im.reviewed_at;

function visibleImages() {
  const all = state.group ? state.group.images : [];
  return state.filter === "attention" ? all.filter(needsWork) : all;
}

function currentImage() { return visibleImages()[state.cur] || null; }

function renderReview() {
  const g = state.group, list = visibleImages(), im = currentImage();
  const all = g.images;
  const todo = all.filter(needsWork).length;
  const strategyLinks = STRATEGIES.map((s) =>
    `<a class="${s === g.strategy ? "on" : ""}" href="${reviewLink(g.event, g.race, s)}">${s}</a>`).join("");
  const imgUrl = im ? "/api/image?" + qs({ event: g.event, file: im.file }) : "";

  $app.innerHTML = `
  <div class="crumbs">
    <a href="#/"><strong>${esc(g.event)}</strong></a><span class="muted">›</span><span>${esc(g.race)}</span>
    <div class="seg">${strategyLinks}</div>
    <div class="seg" style="margin-left:auto">
      <button class="${state.filter === "all" ? "on" : ""}" data-act="filter" data-v="all">すべての画像 ${all.length}</button>
      <button class="${state.filter === "attention" ? "on" : ""}" data-act="filter" data-v="attention">未完了 ${todo}</button>
    </div>
  </div>
  <div class="strip">
    ${list.map((x, i) => {
      const warn = x.rows.some((r) => isMain(r) && r.status === "draft");
      const t = x.tier ? (x.tier === "super_recommended" ? "超" : "お") : "混";
      return `<button class="thumb ${x.reviewed_at ? "done" : ""} ${i === state.cur ? "cur" : ""} ${state.selected.has(x.file) ? "sel" : ""}"
        data-act="thumb" data-i="${i}" title="${esc(x.file)}">${i + 1}<span class="tt">${t}</span>${warn ? '<span class="dot"></span>' : ""}</button>`;
    }).join("")}
    <span class="muted small" style="margin-left:6px">Shift+クリックで範囲選択</span>
  </div>
  ${state.selected.size ? `
  <div class="bulk">選択中の画像 ${state.selected.size}枚の区分を
    <button class="btn sm" data-act="bulk-tier" data-v="super_recommended">超おすすめにする</button>
    <button class="btn sm" data-act="bulk-tier" data-v="recommended">おすすめにする</button>
    <button class="btn sm" data-act="bulk-clear">選択をやめる</button>
  </div>` : ""}
  ${im ? `
  <div class="review">
    <div class="shot">
      ${im.found ? `<img src="${imgUrl}" alt="${esc(im.file)}" data-act="zoom">`
                 : `<div class="missing">画像ファイルが見つかりません<br><span class="small">${esc(im.file)}</span></div>`}
      <div class="cap">
        <button data-act="prev" ${state.cur === 0 ? "disabled" : ""}>‹ 前</button>
        <span>${state.cur + 1} / ${list.length} ・ ${esc(im.file)}${im.reviewed_at ? " ・ 確認済み" : ""}</span>
        <button data-act="next" ${state.cur >= list.length - 1 ? "disabled" : ""}>次 ›</button>
      </div>
    </div>
    <div>${imagePanel(im)}</div>
  </div>` : `<div class="card">${state.filter === "attention" ? "未完了の画像はありません。おつかれさまでした。" : "画像がありません"}</div>`}`;
  focusRow(false);
}

function tierSelect(act, id, value, allowMixed = false) {
  return `<select data-act="${act}" ${id != null ? `data-id="${id}"` : ""}>
    ${allowMixed ? `<option value="" ${value ? "" : "selected"}>(行ごとに違う)</option>` : ""}
    ${Object.entries(TIERS).map(([k, v]) => `<option value="${k}" ${k === value ? "selected" : ""}>${v}</option>`).join("")}
  </select>`;
}

function imagePanel(im) {
  const main = im.rows.filter(isMain), matched = im.rows.filter((r) => !isMain(r));
  const pendingMain = main.filter((r) => r.status === "draft").length;
  return `
    <div class="imgtier">この画像の区分 ${tierSelect("img-tier", null, im.tier, true)}
      <span class="muted small">撮影時の区分切り替え忘れを直すとき用</span></div>
    <div class="rows">
      ${main.length ? main.map(rowHtml).join("")
        : `<div class="allgood">✓ 名前はすべてスキルマスタと合致しました。スクショと見比べて、抜けや読み違いがなければ「この画像OK」</div>`}
    </div>
    ${matched.length ? `
    <details class="matched" ${recall("guide.openMatched") === "1" ? "open" : ""} data-act="toggle-matched">
      <summary>マスタと合致 ${matched.length}件(「この画像OK」でまとめてOK・開くと区分の変更や除外ができます)</summary>
      ${matched.map((r) => `
      <div class="mrow ${r.status}">
        ${tierSelect("row-tier", r.id, r.tier)}
        <span class="nm">${esc(r.skill)}${r.skill !== r.extracted_skill ? ` <span class="small muted">(読み取り: ${esc(r.extracted_skill)})</span>` : ""}</span>
        <span class="small muted">${r.status === "ready" ? "OK" : r.status === "rejected" ? "除外" : ""}</span>
        <button class="btn sm" data-act="row-status" data-id="${r.id}" data-v="${r.status === "rejected" ? "draft" : "rejected"}">${r.status === "rejected" ? "戻す" : "除外"}</button>
      </div>`).join("")}
    </details>` : ""}
    <div class="foot">
      <button class="btn primary" data-act="confirm">この画像OK・次へ <kbd>Space</kbd></button>
      ${pendingMain ? `<span class="small" style="color:var(--warn)">要確認の行が ${pendingMain} 件残っています(OKにするまで公開されません)</span>` : ""}
    </div>
    <div class="keys"><kbd>←</kbd><kbd>→</kbd> 画像の移動 ・ <kbd>↑</kbd><kbd>↓</kbd> 行の選択 ・ <kbd>Enter</kbd> 行をOK ・ <kbd>X</kbd> 行を却下 ・ 画像クリックで拡大</div>`;
}

function rowHtml(r) {
  const names = [...new Set([r.skill, ...r.suggestions, r.extracted_skill])];
  const nameField = state.editing === r.id
    ? `<input type="text" class="name" list="master" data-act="row-name-input" data-id="${r.id}" value="${esc(r.skill)}" placeholder="スキル名を入力">`
    : `<select class="name" data-act="row-name" data-id="${r.id}">
        ${names.map((n) => `<option value="${esc(n)}" ${n === r.skill ? "selected" : ""}>${esc(n)}${n === r.extracted_skill ? "(読み取ったまま)" : ""}</option>`).join("")}
        <option value="__input">手入力…</option>
      </select>`;
  const why = r.attention.length ? r.attention.join(" / ") : "";
  return `
  <div class="row ${r.status} ${why ? "warn" : ""}" data-row="${r.id}">
    ${tierSelect("row-tier", r.id, r.tier)}
    ${nameField}
    <div class="acts">
      <button class="okb ${r.status === "ready" ? "on" : ""}" data-act="row-status" data-id="${r.id}" data-v="${r.status === "ready" ? "draft" : "ready"}" title="OK (Enter)">✓</button>
      <button class="ngb ${r.status === "rejected" ? "on" : ""}" data-act="row-status" data-id="${r.id}" data-v="${r.status === "rejected" ? "draft" : "rejected"}" title="却下 (X)">✕</button>
    </div>
    ${why ? `<div class="why">${esc(why)}</div>` : ""}
    ${r.skill !== r.extracted_skill ? `<div class="orig">読み取り: ${esc(r.extracted_skill)}</div>` : ""}
  </div>`;
}

function focusRow(scroll = true) {
  const rows = [...document.querySelectorAll(".row[data-row]")];
  rows.forEach((el) => el.classList.remove("focus"));
  if (!rows.length) return;
  state.focus = Math.max(0, Math.min(state.focus, rows.length - 1));
  rows[state.focus].classList.add("focus");
  if (scroll) rows[state.focus].scrollIntoView({ block: "nearest" });
}

// ---------- 書き込み ----------
async function mutate(fn, okMessage) {
  if (state.busy) return;
  state.busy = true;
  const im = currentImage();
  try {
    const result = await fn();
    await loadGroup(im && im.file);
    if (okMessage) toast(typeof okMessage === "function" ? okMessage(result) : okMessage);
  } catch (e) {
    toast(e.message, true);
  } finally {
    state.busy = false;
  }
}

const updateRow = (id, changes) => mutate(() => api(`/api/rows/${id}`, changes));

function setImagesTier(files, tier) {
  const g = state.group;
  return mutate(() => api("/api/images-tier", { event: g.event, race: g.race, strategy: g.strategy, files, tier }),
    (r) => `${r.changed}行の区分を${TIERS[tier]}にしました` + (r.duplicates ? `(変更先と重複した${r.duplicates}行は却下)` : ""));
}

async function confirmImage() {
  const g = state.group, im = currentImage();
  if (!im || state.busy) return;
  state.busy = true;
  try {
    const r = await api("/api/review-image", { event: g.event, race: g.race, strategy: g.strategy, file: im.file });
    toast(`${r.approved}行をOKにしました` + (r.pending ? `(要確認 ${r.pending}行は未確認のまま)` : ""));
    if (state.filter === "all") state.cur += 1;  // 未完了モードでは確認した画像が一覧から消えるので位置はそのまま
    await loadGroup();
    window.scrollTo(0, 0);
  } catch (e) {
    toast(e.message, true);
  } finally {
    state.busy = false;
  }
}

function move(delta) {
  const n = visibleImages().length;
  const next = Math.max(0, Math.min(n - 1, state.cur + delta));
  if (next === state.cur) return;
  Object.assign(state, { cur: next, focus: 0, editing: null });
  renderReview();
  window.scrollTo(0, 0);
}

// ---------- 公開(ステップ3で作る) ----------
async function showPublish() {
  const { events } = await api("/api/overview");
  $app.innerHTML = `
  <div class="card">
    <h2>公開</h2>
    <p class="muted">公開ボタンは次の段階で作ります。今はOKにした行の件数だけ表示しています。</p>
    <table class="grid">
      <tr><th>イベント</th><th class="n">OK</th><th class="n">未確認</th><th class="n">未確認の画像</th></tr>
      ${events.map((e) => `<tr><td>${esc(e.event)}</td><td class="n">${e.ready}</td><td class="n">${e.draft}</td><td class="n">${e.images - e.images_reviewed}</td></tr>`).join("")}
    </table>
  </div>`;
}

// ---------- イベント ----------
document.addEventListener("click", (ev) => {
  const el = ev.target.closest("[data-act]");
  if (!el || el.tagName === "SELECT" || el.tagName === "INPUT" || el.tagName === "DETAILS") return;
  const { act, v, id } = el.dataset;
  if (act === "import-now") {
    api("/api/import", {}).then((r) => { toast(`取り込み: 追加 ${r.added}行`); route(); }).catch((e) => toast(e.message, true));
  } else if (act === "filter") {
    Object.assign(state, { filter: v, cur: 0, selected: new Set(), focus: 0 });
    renderReview();
  } else if (act === "thumb") {
    const i = Number(el.dataset.i), list = visibleImages();
    if (ev.shiftKey && state.anchor !== null) {
      const [a, b] = [Math.min(state.anchor, i), Math.max(state.anchor, i)];
      state.selected = new Set(list.slice(a, b + 1).map((x) => x.file));
    } else if (ev.ctrlKey || ev.metaKey) {
      const f = list[i].file;
      state.selected.has(f) ? state.selected.delete(f) : state.selected.add(f);
      state.anchor = i;
    } else {
      Object.assign(state, { cur: i, anchor: i, selected: new Set(), focus: 0, editing: null });
    }
    renderReview();
  } else if (act === "bulk-tier") {
    setImagesTier([...state.selected], v).then(() => { state.selected = new Set(); renderReview(); });
  } else if (act === "bulk-clear") {
    state.selected = new Set(); renderReview();
  } else if (act === "row-status") {
    updateRow(Number(id), { status: v });
  } else if (act === "confirm") {
    confirmImage();
  } else if (act === "prev" || act === "next") {
    move(act === "prev" ? -1 : 1);
  } else if (act === "zoom") {
    const z = document.getElementById("zoom");
    z.querySelector("img").src = el.src;
    z.hidden = false;
  }
});

document.getElementById("zoom").addEventListener("click", (ev) => { ev.currentTarget.hidden = true; });

document.addEventListener("change", (ev) => {
  const el = ev.target, { act, id } = el.dataset;
  if (act === "row-tier") updateRow(Number(id), { tier: el.value });
  else if (act === "img-tier" && el.value) setImagesTier([currentImage().file], el.value);
  else if (act === "row-name") {
    if (el.value === "__input") { state.editing = Number(id); renderReview(); document.querySelector("input.name")?.focus(); }
    else updateRow(Number(id), { skill: el.value, status: "ready" });
  } else if (act === "row-name-input") {
    state.editing = null;
    if (el.value.trim()) updateRow(Number(id), { skill: el.value.trim(), status: "ready" });
    else renderReview();
  }
});

document.addEventListener("toggle", (ev) => {
  if (ev.target.dataset && ev.target.dataset.act === "toggle-matched") remember("guide.openMatched", ev.target.open ? "1" : "0");
}, true);

document.addEventListener("keydown", (ev) => {
  const z = document.getElementById("zoom");
  if (!z.hidden && ev.key === "Escape") { z.hidden = true; return; }
  if (parseHash().view !== "review" || !state.group) return;
  if (["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName)) {
    if (ev.key === "Escape") { state.editing = null; document.activeElement.blur(); renderReview(); }
    return;
  }
  if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
  const rows = [...document.querySelectorAll(".row[data-row]")];
  const focused = rows[state.focus] && Number(rows[state.focus].dataset.row);
  const key = ev.key;
  if (key === "ArrowRight") move(1);
  else if (key === "ArrowLeft") move(-1);
  else if (key === "ArrowDown" && rows.length) { state.focus += 1; focusRow(); }
  else if (key === "ArrowUp" && rows.length) { state.focus -= 1; focusRow(); }
  else if (key === "Enter" && focused) updateRow(focused, { status: "ready" });
  else if ((key === "x" || key === "X") && focused) updateRow(focused, { status: "rejected" });
  else if (key === " ") confirmImage();
  else return;
  ev.preventDefault();
});

// スキル名の入力候補(手入力用)
api("/api/master").then((names) => {
  document.getElementById("master").innerHTML = names.map((n) => `<option value="${esc(n)}">`).join("");
}).catch(() => {});

window.addEventListener("hashchange", route);
route();

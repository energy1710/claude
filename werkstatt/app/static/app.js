'use strict';
/* Werkstatt – Weboberfläche (ohne Framework) */

let D = null;            // alle Daten von /api/data
let S = {};              // Einstellungen
const view = document.getElementById('view');
const STATUS_LABEL = { anfrage: 'Anfrage', angebot: 'Angebot', in_arbeit: 'In Arbeit', fertig: 'Fertig',
  abgeholt: 'Übergeben', abgerechnet: 'Abgerechnet', bezahlt: 'Bezahlt', storniert: 'Storniert' };
const OPEN_STATUS = ['anfrage', 'angebot', 'in_arbeit', 'fertig', 'abgeholt'];
const DOC_STATUS = { offen: 'offen', bezahlt: 'bezahlt', storniert: 'storniert', angenommen: 'angenommen', abgelehnt: 'abgelehnt' };
const ZS_LABEL = { offen: 'offen', angezahlt: 'angezahlt', bezahlt: 'bezahlt' };
const MTYP = { fdm: '3D-Drucker', laser: 'Laser', sonstige: 'Sonstige' };
const MATTYP = { filament: 'Filament', platte: 'Platte', sonstiges: 'Sonstiges' };

// ---------- Helfer ----------
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const nf2 = new Intl.NumberFormat('de-AT', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const nfx = new Intl.NumberFormat('de-AT', { maximumFractionDigits: 2 });
const eur = (x) => nf2.format(+x || 0) + ' ' + (S.currency || '€');
const eur3 = (x) => new Intl.NumberFormat('de-AT', { minimumFractionDigits: 2, maximumFractionDigits: 3 }).format(+x || 0) + ' €';
const num = (x) => nfx.format(+x || 0);
const today = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
const dmy = (s) => (s ? s.slice(0, 10).split('-').reverse().join('.') : '');
const hm = (h) => { h = +h || 0; const H = Math.floor(h); const M = Math.round((h - H) * 60); return M === 60 ? `${H + 1}:00` : `${H}:${String(M).padStart(2, '0')}`; };
const byId = (arr, id) => arr.find((x) => x.id === id);
const kname = (k) => (k ? (k.firma || [k.vorname, k.nachname].filter(Boolean).join(' ') || k.nr || '–') : '–');
const parseNum = (v) => { if (v === '' || v == null) return null; const n = parseFloat(String(v).replace(/\s/g, '').replace(',', '.')); return isNaN(n) ? null : n; };
function parseHours(v) {
  if (v === '' || v == null) return null;
  const s = String(v).trim().toLowerCase().replace(',', '.');
  let m;
  if ((m = s.match(/^(\d+):(\d{1,2})$/))) return +m[1] + +m[2] / 60;
  if ((m = s.match(/^(?:(\d+(?:\.\d+)?)\s*h)?\s*(?:(\d+)\s*m(?:in)?)?$/)) && (m[1] || m[2])) return (+m[1] || 0) + (+m[2] || 0) / 60;
  const n = parseFloat(s);
  return isNaN(n) ? null : n;
}
const r2 = (x) => Math.round((+x || 0) * 100) / 100;

async function api(method, url, body) {
  const opt = { method, headers: {} };
  if (body instanceof FormData) opt.body = body;
  else if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  const r = await fetch(url, opt);
  if (r.status === 401) { location.href = '/login'; throw new Error('Anmeldung erforderlich'); }
  let data = null;
  try { data = await r.json(); } catch { /* leer */ }
  if (!r.ok) throw new Error((data && (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail))) || `Fehler ${r.status}`);
  return data;
}

function toast(msg, type = 'ok', ms = 3500) {
  const t = document.createElement('div');
  t.className = 'toast ' + (type === 'ok' ? '' : type);
  t.textContent = msg;
  $('#toasts').appendChild(t);
  setTimeout(() => t.remove(), type === 'err' ? 7000 : ms);
}
const fail = (e) => toast(e.message || String(e), 'err');
const warnIf = (r) => { if (r && r.warning) toast(r.warning, 'warn', 7000); };

function copyText(text) {
  const done = () => toast('In die Zwischenablage kopiert');
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text).then(done, () => fallback());
  fallback();
  function fallback() {
    const ta = document.createElement('textarea');
    ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); done(); } catch { prompt('Pfad kopieren:', text); }
    ta.remove();
  }
}

async function reload() {
  D = await api('GET', '/api/data');
  S = D.settings;
  $('#brandName').textContent = S.firma_name || 'Werkstatt';
  document.title = S.firma_name || 'Werkstatt';
  applyTheme(S.akzentfarbe);
  updateDruckBadge();
}

// Markenfarbe aus der Rechnungsvorlage auch in der Oberfläche verwenden (für dunklen Hintergrund aufgehellt)
function applyTheme(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || '');
  if (!m) return;
  const rgb = [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16));
  const mix = (c, t, f) => Math.round(c + (t - c) * f);
  const lum = ([r, g, b]) => (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
  let f = 0; let acc = rgb;
  while (lum(acc) < 0.42 && f < 0.7) { f += 0.05; acc = rgb.map((c) => mix(c, 255, f)); }
  const acc2 = rgb.map((c) => mix(c, 255, Math.min(0.85, f + 0.3)));
  const css = (a) => `rgb(${a.join(',')})`;
  const st = document.documentElement.style;
  st.setProperty('--accent', css(acc));
  st.setProperty('--accent2', css(acc2));
  st.setProperty('--accentbg', `rgba(${acc.join(',')},.14)`);
  const lin = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
  const L = 0.2126 * lin(acc[0]) + 0.7152 * lin(acc[1]) + 0.0722 * lin(acc[2]);
  st.setProperty('--on-accent', L > 0.22 ? '#1a1220' : '#fff');
}
async function refresh() { const y = window.scrollY; await reload(); await render(); window.scrollTo(0, y); }

const chip = (st, label) => `<span class="chip st-${esc(st)}">${esc(label || STATUS_LABEL[st] || st)}</span>`;
const opt = (v, l, sel) => `<option value="${esc(v)}" ${String(v) === String(sel ?? '') ? 'selected' : ''}>${esc(l)}</option>`;
const custOptions = (sel, empty = '— kein Kunde —') => opt('', empty, sel) + [...D.customers].sort((a, b) => kname(a).localeCompare(kname(b), 'de')).map((k) => opt(k.id, `${kname(k)}${k.ort ? ' · ' + k.ort : ''}`, sel)).join('');
const listOpts = (csv) => String(csv || '').split(',').map((x) => x.trim()).filter(Boolean);

// ---------- Modal + Formulare ----------
function modal({ title, body, footer = '', wide = false, onClose }) {
  const bg = document.createElement('div');
  bg.className = 'modal-bg';
  bg.innerHTML = `<div class="modal ${wide ? 'wide' : ''}"><div class="mh"><h2>${esc(title)}</h2><button class="icon" data-x>✕</button></div>
    <div class="mb">${body}</div>${footer ? `<div class="mf">${footer}</div>` : ''}</div>`;
  const close = () => { bg.remove(); document.removeEventListener('keydown', onKey); onClose && onClose(); };
  const onKey = (e) => { if (e.key === 'Escape' && bg === $('#modalRoot').lastElementChild) close(); };
  bg.addEventListener('mousedown', (e) => { if (e.target === bg) bg._down = true; });
  bg.addEventListener('click', (e) => { if (e.target === bg && bg._down) close(); bg._down = false; });
  $('[data-x]', bg).onclick = close;
  document.addEventListener('keydown', onKey);
  $('#modalRoot').appendChild(bg);
  const first = $('input:not([type=hidden]):not([type=checkbox]), textarea, select', bg);
  if (first && !('ontouchstart' in window)) setTimeout(() => first.focus(), 30);
  return { el: bg, close };
}

function fieldHtml(f, v) {
  const id = 'f_' + f.k;
  const span = f.s ? ` s${f.s}` : '';
  if (f.t === 'h4') return `<h4>${esc(f.l)}</h4>`;
  if (f.t === 'html') return `<div class="f${span}">${f.html}</div>`;
  if (f.t === 'check') return `<div class="f chk${span}"><input type="checkbox" id="${id}" name="${f.k}" ${+v ? 'checked' : ''}><label for="${id}">${esc(f.l)}</label></div>`;
  let input;
  const val = v ?? f.def ?? '';
  const ph = f.ph ? ` placeholder="${esc(f.ph)}"` : '';
  if (f.t === 'select') input = `<select id="${id}" name="${f.k}" style="width:100%">${(typeof f.o === 'function' ? f.o(val) : f.o.map(([a, b]) => opt(a, b, val)).join(''))}</select>`;
  else if (f.t === 'textarea') input = `<textarea id="${id}" name="${f.k}" rows="${f.rows || 3}"${ph}>${esc(val)}</textarea>`;
  else if (f.t === 'h') input = `<input id="${id}" name="${f.k}" inputmode="decimal" data-hours value="${val === '' || val == null ? '' : esc(hm(val))}"${ph || ' placeholder="z. B. 2:30"'}>`;
  else if (f.t === 'num') input = `<input id="${id}" name="${f.k}" inputmode="decimal" data-num value="${val === '' || val == null ? '' : esc(String(val).replace('.', ','))}"${ph}>`;
  else input = `<input id="${id}" name="${f.k}" type="${f.t || 'text'}" value="${esc(val)}"${ph}${f.list ? ` list="${id}_l"` : ''}>${f.list ? `<datalist id="${id}_l">${f.list.map((x) => `<option value="${esc(x)}">`).join('')}</datalist>` : ''}`;
  if (f.extra) input = `<div class="inline">${input}${f.extra}</div>`;
  return `<div class="f${span}"><label for="${id}">${esc(f.l)}</label>${input}${f.hint ? `<div class="hint">${f.hint}</div>` : ''}</div>`;
}

function readForm(el, fields) {
  const out = {};
  for (const f of fields) {
    if (!f.k || ['h4', 'html'].includes(f.t)) continue;
    const inp = el.querySelector(`[name="${f.k}"]`);
    if (!inp) continue;
    if (f.t === 'check') out[f.k] = inp.checked ? 1 : 0;
    else if (f.t === 'h') out[f.k] = parseHours(inp.value);
    else if (f.t === 'num') out[f.k] = parseNum(inp.value);
    else out[f.k] = inp.value;
  }
  return out;
}

function openForm({ title, fields, values = {}, onSave, onDelete, wide, saveLabel = 'Speichern', after }) {
  const m = modal({
    title, wide,
    body: `<form class="form" autocomplete="off">${fields.map((f) => fieldHtml(f, values[f.k])).join('')}<button type="submit" hidden></button></form>`,
    footer: `${onDelete ? '<button class="danger" data-del>Löschen</button>' : ''}<span class="spacer"></span>
      <button class="secondary" data-cancel>Abbrechen</button><button data-save>${esc(saveLabel)}</button>`,
  });
  const form = $('form', m.el);
  const save = async () => {
    const btn = $('[data-save]', m.el);
    btn.disabled = true;
    try { await onSave(readForm(form, fields), m); m.close(); } catch (e) { fail(e); } finally { btn.disabled = false; }
  };
  form.onsubmit = (e) => { e.preventDefault(); save(); };
  $('[data-save]', m.el).onclick = save;
  $('[data-cancel]', m.el).onclick = m.close;
  if (onDelete) $('[data-del]', m.el).onclick = async () => {
    if (!confirm('Wirklich löschen?')) return;
    try { await onDelete(); m.close(); } catch (e) { fail(e); }
  };
  after && after(m.el, form);
  return m;
}

function confirmDlg(text) { return Promise.resolve(confirm(text)); }

// ---------- Router ----------
const routes = {};
let current = '';
async function render() {
  const h = (location.hash || '#uebersicht').slice(1);
  const [name, arg] = h.split('/');
  current = name;
  $$('#nav a').forEach((a) => a.classList.toggle('active', a.dataset.r.split(' ').includes(name)));
  $('#nav').classList.remove('open');
  const fn = routes[name] || routes.uebersicht;
  try { await fn(arg ? decodeURIComponent(arg) : undefined); } catch (e) { console.error(e); view.innerHTML = `<div class="card pad err">${esc(e.message)}</div>`; }
}
window.addEventListener('hashchange', () => { render(); window.scrollTo(0, 0); });
$('#navToggle').onclick = () => $('#nav').classList.toggle('open');

// ======================================================================
//  Übersicht
// ======================================================================
routes.uebersicht = async () => {
  const jahr = new Date().getFullYear();
  const aw = await api('GET', '/api/auswertung?jahr=' + jahr);
  const open = D.orders.filter((o) => OPEN_STATUS.includes(o.status));
  const in7 = new Date(Date.now() + 7 * 864e5).toISOString().slice(0, 10);
  const due = open.filter((o) => o.termin && o.termin <= in7);
  const offeneDocs = D.documents.filter((d) => d.typ === 'rechnung' && d.status === 'offen');
  const ueber = offeneDocs.filter((d) => d.faellig && d.faellig < today());
  const wartung = [];
  D.machines.forEach((m) => D.wear_parts.filter((p) => p.machine_id === m.id && p.pct >= 90).forEach((p) => wartung.push({ m, p })));
  const sorted = [...open].sort((a, b) => (a.termin || '9999').localeCompare(b.termin || '9999'));
  const first = !D.orders.length && !D.customers.length;
  view.innerHTML = `
  <div class="pagehead"><h1>Servus! 👋</h1>
    <button class="secondary" onclick="location.hash='#rechner'">🧮 Rechner</button>
    <button class="secondary" onclick="newCustomer()">+ Kunde</button>
    <button onclick="newOrder()">+ Neuer Auftrag</button></div>
  ${first ? `<div class="card pad" style="border-color:var(--accent)"><h2>Willkommen in eurer Werkstatt-Verwaltung</h2>
    <p class="muted">So geht's los: <b>1.</b> unter <a href="#einstellungen">Einstellungen</a> Firmendaten, Bankverbindung und Logo eintragen (für Rechnungen),
    <b>2.</b> Netzlaufwerk & Backup einrichten, <b>3.</b> unter <a href="#maschinen">Maschinen</a> die vorbelegten Werte prüfen – und dann den ersten Auftrag anlegen.</p></div>` : ''}
  <div class="tiles">
    <div class="tile accent clickable" onclick="location.hash='#auftraege'"><span>Offene Aufträge</span><b>${open.length}</b><small>${due.length} in den nächsten 7 Tagen fällig</small></div>
    ${(D.prints || []).length ? `<div class="tile clickable" onclick="location.hash='#drucke'"><span>Drucke einstufen / zuordnen</span><b>${D.prints.filter((p) => p.art === 'offen' || (p.art === 'gewerbe' && !p.job_id)).length}</b><small>aus Home Assistant</small></div>` : ''}
    <div class="tile clickable" onclick="location.hash='#rechnungen'"><span>Offene Rechnungen</span><b>${eur(aw.offen_summe)}</b><small>${aw.offen_anzahl} Rechnung(en)${ueber.length ? `, <span class="err">${ueber.length} überfällig</span>` : ''}</small></div>
    <div class="tile clickable" onclick="location.hash='#auswertung'"><span>Umsatz ${jahr} (netto)</span><b>${eur(aw.summe.umsatz)}</b><small>Gewinn ${eur(aw.summe.gewinn)}</small></div>
    <div class="tile clickable" onclick="location.hash='#auswertung'"><span>Arbeitszeit ${jahr}</span><b>${hm(aw.monate.reduce((s, m) => s + Object.values(m.stunden).reduce((a, b) => a + b, 0), 0))} h</b>
      <small>${D.persons.map((p) => `${esc(p.name)} ${hm(aw.monate.reduce((s, m) => s + (m.stunden[p.id] || 0), 0))}`).join(' · ')}</small></div>
  </div>
  <div class="grid2">
    <div>
      <div class="card"><div class="ch"><h3>Laufende Aufträge</h3><a href="#auftraege" class="small">alle anzeigen →</a></div>
        ${sorted.length ? `<div class="tblwrap"><table class="tbl"><thead><tr><th>Nr.</th><th>Auftrag</th><th>Kunde</th><th>Status</th><th>Fertig bis</th></tr></thead><tbody>
        ${sorted.slice(0, 12).map((o) => `<tr class="click" onclick="location.hash='#auftrag/${o.id}'"><td class="nowrap muted">${esc(o.nr)}</td><td><b>${esc(o.titel)}</b>${o.vertrieb ? `<div class="sub">${esc(o.vertrieb)}</div>` : ''}</td>
          <td>${esc(kname(byId(D.customers, o.customer_id)))}</td><td>${chip(o.status)}</td><td class="nowrap ${o.termin && o.termin < today() ? 'err' : o.termin && o.termin <= in7 ? 'warnc' : ''}">${dmy(o.termin) || '–'}</td></tr>`).join('')}
        </tbody></table></div>` : '<div class="empty">Keine offenen Aufträge 🎉</div>'}
      </div>
    </div>
    <div>
      <div class="card"><div class="ch"><h3>Offene Rechnungen</h3></div>
        ${offeneDocs.length ? `<ul class="list-compact">${offeneDocs.slice(0, 8).map((d) => `<li class="click" onclick="docActions(${d.id})"><div class="grow"><b>${esc(d.nr)}</b> · ${esc(kname(d.kunde))}<div class="tiny muted">fällig ${dmy(d.faellig)}</div></div>
          <span class="num">${eur(d.brutto - (d.anzahlung || 0))}</span>${d.faellig < today() ? chip('ueberfaellig', 'überfällig') : ''}</li>`).join('')}</ul>` : '<div class="empty">Alles bezahlt 👍</div>'}
      </div>
      <div class="card"><div class="ch"><h3>Wartung & Verschleiß</h3><a href="#maschinen" class="small">Maschinen →</a></div>
        ${wartung.length ? `<ul class="list-compact">${wartung.map(({ m, p }) => `<li><div class="grow"><b>${esc(p.name)}</b><div class="tiny muted">${esc(m.name)} · ${num(p.stunden_seit)} von ${num(p.lebensdauer_h)} h</div></div>
          <div style="width:90px" class="bar ${p.pct >= 100 ? 'e' : 'w'}"><div style="width:${Math.min(100, p.pct)}%"></div></div></li>`).join('')}</ul>`
          : '<div class="empty">Kein Verschleißteil ist fällig.</div>'}
      </div>
      <div class="card"><div class="ch"><h3>Datensicherung</h3><a href="#einstellungen/netz" class="small">Einstellungen →</a></div>
        <div class="cb small">${S.backup_aktiv === '1' ? `Automatisch täglich um ${esc(S.backup_uhrzeit)} Uhr.` : '<span class="warnc">Automatisches Backup ist noch nicht eingeschaltet.</span>'}
          ${S.backup_letzt ? `<br>Letzte Sicherung: ${esc(S.backup_letzt)} – <span class="${S.backup_letzt_status.startsWith('ok') ? 'okc' : 'err'}">${esc(S.backup_letzt_status.replace(/^(ok|fehler): /, ''))}</span>` : ''}</div></div>
    </div>
  </div>`;
};

// ======================================================================
//  Aufträge
// ======================================================================
let oFilter = { q: '', status: 'offen' };
routes.auftraege = () => {
  const counts = {};
  D.orders.forEach((o) => { counts[o.status] = (counts[o.status] || 0) + 1; });
  const nOpen = D.orders.filter((o) => OPEN_STATUS.includes(o.status)).length;
  view.innerHTML = `
  <div class="pagehead"><h1>Aufträge</h1><span class="sub">${D.orders.length} insgesamt</span>
    <a class="button secondary" href="/api/vorlage/bestellformular.pdf" target="_blank">🖨 Leeres Bestellformular</a>
    <button onclick="newOrder()">+ Neuer Auftrag</button></div>
  <div class="filterchips" id="oChips">
    <button data-s="offen">Offen<i>${nOpen}</i></button><button data-s="">Alle<i>${D.orders.length}</i></button>
    ${D.status_list.map((s) => `<button data-s="${s}">${STATUS_LABEL[s]}<i>${counts[s] || 0}</i></button>`).join('')}
  </div>
  <div class="toolbar"><input type="search" id="oq" placeholder="Suche nach Nummer, Titel, Kunde, Personalisierung …" value="${esc(oFilter.q)}"></div>
  <div class="card"><div class="tblwrap" id="oList"></div></div>`;
  const draw = () => {
    $$('#oChips button').forEach((b) => b.classList.toggle('on', b.dataset.s === oFilter.status));
    const q = oFilter.q.toLowerCase();
    let list = D.orders.filter((o) => (oFilter.status === 'offen' ? OPEN_STATUS.includes(o.status) : !oFilter.status || o.status === oFilter.status));
    if (q) list = list.filter((o) => {
      const k = byId(D.customers, o.customer_id);
      const items = D.order_items.filter((i) => i.order_id === o.id).map((i) => `${i.bezeichnung} ${i.personalisierung} ${i.farbe_material}`).join(' ');
      return `${o.nr} ${o.titel} ${o.beschreibung} ${o.vertrieb} ${kname(k)} ${items}`.toLowerCase().includes(q);
    });
    list.sort((a, b) => b.id - a.id);
    $('#oList').innerHTML = list.length ? `<table class="tbl"><thead><tr><th>Nr.</th><th>Auftrag</th><th>Kunde</th><th>Status</th><th>Zahlung</th><th>Eingang</th><th>Fertig bis</th>
      <th class="num">Kosten</th><th class="num">Umsatz</th><th class="num">Gewinn</th></tr></thead><tbody>
      ${list.map((o) => `<tr class="click" onclick="location.hash='#auftrag/${o.id}'"><td class="nowrap muted">${esc(o.nr)}</td>
        <td><b>${esc(o.titel)}</b>${o.vertrieb ? `<div class="sub">${esc(o.vertrieb)}${o.uebergabe ? ' · ' + (o.uebergabe === 'versand' ? 'Versand' : 'Abholung') : ''}</div>` : ''}</td>
        <td>${esc(kname(byId(D.customers, o.customer_id)))}</td><td>${chip(o.status)}</td><td>${o.zahlungsstatus ? chip(o.zahlungsstatus === 'angezahlt' ? 'offen' : o.zahlungsstatus, ZS_LABEL[o.zahlungsstatus]) : ''}</td>
        <td class="nowrap">${dmy(o.eingang)}</td><td class="nowrap ${o.termin && o.termin < today() && OPEN_STATUS.includes(o.status) ? 'err' : ''}">${dmy(o.termin) || '–'}</td>
        <td class="num">${eur(o.kosten.selbstkosten)}</td><td class="num">${eur(o.kosten.umsatz)}</td><td class="num ${o.kosten.gewinn < 0 ? 'err' : 'okc'}">${o.kosten.umsatz ? eur(o.kosten.gewinn) : '–'}</td></tr>`).join('')}
      </tbody></table>` : '<div class="empty">Keine Aufträge gefunden.</div>';
  };
  $('#oChips').onclick = (e) => { const b = e.target.closest('button'); if (b) { oFilter.status = b.dataset.s; draw(); } };
  $('#oq').oninput = (e) => { oFilter.q = e.target.value; draw(); };
  draw();
};

function orderFields() {
  return [
    { k: 'titel', l: 'Titel / Bezeichnung des Auftrags', ph: 'z. B. Geburtstagsdeko Lena', s: 8 },
    { k: 'status', l: 'Status', t: 'select', o: D.status_list.map((s) => [s, STATUS_LABEL[s]]), s: 4, def: 'anfrage' },
    { k: 'customer_id', l: 'Kunde', t: 'select', o: (v) => custOptions(v), s: 8, extra: '<button type="button" class="secondary fixed" onclick="quickCustomer(this)">+ neu</button>' },
    { k: 'vertrieb', l: 'Vertrieb / Kreativabend', s: 4, list: listOpts(S.vertrieb_optionen) },
    { k: 'eingang', l: 'Bestelldatum', t: 'date', s: 4, def: today() },
    { k: 'termin', l: 'Voraussichtliche Fertigstellung', t: 'date', s: 4 },
    { k: 'uebergabe', l: 'Übergabe', t: 'select', o: [['', '–'], ['abholung', 'Abholung'], ['versand', 'Versand']], s: 4 },
    { t: 'h4', l: 'Zahlung' },
    { k: 'zahlungsart', l: 'Zahlungsart', t: 'select', o: [['', '–'], ...listOpts(S.zahlungsarten).map((x) => [x, x])], s: 3 },
    { k: 'versand', l: 'Versandkosten €', t: 'num', s: 3 },
    { k: 'anzahlung', l: 'Anzahlung €', t: 'num', s: 3 },
    { k: 'zahlungsstatus', l: 'Zahlungsstatus', t: 'select', o: [['offen', 'offen'], ['angezahlt', 'angezahlt'], ['bezahlt', 'bezahlt']], s: 3, def: 'offen' },
    { k: 'zahlungsdatum', l: 'Zahlungsdatum', t: 'date', s: 4 },
    { k: 'aufschlag_pct', l: 'Gewinnaufschlag % (leer = Standard)', t: 'num', s: 4, ph: S.aufschlag_pct + ' %' },
    { t: 'h4', l: 'Details' },
    { k: 'beschreibung', l: 'Beschreibung (intern)', t: 'textarea', rows: 2 },
    { k: 'wuensche', l: 'Besondere Wünsche / Hinweise (steht auf dem Bestellformular)', t: 'textarea', rows: 2 },
    { k: 'notizen', l: 'Notizen (intern)', t: 'textarea', rows: 2 },
  ];
}

window.quickCustomer = (btn) => {
  const sel = btn.closest('.inline').querySelector('select');
  editCustomer(null, (row) => { sel.innerHTML = custOptions(row.id); });
};

window.newOrder = (preset = {}, after) => openForm({
  title: 'Neuer Auftrag', fields: orderFields(), values: preset, wide: true, saveLabel: 'Auftrag anlegen',
  onSave: async (v) => {
    const r = await api('POST', '/api/t/orders', v);
    warnIf(r);
    await reload();
    if (after) await after(r.row);
    location.hash = '#auftrag/' + r.row.id;
    render();
  },
});

function editOrder(o) {
  openForm({
    title: `Auftrag ${o.nr} bearbeiten`, fields: orderFields(), values: o, wide: true,
    onSave: async (v) => { await api('PUT', `/api/t/orders/${o.id}`, v); await refresh(); },
    onDelete: async () => { await api('DELETE', `/api/t/orders/${o.id}`); await reload(); location.hash = '#auftraege'; },
  });
}

// ---------- Auftragsdetail ----------
routes.auftrag = async (id) => {
  const o = byId(D.orders, +id);
  if (!o) { view.innerHTML = '<div class="card pad">Auftrag nicht gefunden. <a href="#auftraege">Zurück</a></div>'; return; }
  const k = byId(D.customers, o.customer_id);
  const items = D.order_items.filter((x) => x.order_id === o.id).sort((a, b) => a.sort - b.sort || a.id - b.id);
  const jobs = D.order_jobs.filter((x) => x.order_id === o.id);
  const times = D.order_times.filter((x) => x.order_id === o.id);
  const costs = D.order_costs.filter((x) => x.order_id === o.id);
  const imgs = D.images.filter((x) => x.order_id === o.id);
  const docs = D.documents.filter((x) => x.order_id === o.id);
  const K = o.kosten;
  const zw = items.reduce((s, i) => s + (+i.menge || 0) * (+i.einzelpreis || 0), 0);
  const versand = +o.versand || 0;
  const ku = S.kleinunternehmer === '1';
  const ust = ku ? 0 : +S.ust_satz || 0;
  const gesamt = (zw + versand) * (1 + ust / 100);
  const parts = [['maschine', 'Maschinen'], ['material', 'Material'], ['arbeit', 'Arbeitszeit'], ['fremd', 'Zubehör / Fremd']];
  const perPerson = {};
  times.forEach((t) => { perPerson[t.person_id] = (perPerson[t.person_id] || 0) + (+t.stunden || 0); });

  view.innerHTML = `
  <div class="ohead">
    <div class="t"><div class="nr"><a href="#auftraege">Aufträge</a> › ${esc(o.nr)}</div><h1>${esc(o.titel)}</h1>
      <div class="meta">${k ? `<a href="#kunde/${k.id}">👤 ${esc(kname(k))}</a>` : '<span class="warnc">kein Kunde zugeordnet</span>'}
        <span>📅 ${dmy(o.eingang)}</span>${o.termin ? `<span class="${o.termin < today() && OPEN_STATUS.includes(o.status) ? 'err' : ''}">⏰ fertig bis ${dmy(o.termin)}</span>` : ''}
        ${o.vertrieb ? `<span>🛍 ${esc(o.vertrieb)}</span>` : ''}${o.uebergabe ? `<span>${o.uebergabe === 'versand' ? '📦 Versand' : '🤝 Abholung'}</span>` : ''}</div></div>
    <select class="status" id="oStatus">${D.status_list.map((s) => opt(s, STATUS_LABEL[s], o.status)).join('')}</select>
    <button class="secondary" id="oEdit">✎ Bearbeiten</button>
  </div>
  <div class="grid2">
  <div>
    <div class="card"><div class="ch"><h3>Bestellte Artikel</h3>
        <button class="secondary small" id="genP" title="Positionen aus der Kalkulation erzeugen">⚡ Aus Kalkulation</button>
        <button class="small" id="addItem">+ Artikel</button></div>
      <div class="tblwrap"><table class="tbl posed"><thead><tr><th>Artikel / Beschreibung</th><th>Farbe / Material / Größe</th><th>Personalisierung</th><th class="num">Menge</th><th>Einh.</th><th class="num">Einzelpreis</th><th class="num">Gesamt</th><th></th></tr></thead>
      <tbody id="itemRows">${items.map((i) => `<tr data-id="${i.id}">
        <td><input data-f="bezeichnung" value="${esc(i.bezeichnung)}" placeholder="Artikel"><input data-f="beschreibung" class="desc" value="${esc(i.beschreibung)}" placeholder="Beschreibung (optional)"></td>
        <td><input data-f="farbe_material" value="${esc(i.farbe_material)}"></td>
        <td><input data-f="personalisierung" value="${esc(i.personalisierung)}" placeholder="genauer Text"></td>
        <td class="c-menge"><input data-f="menge" data-n inputmode="decimal" class="right" value="${esc(num(i.menge))}"></td>
        <td class="c-einheit"><input data-f="einheit" value="${esc(i.einheit)}"></td>
        <td class="c-preis"><input data-f="einzelpreis" data-n inputmode="decimal" class="right" value="${esc(nf2.format(i.einzelpreis || 0))}"></td>
        <td class="num c-ges">${eur((+i.menge || 0) * (+i.einzelpreis || 0))}</td>
        <td class="act"><button class="icon" data-delitem title="Entfernen">✕</button></td></tr>`).join('') || `<tr><td colspan="8" class="empty">Noch keine Artikel. Füge Artikel hinzu oder erzeuge sie aus der Kalkulation.</td></tr>`}</tbody>
      ${items.length ? `<tfoot><tr><td colspan="6" class="right muted">Zwischensumme</td><td class="num">${eur(zw)}</td><td></td></tr>
        ${versand ? `<tr><td colspan="6" class="right muted" style="font-weight:500">Versand</td><td class="num" style="font-weight:500">${eur(versand)}</td><td></td></tr>` : ''}
        ${!ku ? `<tr><td colspan="6" class="right muted" style="font-weight:500">zzgl. ${num(ust)} % USt</td><td class="num" style="font-weight:500">${eur((zw + versand) * ust / 100)}</td><td></td></tr>` : ''}
        <tr><td colspan="6" class="right">Gesamtbetrag</td><td class="num" style="color:var(--accent2)">${eur(gesamt)}</td><td></td></tr>
        ${+o.anzahlung ? `<tr><td colspan="6" class="right muted" style="font-weight:500">Anzahlung / Restbetrag</td><td class="num" style="font-weight:500">${eur(o.anzahlung)} / ${eur(gesamt - o.anzahlung)}</td><td></td></tr>` : ''}</tfoot>` : ''}
      </table></div>
    </div>

    <div class="card"><div class="ch"><h3>Kalkulation</h3><span class="muted small">Was steckt drin?</span></div>
      <div class="subsec"><div class="sh"><h4>🖨 Maschinenzeit & Material</h4><span class="sum">${eur(K.maschine + K.material)}</span>${(D.prints || []).length ? `<button class="small secondary" onclick="pickPrintForOrder(${o.id})" title="Gemessenen Druck aus Home Assistant übernehmen">🖨 aus HA</button>` : ''}<button class="small secondary" onclick="editJob(null, ${o.id})">+ Druck / Laser</button></div>
        ${jobs.length ? `<div class="tblwrap"><table class="tbl"><thead><tr><th>Datum</th><th>Maschine</th><th>Was</th><th>Material</th><th class="num">Zeit</th><th class="num">Menge</th><th class="num">Kosten</th></tr></thead><tbody>
        ${jobs.map((j) => { const m = byId(D.machines, j.machine_id); const mat = byId(D.materials, j.material_id);
          return `<tr class="click" onclick="editJob(${j.id})"><td class="nowrap">${dmy(j.datum)}</td><td>${m ? `<span class="legend-dot" style="background:${esc(m.farbe || '#888')}"></span>${esc(m.name)}` : '–'}</td>
          <td>${esc(j.bezeichnung || '')}${j.stueck ? ` <span class="muted">(${num(j.stueck)} Stk)</span>` : ''}</td><td>${esc(mat ? mat.name : '–')}</td><td class="num">${hm(j.dauer_h)} h</td>
          <td class="num">${j.menge ? num(j.menge) + (mat && mat.einheit === 'kg' ? ' g' : ' ' + esc(mat ? mat.einheit : '')) : '–'}</td><td class="num">${eur(j.kosten_maschine + j.kosten_material)}${j.kwh != null ? `<div class="sub" title="Strom gemessen in Home Assistant">⚡ ${num(j.kwh)} kWh</div>` : ''}</td></tr>`; }).join('')}
        </tbody></table></div>` : '<div class="empty small">Noch keine Druck-/Laserzeiten erfasst.</div>'}</div>
      <div class="subsec"><div class="sh"><h4>⏱ Arbeitszeit</h4><span class="sum">${eur(K.arbeit)}</span><button class="small secondary" onclick="editTime(null, ${o.id})">+ Zeit</button></div>
        ${times.length ? `<div class="tblwrap"><table class="tbl"><thead><tr><th>Datum</th><th>Person</th><th>Tätigkeit</th><th class="num">Stunden</th><th class="num">Kosten</th></tr></thead><tbody>
        ${times.map((t) => { const p = byId(D.persons, t.person_id); return `<tr class="click" onclick="editTime(${t.id})"><td class="nowrap">${dmy(t.datum)}</td>
          <td>${p ? `<span class="legend-dot" style="background:${esc(p.farbe || '#888')}"></span>${esc(p.name)}` : '–'}</td><td>${esc(t.taetigkeit || '')}</td><td class="num">${hm(t.stunden)} h</td><td class="num">${eur(t.kosten)}</td></tr>`; }).join('')}
        </tbody></table></div>` : '<div class="empty small">Noch keine Arbeitszeit erfasst.</div>'}</div>
      <div class="subsec"><div class="sh"><h4>🧩 Zubehör & Fremdkosten</h4><span class="sum">${eur(K.fremd)}</span><button class="small secondary" onclick="editCost(null, ${o.id})">+ Kosten</button></div>
        ${costs.length ? `<div class="tblwrap"><table class="tbl"><tbody>${costs.map((x) => `<tr class="click" onclick="editCost(${x.id})"><td class="nowrap" style="width:110px">${dmy(x.datum)}</td><td>${esc(x.bezeichnung)}</td><td class="num">${eur(x.betrag)}</td></tr>`).join('')}</tbody></table></div>`
          : '<div class="empty small">z. B. Magnete, Schlüsselringe, Verpackung, Porto-Einkauf …</div>'}</div>
    </div>

    ${(o.beschreibung || o.wuensche || o.notizen) ? `<div class="card"><div class="ch"><h3>Beschreibung & Hinweise</h3></div><div class="cb">
      ${o.beschreibung ? `<p style="white-space:pre-wrap;margin-top:0">${esc(o.beschreibung)}</p>` : ''}
      ${o.wuensche ? `<p style="white-space:pre-wrap"><b>Besondere Wünsche:</b><br>${esc(o.wuensche)}</p>` : ''}
      ${o.notizen ? `<p class="muted" style="white-space:pre-wrap;margin-bottom:0"><b>Notizen:</b><br>${esc(o.notizen)}</p>` : ''}</div></div>` : ''}
  </div>

  <div>
    <div class="card"><div class="ch"><h3>Kosten & Preis</h3></div><div class="cb sumbox">
      <div class="stackbar">${parts.map(([key]) => K.selbstkosten ? `<div class="c-${key}" style="width:${(K[key] / K.selbstkosten) * 100}%" title="${key}"></div>` : '').join('')}</div>
      ${parts.map(([key, l]) => `<div class="row"><span><span class="legend-dot c-${key}"></span>${l}</span><span>${eur(K[key])}</span></div>`).join('')}
      <div class="row total"><span>Selbstkosten</span><span>${eur(K.selbstkosten)}</span></div>
      <div class="row"><span>+ ${num(K.aufschlag_pct)} % Aufschlag → empfohlen (netto)</span><span>${eur(K.empfohlen)}</span></div>
      ${K.stueck > 1 ? `<div class="row"><span>pro Stück (${num(K.stueck)} Stk)</span><span>${eur(K.empfohlen / K.stueck)}</span></div>` : ''}
      <div class="row total"><span>Artikel laut Bestellung (netto)</span><span>${eur(K.umsatz)}</span></div>
      <div class="row big"><span>Gewinn</span><span class="${K.gewinn < 0 ? 'err' : ''}">${K.umsatz ? eur(K.gewinn) : '–'}</span></div>
      <div class="muted tiny">Maschinen ${hm(K.stunden_maschine)} h · Arbeit ${hm(K.stunden_arbeit)} h${Object.keys(perPerson).length ? ' (' + Object.entries(perPerson).map(([pid, h]) => `${esc((byId(D.persons, +pid) || {}).name || '?')} ${hm(h)}`).join(', ') + ')' : ''}</div>
    </div></div>

    <div class="card"><div class="ch"><h3>Dokumente</h3></div>
      <ul class="list-compact">
        <li><div class="grow">📝 <b>Kundenbestellung</b><div class="tiny muted">Bestellformular mit allen Angaben – zum Unterschreiben</div></div>
          <a class="button secondary small" target="_blank" href="/api/orders/${o.id}/bestellung.pdf">PDF</a>
          ${D.storage_ok ? `<button class="ghost small" title="Im Auftragsordner speichern" onclick="bestellungToFolder(${o.id})">💾</button>` : ''}</li>
        ${docs.map((d) => `<li class="click" onclick="docActions(${d.id})"><div class="grow">${d.typ === 'rechnung' ? '🧾' : '📄'} <b>${d.typ === 'rechnung' ? 'Rechnung' : 'Angebot'} ${esc(d.nr)}</b>
          <div class="tiny muted">${dmy(d.datum)} · ${eur(d.brutto)}</div></div>${chip(d.status === 'offen' && d.typ === 'rechnung' && d.faellig < today() ? 'ueberfaellig' : d.status, d.status === 'offen' && d.typ === 'rechnung' && d.faellig < today() ? 'überfällig' : DOC_STATUS[d.status])}</li>`).join('')}
      </ul>
      <div class="cb" style="display:flex;gap:8px;flex-wrap:wrap;border-top:1px solid var(--line)">
        <button class="secondary small" onclick="docEditor({orderId:${o.id}, typ:'angebot'})">+ Angebot</button>
        <button class="small" onclick="docEditor({orderId:${o.id}, typ:'rechnung'})">+ Rechnung erstellen</button></div>
    </div>

    <div class="card"><div class="ch"><h3>Bilder</h3><span class="muted small">${imgs.length || ''}</span></div>
      ${imgs.length ? `<div class="gallery">${imgs.map((im, i) => `<div class="img" data-i="${i}"><img loading="lazy" src="/bilder/${esc(im.datei.replace('.jpg', '_t.jpg'))}" alt="">
        ${im.titel ? `<div class="cap">${esc(im.titel)}</div>` : ''}<button class="x" data-imgdel="${im.id}" title="Bild löschen">✕</button></div>`).join('')}</div>` : ''}
      <label class="drop" id="imgDrop">📷 Bilder hierher ziehen oder <u>auswählen</u> (auch Handy-Kamera, HEIC)<input type="file" accept="image/*,.heic,.heif" multiple hidden id="imgInput"></label>
    </div>

    <div class="card"><div class="ch"><h3>Auftragsordner</h3>${D.storage_ok ? '' : '<a href="#einstellungen/netz" class="small">einrichten →</a>'}</div>
      <div id="folderBox">${D.storage_ok ? '<div class="empty small">Lade …</div>' : '<div class="cb small muted">Noch kein Netzlaufwerk eingerichtet. Unter Einstellungen → Netzlaufwerk kannst du die Freigabe für eure Kundenaufträge hinterlegen. Dann bekommt jeder Auftrag automatisch einen eigenen Ordner.</div>'}</div>
    </div>
  </div></div>`;

  $('#oStatus').onchange = async (e) => { try { await api('PUT', `/api/t/orders/${o.id}`, { status: e.target.value }); await refresh(); toast('Status geändert'); } catch (err) { fail(err); } };
  $('#oEdit').onclick = () => editOrder(o);

  // Positionen inline bearbeiten
  $('#itemRows').addEventListener('change', async (e) => {
    const inp = e.target.closest('input[data-f]');
    if (!inp) return;
    const tr = inp.closest('tr');
    const val = inp.dataset.n !== undefined ? parseNum(inp.value) : inp.value;
    try { await api('PUT', `/api/t/order_items/${tr.dataset.id}`, { [inp.dataset.f]: val }); await refresh(); } catch (err) { fail(err); }
  });
  $('#itemRows').addEventListener('click', async (e) => {
    const b = e.target.closest('[data-delitem]');
    if (!b) return;
    try { await api('DELETE', `/api/t/order_items/${b.closest('tr').dataset.id}`); await refresh(); } catch (err) { fail(err); }
  });
  $('#addItem').onclick = async () => {
    try { await api('POST', '/api/t/order_items', { order_id: o.id, bezeichnung: '', menge: 1, einheit: 'Stk', einzelpreis: 0 }); await refresh();
      const rows = $$('#itemRows tr'); const last = rows[rows.length - 1]; last && $('input', last).focus(); } catch (err) { fail(err); }
  };
  $('#genP').onclick = () => genItems(o);

  // Bilder
  $$('.gallery .img').forEach((el) => el.addEventListener('click', (e) => { if (!e.target.closest('[data-imgdel]')) lightbox(imgs, +el.dataset.i); }));
  $$('[data-imgdel]').forEach((b) => b.onclick = async (e) => { e.stopPropagation(); if (!confirm('Bild löschen?')) return; try { await api('DELETE', `/api/t/images/${b.dataset.imgdel}`); await refresh(); } catch (err) { fail(err); } });
  setupDrop($('#imgDrop'), $('#imgInput'), async (files) => {
    const fd = new FormData(); files.forEach((f) => fd.append('files', f));
    toast(`Lade ${files.length} Bild(er) hoch …`);
    try { const r = await api('POST', `/api/orders/${o.id}/images`, fd); r.errors.forEach((x) => toast(x, 'err')); await refresh(); } catch (err) { fail(err); }
  });

  if (D.storage_ok) folderView(o, '');
};

function setupDrop(zone, input, onFiles) {
  input.onchange = () => { if (input.files.length) onFiles([...input.files]); input.value = ''; };
  zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('over'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('over'));
  zone.addEventListener('drop', (e) => { e.preventDefault(); zone.classList.remove('over'); if (e.dataTransfer.files.length) onFiles([...e.dataTransfer.files]); });
}

window.bestellungToFolder = async (oid) => {
  try { const r = await api('POST', `/api/orders/${oid}/bestellung/to-folder`); toast(`${r.name} im Auftragsordner gespeichert`); folderView(byId(D.orders, oid), ''); } catch (e) { fail(e); }
};

async function folderView(o, sub) {
  const box = $('#folderBox');
  if (!box) return;
  if (!o.ordner) {
    box.innerHTML = `<div class="cb small muted">Für diesen Auftrag gibt es noch keinen Ordner.</div>
      <div class="cb" style="padding-top:0;display:flex;gap:8px;flex-wrap:wrap"><button class="small" id="mkFolder">📁 Ordner anlegen</button><button class="small secondary" id="linkFolder">Vorhandenen Ordner zuordnen</button></div>`;
    $('#mkFolder').onclick = async () => { try { await api('POST', `/api/orders/${o.id}/folder`); await refresh(); toast('Ordner angelegt'); } catch (e) { fail(e); } };
    $('#linkFolder').onclick = () => linkFolder(o);
    return;
  }
  let r;
  try { r = await api('GET', `/api/orders/${o.id}/files?sub=${encodeURIComponent(sub)}`); } catch (e) {
    box.innerHTML = `<div class="cb small err">${esc(e.message)}</div>`; return;
  }
  const crumbs = sub ? sub.split('/').filter(Boolean) : [];
  box.innerHTML = `<div class="cb" style="padding-bottom:6px"><div class="pathbox"><code title="${esc(r.pfad)}">${esc(r.pfad)}</code><button class="small secondary" id="cpPath" title="Pfad kopieren → im Windows-Explorer oben einfügen">📋 Kopieren</button></div>
      <div class="tiny dim" style="margin-top:5px">Pfad kopieren und im Windows-Explorer in die Adresszeile einfügen.</div></div>
    ${crumbs.length ? `<div class="crumbs"><a data-sub="">${esc(o.ordner.split('/').pop())}</a>${crumbs.map((c, i) => ` › <a data-sub="${esc(crumbs.slice(0, i + 1).join('/'))}">${esc(c)}</a>`).join('')}</div>` : ''}
    ${r.fehlt ? `<div class="cb small warnc">Ordner existiert nicht (mehr). <button class="small" id="mkFolder2">Neu anlegen</button></div>` : ''}
    ${r.files.length ? `<ul class="files">${r.files.map((f) => `<li><span class="ic">${f.dir ? '📁' : fileIcon(f.name)}</span>
      ${f.dir ? `<a class="n" data-sub="${esc((sub ? sub + '/' : '') + f.name)}" href="javascript:void 0">${esc(f.name)}</a>`
        : `<a class="n" target="_blank" href="/api/orders/${o.id}/file?path=${encodeURIComponent((sub ? sub + '/' : '') + f.name)}">${esc(f.name)}</a>`}
      <span class="tiny muted nowrap">${f.dir ? '' : fsize(f.size)}</span>
      ${f.dir ? '' : `<a class="icon" title="Herunterladen" href="/api/orders/${o.id}/file?download=1&path=${encodeURIComponent((sub ? sub + '/' : '') + f.name)}">⬇</a>`}</li>`).join('')}</ul>`
      : (r.fehlt ? '' : '<div class="empty small">Ordner ist leer.</div>')}
    <label class="drop" id="fDrop">⬆ Dateien hierher ziehen oder <u>auswählen</u> (STL, 3MF, LightBurn, SVG, Fotos …)<input type="file" multiple hidden id="fInput"></label>
    <div class="cb tiny" style="padding-top:0"><a href="javascript:void 0" id="relink">Anderen Ordner zuordnen</a></div>`;
  $('#cpPath').onclick = () => copyText(r.pfad);
  $$('[data-sub]', box).forEach((a) => a.onclick = (e) => { e.preventDefault(); folderView(o, a.dataset.sub); });
  if ($('#mkFolder2')) $('#mkFolder2').onclick = async () => { try { await api('POST', `/api/orders/${o.id}/folder`); folderView(o, ''); } catch (e) { fail(e); } };
  $('#relink').onclick = () => linkFolder(o);
  setupDrop($('#fDrop'), $('#fInput'), async (files) => {
    const fd = new FormData(); files.forEach((f) => fd.append('files', f)); fd.append('sub', sub);
    toast(`Lade ${files.length} Datei(en) hoch …`);
    try { await api('POST', `/api/orders/${o.id}/files`, fd); toast('Hochgeladen'); folderView(o, sub); } catch (e) { fail(e); }
  });
}
const fsize = (b) => (b > 1048576 ? (b / 1048576).toFixed(1) + ' MB' : b > 1024 ? Math.round(b / 1024) + ' KB' : b + ' B');
function fileIcon(n) {
  const e = n.split('.').pop().toLowerCase();
  if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'heic'].includes(e)) return '🖼';
  if (e === 'pdf') return '📕';
  if (['stl', '3mf', 'step', 'stp', 'obj', 'f3d', 'gcode'].includes(e)) return '🧊';
  if (['lbrn', 'lbrn2', 'svg', 'dxf', 'ai', 'eps'].includes(e)) return '✏️';
  return '📄';
}
function linkFolder(o) {
  openForm({
    title: 'Ordner zuordnen',
    fields: [{ k: 'ordner', l: 'Pfad relativ zum Auftrags-Hauptordner', ph: 'z. B. 2026/Huber Anna - Hochzeit', hint: 'Unterordner mit / trennen. Der Ordner wird angelegt, falls er noch nicht existiert.' }],
    values: { ordner: o.ordner || '' },
    onSave: async (v) => { await api('PUT', `/api/t/orders/${o.id}`, { ordner: v.ordner }); if (v.ordner) await api('POST', `/api/orders/${o.id}/folder`); await refresh(); },
  });
}

function lightbox(list, i) {
  const lb = $('#lightbox');
  const show = () => { $('img', lb).src = '/bilder/' + list[i].datei; $('.lb-cap', lb).textContent = list[i].titel || list[i].original || ''; };
  lb.classList.remove('hidden'); show();
  const close = () => { lb.classList.add('hidden'); document.removeEventListener('keydown', key); };
  const key = (e) => { if (e.key === 'Escape') close(); if (e.key === 'ArrowRight') { i = (i + 1) % list.length; show(); } if (e.key === 'ArrowLeft') { i = (i - 1 + list.length) % list.length; show(); } };
  document.addEventListener('keydown', key);
  $('.lb-close', lb).onclick = close;
  lb.onclick = (e) => { if (e.target === lb) close(); };
  $('.lb-next', lb).onclick = () => { i = (i + 1) % list.length; show(); };
  $('.lb-prev', lb).onclick = () => { i = (i - 1 + list.length) % list.length; show(); };
}

function genItems(o) {
  const K = o.kosten;
  if (!K.selbstkosten) { toast('Erst Druck-/Laserzeit, Arbeitszeit oder Kosten erfassen – dann kann ich daraus Preise berechnen.', 'warn', 6000); return; }
  openForm({
    title: 'Artikel aus Kalkulation erzeugen',
    fields: [
      { t: 'html', html: `<div class="notice">Selbstkosten <b>${eur(K.selbstkosten)}</b> + ${num(K.aufschlag_pct)} % Aufschlag = <b>${eur(K.empfohlen)}</b> netto (gerundet auf ${esc(S.rundung)} €).</div>` },
      { k: 'modus', l: 'Art', t: 'select', o: [['pauschal', 'Pauschal – eine Position mit dem empfohlenen Preis'], ['detail', 'Detailliert – Druck/Laser, Arbeitszeit, Zubehör einzeln']] },
      { k: 'stueck', l: 'Stückzahl (bei pauschal)', t: 'num', def: K.stueck || 1, s: 6 },
      { k: 'ersetzen', l: 'Vorhandene Artikel ersetzen', t: 'check', def: 1, s: 6 },
    ],
    values: { ersetzen: 1 },
    saveLabel: 'Erzeugen',
    onSave: async (v) => { await api('POST', `/api/orders/${o.id}/items/generate`, { modus: v.modus, stueck: v.stueck, ersetzen: !!v.ersetzen }); await refresh(); toast('Artikel erzeugt – Preise kannst du direkt in der Tabelle anpassen.'); },
  });
}

// ---------- Kalkulationseinträge ----------
function machineOpts(sel) { return opt('', '— keine —', sel) + D.machines.filter((m) => m.aktiv || m.id === +sel).map((m) => opt(m.id, `${m.name} (${eur3(m.satz)}/h)`, sel)).join(''); }
function materialOpts(sel) { return opt('', '— kein Material —', sel) + D.materials.filter((m) => m.aktiv || m.id === +sel).map((m) => opt(m.id, `${m.name}${m.farbe && m.farbe !== 'diverse' ? ' · ' + m.farbe : ''} (${eur(m.preis)}/${m.einheit})`, sel)).join(''); }
function personOpts(sel) { return D.persons.filter((p) => p.aktiv || p.id === +sel).map((p) => opt(p.id, p.name, sel)).join(''); }

window.editJob = (id, orderId) => {
  const j = id ? byId(D.order_jobs, id) : { order_id: orderId, datum: today(), machine_id: (D.machines[0] || {}).id };
  openForm({
    title: id ? 'Druck / Laser bearbeiten' : 'Druck / Laser erfassen',
    fields: [
      { k: 'machine_id', l: 'Maschine', t: 'select', o: machineOpts, s: 6 },
      { k: 'datum', l: 'Datum', t: 'date', s: 6 },
      { k: 'bezeichnung', l: 'Was wurde gedruckt / gelasert?', ph: 'z. B. Schlüsselanhänger Platte 1' },
      { k: 'dauer_h', l: 'Dauer (Std:Min)', t: 'h', s: 4, hint: 'z. B. 2:15 oder 2h15m – steht im Slicer / LightBurn' },
      { k: 'material_id', l: 'Material', t: 'select', o: materialOpts, s: 8 },
      { k: 'menge', l: 'Materialmenge', t: 'num', s: 4, hint: '<span id="mengeHint">Gramm bei Filament, sonst Stück/m²</span>' },
      { k: 'stueck', l: 'Ergibt Stück', t: 'num', s: 4, hint: 'für Preis pro Stück' },
      { k: 'notizen', l: 'Notiz', s: 4 },
    ],
    values: j,
    onSave: async (v) => { v.order_id = j.order_id; await api(id ? 'PUT' : 'POST', id ? `/api/t/order_jobs/${id}` : '/api/t/order_jobs', v); await refresh(); },
    onDelete: id ? async () => { await api('DELETE', `/api/t/order_jobs/${id}`); await refresh(); } : null,
    after: (el) => {
      const upd = () => { const m = byId(D.materials, +$('[name=material_id]', el).value); $('#mengeHint', el).textContent = m ? (m.einheit === 'kg' ? 'in Gramm (laut Slicer)' : `in ${m.einheit}`) : 'Gramm bei Filament, sonst Stück/m²'; };
      $('[name=material_id]', el).onchange = upd; upd();
    },
  });
};

window.editTime = (id, orderId) => {
  const t = id ? byId(D.order_times, id) : { order_id: orderId, datum: today(), person_id: (D.persons[0] || {}).id };
  openForm({
    title: id ? 'Arbeitszeit bearbeiten' : 'Arbeitszeit erfassen',
    fields: [
      { k: 'person_id', l: 'Wer?', t: 'select', o: personOpts, s: 6 },
      { k: 'datum', l: 'Datum', t: 'date', s: 6 },
      { k: 'stunden', l: 'Dauer (Std:Min)', t: 'h', s: 4, hint: 'z. B. 0:45 oder 1:30' },
      { k: 'taetigkeit', l: 'Tätigkeit', s: 8, list: ['Design / Konstruktion', 'Vorbereitung', 'Nachbearbeitung', 'Bemalen / Veredeln', 'Montage', 'Verpackung & Versand', 'Kundengespräch'] },
    ],
    values: t,
    onSave: async (v) => { v.order_id = t.order_id; await api(id ? 'PUT' : 'POST', id ? `/api/t/order_times/${id}` : '/api/t/order_times', v); await refresh(); },
    onDelete: id ? async () => { await api('DELETE', `/api/t/order_times/${id}`); await refresh(); } : null,
  });
};

window.editCost = (id, orderId) => {
  const x = id ? byId(D.order_costs, id) : { order_id: orderId, datum: today() };
  openForm({
    title: id ? 'Kosten bearbeiten' : 'Zubehör / Fremdkosten erfassen',
    fields: [
      { k: 'bezeichnung', l: 'Bezeichnung', ph: 'z. B. 10 Schlüsselringe, Geschenkbox', s: 8 },
      { k: 'betrag', l: 'Betrag €', t: 'num', s: 4 },
      { k: 'datum', l: 'Datum', t: 'date', s: 6 },
    ],
    values: x,
    onSave: async (v) => { v.order_id = x.order_id; await api(id ? 'PUT' : 'POST', id ? `/api/t/order_costs/${id}` : '/api/t/order_costs', v); await refresh(); },
    onDelete: id ? async () => { await api('DELETE', `/api/t/order_costs/${id}`); await refresh(); } : null,
  });
};

// ======================================================================
//  Rechnungen & Angebote
// ======================================================================
window.docEditor = ({ orderId, typ, docId }) => {
  const d = docId ? byId(D.documents, docId) : null;
  const o = byId(D.orders, d ? d.order_id : orderId);
  typ = d ? d.typ : typ;
  let pos;
  if (d) pos = d.positionen.map((p) => ({ ...p }));
  else {
    pos = D.order_items.filter((i) => i.order_id === orderId).sort((a, b) => a.sort - b.sort || a.id - b.id)
      .map((i) => ({ bezeichnung: i.bezeichnung, beschreibung: i.beschreibung, farbe_material: i.farbe_material, personalisierung: i.personalisierung, menge: i.menge, einheit: i.einheit, einzelpreis: i.einzelpreis }));
    if (o && +o.versand) pos.push({ bezeichnung: 'Versand', menge: 1, einheit: 'pausch.', einzelpreis: +o.versand });
  }
  if (!pos.length) pos.push({ bezeichnung: '', menge: 1, einheit: 'Stk', einzelpreis: 0 });
  const label = typ === 'rechnung' ? 'Rechnung' : 'Angebot';
  if (!d && o && !o.customer_id) { toast('Bitte dem Auftrag zuerst einen Kunden zuordnen.', 'warn'); editOrder(o); return; }
  const tage = +(typ === 'rechnung' ? S.zahlungsziel_tage : S.angebot_gueltig_tage) || 14;
  const addDays = (iso, n) => { const x = new Date(iso); x.setDate(x.getDate() + n); return x.toISOString().slice(0, 10); };
  const v = d ? d : { datum: today(), leistungsdatum: today(), faellig: addDays(today(), tage), einleitung: S[typ + '_einleitung'], schluss: S[typ + '_schluss'], anzahlung: o && o.anzahlung };
  const ku = S.kleinunternehmer === '1';
  const ust = ku ? 0 : +S.ust_satz || 0;
  const m = modal({
    title: d ? `${label} ${d.nr} bearbeiten` : `${label} erstellen`, wide: true,
    body: `<div class="form">
      <div class="f s3"><label>Datum</label><input type="date" name="datum" value="${esc(v.datum || '')}"></div>
      ${typ === 'rechnung' ? `<div class="f s3"><label>Leistungsdatum</label><input type="date" name="leistungsdatum" value="${esc(v.leistungsdatum || '')}"></div>` : ''}
      <div class="f s3"><label>${typ === 'rechnung' ? 'Fällig am' : 'Gültig bis'}</label><input type="date" name="faellig" value="${esc(v.faellig || '')}"></div>
      ${typ === 'rechnung' ? `<div class="f s3"><label>Bereits angezahlt €</label><input name="anzahlung" inputmode="decimal" value="${v.anzahlung ? esc(String(v.anzahlung).replace('.', ',')) : ''}"></div>` : ''}
      <div class="f"><label>Einleitungstext</label><textarea name="einleitung" rows="2">${esc(v.einleitung || '')}</textarea></div>
      <div class="f"><label>Positionen</label>
        <div class="tblwrap" style="border:1px solid var(--line);border-radius:10px"><table class="tbl posed"><thead><tr><th>Bezeichnung / Beschreibung</th><th>Farbe / Material</th><th>Personalisierung</th><th class="num">Menge</th><th>Einh.</th><th class="num">Einzelpreis</th><th class="num">Gesamt</th><th></th></tr></thead>
        <tbody id="dpos"></tbody><tfoot><tr><td colspan="6" class="right">${ku ? 'Gesamtbetrag' : 'Summe netto'}</td><td class="num" id="dsum"></td><td></td></tr></tfoot></table></div>
        <div><button type="button" class="small secondary" id="dAdd">+ Position</button></div></div>
      <div class="f"><label>Schlusstext</label><textarea name="schluss" rows="3">${esc(v.schluss || '')}</textarea>
        <div class="hint">Platzhalter: {nr} {datum} {faellig} {gueltig} {gesamt} {zahlbetrag} {kunde}</div></div>
      ${d ? `<div class="f chk"><input type="checkbox" id="kuAkt" name="kunde_aktualisieren"><label for="kuAkt">Kundenanschrift aus der Kundenkartei neu übernehmen</label></div>` : ''}
    </div>`,
    footer: `<span class="muted small">${ku ? 'Kleinunternehmer – ohne USt.' : `zzgl. ${num(ust)} % USt.`}</span><span class="spacer"></span>
      <button class="secondary" data-cancel>Abbrechen</button><button data-save>${d ? 'Speichern & PDF neu erzeugen' : `${label} erstellen`}</button>`,
  });
  const draw = () => {
    $('#dpos', m.el).innerHTML = pos.map((p, i) => `<tr data-i="${i}">
      <td><input data-f="bezeichnung" value="${esc(p.bezeichnung)}" placeholder="Bezeichnung"><input data-f="beschreibung" class="desc" value="${esc(p.beschreibung || '')}" placeholder="Beschreibung"></td>
      <td><input data-f="farbe_material" value="${esc(p.farbe_material || '')}"></td><td><input data-f="personalisierung" value="${esc(p.personalisierung || '')}"></td>
      <td class="c-menge"><input data-f="menge" class="right" inputmode="decimal" value="${esc(num(p.menge))}"></td>
      <td class="c-einheit"><input data-f="einheit" value="${esc(p.einheit || '')}"></td>
      <td class="c-preis"><input data-f="einzelpreis" class="right" inputmode="decimal" value="${esc(nf2.format(p.einzelpreis || 0))}"></td>
      <td class="num c-ges">${eur((+p.menge || 0) * (+p.einzelpreis || 0))}</td><td class="act"><button type="button" class="icon" data-rm>✕</button></td></tr>`).join('');
    $('#dsum', m.el).textContent = eur(pos.reduce((s, p) => s + (+p.menge || 0) * (+p.einzelpreis || 0), 0));
  };
  draw();
  $('#dpos', m.el).addEventListener('change', (e) => {
    const inp = e.target.closest('[data-f]'); if (!inp) return;
    const p = pos[+inp.closest('tr').dataset.i];
    p[inp.dataset.f] = ['menge', 'einzelpreis'].includes(inp.dataset.f) ? (parseNum(inp.value) || 0) : inp.value;
    draw();
  });
  $('#dpos', m.el).addEventListener('click', (e) => { if (e.target.closest('[data-rm]')) { pos.splice(+e.target.closest('tr').dataset.i, 1); draw(); } });
  $('#dAdd', m.el).onclick = () => { pos.push({ bezeichnung: '', menge: 1, einheit: 'Stk', einzelpreis: 0 }); draw(); };
  $('[data-cancel]', m.el).onclick = m.close;
  $('[data-save]', m.el).onclick = async (e) => {
    e.target.disabled = true;
    const g = (n) => { const x = $(`[name=${n}]`, m.el); return x ? x.value : undefined; };
    const body = { datum: g('datum'), faellig: g('faellig'), einleitung: g('einleitung'), schluss: g('schluss'), positionen: pos.filter((p) => (p.bezeichnung || '').trim()) };
    if (typ === 'rechnung') { body.leistungsdatum = g('leistungsdatum'); body.anzahlung = parseNum(g('anzahlung')) || 0; }
    try {
      let r;
      if (d) { body.kunde_aktualisieren = $('#kuAkt', m.el).checked; r = await api('PUT', `/api/documents/${d.id}`, body); r.id = d.id; }
      else { body.typ = typ; r = await api('POST', `/api/orders/${orderId}/documents`, body); toast(`${label} ${r.nr} erstellt`); }
      warnIf(r);
      m.close();
      window.open(`/api/documents/${r.id}/pdf`, '_blank');
      await refresh();
    } catch (err) { fail(err); e.target.disabled = false; }
  };
};

window.docActions = (id) => {
  const d = byId(D.documents, id);
  const o = byId(D.orders, d.order_id);
  const isR = d.typ === 'rechnung';
  const m = modal({
    title: `${isR ? 'Rechnung' : 'Angebot'} ${d.nr}`,
    body: `<div class="sumbox">
      <div class="row"><span>Kunde</span><span>${esc(kname(d.kunde))}</span></div>
      ${o ? `<div class="row"><span>Auftrag</span><span><a href="#auftrag/${o.id}" data-x2>${esc(o.nr)} · ${esc(o.titel)}</a></span></div>` : ''}
      <div class="row"><span>Datum</span><span>${dmy(d.datum)}</span></div>
      <div class="row"><span>${isR ? 'Fällig am' : 'Gültig bis'}</span><span>${dmy(d.faellig)}</span></div>
      <div class="row"><span>Status</span><span>${chip(d.status, DOC_STATUS[d.status])}${d.bezahlt_am ? ` am ${dmy(d.bezahlt_am)}` : ''}</span></div>
      ${!d.kleinunternehmer ? `<div class="row"><span>Netto</span><span>${eur(d.netto)}</span></div><div class="row"><span>USt ${num(d.ust_satz)} %</span><span>${eur(d.ust)}</span></div>` : ''}
      <div class="row total"><span>Gesamt</span><span>${eur(d.brutto)}</span></div>
      ${d.anzahlung ? `<div class="row"><span>davon angezahlt</span><span>${eur(d.anzahlung)}</span></div>` : ''}
      </div>
      ${isR && d.status === 'offen' ? `<div class="form" style="margin-top:14px"><div class="f s6"><label>Bezahlt am</label><input type="date" id="payDate" value="${today()}"></div></div>` : ''}`,
    footer: `<a class="button secondary" target="_blank" href="/api/documents/${d.id}/pdf">📄 PDF ansehen</a>
      <a class="button secondary" href="/api/documents/${d.id}/pdf?download=1">⬇</a>
      <button class="secondary" data-a="edit">✎ Bearbeiten</button><span class="spacer"></span>
      ${isR ? (d.status === 'offen' ? '<button class="ok" data-a="paid">✔ Bezahlt</button><button class="danger" data-a="storno">Stornieren</button>' : `<button class="secondary" data-a="open">Wieder offen</button>`)
        : (d.status === 'offen' ? '<button class="ok" data-a="angenommen">Angenommen</button><button class="secondary" data-a="abgelehnt">Abgelehnt</button>' : '<button class="secondary" data-a="open">Wieder offen</button>')}
      <button class="danger" data-a="del" title="Löschen">🗑</button>`,
  });
  const x2 = $('[data-x2]', m.el); if (x2) x2.onclick = () => m.close();
  $$('[data-a]', m.el).forEach((b) => b.onclick = async () => {
    const a = b.dataset.a;
    try {
      if (a === 'edit') { m.close(); docEditor({ docId: d.id }); return; }
      if (a === 'paid') await api('PUT', `/api/documents/${d.id}`, { status: 'bezahlt', bezahlt_am: $('#payDate', m.el).value });
      if (a === 'storno') { if (!confirm('Rechnung stornieren?')) return; await api('PUT', `/api/documents/${d.id}`, { status: 'storniert' }); }
      if (a === 'open') await api('PUT', `/api/documents/${d.id}`, { status: 'offen' });
      if (a === 'angenommen' || a === 'abgelehnt') await api('PUT', `/api/documents/${d.id}`, { status: a });
      if (a === 'del') { if (!confirm(`${d.nr} wirklich löschen?`)) return; await api('DELETE', `/api/documents/${d.id}`); }
      m.close(); await refresh(); toast('Gespeichert');
    } catch (e) { fail(e); }
  });
};

let dFilter = { typ: 'rechnung', status: '', jahr: String(new Date().getFullYear()), q: '' };
routes.rechnungen = () => {
  const jahre = [...new Set(D.documents.map((d) => (d.datum || '').slice(0, 4)).filter(Boolean).concat(String(new Date().getFullYear())))].sort().reverse();
  view.innerHTML = `<div class="pagehead"><h1>Rechnungen & Angebote</h1>
      <a class="button secondary" id="csvR" href="#">⬇ Rechnungsliste (CSV)</a></div>
    <div class="toolbar">
      <select id="dTyp">${opt('rechnung', 'Rechnungen', dFilter.typ)}${opt('angebot', 'Angebote', dFilter.typ)}</select>
      <select id="dSt">${opt('', 'Alle Status', dFilter.status)}${['offen', 'bezahlt', 'storniert', 'angenommen', 'abgelehnt'].map((s) => opt(s, DOC_STATUS[s], dFilter.status)).join('')}${opt('ueber', 'überfällig', dFilter.status)}</select>
      <select id="dJahr">${opt('', 'Alle Jahre', dFilter.jahr)}${jahre.map((j) => opt(j, j, dFilter.jahr)).join('')}</select>
      <input type="search" id="dQ" placeholder="Nummer oder Kunde …" value="${esc(dFilter.q)}">
    </div>
    <div class="tiles" id="dTiles"></div>
    <div class="card"><div class="tblwrap" id="dList"></div></div>
    <p class="muted small">Neue Rechnungen und Angebote erstellst du direkt im jeweiligen Auftrag.</p>`;
  const draw = () => {
    const q = dFilter.q.toLowerCase();
    const list = D.documents.filter((d) => d.typ === dFilter.typ && (!dFilter.jahr || (d.datum || '').startsWith(dFilter.jahr))
      && (!dFilter.status || (dFilter.status === 'ueber' ? d.status === 'offen' && d.faellig < today() : d.status === dFilter.status))
      && (!q || `${d.nr} ${kname(d.kunde)}`.toLowerCase().includes(q)));
    const sum = (f) => list.filter(f).reduce((s, d) => s + (d.brutto || 0), 0);
    $('#dTiles').innerHTML = dFilter.typ === 'rechnung' ? `<div class="tile"><span>Summe (brutto)</span><b>${eur(sum((d) => d.status !== 'storniert'))}</b><small>${list.length} Rechnungen</small></div>
      <div class="tile"><span>bezahlt</span><b class="okc">${eur(sum((d) => d.status === 'bezahlt'))}</b></div>
      <div class="tile"><span>offen</span><b class="warnc">${eur(list.filter((d) => d.status === 'offen').reduce((s, d) => s + d.brutto - (d.anzahlung || 0), 0))}</b><small>abzüglich Anzahlungen</small></div>` : '';
    $('#csvR').href = `/api/export/rechnungen.csv${dFilter.jahr ? '?jahr=' + dFilter.jahr : ''}`;
    $('#dList').innerHTML = list.length ? `<table class="tbl"><thead><tr><th>Nummer</th><th>Datum</th><th>Kunde</th><th>Auftrag</th><th class="num">Netto</th><th class="num">Brutto</th><th>${dFilter.typ === 'rechnung' ? 'Fällig' : 'Gültig bis'}</th><th>Status</th><th></th></tr></thead><tbody>
      ${list.map((d) => { const o = byId(D.orders, d.order_id); const ue = d.typ === 'rechnung' && d.status === 'offen' && d.faellig < today();
        return `<tr class="click" data-id="${d.id}"><td class="nowrap"><b>${esc(d.nr)}</b></td><td class="nowrap">${dmy(d.datum)}</td><td>${esc(kname(d.kunde))}</td>
        <td>${o ? `<span class="muted">${esc(o.nr)}</span> ${esc(o.titel)}` : '–'}</td><td class="num">${eur(d.netto)}</td><td class="num">${eur(d.brutto)}</td>
        <td class="nowrap ${ue ? 'err' : ''}">${dmy(d.faellig)}</td><td>${chip(ue ? 'ueberfaellig' : d.status, ue ? 'überfällig' : DOC_STATUS[d.status])}</td>
        <td class="act"><a class="icon" target="_blank" href="/api/documents/${d.id}/pdf" onclick="event.stopPropagation()" title="PDF">📄</a></td></tr>`; }).join('')}
      </tbody></table>` : '<div class="empty">Keine Einträge.</div>';
    $$('#dList tr[data-id]').forEach((tr) => tr.onclick = () => docActions(+tr.dataset.id));
  };
  $('#dTyp').onchange = (e) => { dFilter.typ = e.target.value; draw(); };
  $('#dSt').onchange = (e) => { dFilter.status = e.target.value; draw(); };
  $('#dJahr').onchange = (e) => { dFilter.jahr = e.target.value; draw(); };
  $('#dQ').oninput = (e) => { dFilter.q = e.target.value; draw(); };
  draw();
};

// ======================================================================
//  Kunden
// ======================================================================
const custFields = [
  { k: 'firma', l: 'Firma (optional)', s: 12 },
  { k: 'anrede', l: 'Anrede', t: 'select', o: [['', '–'], ['Frau', 'Frau'], ['Herr', 'Herr'], ['Familie', 'Familie']], s: 3 },
  { k: 'vorname', l: 'Vorname', s: 4 }, { k: 'nachname', l: 'Nachname', s: 5 },
  { k: 'strasse', l: 'Straße & Hausnummer', s: 12 },
  { k: 'plz', l: 'PLZ', s: 3 }, { k: 'ort', l: 'Ort', s: 6 }, { k: 'land', l: 'Land', s: 3, ph: 'AT' },
  { k: 'telefon', l: 'Telefon', s: 6, t: 'tel' }, { k: 'email', l: 'E-Mail', s: 6, t: 'email' },
  { k: 'uid', l: 'UID-Nummer (nur Firmen)', s: 6 },
  { k: 'notizen', l: 'Notizen', t: 'textarea', rows: 2 },
];
window.editCustomer = (k, after) => openForm({
  title: k ? `Kunde ${k.nr} bearbeiten` : 'Neuer Kunde', fields: custFields, values: k || {}, wide: true,
  onSave: async (v) => {
    if (!v.firma && !v.vorname && !v.nachname) throw new Error('Bitte Name oder Firma angeben');
    const r = await api(k ? 'PUT' : 'POST', k ? `/api/t/customers/${k.id}` : '/api/t/customers', v);
    await reload();
    if (after) after(r.row); else render();
  },
  onDelete: k ? async () => { await api('DELETE', `/api/t/customers/${k.id}`); await reload(); location.hash = '#kunden'; render(); } : null,
});
window.newCustomer = () => editCustomer(null, (row) => { location.hash = '#kunde/' + row.id; });

let kq = '';
routes.kunden = () => {
  view.innerHTML = `<div class="pagehead"><h1>Kunden</h1><span class="sub">${D.customers.length}</span>
    <a class="button secondary" href="/api/export/kunden.csv">⬇ CSV</a><button onclick="newCustomer()">+ Neuer Kunde</button></div>
    <div class="toolbar"><input type="search" id="kq" placeholder="Name, Ort, Telefon, E-Mail …" value="${esc(kq)}"></div>
    <div class="card"><div class="tblwrap" id="kList"></div></div>`;
  const umsatz = {};
  D.documents.forEach((d) => { if (d.typ === 'rechnung' && d.status !== 'storniert') umsatz[d.customer_id] = (umsatz[d.customer_id] || 0) + d.netto; });
  const draw = () => {
    const q = kq.toLowerCase();
    const list = D.customers.filter((k) => !q || `${k.nr} ${kname(k)} ${k.vorname} ${k.nachname} ${k.ort} ${k.telefon} ${k.email}`.toLowerCase().includes(q))
      .sort((a, b) => kname(a).localeCompare(kname(b), 'de'));
    $('#kList').innerHTML = list.length ? `<table class="tbl"><thead><tr><th>Nr.</th><th>Name</th><th>Ort</th><th>Kontakt</th><th class="num">Aufträge</th><th class="num">Umsatz</th></tr></thead><tbody>
      ${list.map((k) => `<tr class="click" onclick="location.hash='#kunde/${k.id}'"><td class="muted nowrap">${esc(k.nr)}</td><td><b>${esc(kname(k))}</b>${k.firma && (k.vorname || k.nachname) ? `<div class="sub">${esc([k.vorname, k.nachname].filter(Boolean).join(' '))}</div>` : ''}</td>
        <td>${esc([k.plz, k.ort].filter(Boolean).join(' '))}</td><td class="small">${esc(k.telefon || '')}${k.telefon && k.email ? '<br>' : ''}${esc(k.email || '')}</td>
        <td class="num">${D.orders.filter((o) => o.customer_id === k.id).length}</td><td class="num">${eur(umsatz[k.id] || 0)}</td></tr>`).join('')}
      </tbody></table>` : `<div class="empty">${D.customers.length ? 'Nichts gefunden.' : 'Noch keine Kunden angelegt.'}</div>`;
  };
  $('#kq').oninput = (e) => { kq = e.target.value; draw(); };
  draw();
};

routes.kunde = (id) => {
  const k = byId(D.customers, +id);
  if (!k) { view.innerHTML = '<div class="card pad">Kunde nicht gefunden.</div>'; return; }
  const orders = D.orders.filter((o) => o.customer_id === k.id).sort((a, b) => b.id - a.id);
  const docs = D.documents.filter((d) => d.customer_id === k.id);
  const ums = docs.filter((d) => d.typ === 'rechnung' && d.status !== 'storniert').reduce((s, d) => s + d.netto, 0);
  view.innerHTML = `<div class="ohead"><div class="t"><div class="nr"><a href="#kunden">Kunden</a> › ${esc(k.nr)}</div><h1>${esc(kname(k))}</h1>
      <div class="meta">${k.telefon ? `<a href="tel:${esc(k.telefon)}">📞 ${esc(k.telefon)}</a>` : ''}${k.email ? `<a href="mailto:${esc(k.email)}">✉ ${esc(k.email)}</a>` : ''}</div></div>
      <button class="secondary" id="kEdit">✎ Bearbeiten</button><button id="kOrder">+ Auftrag für ${esc(k.vorname || kname(k))}</button></div>
    <div class="tiles"><div class="tile"><span>Aufträge</span><b>${orders.length}</b></div><div class="tile"><span>Umsatz (netto)</span><b>${eur(ums)}</b></div>
      <div class="tile"><span>Offen</span><b>${eur(docs.filter((d) => d.typ === 'rechnung' && d.status === 'offen').reduce((s, d) => s + d.brutto - (d.anzahlung || 0), 0))}</b></div></div>
    <div class="grid2"><div class="card"><div class="ch"><h3>Aufträge</h3></div>
      ${orders.length ? `<div class="tblwrap"><table class="tbl"><tbody>${orders.map((o) => `<tr class="click" onclick="location.hash='#auftrag/${o.id}'"><td class="muted nowrap">${esc(o.nr)}</td><td><b>${esc(o.titel)}</b></td><td>${chip(o.status)}</td><td class="nowrap">${dmy(o.eingang)}</td><td class="num">${eur(o.kosten.umsatz)}</td></tr>`).join('')}</tbody></table></div>` : '<div class="empty">Noch keine Aufträge.</div>'}</div>
    <div><div class="card"><div class="ch"><h3>Anschrift</h3></div><div class="cb">${esc([k.firma, [k.anrede, k.vorname, k.nachname].filter(Boolean).join(' '), k.strasse, [k.plz, k.ort].filter(Boolean).join(' '), k.land].filter(Boolean).join('\n')).replace(/\n/g, '<br>') || '<span class="muted">–</span>'}
      ${k.uid ? `<div class="muted small" style="margin-top:6px">UID ${esc(k.uid)}</div>` : ''}${k.notizen ? `<p class="muted small" style="white-space:pre-wrap">${esc(k.notizen)}</p>` : ''}</div></div>
      <div class="card"><div class="ch"><h3>Rechnungen & Angebote</h3></div>${docs.length ? `<ul class="list-compact">${docs.map((d) => `<li class="click" onclick="docActions(${d.id})"><div class="grow"><b>${esc(d.nr)}</b> <span class="muted tiny">${dmy(d.datum)}</span></div><span class="num">${eur(d.brutto)}</span>${chip(d.status, DOC_STATUS[d.status])}</li>`).join('')}</ul>` : '<div class="empty small">Keine.</div>'}</div></div></div>`;
  $('#kEdit').onclick = () => editCustomer(k);
  $('#kOrder').onclick = () => newOrder({ customer_id: k.id });
};

// ======================================================================
//  Rechner
// ======================================================================
let rcState = null;
routes.rechner = () => {
  const firstFdm = D.machines.find((m) => m.typ === 'fdm' && m.aktiv) || D.machines[0] || {};
  rcState = rcState || { machine_id: firstFdm.id, material_id: (D.materials.find((m) => m.typ === 'filament') || {}).id, menge: '', dauer_h: '', arbeit_h: '', person_id: (D.persons[0] || {}).id, extra: '', stueck: 1, aufschlag_pct: '' };
  view.innerHTML = `<div class="pagehead"><h1>🧮 Schnellrechner</h1><span class="sub">Was kostet's – und was sollten wir verlangen?</span></div>
  <div class="grid2e">
    <div class="card"><div class="ch"><h3>Eingaben</h3></div><div class="cb"><form class="form" id="rcForm" autocomplete="off">
      <div class="f s6"><label>Maschine</label><select name="machine_id" style="width:100%">${machineOpts(rcState.machine_id)}</select></div>
      <div class="f s6"><label>Druck-/Laserzeit (Std:Min)</label><input name="dauer_h" data-hours placeholder="z. B. 3:20" value="${esc(rcState.dauer_h)}"></div>
      <div class="f s8"><label>Material</label><select name="material_id" style="width:100%">${materialOpts(rcState.material_id)}</select></div>
      <div class="f s4"><label id="rcMengeL">Menge</label><input name="menge" inputmode="decimal" value="${esc(rcState.menge)}"></div>
      <div class="f s6"><label>Arbeitszeit (Std:Min)</label><input name="arbeit_h" placeholder="Design, Nachbearbeitung …" value="${esc(rcState.arbeit_h)}"></div>
      <div class="f s6"><label>Wer arbeitet?</label><select name="person_id" style="width:100%">${personOpts(rcState.person_id)}</select></div>
      <div class="f s4"><label>Zubehör / Extras €</label><input name="extra" inputmode="decimal" value="${esc(rcState.extra)}"></div>
      <div class="f s4"><label>Ergibt Stück</label><input name="stueck" inputmode="decimal" value="${esc(rcState.stueck)}"></div>
      <div class="f s4"><label>Aufschlag %</label><input name="aufschlag_pct" inputmode="decimal" placeholder="${esc(S.aufschlag_pct)}" value="${esc(rcState.aufschlag_pct)}"></div>
    </form></div></div>
    <div class="card"><div class="ch"><h3>Ergebnis</h3></div><div class="cb" id="rcOut"><div class="muted">Werte eingeben …</div></div></div>
  </div>`;
  const form = $('#rcForm');
  let timer;
  const calc = async () => {
    const fd = Object.fromEntries(new FormData(form));
    rcState = { ...fd };
    const mat = byId(D.materials, +fd.material_id);
    $('#rcMengeL').textContent = mat ? (mat.einheit === 'kg' ? 'Menge (Gramm)' : `Menge (${mat.einheit})`) : 'Menge';
    const body = { ...fd, dauer_h: parseHours(fd.dauer_h), arbeit_h: parseHours(fd.arbeit_h), menge: parseNum(fd.menge), extra: parseNum(fd.extra), stueck: parseNum(fd.stueck), aufschlag_pct: parseNum(fd.aufschlag_pct) };
    try {
      const r = await api('POST', '/api/rechner', body);
      const sd = r.satz_detail;
      $('#rcOut').innerHTML = `
        <div class="muted small">Empfohlener Preis pro Stück ${r.ust_satz ? '(netto)' : ''}</div>
        <div class="result-big">${eur(r.netto_stueck_gerundet)}</div>
        ${r.ust_satz ? `<div class="muted">brutto ${eur(r.brutto_stueck)} inkl. ${num(r.ust_satz)} % USt</div>` : ''}
        ${r.stueck > 1 ? `<div class="muted">gesamt für ${num(r.stueck)} Stück: <b>${eur(r.netto_gerundet)}</b></div>` : ''}
        <div class="stackbar" style="margin-top:16px">${r.selbstkosten ? [['maschine', r.maschine], ['material', r.material], ['arbeit', r.arbeit], ['fremd', r.extra]].map(([c, v]) => `<div class="c-${c}" style="width:${(v / r.selbstkosten) * 100}%"></div>`).join('') : ''}</div>
        <div class="calcrow"><span><span class="legend-dot c-maschine"></span>Maschine${sd ? ` <span class="tiny muted">(${eur3(sd.satz)}/h: Abschreibung ${eur3(sd.abschreibung)}, Verschleiß ${eur3(sd.verschleiss)}, Strom ${eur3(sd.strom)})</span>` : ''}</span><span>${eur(r.maschine)}</span></div>
        <div class="calcrow"><span><span class="legend-dot c-material"></span>Material${+S.ausschuss_pct ? ` <span class="tiny muted">(inkl. ${num(S.ausschuss_pct)} % Ausschuss)</span>` : ''}</span><span>${eur(r.material)}</span></div>
        <div class="calcrow"><span><span class="legend-dot c-arbeit"></span>Arbeitszeit</span><span>${eur(r.arbeit)}</span></div>
        <div class="calcrow"><span><span class="legend-dot c-fremd"></span>Zubehör / Extras</span><span>${eur(r.extra)}</span></div>
        <div class="calcrow"><b>Selbstkosten</b><b>${eur(r.selbstkosten)}</b></div>
        <div class="calcrow"><span>+ ${num(r.aufschlag_pct)} % Aufschlag</span><span>${eur(r.netto)}</span></div>
        <div class="calcrow"><span>Gewinn (über Stundenlohn hinaus)</span><span class="okc">${eur(r.netto_gerundet - r.selbstkosten)}</span></div>
        <div style="margin-top:16px;display:flex;gap:8px;flex-wrap:wrap"><button id="rcOrder">Als neuen Auftrag anlegen</button><button class="secondary" id="rcReset">Zurücksetzen</button></div>`;
      $('#rcOrder').onclick = () => rcToOrder(body, r);
      $('#rcReset').onclick = () => { rcState = null; routes.rechner(); };
    } catch (e) { $('#rcOut').innerHTML = `<div class="err">${esc(e.message)}</div>`; }
  };
  form.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(calc, 250); });
  form.addEventListener('change', calc);
  calc();
};

function rcToOrder(b, r) {
  newOrder({ titel: '' }, async (order) => {
    const mat = byId(D.materials, +b.material_id);
    if (b.dauer_h || b.menge) await api('POST', '/api/t/order_jobs', { order_id: order.id, machine_id: b.machine_id || null, material_id: b.material_id || null, dauer_h: b.dauer_h || 0, menge: b.menge || 0, stueck: b.stueck || null, bezeichnung: 'aus Rechner' });
    if (b.arbeit_h) await api('POST', '/api/t/order_times', { order_id: order.id, person_id: b.person_id, stunden: b.arbeit_h, taetigkeit: 'Arbeitszeit' });
    if (b.extra) await api('POST', '/api/t/order_costs', { order_id: order.id, bezeichnung: 'Zubehör / Extras', betrag: b.extra });
    await api('POST', '/api/t/order_items', { order_id: order.id, bezeichnung: order.titel, farbe_material: mat ? mat.name : '', menge: r.stueck, einheit: 'Stk', einzelpreis: r.netto_stueck_gerundet });
    if (b.aufschlag_pct != null) await api('PUT', `/api/t/orders/${order.id}`, { aufschlag_pct: b.aufschlag_pct });
    await reload();
  });
}

// ======================================================================
//  Auswertung
// ======================================================================
let awJahr = new Date().getFullYear();
routes.auswertung = async () => {
  const a = await api('GET', '/api/auswertung?jahr=' + awJahr);
  const M = ['Jän', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez'];
  const s = a.summe;
  const hp = {};
  a.monate.forEach((m) => Object.entries(m.stunden).forEach(([p, h]) => { hp[p] = (hp[p] || 0) + h; }));
  const hm_ = {};
  a.monate.forEach((m) => Object.entries(m.maschinen_h).forEach(([p, h]) => { hm_[p] = (hm_[p] || 0) + h; }));
  view.innerHTML = `<div class="pagehead"><h1>Auswertung</h1>
    <select id="awJ">${a.jahre.map((j) => opt(j, j, awJahr)).join('')}</select>
    <a class="button secondary" href="/api/export/auftraege.csv?jahr=${awJahr}">⬇ Aufträge CSV</a>
    <a class="button secondary" href="/api/export/rechnungen.csv?jahr=${awJahr}">⬇ Rechnungen CSV</a></div>
  <div class="tiles">
    <div class="tile accent"><span>Umsatz netto ${awJahr}</span><b>${eur(s.umsatz)}</b><small>davon bezahlt ${eur(s.bezahlt)}</small></div>
    <div class="tile"><span>Kosten gesamt</span><b>${eur(s.kosten)}</b><small>inkl. ${eur(s.arbeit)} Arbeitszeit</small></div>
    <div class="tile"><span>Gewinn (nach Stundenlohn)</span><b class="${s.gewinn < 0 ? 'err' : 'okc'}">${eur(s.gewinn)}</b><small>Umsatz − alle Kosten</small></div>
    <div class="tile"><span>Ergebnis ohne Arbeitszeit</span><b>${eur(s.umsatz - s.maschine - s.material - s.fremd)}</b><small>Umsatz − Maschine − Material − Fremd</small></div>
    <div class="tile"><span>Offene Rechnungen (alle Jahre)</span><b class="warnc">${eur(a.offen_summe)}</b><small>${a.offen_anzahl} Stück</small></div>
  </div>
  <div class="card"><div class="ch"><h3>Umsatz & Kosten pro Monat</h3></div><div class="cb">${barChart(a.monate, M)}</div>
    <div class="legend"><span><span class="legend-dot" style="background:var(--ok)"></span>Umsatz</span><span><span class="legend-dot c-maschine"></span>Maschine</span><span><span class="legend-dot c-material"></span>Material</span><span><span class="legend-dot c-arbeit"></span>Arbeitszeit</span><span><span class="legend-dot c-fremd"></span>Zubehör/Fremd</span></div></div>
  <div class="grid2e">
    <div class="card"><div class="ch"><h3>Arbeitszeit pro Person</h3></div><div class="tblwrap"><table class="tbl"><thead><tr><th>Monat</th>${D.persons.map((p) => `<th class="num"><span class="legend-dot" style="background:${esc(p.farbe || '#888')}"></span>${esc(p.name)}</th>`).join('')}<th class="num">Summe</th></tr></thead><tbody>
      ${a.monate.map((m, i) => { const tot = Object.values(m.stunden).reduce((x, y) => x + y, 0); return tot ? `<tr><td>${M[i]}</td>${D.persons.map((p) => `<td class="num">${m.stunden[p.id] ? hm(m.stunden[p.id]) + ' h' : '–'}</td>`).join('')}<td class="num"><b>${hm(tot)} h</b></td></tr>` : ''; }).join('')}
      </tbody><tfoot><tr><td>Gesamt</td>${D.persons.map((p) => `<td class="num">${hm(hp[p.id] || 0)} h</td>`).join('')}<td class="num">${hm(Object.values(hp).reduce((x, y) => x + y, 0))} h</td></tr>
      <tr><td class="muted" style="font-weight:500">Wert</td>${D.persons.map((p) => `<td class="num muted" style="font-weight:500">${eur((hp[p.id] || 0) * p.stundensatz)}</td>`).join('')}<td class="num">${eur(s.arbeit)}</td></tr></tfoot></table></div></div>
    <div class="card"><div class="ch"><h3>Maschinenstunden</h3></div><div class="tblwrap"><table class="tbl"><thead><tr><th>Maschine</th><th class="num">Stunden ${awJahr}</th><th class="num">Abnutzung ${awJahr}</th></tr></thead><tbody>
      ${D.machines.map((m) => `<tr><td><span class="legend-dot" style="background:${esc(m.farbe || '#888')}"></span>${esc(m.name)}</td><td class="num">${hm(hm_[m.id] || 0)} h</td><td class="num">${eur((hm_[m.id] || 0) * (m.abschreibung + m.verschleiss))}</td></tr>`).join('')}
      </tbody></table></div></div>
  </div>
  <div class="grid2">
    <div class="card"><div class="ch"><h3>Aufträge ${awJahr}</h3></div>${a.auftraege.length ? `<div class="tblwrap"><table class="tbl"><thead><tr><th>Nr.</th><th>Auftrag</th><th>Kunde</th><th class="num">Kosten</th><th class="num">Umsatz</th><th class="num">Gewinn</th></tr></thead><tbody>
      ${a.auftraege.sort((x, y) => y.id - x.id).map((o) => `<tr class="click" onclick="location.hash='#auftrag/${o.id}'"><td class="muted nowrap">${esc(o.nr)}</td><td>${esc(o.titel)}</td><td>${esc(o.kunde)}</td><td class="num">${eur(o.selbstkosten)}</td><td class="num">${eur(o.umsatz)}</td><td class="num ${o.gewinn < 0 ? 'err' : 'okc'}">${o.umsatz ? eur(o.gewinn) : '–'}</td></tr>`).join('')}
      </tbody></table></div>` : '<div class="empty">Keine Aufträge in diesem Jahr.</div>'}</div>
    <div class="card"><div class="ch"><h3>Top-Kunden ${awJahr}</h3></div>${a.top_kunden.length ? `<ul class="list-compact">${a.top_kunden.map((k) => `<li class="click" onclick="location.hash='#kunde/${k.id}'"><span class="grow">${esc(k.name)}</span><span class="num">${eur(k.umsatz)}</span></li>`).join('')}</ul>` : '<div class="empty small">Noch keine Rechnungen.</div>'}</div>
  </div>`;
  $('#awJ').onchange = (e) => { awJahr = +e.target.value; routes.auswertung(); };
};

function barChart(months, labels) {
  const W = 900, H = 260, pl = 54, pb = 24, pt = 10;
  const max = Math.max(10, ...months.map((m) => Math.max(m.umsatz, m.kosten))) * 1.1;
  const step = niceStep(max / 4);
  const top = Math.ceil(max / step) * step;
  const cw = (W - pl) / 12;
  const y = (v) => pt + (H - pt - pb) * (1 - v / top);
  let g = '';
  for (let v = 0; v <= top + 1e-9; v += step) g += `<line class="gl" x1="${pl}" x2="${W}" y1="${y(v)}" y2="${y(v)}"/><text x="${pl - 6}" y="${y(v) + 4}" text-anchor="end">${nfx.format(v)}</text>`;
  months.forEach((m, i) => {
    const x = pl + i * cw;
    const bw = cw * 0.32;
    g += `<rect x="${x + cw * 0.14}" y="${y(m.umsatz)}" width="${bw}" height="${Math.max(0, y(0) - y(m.umsatz))}" rx="3" fill="var(--ok)"><title>${labels[i]}: Umsatz ${eur(m.umsatz)}</title></rect>`;
    let acc = 0;
    [['maschine', 'var(--info)'], ['material', 'var(--teal)'], ['arbeit', '#ff922b'], ['fremd', 'var(--violet)']].forEach(([k, c]) => {
      if (!m[k]) return;
      g += `<rect x="${x + cw * 0.14 + bw + 3}" y="${y(acc + m[k])}" width="${bw}" height="${Math.max(0, y(acc) - y(acc + m[k]))}" fill="${c}"><title>${labels[i]}: ${k} ${eur(m[k])}</title></rect>`;
      acc += m[k];
    });
    g += `<text x="${x + cw / 2}" y="${H - 6}" text-anchor="middle">${labels[i]}</text>`;
  });
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Umsatz und Kosten pro Monat">${g}</svg>`;
}
function niceStep(x) { const p = 10 ** Math.floor(Math.log10(x)); const f = x / p; return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p; }

// ======================================================================
//  Maschinen
// ======================================================================
routes.maschinen = () => {
  view.innerHTML = `<div class="pagehead"><h1>Maschinen</h1><span class="sub">Stundensatz = Abschreibung + Verschleißteile + Strom (${esc(String(S.strompreis).replace('.', ','))} €/kWh)</span>
    <button onclick="editMachine()">+ Maschine</button></div>
    <div class="notice">Die vorbelegten Preise, Lebensdauern und Verschleißteile sind <b>grobe Richtwerte</b> – tragt eure echten Kaufpreise und die bisherigen Betriebsstunden ein (stehen bei Bambu im Handy-App/Druckerdisplay, bei LightBurn im Job-Log). Verschleißteil gewechselt? Einfach auf <b>↻</b> klicken.</div>
    <div class="mcards">${D.machines.map((m) => {
      const parts = D.wear_parts.filter((p) => p.machine_id === m.id);
      const lp = Math.min(100, m.verbraucht_pct);
      return `<div class="mcard" style="--mc:${esc(m.farbe || 'var(--accent)')}${m.aktiv ? '' : ';opacity:.55'}">
        <div class="top"><div class="t"><div class="typ">${esc(MTYP[m.typ] || m.typ)}${m.aktiv ? '' : ' · inaktiv'}</div><h3>${esc(m.name)}</h3><div class="tiny muted">${esc(m.modell || '')}</div></div>
          <div class="rate"><b>${eur3(m.satz)}</b><span>pro Stunde</span></div></div>
        <div class="kv"><div><b>${eur3(m.abschreibung)}</b><span>Abschreibung/h</span></div><div><b>${eur3(m.verschleiss)}</b><span>Verschleiß/h</span></div><div><b>${eur3(m.strom)}</b><span>Strom/h (${num(m.leistung_w)} W)</span></div>
          <div><b>${num(m.stunden_gesamt)} h</b><span>Betriebsstunden${m.stunden_ha_frei ? ` (${num(m.stunden_ha_frei)} h privat/offen)` : ''}</span></div><div><b>${eur(m.abnutzung_eur)}</b><span>Abnutzung bisher</span></div><div><b>${eur(m.restwert)}</b><span>Restwert (von ${eur(m.anschaffung_preis)})</span></div></div>
        <div class="life"><div class="tiny muted" style="display:flex;justify-content:space-between;margin-bottom:4px"><span>Lebensdauer</span><span>${num(m.stunden_gesamt)} / ${num(m.lebensdauer_h)} h (${num(m.verbraucht_pct)} %)</span></div>
          <div class="bar ${lp > 90 ? 'e' : lp > 70 ? 'w' : ''}"><div style="width:${lp}%"></div></div></div>
        <ul class="parts">${parts.map((p) => `<li><div class="pn">${esc(p.name)}<small>${eur(p.preis)} alle ${num(p.lebensdauer_h)} h · ${num(p.stunden_seit)} h seit Wechsel</small></div>
          <div class="bar ${p.pct >= 100 ? 'e' : p.pct >= 80 ? 'w' : ''}" title="${num(p.pct)} %"><div style="width:${Math.min(100, p.pct)}%"></div></div>
          <div class="nowrap"><button class="icon" title="Gewechselt – Zähler zurücksetzen" onclick="wearChanged(${p.id})">↻</button><button class="icon" title="Bearbeiten" onclick="editPart(${p.id})">✎</button></div></li>`).join('') || '<li class="muted small">Keine Verschleißteile hinterlegt.</li>'}</ul>
        <div class="foot"><button class="secondary small" onclick="editMachine(${m.id})">✎ Bearbeiten</button><button class="secondary small" onclick="editPart(null, ${m.id})">+ Verschleißteil</button></div>
      </div>`; }).join('')}</div>`;
};
window.wearChanged = async (id) => {
  if (!confirm('Verschleißteil wurde gewechselt? Der Stundenzähler wird zurückgesetzt.')) return;
  try { await api('POST', `/api/wear_parts/${id}/gewechselt`); await refresh(); toast('Zähler zurückgesetzt'); } catch (e) { fail(e); }
};
window.editMachine = (id) => {
  const m = id ? byId(D.machines, id) : { typ: 'fdm', aktiv: 1, lebensdauer_h: 5000, leistung_w: 120, farbe: '#59a8ff' };
  openForm({
    title: id ? `${m.name} bearbeiten` : 'Neue Maschine', wide: true,
    fields: [
      { k: 'name', l: 'Name', s: 6 }, { k: 'typ', l: 'Art', t: 'select', o: Object.entries(MTYP), s: 3 }, { k: 'farbe', l: 'Farbe', t: 'color', s: 3 },
      { k: 'hersteller', l: 'Hersteller', s: 6 }, { k: 'modell', l: 'Modell / Ausstattung', s: 6 },
      { t: 'h4', l: 'Abschreibung' },
      { k: 'anschaffung_preis', l: 'Kaufpreis €', t: 'num', s: 4 }, { k: 'anschaffung_datum', l: 'Kaufdatum', t: 'date', s: 4 },
      { k: 'lebensdauer_h', l: 'Erwartete Lebensdauer (Stunden)', t: 'num', s: 4, hint: 'nach so vielen Druckstunden ist der Kaufpreis „verbraucht“' },
      { t: 'h4', l: 'Laufende Kosten' },
      { k: 'leistung_w', l: 'Mittlere Leistungsaufnahme (Watt)', t: 'num', s: 4 },
      { k: 'wartung_eur_h', l: 'Sonstige Wartung €/h', t: 'num', s: 4, hint: 'z. B. Schmierstoffe, Reinigung' },
      { k: 'stunden_vorher', l: 'Betriebsstunden ohne Aufträge', t: 'num', s: 4, hint: 'bisherige Stunden + Eigen-/Testdrucke' },
      { k: 'ha_liste', l: 'HA-Druckprotokoll (optional)', ph: 'todo.p1s_druckprotokoll', s: 6, hint: 'To-do-Liste in Home Assistant, in die diese Maschine ihre Drucke schreibt' },
      { k: 'notizen', l: 'Notizen', t: 'textarea', rows: 2 },
      { k: 'aktiv', l: 'aktiv (in Auswahllisten anzeigen)', t: 'check' },
    ],
    values: m,
    onSave: async (v) => { await api(id ? 'PUT' : 'POST', id ? `/api/t/machines/${id}` : '/api/t/machines', v); await refresh(); },
    onDelete: id ? async () => { await api('DELETE', `/api/t/machines/${id}`); await refresh(); } : null,
  });
};
window.editPart = (id, machineId) => {
  const p = id ? byId(D.wear_parts, id) : { machine_id: machineId, lebensdauer_h: 1000, gewechselt_bei_h: (byId(D.machines, machineId) || {}).stunden_gesamt || 0 };
  openForm({
    title: id ? 'Verschleißteil bearbeiten' : 'Neues Verschleißteil',
    fields: [
      { k: 'name', l: 'Bezeichnung', ph: 'z. B. Hotend 0,4 mm' },
      { k: 'preis', l: 'Preis €', t: 'num', s: 4 }, { k: 'lebensdauer_h', l: 'Hält ca. (Stunden)', t: 'num', s: 4 },
      { k: 'gewechselt_bei_h', l: 'Zuletzt gewechselt bei Betriebsstunde', t: 'num', s: 4 },
      { k: 'notizen', l: 'Notizen', t: 'textarea', rows: 2 },
    ],
    values: p,
    onSave: async (v) => { v.machine_id = p.machine_id; await api(id ? 'PUT' : 'POST', id ? `/api/t/wear_parts/${id}` : '/api/t/wear_parts', v); await refresh(); },
    onDelete: id ? async () => { await api('DELETE', `/api/t/wear_parts/${id}`); await refresh(); } : null,
  });
};

// ======================================================================
//  Material
// ======================================================================
routes.material = () => {
  view.innerHTML = `<div class="pagehead"><h1>Material</h1><span class="sub">Preise für die Kalkulation · Lagerbestand wird bei Druck/Laser automatisch abgebucht</span><button onclick="editMaterial()">+ Material</button></div>
    <div class="card"><div class="tblwrap"><table class="tbl"><thead><tr><th>Material</th><th>Art</th><th>Hersteller</th><th>Farbe</th><th class="num">Preis</th><th class="num">Bestand</th></tr></thead><tbody>
    ${[...D.materials].sort((a, b) => (a.typ + a.name).localeCompare(b.typ + b.name, 'de')).map((m) => `<tr class="click" onclick="editMaterial(${m.id})" style="${m.aktiv ? '' : 'opacity:.5'}"><td><b>${esc(m.name)}</b></td><td>${esc(MATTYP[m.typ] || m.typ)}</td>
      <td>${esc(m.hersteller || '')}</td><td>${esc(m.farbe || '')}</td><td class="num">${eur(m.preis)} / ${esc(m.einheit)}</td>
      <td class="num ${m.bestand != null && m.bestand <= 0 ? 'err' : ''}">${m.bestand == null ? '<span class="dim">–</span>' : num(m.bestand) + ' ' + esc(m.einheit)}</td></tr>`).join('')}
    </tbody></table></div></div>`;
};
window.editMaterial = (id) => {
  const m = id ? byId(D.materials, id) : { typ: 'filament', einheit: 'kg', aktiv: 1 };
  openForm({
    title: id ? `${m.name} bearbeiten` : 'Neues Material',
    fields: [
      { k: 'name', l: 'Bezeichnung', s: 8 }, { k: 'typ', l: 'Art', t: 'select', o: Object.entries(MATTYP), s: 4 },
      { k: 'hersteller', l: 'Hersteller / Lieferant', s: 6 }, { k: 'farbe', l: 'Farbe', s: 6 },
      { k: 'einheit', l: 'Einheit', t: 'select', o: [['kg', 'kg (Eingabe in Gramm)'], ['Stück', 'Stück / Platte'], ['m²', 'm²'], ['m', 'm'], ['l', 'Liter']], s: 4 },
      { k: 'preis', l: 'Preis € pro Einheit', t: 'num', s: 4 },
      { k: 'bestand', l: 'Lagerbestand (optional)', t: 'num', s: 4, hint: 'leer = nicht mitzählen' },
      { k: 'notizen', l: 'Notizen', t: 'textarea', rows: 2 },
      { k: 'aktiv', l: 'aktiv', t: 'check' },
    ],
    values: m,
    onSave: async (v) => { await api(id ? 'PUT' : 'POST', id ? `/api/t/materials/${id}` : '/api/t/materials', v); await refresh(); },
    onDelete: id ? async () => { await api('DELETE', `/api/t/materials/${id}`); await refresh(); } : null,
  });
};

// ======================================================================
//  Einstellungen
// ======================================================================
const SET_TABS = [['firma', 'Firma & Vorlagen'], ['kalk', 'Kalkulation & Personen'], ['netz', 'Netzlaufwerk & Backup'], ['ha', 'Home Assistant'], ['zugang', 'Zugang & Info']];
routes.einstellungen = (tab = 'firma') => {
  view.innerHTML = `<div class="pagehead"><h1>Einstellungen</h1></div>
    <div class="setnav">${SET_TABS.map(([k, l]) => `<button class="${k === tab ? 'on' : ''}" onclick="location.hash='#einstellungen/${k}'">${l}</button>`).join('')}</div><div id="setBody"></div>`;
  ({ firma: setFirma, kalk: setKalk, netz: setNetz, ha: setHA, zugang: setZugang }[tab] || setFirma)();
};

function settingsForm(fields, opts = {}) {
  const id = 'sf' + Math.random().toString(36).slice(2, 7);
  const html = `<form class="form" id="${id}" autocomplete="off">${fields.map((f) => fieldHtml(f, S[f.k])).join('')}
    <div class="f" style="flex-direction:row;gap:8px;margin-top:6px"><button type="submit">${opts.label || 'Speichern'}</button>${opts.extraButtons || ''}</div></form>`;
  return { html, bind: () => {
    $('#' + id).onsubmit = async (e) => {
      e.preventDefault();
      const v = readForm($('#' + id), fields);
      for (const k in v) if (typeof v[k] === 'number') v[k] = String(v[k]);
      try { await api('PUT', '/api/settings', v); await reload(); toast('Gespeichert'); opts.after && opts.after(); } catch (err) { fail(err); }
    };
  } };
}

function setFirma() {
  const f = settingsForm([
    { t: 'h4', l: 'Firma' },
    { k: 'firma_name', l: 'Firmenname', s: 6 }, { k: 'firma_slogan', l: 'Slogan', s: 6 },
    { k: 'firma_inhaber', l: 'Inhaber/in', s: 6 }, { k: 'firma_strasse', l: 'Straße', s: 6 },
    { k: 'firma_plz_ort', l: 'PLZ & Ort', s: 6 }, { k: 'firma_land', l: 'Land', t: 'select', o: [['AT', 'Österreich'], ['DE', 'Deutschland']], s: 6 },
    { k: 'firma_tel', l: 'Telefon', s: 4 }, { k: 'firma_email', l: 'E-Mail', s: 4 }, { k: 'firma_web', l: 'Website / Instagram', s: 4 },
    { k: 'firma_uid', l: 'UID-Nummer', s: 6 }, { k: 'firma_steuernr', l: 'Steuernummer', s: 6 },
    { k: 'bank_name', l: 'Bank', s: 4 }, { k: 'bank_iban', l: 'IBAN', s: 5 }, { k: 'bank_bic', l: 'BIC', s: 3 },
    { t: 'h4', l: 'Steuer & Zahlungsziel' },
    { k: 'kleinunternehmer', l: 'Kleinunternehmer (keine Umsatzsteuer)', t: 'check', s: 6 },
    { k: 'ust_satz', l: 'USt-Satz %', t: 'num', s: 3 }, { k: 'zahlungsziel_tage', l: 'Zahlungsziel (Tage)', t: 'num', s: 3 },
    { k: 'kleinunternehmer_text', l: 'Hinweis Kleinunternehmer', t: 'textarea', rows: 2 },
    { t: 'h4', l: 'Rechnung & Angebot' },
    { k: 'akzentfarbe', l: 'Akzentfarbe', t: 'color', s: 3 }, { k: 'angebot_gueltig_tage', l: 'Angebot gültig (Tage)', t: 'num', s: 3 },
    { k: 'prefix_rechnung', l: 'Präfix Rechnungen', s: 3 }, { k: 'prefix_angebot', l: 'Präfix Angebote', s: 3 },
    { k: 'rechnung_einleitung', l: 'Rechnung – Einleitung', t: 'textarea', rows: 2 }, { k: 'rechnung_schluss', l: 'Rechnung – Schlusstext', t: 'textarea', rows: 3, hint: 'Platzhalter: {nr} {faellig} {gesamt} {zahlbetrag} {kunde} {datum}' },
    { k: 'angebot_einleitung', l: 'Angebot – Einleitung', t: 'textarea', rows: 2 }, { k: 'angebot_schluss', l: 'Angebot – Schlusstext', t: 'textarea', rows: 2, hint: 'Platzhalter: {gueltig}' },
    { k: 'fusszeile', l: 'Zusätzliche Fußzeile (optional)' },
    { t: 'h4', l: 'Kundenbestellung (Bestellformular)' },
    { k: 'vertrieb_optionen', l: 'Vertriebswege (Komma-getrennt)', s: 6 }, { k: 'zahlungsarten', l: 'Zahlungsarten (Komma-getrennt)', s: 6 },
    { k: 'bestellung_bestaetigung', l: 'Bestätigungstext', t: 'textarea', rows: 3 },
    { k: 'bestellung_hinweis', l: 'Hinweis (klein unten)', t: 'textarea', rows: 3 },
    { k: 'prefix_auftrag', l: 'Präfix Bestell-/Auftragsnummer', s: 6 }, { k: 'prefix_kunde', l: 'Präfix Kundennummer', s: 6 },
  ], { after: () => { $('#prevFrame').src = $('#prevFrame').dataset.src + '?t=' + Date.now(); } });
  $('#setBody').innerHTML = `<div class="grid2e"><div class="card"><div class="cb">
      <div class="f" style="margin-bottom:14px"><label class="small muted" style="font-weight:600">Logo (oben rechts auf Rechnungen)</label>
        <div class="inline" style="margin-top:6px">${S.logo ? `<img class="logo-prev" src="/vorlage/${esc(S.logo)}" alt="Logo">` : '<span class="muted small">kein Logo</span>'}
        <label class="button secondary small fixed">Logo hochladen<input type="file" accept="image/*" hidden id="logoIn"></label>${S.logo ? '<button class="ghost small fixed" id="logoDel">entfernen</button>' : ''}</div></div>
      ${f.html}</div></div>
    <div><div class="card"><div class="ch"><h3>Vorschau</h3>
      <select id="prevSel"><option value="/api/vorlage/muster.pdf">Musterrechnung</option><option value="/api/vorlage/bestellformular.pdf">Bestellformular (leer)</option></select>
      <button class="secondary small" onclick="const f=document.getElementById('prevFrame');f.src=f.dataset.src+'?t='+Date.now()">↻</button></div>
      <div class="cb"><iframe id="prevFrame" class="preview-frame" data-src="/api/vorlage/muster.pdf" src="/api/vorlage/muster.pdf"></iframe></div></div></div></div>`;
  f.bind();
  $('#prevSel').onchange = (e) => { const fr = $('#prevFrame'); fr.dataset.src = e.target.value; fr.src = e.target.value + '?t=' + Date.now(); };
  $('[name=firma_land]').addEventListener('change', (e) => {
    const t = { AT: 'Umsatzsteuerfrei aufgrund der Kleinunternehmerregelung gemäß § 6 Abs. 1 Z 27 UStG.', DE: 'Gemäß § 19 UStG wird keine Umsatzsteuer berechnet (Kleinunternehmerregelung).' }[e.target.value];
    $('[name=kleinunternehmer_text]').value = t; $('[name=ust_satz]').value = e.target.value === 'DE' ? '19' : '20';
  });
  $('#logoIn').onchange = async (e) => {
    const fd = new FormData(); fd.append('file', e.target.files[0]);
    try { await api('POST', '/api/vorlage/logo', fd); await reload(); setFirma(); toast('Logo gespeichert'); } catch (err) { fail(err); }
  };
  if ($('#logoDel')) $('#logoDel').onclick = async () => { await api('DELETE', '/api/vorlage/logo'); await reload(); setFirma(); };
}

function setKalk() {
  const f = settingsForm([
    { k: 'strompreis', l: 'Strompreis € / kWh', t: 'num', s: 6 },
    { k: 'aufschlag_pct', l: 'Standard-Gewinnaufschlag %', t: 'num', s: 6, hint: 'auf die Selbstkosten (inkl. Arbeitszeit)' },
    { k: 'ausschuss_pct', l: 'Ausschuss / Fehldrucke % auf Material', t: 'num', s: 6 },
    { k: 'rundung', l: 'Preise aufrunden auf €', t: 'num', s: 6, hint: 'z. B. 0,50 → 12,38 € wird 12,50 €; 0 = nicht runden' },
  ]);
  $('#setBody').innerHTML = `<div class="grid2e"><div class="card"><div class="ch"><h3>Kalkulation</h3></div><div class="cb">${f.html}</div></div>
    <div class="card"><div class="ch"><h3>Personen</h3><button class="small" onclick="editPerson()">+ Person</button></div>
      <div class="tblwrap"><table class="tbl"><thead><tr><th>Name</th><th class="num">Interner Stundensatz</th><th class="num">Verrechnungssatz</th></tr></thead><tbody>
      ${D.persons.map((p) => `<tr class="click" onclick="editPerson(${p.id})" style="${p.aktiv ? '' : 'opacity:.5'}"><td><span class="legend-dot" style="background:${esc(p.farbe || '#888')}"></span><b>${esc(p.name)}</b></td><td class="num">${eur(p.stundensatz)}/h</td><td class="num">${eur(p.verrechnungssatz)}/h</td></tr>`).join('')}
      </tbody></table></div>
      <div class="cb tiny muted"><b>Interner Stundensatz</b> = was eure Zeit „kostet“ (fließt in Selbstkosten & Gewinn ein). <b>Verrechnungssatz</b> = was ihr Kunden für Arbeitszeit verrechnet (bei „detailliert erzeugen“).</div></div></div>`;
  f.bind();
}
window.editPerson = (id) => {
  const p = id ? byId(D.persons, id) : { stundensatz: 25, verrechnungssatz: 35, aktiv: 1, farbe: '#36c2b4' };
  openForm({
    title: id ? `${p.name} bearbeiten` : 'Neue Person',
    fields: [{ k: 'name', l: 'Name', s: 8 }, { k: 'farbe', l: 'Farbe', t: 'color', s: 4 },
      { k: 'stundensatz', l: 'Interner Stundensatz €', t: 'num', s: 6 }, { k: 'verrechnungssatz', l: 'Verrechnungssatz €', t: 'num', s: 6 }, { k: 'aktiv', l: 'aktiv', t: 'check' }],
    values: p,
    onSave: async (v) => { await api(id ? 'PUT' : 'POST', id ? `/api/t/persons/${id}` : '/api/t/persons', v); await refresh(); },
    onDelete: id ? async () => { await api('DELETE', `/api/t/persons/${id}`); await refresh(); } : null,
  });
};

async function setNetz() {
  const f = settingsForm([
    { t: 'h4', l: 'Verbindung zum NAS' },
    { k: 'smb_host', l: 'NAS-Adresse (IP oder Name)', s: 6, ph: '192.168.178.41' },
    { k: 'smb_user', l: 'Benutzer', s: 3 },
    { k: 'smb_password', l: 'Passwort', t: 'password', s: 3, ph: S.smb_password_set ? '•••••• (gespeichert)' : '' },
    { t: 'h4', l: 'Auftragsordner' },
    { k: 'smb_auftraege_share', l: 'Freigabe', s: 4, ph: 'z. B. allerlei' },
    { k: 'smb_auftraege_pfad', l: 'Unterordner', s: 8, ph: 'Werkstatt/Auftraege' },
    { k: 'smb_ordner_schema', l: 'Ordnername für neue Aufträge', s: 8, hint: 'Platzhalter: {jahr} {nr} {kunde} {titel} – Unterordner mit /' },
    { k: 'smb_ordner_auto', l: 'Ordner bei neuem Auftrag automatisch anlegen', t: 'check', s: 4 },
    { k: 'smb_pdf_kopieren', l: 'Rechnungen/Angebote als PDF in den Auftragsordner kopieren', t: 'check', s: 12 },
    { k: 'smb_unc_anzeige', l: 'So heißt der Ordner am Windows-PC (optional)', s: 12, ph: 'z. B. V:\\Werkstatt\\Auftraege', hint: 'Wenn ihr die Freigabe als Laufwerk verbunden habt, wird der kopierbare Pfad so angezeigt.' },
    { t: 'h4', l: 'Automatisches Backup' },
    { k: 'backup_aktiv', l: 'Täglich automatisch sichern', t: 'check', s: 6 }, { k: 'backup_uhrzeit', l: 'Uhrzeit', t: 'time', s: 3 },
    { k: 'backup_behalten', l: 'Sicherungen behalten', t: 'num', s: 3 },
    { k: 'backup_share', l: 'Freigabe', s: 4, ph: 'backups' }, { k: 'backup_pfad', l: 'Unterordner', s: 4, ph: 'Werkstatt' },
    { k: 'backup_mit_bildern', l: 'Bilder & PDFs mitsichern', t: 'check', s: 4 },
  ], { extraButtons: '<button type="button" class="secondary" id="tA">Auftragsordner testen</button><button type="button" class="secondary" id="tB">Backup-Ziel testen</button>', after: () => setNetz() });
  let bl = [];
  try { bl = await api('GET', '/api/backup/list'); } catch { /* egal */ }
  $('#setBody').innerHTML = `<div class="grid2"><div class="card"><div class="cb">
      <div class="notice">Die App greift selbst auf euer NAS zu (SMB) – Dateien hochladen, Ordner anlegen und Backups laufen also auch vom Handy aus.
      Tipp: Für die App am NAS einen eigenen Benutzer anlegen, der nur auf die nötigen Ordner schreiben darf.</div>
      ${f.html}</div></div>
    <div><div class="card"><div class="ch"><h3>Datensicherung</h3><button class="small" id="bNow">Jetzt sichern</button></div><div class="cb small">
      ${S.backup_letzt ? `Letzte Sicherung: <b>${esc(S.backup_letzt)}</b><br><span class="${S.backup_letzt_status.startsWith('ok') ? 'okc' : 'err'}">${esc(S.backup_letzt_status.replace(/^(ok|fehler): /, ''))}</span>` : '<span class="muted">Noch keine Sicherung.</span>'}
      <p class="muted">Zusätzlich bleiben die letzten 7 Sicherungen im Container. Gesichert werden Datenbank, Logo, Rechnungs-PDFs und (optional) Bilder.</p></div>
      ${bl.length ? `<ul class="list-compact">${bl.map((b) => `<li><span class="grow mono">${esc(b.name)}</span><span class="tiny muted">${fsize(b.size)}</span><a class="icon" href="/api/backup/download/${encodeURIComponent(b.name)}" title="Herunterladen">⬇</a></li>`).join('')}</ul>` : ''}
      <div class="cb" style="border-top:1px solid var(--line)"><label class="button secondary small">Sicherung wiederherstellen …<input type="file" accept=".zip,.db" hidden id="restoreIn"></label>
        <div class="tiny dim" style="margin-top:6px">Vorher wird automatisch der aktuelle Stand gesichert.</div></div></div></div></div>`;
  f.bind();
  const test = async (area, btn) => {
    btn.disabled = true;
    try { const r = await api('POST', '/api/storage/test', { area }); toast(`✔ Verbindung ok: ${r.pfad} (${r.eintraege} Einträge)`, 'ok', 6000); } catch (e) { fail(e); } finally { btn.disabled = false; }
  };
  $('#tA').onclick = async (e) => { await saveThen(e.target, () => test('auftraege', e.target)); };
  $('#tB').onclick = async (e) => { await saveThen(e.target, () => test('backup', e.target)); };
  $('#bNow').onclick = async (e) => {
    e.target.disabled = true; toast('Sicherung läuft …');
    try { const r = await api('POST', '/api/backup/run'); toast(r.text, r.ok ? 'ok' : 'warn', 8000); await reload(); setNetz(); } catch (err) { fail(err); } finally { e.target.disabled = false; }
  };
  $('#restoreIn').onchange = async (e) => {
    const file = e.target.files[0]; if (!file) return;
    if (!confirm(`Sicherung „${file.name}“ einspielen? Der aktuelle Stand wird dabei ersetzt (vorher automatisch gesichert).`)) { e.target.value = ''; return; }
    const fd = new FormData(); fd.append('file', file);
    try { await api('POST', '/api/backup/restore', fd); toast('Wiederhergestellt'); await reload(); location.hash = '#uebersicht'; } catch (err) { fail(err); }
  };
}
async function saveThen(btn, fn) {
  const form = btn.closest('form');
  const fields = $$('[name]', form);
  const v = {};
  fields.forEach((i) => { v[i.name] = i.type === 'checkbox' ? (i.checked ? '1' : '0') : i.value; });
  try { await api('PUT', '/api/settings', v); await reload(); } catch (e) { fail(e); return; }
  await fn();
}

function setZugang() {
  $('#setBody').innerHTML = `<div class="grid2e"><div class="card"><div class="ch"><h3>Passwort</h3></div><div class="cb">
      <p class="muted small">${S.password_set ? 'Die App ist mit einem Passwort geschützt.' : 'Derzeit kann jeder im Heimnetz die App öffnen. Mit Passwort wird beim ersten Öffnen pro Gerät einmal danach gefragt.'}</p>
      <form class="form" id="pwForm"><div class="f s8"><input type="password" id="pw1" placeholder="${S.password_set ? 'Neues Passwort' : 'Passwort festlegen'}" autocomplete="new-password"></div>
      <div class="f s4"><button>${S.password_set ? 'Ändern' : 'Festlegen'}</button></div></form>
      ${S.password_set ? '<button class="danger small" id="pwOff" style="margin-top:10px">Passwortschutz entfernen</button> <button class="secondary small" id="logout" style="margin-top:10px">Abmelden</button>' : ''}</div></div>
    <div class="card"><div class="ch"><h3>Info</h3></div><div class="cb small">
      <div class="sumbox"><div class="row"><span>Version</span><span>${esc(D.version)}</span></div><div class="row"><span>Kunden</span><span>${D.customers.length}</span></div>
      <div class="row"><span>Aufträge</span><span>${D.orders.length}</span></div><div class="row"><span>Rechnungen</span><span>${D.documents.filter((d) => d.typ === 'rechnung').length}</span></div></div>
      <p class="muted">Exporte: <a href="/api/export/kunden.csv">Kunden</a> · <a href="/api/export/auftraege.csv">Aufträge</a> · <a href="/api/export/rechnungen.csv">Rechnungen</a> (CSV für Excel)</p></div></div></div>`;
  $('#pwForm').onsubmit = async (e) => {
    e.preventDefault(); const pw = $('#pw1').value;
    if (pw.length < 4) { toast('Bitte mindestens 4 Zeichen', 'warn'); return; }
    try { await api('POST', '/api/password', { password: pw }); await reload(); setZugang(); toast('Passwort gespeichert'); } catch (err) { fail(err); }
  };
  if ($('#pwOff')) $('#pwOff').onclick = async () => { if (!confirm('Passwortschutz wirklich entfernen?')) return; await api('POST', '/api/password', { password: '' }); await reload(); setZugang(); };
  if ($('#logout')) $('#logout').onclick = async () => { await api('POST', '/api/logout'); location.href = '/login'; };
}

// ---------- Start ----------
(async () => {
  try { await reload(); await render(); } catch (e) { view.innerHTML = `<div class="card pad err">Konnte Daten nicht laden: ${esc(e.message)}</div>`; }
})();


// ======================================================================
//  Drucke aus Home Assistant
// ======================================================================
const ART_LABEL = { offen: 'offen', privat: '🏠 Privat', gewerbe: '💼 Gewerbe' };
function updateDruckBadge() {
  const n = (D.prints || []).filter((p) => p.art === 'offen' || (p.art === 'gewerbe' && !p.job_id)).length;
  const b = $('#druckBadge');
  if (!b) return;
  b.textContent = n; b.classList.toggle('hidden', !n);
}
const machineName = (id) => (byId(D.machines, id) || {}).name || '–';

let pFilter = 'todo';
const pSel = new Set();
routes.drucke = () => {
  const P = D.prints || [];
  const haOn = S.ha_aktiv === '1' && S.ha_url && S.ha_token_set;
  const counts = {
    todo: P.filter((p) => p.art === 'offen' || (p.art === 'gewerbe' && !p.job_id)).length,
    offen: P.filter((p) => p.art === 'offen').length,
    ohne: P.filter((p) => p.art === 'gewerbe' && !p.job_id).length,
    gewerbe: P.filter((p) => p.art === 'gewerbe').length,
    privat: P.filter((p) => p.art === 'privat').length,
    alle: P.length,
  };
  const ym = today().slice(0, 7);
  const monat = P.filter((p) => (p.datum || '').startsWith(ym));
  const sum = (arr, k) => arr.reduce((s, p) => s + (+p[k] || 0), 0);
  const strom = +S.strompreis || 0.3;
  view.innerHTML = `<div class="pagehead"><h1>🖨 Drucke</h1><span class="sub">aus den Home-Assistant-Druckprotokollen</span>
      <button class="secondary" id="haSync" ${S.ha_url && S.ha_token_set ? '' : 'disabled'}>↻ Jetzt abrufen</button></div>
    ${!haOn ? `<div class="notice warn">Der Abruf aus Home Assistant ist noch nicht eingerichtet – unter <a href="#einstellungen/ha">Einstellungen → Home Assistant</a> Adresse und Zugangstoken eintragen.</div>` : ''}
    ${S.ha_letzt ? `<div class="muted small" style="margin:-6px 0 12px">Letzter Abruf ${esc(S.ha_letzt)} – <span class="${S.ha_letzt_status.startsWith('ok') ? 'okc' : 'err'}">${esc(S.ha_letzt_status.replace(/^(ok|fehler): /, ''))}</span></div>` : ''}
    <div class="tiles">
      <div class="tile accent"><span>Noch einzustufen / zuzuordnen</span><b>${counts.todo}</b><small>${counts.offen} offen · ${counts.ohne} Gewerbe ohne Auftrag</small></div>
      <div class="tile"><span>Gewerbe diesen Monat</span><b>${monat.filter((p) => p.art === 'gewerbe').length}</b><small>${hm(sum(monat.filter((p) => p.art === 'gewerbe'), 'dauer_h'))} h · ${num(sum(monat.filter((p) => p.art === 'gewerbe'), 'kwh'))} kWh</small></div>
      <div class="tile"><span>Privat diesen Monat</span><b>${monat.filter((p) => p.art === 'privat').length}</b><small>${hm(sum(monat.filter((p) => p.art === 'privat'), 'dauer_h'))} h · ${num(sum(monat.filter((p) => p.art === 'privat'), 'gramm'))} g · Strom ${eur(sum(monat.filter((p) => p.art === 'privat'), 'kwh') * strom)}</small></div>
    </div>
    <div class="filterchips" id="pChips">${[['todo', 'Zu erledigen'], ['offen', 'Offen'], ['ohne', 'Gewerbe ohne Auftrag'], ['gewerbe', 'Gewerbe'], ['privat', 'Privat'], ['alle', 'Alle']]
      .map(([k, l]) => `<button data-f="${k}">${l}<i>${counts[k]}</i></button>`).join('')}</div>
    <div class="card"><div id="pBulk"></div><div class="tblwrap" id="pList"></div></div>
    <p class="muted small">Eingestufte Drucke bekommen im HA-Druckprotokoll ein 💼 bzw. 🏠 vorangestellt und werden dort abgehakt. Private Drucke zählen trotzdem zu den Betriebsstunden der Maschine (Verschleiß).</p>`;
  const draw = () => {
    $$('#pChips button').forEach((b) => b.classList.toggle('on', b.dataset.f === pFilter));
    const list = P.filter((p) => ({ todo: p.art === 'offen' || (p.art === 'gewerbe' && !p.job_id), offen: p.art === 'offen',
      ohne: p.art === 'gewerbe' && !p.job_id, gewerbe: p.art === 'gewerbe', privat: p.art === 'privat', alle: true })[pFilter]);
    [...pSel].forEach((id) => { if (!list.some((p) => p.id === id)) pSel.delete(id); });
    $('#pBulk').innerHTML = pSel.size ? `<div class="bulkbar"><b>${pSel.size} ausgewählt</b>
      <button class="small secondary" data-bulk="privat">🏠 Privat</button><button class="small secondary" data-bulk="gewerbe">💼 Gewerbe</button>
      <button class="small" data-bulk="assign">→ Auftrag zuordnen</button><button class="ghost small" data-bulk="none">Auswahl aufheben</button></div>` : '';
    $('#pList').innerHTML = list.length ? `<table class="tbl"><thead><tr><th class="chk"><input type="checkbox" id="pAll"></th><th>Datum</th><th>Drucker</th><th>Druck</th>
      <th class="num">Dauer</th><th class="num">Filament</th><th class="num">Strom</th><th>Einstufung</th><th>Auftrag</th></tr></thead><tbody>
      ${list.map((p) => { const o = byId(D.orders, p.order_id); const m = byId(D.machines, p.machine_id);
        return `<tr data-id="${p.id}"><td class="chk"><input type="checkbox" data-sel ${pSel.has(p.id) ? 'checked' : ''}></td>
        <td class="nowrap">${dmy(p.datum)}${p.uhrzeit ? `<div class="sub">${esc(p.uhrzeit)}</div>` : ''}</td>
        <td class="nowrap">${m ? `<span class="legend-dot" style="background:${esc(m.farbe || '#888')}"></span>${esc(m.name.replace('Bambu Lab ', ''))}` : esc(p.ha_liste || '–')}</td>
        <td><b>${esc(p.name)}</b>${p.erfolg ? '' : ' <span class="chip st-storniert nodot">❌ Fehldruck</span>'}${p.notizen ? `<div class="sub">${esc(p.notizen)}</div>` : ''}</td>
        <td class="num">${p.dauer_h != null ? hm(p.dauer_h) + ' h' : '–'}</td><td class="num">${p.gramm != null ? num(p.gramm) + ' g' : '–'}</td>
        <td class="num">${p.kwh != null ? num(p.kwh) + ' kWh' : '–'}</td>
        <td class="nowrap"><span class="artbtns"><button class="privat ${p.art === 'privat' ? 'on' : ''}" data-art="privat" ${p.job_id ? 'disabled' : ''}>🏠 Privat</button>
          <button class="gewerbe ${p.art === 'gewerbe' ? 'on' : ''}" data-art="gewerbe">💼 Gewerbe</button></span>${p.sync_pending ? ' <span class="tiny warnc" title="Wird beim nächsten Abruf an HA gemeldet">⏳</span>' : ''}</td>
        <td>${o ? `<a href="#auftrag/${o.id}">${esc(o.nr)}</a> <span class="muted small">${esc(o.titel)}</span> <button class="icon" data-unassign title="Zuordnung lösen">✕</button>`
          : (p.art !== 'privat' ? '<button class="small secondary" data-assign>→ zuordnen</button>' : '')}</td></tr>`; }).join('')}
      </tbody></table>` : `<div class="empty">${P.length ? 'Nichts zu tun 🎉' : 'Noch keine Drucke abgerufen.'}</div>`;
    if ($('#pAll')) $('#pAll').onchange = (e) => { list.forEach((p) => (e.target.checked ? pSel.add(p.id) : pSel.delete(p.id))); draw(); };
  };
  const setArt = async (ids, art) => {
    try { const r = await api('POST', '/api/prints/art', { ids, art }); warnIf(r); pSel.clear(); await refresh(); } catch (e) { fail(e); }
  };
  $('#pChips').onclick = (e) => { const b = e.target.closest('button'); if (b) { pFilter = b.dataset.f; pSel.clear(); draw(); } };
  $('#pList').onclick = (e) => {
    const tr = e.target.closest('tr[data-id]'); if (!tr) return;
    const id = +tr.dataset.id;
    if (e.target.matches('[data-sel]')) { e.target.checked ? pSel.add(id) : pSel.delete(id); draw(); return; }
    const a = e.target.closest('[data-art]');
    if (a && !a.disabled) { setArt([id], a.dataset.art); return; }
    if (e.target.closest('[data-assign]')) { assignPrints([id]); return; }
    if (e.target.closest('[data-unassign]')) {
      if (!confirm('Zuordnung lösen? Die Druckzeit wird aus dem Auftrag entfernt.')) return;
      api('POST', `/api/prints/${id}/unassign`).then(refresh, fail);
    }
  };
  $('#pBulk').onclick = (e) => {
    const b = e.target.closest('[data-bulk]'); if (!b) return;
    const ids = [...pSel];
    if (b.dataset.bulk === 'none') { pSel.clear(); draw(); return; }
    if (b.dataset.bulk === 'assign') { assignPrints(ids); return; }
    setArt(ids, b.dataset.bulk);
  };
  $('#haSync').onclick = haSyncNow;
  draw();
};

async function haSyncNow(e) {
  const btn = e && e.target; if (btn) btn.disabled = true;
  try { const r = await api('POST', '/api/ha/sync'); toast(r.text, r.ok ? 'ok' : 'warn', 7000); await refresh(); }
  catch (err) { fail(err); } finally { if (btn) btn.disabled = false; }
}

function assignPrints(ids, presetOrderId) {
  const P = ids.map((id) => byId(D.prints, id)).filter(Boolean);
  if (!P.length) return;
  const one = P.length === 1 ? P[0] : null;
  const openOrders = D.orders.filter((o) => OPEN_STATUS.includes(o.status)).sort((a, b) => b.id - a.id);
  const others = D.orders.filter((o) => !OPEN_STATUS.includes(o.status)).sort((a, b) => b.id - a.id);
  const oOpt = (sel) => opt('', '— Auftrag wählen —', sel) + `<option value="__neu">+ Neuen Auftrag anlegen …</option>`
    + `<optgroup label="Offene Aufträge">${openOrders.map((o) => opt(o.id, `${o.nr} · ${o.titel} (${kname(byId(D.customers, o.customer_id))})`, sel)).join('')}</optgroup>`
    + (others.length ? `<optgroup label="Abgeschlossene">${others.map((o) => opt(o.id, `${o.nr} · ${o.titel}`, sel)).join('')}</optgroup>` : '');
  const filament = D.materials.filter((m) => m.aktiv && m.typ === 'filament');
  const totalG = P.reduce((s, p) => s + (+p.gramm || 0), 0);
  openForm({
    title: one ? `Druck „${one.name}“ zuordnen` : `${P.length} Drucke zuordnen`,
    fields: [
      { t: 'html', html: `<div class="notice">${P.length} Druck(e) · ${hm(P.reduce((s, p) => s + (+p.dauer_h || 0), 0))} h · ${num(totalG)} g Filament · ${num(P.reduce((s, p) => s + (+p.kwh || 0), 0))} kWh gemessen</div>` },
      { k: 'order_id', l: 'Auftrag', t: 'select', o: oOpt },
      { k: 'material_id', l: 'Filament / Material', t: 'select', o: (v) => opt('', '— ohne Materialkosten —', v) + filament.map((m) => opt(m.id, `${m.name}${m.farbe && m.farbe !== 'diverse' ? ' · ' + m.farbe : ''} (${eur(m.preis)}/kg)`, v)).join(''), s: 8 },
      ...(one ? [{ k: 'stueck', l: 'Ergibt Stück', t: 'num', s: 4 }, { k: 'bezeichnung', l: 'Bezeichnung im Auftrag' }] : []),
    ],
    values: { order_id: presetOrderId || '', material_id: (filament.find((m) => /pla basic/i.test(m.name)) || filament[0] || {}).id, bezeichnung: one ? one.name : '' },
    saveLabel: 'Zuordnen',
    onSave: async (v) => {
      const send = async (orderId) => {
        const r = await api('POST', '/api/prints/assign', { ids, order_id: +orderId, material_id: v.material_id ? +v.material_id : null, stueck: v.stueck, bezeichnung: v.bezeichnung });
        warnIf(r); pSel.clear(); toast('Zugeordnet'); await refresh();
      };
      if (v.order_id === '__neu') {
        newOrder({ titel: one ? one.name : '' }, async (order) => { await send(order.id); });
        return;
      }
      if (!v.order_id) throw new Error('Bitte einen Auftrag wählen');
      await send(v.order_id);
    },
  });
}
window.assignPrints = assignPrints;

window.pickPrintForOrder = (orderId) => {
  const list = (D.prints || []).filter((p) => !p.job_id && p.art !== 'privat');
  if (!list.length) { toast('Keine offenen Drucke aus Home Assistant vorhanden.', 'warn'); return; }
  const m = modal({
    title: 'Druck aus Home Assistant übernehmen', wide: true,
    body: `<p class="muted small" style="margin-top:0">Drucke auswählen, die zu diesem Auftrag gehören:</p>
      <div class="tblwrap"><table class="tbl"><thead><tr><th class="chk"></th><th>Datum</th><th>Drucker</th><th>Druck</th><th class="num">Dauer</th><th class="num">Filament</th><th class="num">Strom</th></tr></thead><tbody>
      ${list.map((p) => `<tr><td class="chk"><input type="checkbox" value="${p.id}"></td><td class="nowrap">${dmy(p.datum)} ${esc(p.uhrzeit || '')}</td><td>${esc(machineName(p.machine_id).replace('Bambu Lab ', ''))}</td>
        <td><b>${esc(p.name)}</b>${p.erfolg ? '' : ' ❌'} ${p.art === 'gewerbe' ? chip('gewerbe', '💼') : ''}</td><td class="num">${hm(p.dauer_h)} h</td><td class="num">${num(p.gramm)} g</td><td class="num">${num(p.kwh)} kWh</td></tr>`).join('')}
      </tbody></table></div>`,
    footer: '<span class="spacer"></span><button class="secondary" data-c>Abbrechen</button><button data-ok>Weiter</button>',
  });
  $('[data-c]', m.el).onclick = m.close;
  $('[data-ok]', m.el).onclick = () => {
    const ids = $$('input[type=checkbox]:checked', m.el).map((x) => +x.value);
    if (!ids.length) { toast('Bitte mindestens einen Druck auswählen', 'warn'); return; }
    m.close(); assignPrints(ids, orderId);
  };
};

async function setHA() {
  const f = settingsForm([
    { k: 'ha_aktiv', l: 'Drucke automatisch aus Home Assistant abholen', t: 'check', s: 8 },
    { k: 'ha_intervall_min', l: 'alle … Minuten', t: 'num', s: 4 },
    { k: 'ha_url', l: 'Adresse von Home Assistant', s: 6, ph: 'http://192.168.178.xx:8123' },
    { k: 'ha_token', l: 'Langlebiges Zugangstoken', t: 'password', s: 6, ph: S.ha_token_set ? '•••••• (gespeichert)' : 'eyJ…' },
    { k: 'ha_listen', l: 'Druckprotokoll-Listen (Komma-getrennt)', hint: 'Die Zuordnung zur Maschine steht bei der Maschine („HA-Druckprotokoll“) oder wird am Namen erkannt (a1, p1s, a2l, x2d).' },
    { k: 'ha_import_ab', l: 'Nur Drucke ab diesem Datum übernehmen (optional)', t: 'date', s: 6 },
  ], { extraButtons: '<button type="button" class="secondary" id="haTest">Verbindung testen</button><button type="button" class="secondary" id="haNow">Jetzt abrufen</button>', after: () => setHA() });
  $('#setBody').innerHTML = `<div class="grid2"><div class="card"><div class="cb">${f.html}</div></div>
    <div><div class="card"><div class="ch"><h3>So funktioniert's</h3></div><div class="cb small">
      <ol style="padding-left:18px;margin:0">
        <li>Home Assistant schreibt nach jedem Druck einen Eintrag ins Druckprotokoll des Druckers (gibt's schon) und schickt eine Push-Mitteilung mit <b>🏠 Privat</b> / <b>💼 Gewerbe</b>.</li>
        <li>Die Werkstatt holt die Einträge alle paar Minuten ab → <a href="#drucke">Drucke</a>.</li>
        <li>Eingestuft wird per Push-Knopf oder hier in der Werkstatt – beides landet überall.</li>
        <li>Gewerbliche Drucke ordnest du einem Auftrag zu: Maschinenzeit, Filament und der <b>gemessene Strom</b> fließen in die Kalkulation.</li>
      </ol>
      <h4 style="margin:14px 0 6px">Zugangstoken erstellen</h4>
      In Home Assistant links unten auf deinen Namen → Reiter <b>Sicherheit</b> → ganz unten <b>Langlebige Zugangstoken → Token erstellen</b>, Name z. B. „Werkstatt“. Den angezeigten Token hier einfügen (er wird nur einmal angezeigt).
      </div></div>
      ${S.ha_letzt ? `<div class="card"><div class="cb small">Letzter Abruf: <b>${esc(S.ha_letzt)}</b><br><span class="${S.ha_letzt_status.startsWith('ok') ? 'okc' : 'err'}">${esc(S.ha_letzt_status.replace(/^(ok|fehler): /, ''))}</span></div></div>` : ''}</div></div>`;
  f.bind();
  $('#haTest').onclick = (e) => saveThen(e.target, async () => {
    try { const r = await api('POST', '/api/ha/test'); toast('✔ ' + r.listen.map((l) => `${l.liste.replace('todo.', '')}: ${l.eintraege}`).join(' · '), 'ok', 8000); } catch (err) { fail(err); }
  });
  $('#haNow').onclick = (e) => saveThen(e.target, () => haSyncNow());
}

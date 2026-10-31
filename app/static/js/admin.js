/* nuhdbot admin — runtime: CSRF, toasts, dialogs, theme, search, forms, drag & drop, live auction. */
(function () {
  const csrf = document.querySelector('meta[name="csrf"]')?.content || '';
  const root = document.documentElement;
  const T = (k, d) => (window.ADMIN_I18N && window.ADMIN_I18N[k]) || d;
  const ICONS = {
    ok: '<svg viewBox="0 0 256 256" fill="currentColor"><path d="M229.66,77.66l-128,128a8,8,0,0,1-11.32,0l-56-56a8,8,0,0,1,11.32-11.32L96,188.69,218.34,66.34a8,8,0,0,1,11.32,11.32Z"/></svg>',
    bad: '<svg viewBox="0 0 256 256" fill="currentColor"><path d="M236.8,188.09,149.35,36.22h0a24.76,24.76,0,0,0-42.7,0L19.2,188.09a23.51,23.51,0,0,0,0,23.72A24.35,24.35,0,0,0,40.55,224h174.9a24.35,24.35,0,0,0,21.33-12.19A23.51,23.51,0,0,0,236.8,188.09ZM120,104a8,8,0,0,1,16,0v40a8,8,0,0,1-16,0Zm8,88a12,12,0,1,1,12-12A12,12,0,0,1,128,192Z"/></svg>',
    warn: '<svg viewBox="0 0 256 256" fill="currentColor"><path d="M128,24A104,104,0,1,0,232,128,104.11,104.11,0,0,0,128,24Zm-8,56a8,8,0,0,1,16,0v56a8,8,0,0,1-16,0Zm8,104a12,12,0,1,1,12-12A12,12,0,0,1,128,184Z"/></svg>',
    info: '<svg viewBox="0 0 256 256" fill="currentColor"><path d="M128,24A104,104,0,1,0,232,128,104.11,104.11,0,0,0,128,24Zm-4,48a12,12,0,1,1-12,12A12,12,0,0,1,124,72Zm12,112a16,16,0,0,1-16-16V128a8,8,0,0,1,0-16,16,16,0,0,1,16,16v40a8,8,0,0,1,0,16Z"/></svg>',
  };

  // ---------- HTMX: CSRF + errors ----------
  document.addEventListener('htmx:configRequest', (e) => { e.detail.headers['X-CSRF'] = csrf; });
  document.addEventListener('htmx:responseError', (e) => {
    const x = e.detail.xhr; toast(x && x.responseText && x.responseText.length < 200 ? x.responseText : 'Error ' + (x ? x.status : ''), 'bad');
  });

  // ---------- toasts ----------
  function toast(msg, type, ms) {
    let box = document.querySelector('.toasts');
    if (!box) { box = document.createElement('div'); box.className = 'toasts'; document.body.appendChild(box); }
    const el = document.createElement('div'); el.className = 'toast ' + (type || 'info');
    el.innerHTML = (ICONS[type] || ICONS.info) + '<span></span>'; el.querySelector('span').textContent = msg;
    box.appendChild(el); setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 300); }, ms || 3200);
  }
  window.toast = toast;
  document.addEventListener('toast', (e) => { const d = e.detail || {}; toast(d.msg || d.value, d.type); });
  const params = new URLSearchParams(location.search);
  if (params.get('flash')) {
    toast(params.get('flash'), params.get('flash_kind') || 'ok'); params.delete('flash'); params.delete('flash_kind');
    const qs = params.toString(); history.replaceState({}, '', location.pathname + (qs ? '?' + qs : '') + location.hash);
  }

  // ---------- theme ----------
  function resolvedTheme() { const m = root.dataset.themeMode || 'auto'; if (m === 'light' || m === 'dark') return m; return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'; }
  function applyTheme() {
    const m = root.dataset.themeMode || 'auto'; const dark = resolvedTheme() === 'dark';
    root.classList.toggle('tg-dark', dark); if (m === 'auto') root.removeAttribute('data-theme'); else root.setAttribute('data-theme', m);
    const meta = document.querySelector('meta[name="color-scheme"]'); if (meta) meta.setAttribute('content', m === 'auto' ? 'light dark' : m);
  }
  window.setTheme = function (mode) {
    root.classList.add('theme-transition'); setTimeout(() => root.classList.remove('theme-transition'), 260);
    root.dataset.themeMode = mode; applyTheme();
    fetch('/admin/theme/' + mode, { method: 'POST', headers: { 'X-CSRF': csrf }, credentials: 'same-origin' }).catch(() => {});
  };
  document.addEventListener('click', (e) => { const b = e.target.closest('[data-theme-cycle]'); if (b) window.setTheme(resolvedTheme() === 'dark' ? 'light' : 'dark'); });

  // ---------- confirm dialog (no window.confirm) ----------
  const dlg = document.getElementById('confirm-dlg');
  function askConfirm(opts) {
    return new Promise((resolve) => {
      if (!dlg || !dlg.showModal) { resolve({ ok: true, reason: '' }); return; }
      dlg.querySelector('[data-dlg-title]').textContent = opts.title || T('confirm_q', 'Are you sure?');
      const p = dlg.querySelector('[data-dlg-text]'); p.textContent = opts.text || ''; p.hidden = !opts.text;
      const rf = dlg.querySelector('[data-dlg-reason]'); const ta = rf.querySelector('textarea'); rf.hidden = !opts.reason; ta.value = ''; ta.required = !!opts.reason;
      const okBtn = dlg.querySelector('[data-dlg-ok]'); okBtn.textContent = opts.okText || T('confirm', 'Confirm'); okBtn.className = 'btn ' + (opts.danger ? 'btn-danger' : 'btn-primary');
      const done = (ok) => { dlg.close(); okBtn.onclick = null; dlg.onclose = null; resolve({ ok, reason: ta.value.trim() }); };
      okBtn.onclick = (ev) => { ev.preventDefault(); if (opts.reason && !ta.value.trim()) { ta.classList.add('invalid'); ta.focus(); return; } done(true); };
      dlg.onclose = () => resolve({ ok: false, reason: '' });
      dlg.querySelector('[data-dlg-cancel]').onclick = (ev) => { ev.preventDefault(); done(false); };
      dlg.showModal(); if (opts.reason) ta.focus();
    });
  }
  window.askConfirm = askConfirm;
  document.addEventListener('submit', (e) => {
    const f = e.target; if (!(f instanceof HTMLFormElement)) return;
    const sub = e.submitter; const el = (sub && sub.dataset.confirm) ? sub : (f.dataset.confirm ? f : null);
    if (!el || f.dataset.confirmed === '1') return;
    e.preventDefault();
    askConfirm({ title: el.dataset.confirm, text: el.dataset.confirmText, reason: el.dataset.confirmReason, danger: el.dataset.confirmDanger === '1', okText: el.dataset.confirmOk }).then((r) => {
      if (!r.ok) return;
      if (el.dataset.confirmReason) { let h = f.querySelector('input[name="' + el.dataset.confirmReason + '"]'); if (!h) { h = document.createElement('input'); h.type = 'hidden'; h.name = el.dataset.confirmReason; f.appendChild(h); } h.value = r.reason; }
      f.dataset.confirmed = '1';
      if (sub && sub.name) { const h = document.createElement('input'); h.type = 'hidden'; h.name = sub.name; h.value = sub.value; f.appendChild(h); }
      f.requestSubmit ? f.requestSubmit() : f.submit();
      setTimeout(() => { delete f.dataset.confirmed; }, 500);
    });
  }, true);
  document.addEventListener('htmx:confirm', (e) => {
    const el = e.detail.elt; if (!el.dataset.confirm) return; e.preventDefault();
    askConfirm({ title: el.dataset.confirm, text: el.dataset.confirmText, danger: el.dataset.confirmDanger === '1' }).then((r) => { if (r.ok) e.detail.issueRequest(true); });
  });

  // ---------- sidebar drawer / dropdowns ----------
  const sb = document.querySelector('.sidebar'); const scrim = document.querySelector('.scrim');
  function closeSb() { sb && sb.classList.remove('open'); scrim && scrim.classList.remove('show'); }
  document.querySelector('.menu-btn')?.addEventListener('click', () => { sb.classList.toggle('open'); scrim && scrim.classList.toggle('show', sb.classList.contains('open')); });
  scrim && scrim.addEventListener('click', closeSb);
  document.addEventListener('click', (e) => {
    const t = e.target.closest('[data-dd]');
    document.querySelectorAll('.dd-menu').forEach((m) => { if (!t || m.id !== t.dataset.dd) m.hidden = true; });
    if (t) { const m = document.getElementById(t.dataset.dd); if (m) m.hidden = !m.hidden; }
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { document.querySelectorAll('.dd-menu,.gsearch-pop').forEach((m) => m.hidden = true); closeSb(); } });

  // ---------- sidebar order: hold an item to start, then drag it to any place in any group ----------
  const nav = sb && sb.querySelector('.sb-nav'); const navEdit = sb && sb.querySelector('.sb-edit');
  if (nav && navEdit) {
    const HOLD = 450, SLOP = 8, EDGE = 44;
    const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let press = null, drag = null, editing = false, droppedAt = 0;
    const groups = () => [...nav.querySelectorAll('.sb-group')];
    const layout = () => Object.fromEntries(groups().map((g) => [g.dataset.group, [...g.querySelectorAll('.sb-item')].map((a) => a.dataset.key)]));
    const markEmpty = () => groups().forEach((g) => g.classList.toggle('is-empty', !g.querySelector('.sb-item')));
    const setEditing = (on) => { editing = on; sb.classList.toggle('editing', on); navEdit.hidden = !on; };
    const post = (body) => fetch('/admin/nav-layout', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF': csrf }, credentials: 'same-origin', body: JSON.stringify(body) })
      .then((r) => { if (!r.ok) throw new Error(r.status); }).catch(() => toast(T('nav_error', 'Not saved'), 'bad'));
    // move nodes, then slide everything from where it was (FLIP)
    function flip(mutate) {
      const els = [...nav.querySelectorAll('.sb-item,.sb-group>span')];
      const was = new Map(els.map((el) => [el, el.getBoundingClientRect().top]));
      mutate();
      if (still) return;
      els.forEach((el) => { const dy = was.get(el) - el.getBoundingClientRect().top; if (Math.abs(dy) > 1) el.animate([{ transform: 'translateY(' + dy + 'px)' }, { transform: 'none' }], { duration: 170, easing: 'cubic-bezier(.2,.8,.2,1)' }); });
    }
    function place() {  // list coordinates (offsetTop), so slides still running do not skew the target
      const y = drag.y - nav.getBoundingClientRect().top - nav.clientTop + nav.scrollTop;
      const gs = groups().filter((g) => g.offsetParent);
      const g = gs.find((el) => y < el.offsetTop + el.offsetHeight) || gs[gs.length - 1];
      const next = [...g.querySelectorAll('.sb-item')].find((a) => a !== drag.item && y < a.offsetTop + a.offsetHeight / 2) || null;
      if (drag.item.parentNode === g && (next ? drag.item.nextElementSibling === next : !drag.item.nextElementSibling)) return;
      flip(() => { g.insertBefore(drag.item, next); markEmpty(); });
    }
    function scroll() {  // auto-scroll while the item is held near the top or bottom of the list
      if (!drag) return;
      const r = nav.getBoundingClientRect();
      const v = drag.y < r.top + EDGE ? -(r.top + EDGE - drag.y) : drag.y > r.bottom - EDGE ? drag.y - (r.bottom - EDGE) : 0;
      if (v && drag.live) { const top = nav.scrollTop; nav.scrollTop += Math.max(-16, Math.min(16, v / 3)); if (nav.scrollTop !== top) place(); }
      drag.raf = requestAnimationFrame(scroll);
    }
    function startDrag(item, ox, oy, x, y, r = item.getBoundingClientRect()) {
      const ghost = item.cloneNode(true); ghost.classList.add('sb-ghost'); ghost.removeAttribute('href');
      Object.assign(ghost.style, { left: r.left + 'px', top: r.top + 'px', width: r.width + 'px', height: r.height + 'px' });
      document.body.appendChild(ghost); item.classList.add('sb-ph'); root.classList.add('sb-dragging');
      drag = { item, ghost, dx: ox - r.left, dy: oy - r.top, x, y, sx: x, sy: y, live: false, before: JSON.stringify(layout()), raf: 0 };
      move(); drag.raf = requestAnimationFrame(scroll);
    }
    function move() {  // a lifted item that is let go without moving stays where it was
      drag.ghost.style.left = (drag.x - drag.dx) + 'px'; drag.ghost.style.top = (drag.y - drag.dy) + 'px';
      drag.live = drag.live || Math.hypot(drag.x - drag.sx, drag.y - drag.sy) > 4;
      if (drag.live) place();
    }
    function endDrag() {
      const { item, ghost, before } = drag; cancelAnimationFrame(drag.raf); drag = null; droppedAt = Date.now();
      root.classList.remove('sb-dragging');
      const done = () => { ghost.remove(); item.classList.remove('sb-ph'); };
      if (still) done();
      else {
        const r = item.getBoundingClientRect();
        ghost.style.transition = 'left .16s ease-out,top .16s ease-out,transform .16s ease-out';
        Object.assign(ghost.style, { left: r.left + 'px', top: r.top + 'px', transform: 'none' });
        setTimeout(done, 170);
      }
      const now = layout(); if (JSON.stringify(now) !== before) post({ groups: now });
    }
    function hold() {  // long press reached: enter edit mode and lift the item under the finger
      const p = press; clearTimeout(p.timer); press = null;
      const r = p.item.getBoundingClientRect();
      setEditing(true);  // empty groups show up now: keep the held item under the finger
      nav.scrollTop += p.item.getBoundingClientRect().top - r.top;
      startDrag(p.item, p.x, p.y, p.lx, p.ly, r);
    }
    nav.addEventListener('pointerdown', (e) => {
      const item = e.target.closest('.sb-item');
      if (!item || e.button !== 0 || drag) return;
      press = { item, id: e.pointerId, touch: e.pointerType !== 'mouse', x: e.clientX, y: e.clientY, lx: e.clientX, ly: e.clientY };
      if (!editing) press.timer = setTimeout(hold, HOLD);  // in edit mode a plain drag is enough
    });
    document.addEventListener('pointermove', (e) => {
      if (drag) { drag.x = e.clientX; drag.y = e.clientY; move(); return; }
      if (!press || e.pointerId !== press.id) return;
      press.lx = e.clientX; press.ly = e.clientY;
      const d = Math.hypot(e.clientX - press.x, e.clientY - press.y);
      if (editing && d > 4) { const p = press; press = null; startDrag(p.item, p.x, p.y, p.lx, p.ly); }
      else if (!editing && d > SLOP) { clearTimeout(press.timer); press = null; }  // scrolling or a normal click-drag
    });
    const up = () => { if (drag) endDrag(); else if (press) { clearTimeout(press.timer); press = null; } };
    document.addEventListener('pointerup', up); document.addEventListener('pointercancel', up);
    sb.addEventListener('touchmove', (e) => { if (drag) e.preventDefault(); }, { passive: false });  // the held item moves, not the list
    nav.addEventListener('contextmenu', (e) => {  // a touch long press: use it as the hold, without the link menu
      if (!e.target.closest('.sb-item') || !(press || drag || editing)) return;
      e.preventDefault(); if (press && press.touch && !editing) hold();
    });
    nav.addEventListener('dragstart', (e) => e.preventDefault());
    nav.addEventListener('click', (e) => { if (editing && e.target.closest('.sb-item')) e.preventDefault(); }, true);
    navEdit.querySelector('[data-nav-done]').addEventListener('click', () => setEditing(false));
    navEdit.querySelector('[data-nav-reset]').addEventListener('click', () => {
      const def = JSON.parse(nav.dataset.default || '{}');
      flip(() => {
        Object.entries(def).forEach(([g, keys]) => { const box = nav.querySelector('.sb-group[data-group="' + g + '"]'); keys.forEach((k) => { const a = nav.querySelector('.sb-item[data-key="' + k + '"]'); if (a && box) box.appendChild(a); }); });
        markEmpty();
      });
      post({ reset: true });
    });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && editing && !drag) setEditing(false); });
    document.addEventListener('click', (e) => { if (editing && !drag && Date.now() - droppedAt > 300 && !sb.contains(e.target)) setEditing(false); });
  }

  // ---------- global search ----------
  const gs = document.getElementById('gsearch'); const gsPop = document.getElementById('gsearch-pop');
  if (gs && gsPop) {
    let timer = null, sel = -1;
    const items = () => [...gsPop.querySelectorAll('a')];
    gs.addEventListener('input', () => {
      clearTimeout(timer); const q = gs.value.trim();
      if (q.length < 2) { gsPop.hidden = true; return; }
      timer = setTimeout(() => {
        fetch('/admin/search?q=' + encodeURIComponent(q), { headers: { 'HX-Request': 'true' }, credentials: 'same-origin' })
          .then((r) => r.text()).then((h) => { gsPop.innerHTML = h; gsPop.hidden = false; sel = -1; }).catch(() => {});
      }, 180);
    });
    gs.addEventListener('focus', () => { if (gsPop.innerHTML.trim() && gs.value.trim().length >= 2) gsPop.hidden = false; });
    gs.addEventListener('keydown', (e) => {
      const it = items(); if (!it.length || gsPop.hidden) return;
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, it.length - 1); } else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); } else if (e.key === 'Enter' && sel >= 0) { e.preventDefault(); location.href = it[sel].href; return; } else return;
      it.forEach((a, i) => a.classList.toggle('sel', i === sel)); it[sel] && it[sel].scrollIntoView({ block: 'nearest' });
    });
    document.addEventListener('click', (e) => { if (!e.target.closest('.gsearch')) gsPop.hidden = true; });
  }
  document.addEventListener('keydown', (e) => {
    if (e.key === '/' && !/input|textarea|select/i.test(document.activeElement.tagName)) { const s = gs || document.querySelector('input[name="q"]'); if (s) { e.preventDefault(); s.focus(); s.select(); } }
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') { const f = document.querySelector('form[data-track]'); if (f) { e.preventDefault(); f.requestSubmit ? f.requestSubmit() : f.submit(); } }
  });

  // ---------- hint card ----------
  document.addEventListener('click', (e) => {
    const b = e.target.closest('[data-dismiss-hint]'); if (!b) return;
    const card = b.closest('.hint-card'); if (card) { card.style.transition = 'opacity .2s, transform .2s'; card.style.opacity = '0'; card.style.transform = 'translateY(-6px)'; setTimeout(() => card.remove(), 200); }
    fetch('/admin/hint/dismiss', { method: 'POST', headers: { 'X-CSRF': csrf }, credentials: 'same-origin' }).catch(() => {});
  });

  // ---------- i18n tabs, repeaters, generic tabs ----------
  function bindI18n(scope) {
    (scope || document).querySelectorAll('[data-i18n]').forEach((box) => {
      if (box.dataset.bound) return; box.dataset.bound = '1';
      const tabs = box.querySelectorAll('.lang-tabs button'), panes = box.querySelectorAll('.pane');
      tabs.forEach((b) => b.addEventListener('click', (ev) => { ev.preventDefault(); tabs.forEach((x) => x.classList.toggle('active', x === b)); panes.forEach((p) => p.hidden = p.dataset.lang !== b.dataset.lang); }));
      panes.forEach((p) => { const f = p.querySelector('input,textarea'); if (f) f.addEventListener('input', () => { const tb = box.querySelector('.lang-tabs button[data-lang="' + p.dataset.lang + '"]'); let d = tb.querySelector('.dot'); if (f.value.trim() && !d) { d = document.createElement('i'); d.className = 'dot'; tb.appendChild(d); } else if (!f.value.trim() && d) d.remove(); }); });
    });
  }
  bindI18n();
  document.addEventListener('htmx:afterSettle', (e) => bindI18n(e.target));
  document.addEventListener('click', (e) => {
    const add = e.target.closest('[data-add-row]'); if (add) { e.preventDefault(); const box = document.getElementById(add.dataset.addRow); const tpl = box.querySelector('template'); box.insertBefore(tpl.content.cloneNode(true), tpl); markDirty(); }
    const rm = e.target.closest('[data-remove-row]'); if (rm) { e.preventDefault(); rm.closest('.rrow').remove(); markDirty(); }
    const tab = e.target.closest('[data-tab]'); if (tab) {
      e.preventDefault(); const g = tab.closest('[data-tabs]'); g.querySelectorAll('[data-tab]').forEach((x) => x.classList.toggle('active', x === tab));
      const scope = g.dataset.tabs ? document.querySelector('[data-tabs-for="' + g.dataset.tabs + '"]') || document : document;
      scope.querySelectorAll('[data-tabpane]').forEach((p) => p.hidden = p.dataset.tabpane !== tab.dataset.tab);
      if (tab.dataset.tab) history.replaceState({}, '', location.pathname + location.search + '#' + tab.dataset.tab);
    }
  });
  if (location.hash) { const t = document.querySelector('[data-tab="' + location.hash.slice(1) + '"]'); if (t) t.click(); }

  // ---------- unsaved changes tracker + sticky save bar ----------
  const tracked = document.querySelector('form[data-track]'); const savebar = document.querySelector('.savebar');
  let dirty = false;
  function markDirty() { if (!tracked) return; dirty = true; savebar && savebar.classList.add('dirty'); const s = savebar && savebar.querySelector('[data-state]'); if (s) s.textContent = savebar.dataset.unsaved || 'Unsaved changes'; }
  if (tracked) {
    tracked.addEventListener('input', markDirty); tracked.addEventListener('change', markDirty);
    tracked.addEventListener('submit', () => { dirty = false; });
    window.addEventListener('beforeunload', (e) => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });
  }
  // form section nav highlight
  const secLinks = [...document.querySelectorAll('.form-nav a[href^="#"]')];
  if (secLinks.length && 'IntersectionObserver' in window) {
    const io = new IntersectionObserver((es) => { es.forEach((en) => { if (en.isIntersecting) secLinks.forEach((a) => a.classList.toggle('active', a.getAttribute('href') === '#' + en.target.id)); }); }, { rootMargin: '-30% 0px -60% 0px' });
    secLinks.forEach((a) => { const s = document.querySelector(a.getAttribute('href')); s && io.observe(s); });
  }

  // ---------- product form: warranty defaults by condition ----------
  const conds = [...document.querySelectorAll('#product-form [name="condition"]')];
  if (conds.length) {
    const defaults = { new: [12, 36], used: [6, 0], refresh: [6, 0] };
    const sw = document.querySelector('input[name="seller_warranty_months"]'), fw = document.querySelector('input[name="factory_warranty_months"]');
    [sw, fw].forEach((i) => i && i.addEventListener('input', () => i.dataset.touched = '1'));
    const cond = { get value() { const c = conds.find((x) => x.checked); return c ? c.value : conds[0].value; } };
    conds.forEach((c) => c.addEventListener('change', () => {
      const d = defaults[cond.value]; if (!d) return;
      if (sw && !sw.dataset.touched) sw.value = d[0]; if (fw && !fw.dataset.touched) fw.value = d[1];
      const lbl = document.getElementById('label-model-row'); if (lbl) lbl.hidden = cond.value !== 'refresh';
      const note = document.getElementById('warranty-autofill'); if (note) note.hidden = false;
      markDirty();
    }));
  }

  // ---------- auction form live preview ----------
  const prev = document.getElementById('lot-preview');
  if (prev) {
    const q = (n) => document.querySelector('[name="' + n + '"]');
    const fmt = (v) => { const n = parseFloat(String(v).replace(',', '.')); return isNaN(n) ? '—' : '$' + n.toLocaleString('en-US', { maximumFractionDigits: 2 }); };
    const upd = () => {
      const qty = parseInt(q('qty')?.value || '1', 10) || 1; const start = parseFloat((q('start_price_total')?.value || '0').replace(',', '.')) || 0; const step = parseFloat((q('step_per_unit')?.value || '0').replace(',', '.')) || 0;
      const set = (k, v) => { const el = prev.querySelector('[data-p="' + k + '"]'); if (el) el.textContent = v; };
      set('title', ((q('brand')?.value || '') + ' ' + (q('model')?.value || '')).trim() || '—');
      const cap = parseInt(q('capacity_gb')?.value || '0', 10); set('cap', cap >= 1000 ? (cap / 1000).toFixed(cap % 1000 ? 1 : 0) + 'TB' : cap + 'GB');
      set('cond', (q('condition')?.value || '').toUpperCase()); const cc = prev.querySelector('[data-p="cond"]'); if (cc) cc.className = 'chip cond-' + (q('condition')?.value || 'used');
      set('qty', qty); set('start', fmt(start)); set('unit', fmt(qty ? start / qty : 0)); set('step', fmt(step) + ' / pc  ·  ' + fmt(step * qty) + ' / lot');
    };
    ['brand', 'model', 'capacity_gb', 'condition', 'qty', 'start_price_total', 'step_per_unit'].forEach((n) => q(n)?.addEventListener('input', upd)); upd();
  }

  // ---------- auction live (SSE) ----------
  document.querySelectorAll('[data-live-auction]').forEach((el) => {
    const id = el.dataset.liveAuction; if (!window.EventSource) return;
    const es = new EventSource('/api/auctions/' + id + '/stream');
    const apply = (d) => {
      const p = el.querySelector('[data-cur]'); if (p && p.textContent !== d.current_total) { p.textContent = d.current_total; p.classList.remove('price-bump'); void p.offsetWidth; p.classList.add('price-bump'); }
      const b = el.querySelector('[data-bids]'); if (b) b.textContent = d.bids; const s = el.querySelector('[data-st]'); if (s) s.textContent = d.status;
      const cd = el.querySelector('[data-countdown]'); if (cd && d.ends_at) cd.dataset.countdown = d.ends_at;
      if (d.type === 'bid' || d.type === 'ended') { const list = document.getElementById('bids-list'); list && window.htmx && htmx.trigger(list, 'refresh'); }
    };
    ['state', 'bid', 'ended'].forEach((ev) => es.addEventListener(ev, (e) => apply(JSON.parse(e.data))));
  });

  // ---------- countdowns ----------
  setInterval(() => document.querySelectorAll('[data-countdown]').forEach((el) => {
    let s = Math.max(0, Math.floor((new Date(el.dataset.countdown) - Date.now()) / 1000)); const d = Math.floor(s / 86400); s -= d * 86400; const h = Math.floor(s / 3600); s -= h * 3600; const m = Math.floor(s / 60); s -= m * 60;
    el.textContent = (d ? d + 'd ' : '') + String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
    el.classList.toggle('urgent', (new Date(el.dataset.countdown) - Date.now()) < 120000);
  }), 1000);

  // ---------- clickable rows, copy, lightbox, quick replies ----------
  document.addEventListener('click', (e) => {
    const tr = e.target.closest('tr.clickable'); if (tr && !e.target.closest('a,button,input,select,form,label')) { if (e.metaKey || e.ctrlKey) window.open(tr.dataset.href, '_blank'); else location.href = tr.dataset.href; }
    const c = e.target.closest('[data-copy]'); if (c) { e.preventDefault(); navigator.clipboard && navigator.clipboard.writeText(c.dataset.copy).then(() => toast(T('copied', 'Copied'), 'ok', 1400)).catch(() => {}); }
    const lb = e.target.closest('[data-lightbox]'); if (lb) { e.preventDefault(); const box = document.createElement('div'); box.className = 'lightbox'; box.innerHTML = '<img src="' + lb.dataset.lightbox + '" alt="">'; box.addEventListener('click', () => box.remove()); document.body.appendChild(box); }
    const qr = e.target.closest('[data-quick]'); if (qr) { e.preventDefault(); const ta = document.querySelector('.composer textarea'); if (ta) { ta.value = (ta.value ? ta.value + '\n' : '') + qr.dataset.quick; ta.focus(); } document.querySelectorAll('.dd-menu').forEach((m) => m.hidden = true); }
    const chk = e.target.closest('[data-check-all]'); if (chk) { document.querySelectorAll('input[name="ids"]').forEach((i) => i.checked = chk.checked); updateBulk(); }
  });
  function updateBulk() { const n = document.querySelectorAll('input[name="ids"]:checked').length; const bar = document.querySelector('.bulkbar'); if (bar) { bar.hidden = n === 0; const c = bar.querySelector('.n'); if (c) c.textContent = n; } }
  document.addEventListener('change', (e) => { if (e.target.name === 'ids') updateBulk(); });
  updateBulk();

  // ---------- image drag reorder ----------
  function bindSortable(scope) {
    (scope || document).querySelectorAll('.sortable').forEach((box) => {
      if (box.dataset.bound) return; box.dataset.bound = '1'; let drag = null;
      box.querySelectorAll('.img-card').forEach((c) => { c.draggable = true; c.addEventListener('dragstart', () => drag = c); c.addEventListener('dragover', (e) => { e.preventDefault(); if (drag && drag !== c) { const r = c.getBoundingClientRect(); box.insertBefore(drag, (e.clientX - r.left) > r.width / 2 ? c.nextSibling : c); } }); });
      box.addEventListener('drop', () => { const ids = [...box.querySelectorAll('.img-card')].map((c) => c.dataset.id); fetch(box.dataset.reorderUrl, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRF': csrf }, body: 'order=' + ids.join(',') }).then((r) => r.ok ? toast(box.dataset.savedText || 'OK', 'ok') : toast('Error', 'bad')); });
    });
  }
  bindSortable();
  // ---------- dropzone (files -> hidden input -> submit) ----------
  function bindDrop(scope) {
    (scope || document).querySelectorAll('.drop[data-for]').forEach((z) => {
      if (z.dataset.bound) return; z.dataset.bound = '1'; const inp = document.getElementById(z.dataset.for);
      z.addEventListener('click', () => inp && inp.click());
      ['dragenter', 'dragover'].forEach((ev) => z.addEventListener(ev, (e) => { e.preventDefault(); z.classList.add('over'); }));
      ['dragleave', 'drop'].forEach((ev) => z.addEventListener(ev, (e) => { e.preventDefault(); z.classList.remove('over'); }));
      z.addEventListener('drop', (e) => { if (!inp || !e.dataTransfer.files.length) return; inp.files = e.dataTransfer.files; inp.dispatchEvent(new Event('change', { bubbles: true })); });
      inp && !z.hasAttribute('data-no-submit') && inp.addEventListener('change', () => { const f = inp.closest('form'); if (f && inp.files.length) { if (window.htmx && f.hasAttribute('hx-post')) htmx.trigger(f, 'submit'); else f.requestSubmit && f.requestSubmit(); } });
    });
  }
  bindDrop();
  document.addEventListener('htmx:afterSettle', (e) => { bindSortable(e.target); bindDrop(e.target); });

  // ---------- support chat: live updates over SSE, no polling ----------
  const chatEl = () => document.getElementById('chat');
  const chatTid = () => { const c = chatEl(); return c ? Number(c.dataset.thread) || 0 : 0; };
  const chatLast = () => { let n = 0; const c = chatEl(); if (c) c.querySelectorAll('.msg[data-id]').forEach((m) => { n = Math.max(n, Number(m.dataset.id)); }); return n; };
  const nearEnd = (c) => c.scrollHeight - c.scrollTop - c.clientHeight < 140;
  // add bubbles in id order, skipping ones already on screen (the composer reply and the stream may both bring a message)
  function chatInsert(html) {
    const c = chatEl(); if (!c || !html) return 0;
    const tpl = document.createElement('template'); tpl.innerHTML = html; let added = 0;
    tpl.content.querySelectorAll('.msg[data-id]').forEach((m) => {
      if (c.querySelector('.msg[data-id="' + m.dataset.id + '"]')) return;
      const next = Array.from(c.querySelectorAll('.msg[data-id]')).find((x) => Number(x.dataset.id) > Number(m.dataset.id));
      c.insertBefore(m, next || null); added++;
      if (m.classList.contains('staff')) {
        const body = Array.from(m.children).filter((x) => x.tagName === 'DIV').map((x) => x.textContent).join(' ').replace(/\s+/g, ' ').trim();
        const twin = Array.from(c.querySelectorAll('.msg.pending:not(.failed)')).find((p) => p.dataset.text && p.dataset.text.trim() === body);
        if (twin) twin.classList.add('arrived');
      }
    });
    if (added) { const e = c.querySelector('[data-chat-empty]'); if (e) e.remove(); }
    return added;
  }
  let chatBusy = false, chatAgain = false;
  function chatCatchUp() {
    const id = chatTid(); if (!id) return;
    if (chatBusy) { chatAgain = true; return; }
    chatBusy = true; const c = chatEl(); const stick = nearEnd(c);
    fetch('/admin/support/' + id + '?partial=messages&after=' + chatLast(), { headers: { 'HX-Request': 'true' }, credentials: 'same-origin' })
      .then((r) => (r.ok ? r.text() : '')).then((html) => { if (chatInsert(html) && stick) c.scrollTop = c.scrollHeight; }).catch(() => {})
      .finally(() => { chatBusy = false; if (chatAgain) { chatAgain = false; chatCatchUp(); } });
  }
  let listTimer, listSeq = 0;
  function refreshList() {
    clearTimeout(listTimer);
    listTimer = setTimeout(() => {
      const l = document.getElementById('thread-list'); if (!l || !l.dataset.listUrl) return;
      const seq = ++listSeq; // a slower, older response must not overwrite a newer list
      fetch(l.dataset.listUrl, { headers: { 'HX-Request': 'true' }, credentials: 'same-origin' }).then((r) => (r.ok ? r.text() : '')).then((html) => {
        const cur = document.getElementById('thread-list'); if (!html || !cur || seq !== listSeq) return;
        const tpl = document.createElement('template'); tpl.innerHTML = html.trim(); const fresh = tpl.content.querySelector('#thread-list'); if (!fresh) return;
        const ul = cur.querySelector('ul'), top = ul ? ul.scrollTop : 0;
        cur.replaceWith(fresh); const nu = fresh.querySelector('ul'); if (nu) nu.scrollTop = top;
      }).catch(() => {});
    }, 200);
  }
  function refreshBadge() {
    fetch('/admin/support/badge', { credentials: 'same-origin' }).then((r) => (r.ok ? r.json() : null)).then((d) => {
      if (!d) return; const a = document.querySelector('.sb-item[href="/admin/support"]'); if (!a) return;
      let cnt = a.querySelector('.cnt'); if (!d.support) { if (cnt) cnt.remove(); return; }
      if (!cnt) { cnt = document.createElement('span'); cnt.className = 'cnt'; a.appendChild(cnt); }
      cnt.textContent = d.support;
    }).catch(() => {});
  }
  if (document.body.dataset.supportStream && window.EventSource) {
    const es = new EventSource('/admin/support/stream');
    const data = (e) => { try { return JSON.parse(e.data); } catch (_) { return {}; } };
    es.addEventListener('ready', () => { chatCatchUp(); refreshList(); refreshBadge(); }); // first connect + every reconnect
    es.addEventListener('msg', (e) => {
      const ev = data(e);
      if (ev.thread_id === chatTid()) chatCatchUp();
      refreshList();
      if (!ev.from_staff) { refreshBadge(); if (ev.thread_id !== chatTid()) toast(T('sup_new', 'New message'), 'info'); }
    });
    es.addEventListener('read', (e) => {
      const ev = data(e);
      if (ev.by === 'customer' && ev.thread_id === chatTid()) document.querySelectorAll('#chat .msg.staff .tick').forEach((x) => x.classList.add('read'));
      refreshList(); refreshBadge();
    });
    es.addEventListener('thread', () => { refreshList(); refreshBadge(); });
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') { chatCatchUp(); refreshList(); } });
  }
  if (chatTid()) setInterval(chatCatchUp, 30000); // safety net if a proxy ever blocks the stream

  // composer: Enter sends (Shift+Enter = new line). Like a messenger: the box clears at once, the bubble
  // shows "sending", replies go out one by one in order, and a failed one keeps its text with a retry button.
  document.querySelectorAll('form.composer').forEach((f) => {
    const ta = f.querySelector('textarea'), fileIn = f.querySelector('input[type=file]'); const jobs = []; let sending = false;
    const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    ta.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); f.requestSubmit(); } });
    ta.addEventListener('input', () => { ta.style.height = 'auto'; ta.style.height = Math.min(ta.scrollHeight, 180) + 'px'; });
    function pump() {
      if (sending || !jobs.length) return;
      sending = true; const job = jobs[0];
      fetch(f.action, { method: 'POST', body: job.fd, credentials: 'same-origin', headers: { 'HX-Request': 'true', 'X-CSRF': csrf } })
        .then((r) => { if (!r.ok) throw new Error(r.status); return r.text(); })
        .then((html) => { jobs.shift(); job.b.remove(); chatInsert(html); const c = chatEl(); if (c) c.scrollTop = c.scrollHeight; refreshList(); })
        .catch(() => {
          jobs.shift(); job.b.classList.add('failed'); job.b._job = job;
          job.b.querySelector('time').innerHTML = '<span>' + esc(f.dataset.failed || 'Not sent') + '</span> <button type="button" class="retry">' + esc(f.dataset.retry || 'Retry') + '</button>';
        })
        .finally(() => { sending = false; pump(); });
    }
    f.addEventListener('submit', (e) => {
      e.preventDefault();
      const text = ta.value.trim(), file = fileIn && fileIn.files[0];
      if (!text && !file) { ta.focus(); return; }
      const fd = new FormData(); fd.append('_csrf', csrf); fd.append('text', text); if (file) fd.append('file', file);
      const c = chatEl(); const b = document.createElement('div'); b.className = 'msg staff pending'; b.dataset.text = text.replace(/\s+/g, ' ');
      b.innerHTML = (file ? '<div class="small" style="opacity:.85">' + esc(file.name) + '</div>' : '') + (text ? '<div>' + esc(text).replace(/\n/g, '<br>') + '</div>' : '') + '<time><span class="spinner"></span></time>';
      if (c) { const em = c.querySelector('[data-chat-empty]'); if (em) em.remove(); c.appendChild(b); c.scrollTop = c.scrollHeight; }
      jobs.push({ fd, b });
      ta.value = ''; ta.style.height = 'auto'; if (fileIn) fileIn.value = ''; const cnt = f.querySelector('[data-count]'); if (cnt) cnt.textContent = '';
      ta.focus(); pump();
    });
    const c = chatEl();
    if (c) c.addEventListener('click', (e) => {
      const r = e.target.closest('.retry'); if (!r) return;
      const b = r.closest('.msg'); b.classList.remove('failed'); b.querySelector('time').innerHTML = '<span class="spinner"></span>';
      jobs.push(b._job); pump();
    });
  });
  const chat = chatEl(); if (chat) chat.scrollTop = chat.scrollHeight;

  // ---------- model chips: type a model + Enter (or paste a list); keeps the hidden `lines` textarea in sync ----------
  const CAP_RE = /^(\d+(?:[.,]\d+)?)\s*(tb|gb|тб|гб)$/i;
  function bindTokens(scope) {
    (scope.querySelectorAll ? scope : document).querySelectorAll('[data-model-tokens]:not([data-bound])').forEach((box) => {
      box.dataset.bound = '1';
      const input = box.querySelector('[data-token-input]'), ta = box.querySelector('textarea'), form = box.closest('form');
      const count = form && form.querySelector('[data-token-count]');
      let items = [];
      const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
      const capOf = (raw) => { const w = raw.split(/\s+/); const m = w.length > 1 && CAP_RE.exec(w[w.length - 1]); return m ? m[1].replace(',', '.') + ' ' + (/[tт]/i.test(m[2]) ? 'TB' : 'GB') : ''; };
      const keyOf = (raw) => raw.split(/\s+/)[0].toUpperCase();
      function sync() {
        const pending = input.value.trim();
        ta.value = items.concat(pending ? [pending] : []).join('\n');
        if (count) { const n = items.length + (pending ? 1 : 0); count.textContent = n ? (count.dataset.tpl || '{n}').replace('{n}', n) : ''; }
      }
      function draw() {
        box.querySelectorAll('.tok').forEach((el) => el.remove());
        items.forEach((raw, i) => {
          const cap = capOf(raw), name = cap ? raw.split(/\s+/).slice(0, -1).join(' ') : raw;
          const el = document.createElement('span'); el.className = 'tok';
          el.innerHTML = '<b>' + esc(name) + '</b>' + (cap ? '<i>' + cap + '</i>' : '') + '<button type="button" aria-label="×" data-i="' + i + '">&times;</button>';
          input.before(el);
        });
        sync();
      }
      function add(text) {
        text.split(/[\n,;]+/).map((s) => s.trim().replace(/^[-•*·]\s*/, '')).filter(Boolean).forEach((t) => {
          // a bare "4TB" belongs to the model typed just before it
          if (CAP_RE.test(t)) { const k = items.length - 1; if (k >= 0 && !capOf(items[k])) items[k] += ' ' + t; return; }
          if (!items.some((x) => keyOf(x) === keyOf(t))) items.push(t);
        });
        draw();
      }
      const commit = () => { if (input.value.trim()) { add(input.value); input.value = ''; sync(); } };
      input.addEventListener('keydown', (e) => {
        if ((e.key === 'Enter' || e.key === ',' || e.key === ';') && input.value.trim()) { e.preventDefault(); commit(); }
        else if (e.key === 'Backspace' && !input.value && items.length) { items.pop(); draw(); }
      });
      input.addEventListener('input', sync);
      input.addEventListener('blur', commit);
      input.addEventListener('paste', (e) => { const t = (e.clipboardData || window.clipboardData).getData('text'); if (/[\n,;]/.test(t)) { e.preventDefault(); add(t); } });
      box.addEventListener('click', (e) => { const x = e.target.closest('[data-i]'); if (x) { items.splice(+x.dataset.i, 1); draw(); input.focus(); } else if (e.target === box) input.focus(); });
      ta.addEventListener('tokens:clear', () => { items = []; input.value = ''; draw(); });
      // nothing entered: stop the submit (also before any other submit handler on the form)
      form && form.addEventListener('submit', (e) => { commit(); if (!ta.value.trim()) { e.preventDefault(); e.stopImmediatePropagation(); box.classList.add('invalid'); input.focus(); setTimeout(() => box.classList.remove('invalid'), 600); } }, true);
      draw();
    });
  }
  bindTokens(document);
  document.addEventListener('htmx:afterSettle', (e) => bindTokens(e.target));

  // ---------- ad post form: pick 3–5 products (search, counter) + live Telegram preview ----------
  function bindAdForm(scope) {
    (scope.querySelectorAll ? scope : document).querySelectorAll('form:not([data-ad-bound])').forEach((form) => {
      const picks = form.querySelector('[data-ad-picks]'); if (!picks) return;
      form.dataset.adBound = '1';
      const boxes = () => Array.from(picks.querySelectorAll('input[type=checkbox]'));
      const count = form.querySelector('[data-ad-count]'), search = form.querySelector('[data-ad-search]'), text = form.querySelector('[data-ad-text]');
      const preview = document.querySelector('[data-ad-preview]');
      const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
      function refresh() {
        const on = boxes().filter((b) => b.checked), n = on.length;
        boxes().forEach((b) => { b.disabled = !b.checked && n >= 5; b.closest('.ad-pick').classList.toggle('is-on', b.checked); });
        if (count) { count.textContent = (count.dataset.tpl || '{n} / 5').replace('{n}', n); count.classList.toggle('ok', n >= 3 && n <= 5); }
        if (!preview) return;
        const body = ((text && text.value) || '').trim();
        if (!body && !n) { preview.innerHTML = '<span class="faint">' + esc(preview.dataset.empty || '') + '</span>'; return; }
        // same shape as the message the bot sends (app/admin/ads.py: render_post)
        const lines = [esc(body), ''];
        on.forEach((b) => lines.push('• <b>' + esc(b.dataset.lineName) + '</b> ' + esc(b.dataset.lineRest)));
        lines.push('', '🛒 <a>' + esc(preview.dataset.app || '') + '</a>');
        preview.innerHTML = lines.join('\n');
      }
      picks.addEventListener('change', refresh);
      text && text.addEventListener('input', refresh);
      if (search) {
        search.addEventListener('keydown', (e) => { if (e.key === 'Enter') e.preventDefault(); });
        search.addEventListener('input', () => { const q = search.value.trim().toLowerCase(); picks.querySelectorAll('.ad-pick').forEach((l) => { l.hidden = !!q && !l.dataset.name.includes(q) && !l.querySelector('input').checked; }); });
      }
      form.addEventListener('submit', (e) => {
        const n = boxes().filter((b) => b.checked).length; if (n >= 3 && n <= 5) return;
        e.preventDefault(); e.stopImmediatePropagation();
        const sec = form.querySelector('#s-products'); if (sec) sec.scrollIntoView({ behavior: 'smooth', block: 'start' });
        if (count) { count.classList.add('bad'); setTimeout(() => count.classList.remove('bad'), 1600); }
      }, true);
      refresh();
    });
  }
  bindAdForm(document);
  document.addEventListener('htmx:afterSettle', (e) => bindAdForm(e.target));

  // ---------- product colour: it comes from the series' direction ----------
  // The series is picked right after the brand (chips of that brand's series, or typed by hand). New product: no
  // colour picker, the colour is the series' (else guessed from the name). Edit: the colour can still be changed in
  // the folded "Direction colour" section; a hand pick stays until the series changes again.
  const COLOR_HINTS = [[/\b(wd\s*)?white\b/i, 'silver'], [/\b(purple|skyhawk|s300)\b/i, 'purple'], [/\b(red|ironwolf|n300)\b/i, 'red'],
    [/\b(gold|exos|ultrastar|mg\d{2})/i, 'gold'], [/\b(black|wd_black|firecuda)\b/i, 'black'], [/\b(blue|barracuda|p300)\b/i, 'blue'],
    [/\bsurveillance\b/i, 'purple'], [/\bnas\b/i, 'red'], [/\benterprise\b/i, 'gold'], [/\bdata\s*cent(er|re)\b/i, 'silver'], [/\bgaming\b/i, 'black'], [/\bdesktop\b/i, 'blue']];
  const normKey = (v) => String(v || '').trim().replace(/\s+/g, ' ').toUpperCase();
  const escHtml = (v) => String(v == null ? '' : v).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  function bindProductColour(scope) {
    (scope.querySelectorAll ? scope : document).querySelectorAll('form[data-colour-form]:not([data-colour-bound])').forEach((form) => {
      form.dataset.colourBound = '1';
      const field = (n) => form.querySelector('[name="' + n + '"]');
      const radios = () => Array.from(form.querySelectorAll('input[type=radio][name=color]'));
      const hidden = form.querySelector('input[data-color-hidden]'), pick = form.querySelector('[data-color-pick]'), now = form.querySelector('[data-color-now]');
      const input = form.querySelector('[data-series-input]'), chips = form.querySelector('[data-series-chips]'), out = form.querySelector('[data-series-out]'), list = document.getElementById('series-list');
      if (!input) return;
      let series = []; try { series = JSON.parse((document.getElementById('series-data') || {}).textContent || '[]'); } catch (e) {}
      const O = out ? out.dataset : {}, C = chips ? chips.dataset : {};
      let dirs = {}; try { dirs = JSON.parse(O.dirs || '{}'); } catch (e) {}
      const brandId = () => (field('brand_id') || {}).value || '';
      const current = () => (hidden ? hidden.value : ((radios().find((r) => r.checked) || {}).value || ''));
      const setColor = (v) => {  // untrusted change: not a hand pick, but the preview and the savebar notice it
        if (hidden) { if (hidden.value !== v) { hidden.value = v; hidden.dispatchEvent(new Event('change', { bubbles: true })); } return; }
        const r = radios().find((x) => x.value === v); if (r && !r.disabled && !r.checked) { r.checked = true; r.dispatchEvent(new Event('change', { bubbles: true })); }
      };
      // the dictionary entry for the typed series: this brand's first, else one every brand that has it agrees on
      const known = () => {
        const k = normKey(input.value); if (!k) return null;
        const same = series.filter((x) => x.k === k), mine = same.find((x) => String(x.b) === brandId());
        if (mine) return mine;
        return same.length && same.every((x) => x.c === same[0].c) ? same[0] : null;
      };
      const guess = () => { const text = [input.value, (field('model') || {}).value].join(' '); const hit = COLOR_HINTS.find(([re]) => re.test(text)); return hit ? hit[1] : ''; };
      const dirName = (c) => (dirs[c] ? dirs[c][0] : c), dirText = (c) => (dirs[c] ? dirs[c][0] + ' · ' + dirs[c][1] : c);
      const dot = (c) => '<span class="series-dot sw sw-' + (c || 'none') + '"></span>';
      let touched = !hidden && radios().some((r) => r.checked && r.value); // on edit a saved colour counts as a choice
      let fromSeries = false, other = false, lastKey = normKey(input.value);

      function renderChips() {
        const b = brandId(), own = series.filter((x) => b && String(x.b) === b), k = normKey(input.value), hit = own.some((x) => x.k === k);
        if (list) { list.textContent = ''; own.forEach((x) => { const o = document.createElement('option'); o.value = x.n; list.appendChild(o); }); }
        if (!chips) return;
        chips.textContent = '';
        if (!b) { chips.innerHTML = '<span class="hint">' + escHtml(C.lPickBrand) + '</span>'; input.hidden = !input.value; return; }
        own.forEach((x) => {
          const btn = document.createElement('button'); btn.type = 'button'; btn.className = 'series-chip' + (x.k === k ? ' on' : ''); btn.dataset.series = x.n; btn.disabled = input.disabled;
          btn.innerHTML = dot(x.c) + escHtml(x.n); btn.title = x.c ? dirText(x.c) : ''; chips.appendChild(btn);
        });
        if (own.length) {
          const o = document.createElement('button'); o.type = 'button'; o.className = 'series-chip series-other' + (other || (k && !hit) ? ' on' : ''); o.dataset.seriesOther = '1'; o.disabled = input.disabled;
          o.textContent = C.lOther; chips.appendChild(o);
        } else if (b !== '__other__') {
          chips.innerHTML = '<span class="hint">' + escHtml(C.lNone) + ' <a href="/admin/series" target="_blank" rel="noopener">→</a></span>';
        }
        input.hidden = own.length > 0 && !other && !(k && !hit);
      }
      function renderOut() {
        const s = known(), c = current();
        if (out) {
          let html;
          if (s && s.c && c === s.c) html = dot(c) + escHtml((O.tSeries || '').replace('{dir}', dirText(c)));
          else if (s && s.c && !hidden) html = dot(s.c) + escHtml((O.tDiff || '').replace('{name}', dirName(s.c))) + ' <button type="button" class="series-apply" data-series-apply>' + escHtml(O.apply) + '</button>';
          else if (c) html = dot(c) + escHtml(((hidden ? O.tGuess : O.tOwn) || '').replace('{dir}', dirText(c)));
          else html = escHtml(O.tNone);
          out.innerHTML = html; out.classList.toggle('on', !!c);
        }
        if (now) now.innerHTML = dot(c) + escHtml(c ? dirName(c) : now.dataset.none);
      }
      const render = () => { renderChips(); renderOut(); };
      // the series (or the brand) changed: take its colour; nothing known → guess from the name
      function apply() {
        const s = known();
        if (s && s.c) { setColor(s.c); touched = false; fromSeries = true; return; }
        if (hidden) { setColor(guess()); return; }  // new product: the colour follows what is typed
        if (touched) return;
        const g = guess(); if (g || !fromSeries) setColor(g);  // a colour the series gave stays until something else gives one
      }
      const onSeries = () => { const k = normKey(input.value); if (k !== lastKey) { lastKey = k; apply(); } render(); };
      input.addEventListener('input', onSeries); input.addEventListener('change', onSeries);
      if (chips) chips.addEventListener('click', (e) => {
        const btn = e.target.closest('button'); if (!btn || btn.disabled) return;
        if (btn.dataset.seriesOther) { other = true; if (known() && known().b && String(known().b) === brandId()) input.value = ''; render(); input.hidden = false; input.focus(); input.dispatchEvent(new Event('input', { bubbles: true })); return; }
        other = false; input.value = normKey(input.value) === normKey(btn.dataset.series) ? '' : btn.dataset.series;  // a second tap clears it
        input.dispatchEvent(new Event('input', { bubbles: true }));
      });
      if (out) out.addEventListener('click', (e) => { const s = known(); if (e.target.closest('[data-series-apply]') && s && s.c) { setColor(s.c); touched = false; fromSeries = true; renderOut(); } });
      if (pick) pick.addEventListener('change', (e) => { if (e.isTrusted) touched = true; renderOut(); });
      const model = field('model'); if (model) { const onModel = () => { if (!known() && (hidden || !touched)) { const g = guess(); if (hidden || g || !fromSeries) setColor(g); } renderOut(); }; model.addEventListener('input', onModel); model.addEventListener('change', onModel); }
      const brand = field('brand_id'); if (brand) brand.addEventListener('change', () => { other = false; lastKey = ''; if (input.value.trim()) onSeries(); else render(); });
      if (hidden && !hidden.value) apply();
      render();
    });
  }
  bindProductColour(document);
  document.addEventListener('htmx:afterSettle', (e) => bindProductColour(e.target));

  // ---------- file input counters ----------
  document.querySelectorAll('input[type=file][multiple]').forEach((i) => i.addEventListener('change', () => { const l = i.closest('label'); const c = l && l.querySelector('[data-count]'); if (c) c.textContent = i.files.length ? '(' + i.files.length + ')' : ''; }));
})();

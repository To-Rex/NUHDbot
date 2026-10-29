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

  // ---------- composer: Ctrl+Enter sends, autosize ----------
  document.querySelectorAll('.composer textarea').forEach((ta) => {
    ta.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); ta.form.requestSubmit(); } });
    ta.addEventListener('input', () => { ta.style.height = 'auto'; ta.style.height = Math.min(ta.scrollHeight, 180) + 'px'; });
  });
  const chat = document.getElementById('chat'); if (chat) chat.scrollTop = chat.scrollHeight;
  document.addEventListener('htmx:afterSettle', (e) => { if (e.target.id === 'chat') e.target.scrollTop = e.target.scrollHeight; });

  // ---------- file input counters ----------
  document.querySelectorAll('input[type=file][multiple]').forEach((i) => i.addEventListener('change', () => { const l = i.closest('label'); const c = l && l.querySelector('[data-count]'); if (c) c.textContent = i.files.length ? '(' + i.files.length + ')' : ''; }));
})();

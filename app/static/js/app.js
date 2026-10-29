/* New & Used Hard Drives — Mini App runtime: Telegram SDK glue, HTMX config, micro-interactions. */
(function () {
  // Boosted navigations swap <body> and re-run this script; the document-level wiring must only be installed once.
  if (window.NUHD && window.NUHD.booted) return;
  const tg = window.Telegram && window.Telegram.WebApp;
  const root = document.documentElement;

  // ---------- Theme: auto (Telegram / OS) | light | dark ----------
  const mq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  function themeMode() { return root.dataset.themeMode || 'auto'; }
  function resolvedTheme() {
    const mode = themeMode();
    if (mode === 'light' || mode === 'dark') return mode;
    if (tg && tg.colorScheme) return tg.colorScheme === 'dark' ? 'dark' : 'light';
    return mq && mq.matches ? 'dark' : 'light';
  }
  function applyTheme() {
    const dark = resolvedTheme() === 'dark';
    root.classList.toggle('tg-dark', dark);
    // explicit modes pin data-theme; in auto inside Telegram we pin it to Telegram's scheme (the webview may ignore prefers-color-scheme)
    if (themeMode() === 'auto' && !tg) root.removeAttribute('data-theme'); else root.setAttribute('data-theme', dark ? 'dark' : 'light');
    const meta = document.querySelector('meta[name="color-scheme"]');
    if (meta) meta.setAttribute('content', themeMode() === 'auto' ? 'light dark' : themeMode());
    if (tg) {
      try {
        const bg = getComputedStyle(root).getPropertyValue('--bg').trim();
        tg.setHeaderColor && tg.setHeaderColor(bg || (dark ? '#0E1116' : '#F5F6F8'));
        tg.setBackgroundColor && tg.setBackgroundColor(bg || (dark ? '#0E1116' : '#F5F6F8'));
        tg.setBottomBarColor && tg.setBottomBarColor(bg || (dark ? '#0E1116' : '#F5F6F8'));
      } catch (e) {}
    }
    document.querySelectorAll('[data-theme-opt]').forEach((b) => {
      const on = b.dataset.themeOpt === themeMode();
      b.classList.toggle('active', on); b.setAttribute('aria-checked', on ? 'true' : 'false');
    });
  }
  function setTheme(mode) {
    if (!['auto', 'light', 'dark'].includes(mode)) mode = 'auto';
    const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!reduce) { root.classList.add('theme-transition'); setTimeout(() => root.classList.remove('theme-transition'), 260); }
    root.dataset.themeMode = mode;
    applyTheme();
    try { haptic.select(); } catch (e) {}
    try { fetch('/app/theme/' + mode, { method: 'POST', credentials: 'same-origin' }); } catch (e) {}
  }
  if (tg) {
    try { tg.ready(); tg.expand(); } catch (e) {}
    try { tg.disableVerticalSwipes && tg.disableVerticalSwipes(); } catch (e) {}
    try { tg.enableClosingConfirmation && document.body.dataset.confirmClose === '1' && tg.enableClosingConfirmation(); } catch (e) {}
    tg.onEvent && tg.onEvent('themeChanged', () => { if (themeMode() === 'auto') applyTheme(); });
  }
  if (mq && mq.addEventListener) mq.addEventListener('change', () => { if (themeMode() === 'auto') applyTheme(); });
  applyTheme();
  document.addEventListener('click', (e) => {
    const b = e.target.closest('[data-theme-cycle]');
    if (!b) return;
    b.classList.remove('spin'); void b.offsetWidth; b.classList.add('spin');
    setTheme(resolvedTheme() === 'dark' ? 'light' : 'dark');
  });

  const haptic = {
    light() { try { tg && tg.HapticFeedback.impactOccurred('light'); } catch (e) {} },
    medium() { try { tg && tg.HapticFeedback.impactOccurred('medium'); } catch (e) {} },
    success() { try { tg && tg.HapticFeedback.notificationOccurred('success'); } catch (e) {} },
    error() { try { tg && tg.HapticFeedback.notificationOccurred('error'); } catch (e) {} },
    select() { try { tg && tg.HapticFeedback.selectionChanged(); } catch (e) {} },
  };

  // Back button: show on every page except roots
  function syncBackButton() {
    if (!tg || !tg.BackButton) return;
    const roots = ['/app', '/app/', '/app/home', '/app/catalog', '/app/auctions', '/app/orders', '/app/profile', '/app/info', '/app/new'];
    const isRoot = roots.includes(location.pathname);
    if (isRoot) tg.BackButton.hide(); else tg.BackButton.show();
  }
  if (tg && tg.BackButton) {
    tg.BackButton.onClick(() => {
      haptic.light();
      const back = document.body.dataset.back;
      if (back) location.href = back; else if (history.length > 1) history.back(); else location.href = '/app/home';
    });
  }
  syncBackButton();

  // ---------- toasts ----------
  function toast(msg, type, ms) {
    let box = document.querySelector('.toasts');
    if (!box) { box = document.createElement('div'); box.className = 'toasts'; document.body.appendChild(box); }
    const el = document.createElement('div');
    el.className = 'toast ' + (type || '');
    var ic = type === 'ok'
      ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8.5"/><path d="m8.5 12.5 2.5 2.5 4.5-5"/></svg>'
      : (type === 'bad' || type === 'warn')
        ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3.5 21 19.5H3z"/><path d="M12 10v4M12 17h.01"/></svg>'
        : '';
    el.innerHTML = ic + '<span></span>';
    el.lastChild.textContent = msg;
    box.appendChild(el);
    if (type === 'ok') haptic.success(); else if (type === 'bad') haptic.error(); else haptic.light();
    setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 300); }, ms || 2600);
  }

  // ---------- progress bar for navigations ----------
  let bar = document.getElementById('page-progress');
  if (!bar) { bar = document.createElement('div'); bar.id = 'page-progress'; document.body.appendChild(bar); }
  function progressStart() { bar.classList.remove('done'); void bar.offsetWidth; bar.classList.add('active'); }
  function progressDone() { bar.classList.remove('active'); bar.classList.add('done'); setTimeout(() => bar.classList.remove('done'), 400); }

  // ---------- HTMX wiring ----------
  document.addEventListener('htmx:configRequest', (e) => { e.detail.headers['X-Lang'] = root.lang || ''; });
  document.addEventListener('htmx:beforeRequest', (e) => { if (e.detail.boosted || e.detail.elt.hasAttribute('hx-get')) progressStart(); });
  document.addEventListener('htmx:afterRequest', progressDone);
  document.addEventListener('htmx:afterSettle', () => { syncBackButton(); lazyImages(); applyTheme(); positionLens(false); bindTopbar(); });
  document.addEventListener('htmx:responseError', () => toast(root.dataset.errorText || 'Error', 'bad'));
  document.addEventListener('htmx:sendError', () => toast(root.dataset.offlineText || 'Offline', 'bad'));
  // server-driven toasts: HX-Trigger: {"toast": {"msg": "...", "type": "ok"}}
  document.addEventListener('toast', (e) => { const d = e.detail || {}; toast(d.msg || d.value, d.type); });
  document.addEventListener('haptic', (e) => { const k = (e.detail && e.detail.value) || 'light'; (haptic[k] || haptic.light)(); });
  document.addEventListener('confetti', () => confetti());
  document.addEventListener('cartUpdated', (e) => {
    const n = e.detail && e.detail.count;
    document.querySelectorAll('[data-cart-count]').forEach((el) => {
      el.textContent = n; el.hidden = !n; el.classList.remove('pop'); void el.offsetWidth; el.classList.add('badge-count');
    });
  });

  // ---------- lazy images with fade ----------
  function lazyImages() {
    document.querySelectorAll('img.lazy:not([data-bound])').forEach((img) => {
      img.dataset.bound = '1';
      if (img.complete && img.naturalWidth) img.classList.add('loaded');
      else img.addEventListener('load', () => img.classList.add('loaded'), { once: true });
      img.addEventListener('error', () => { img.classList.add('loaded'); img.src = '/static/img/placeholder.svg'; }, { once: true });
    });
  }
  lazyImages();

  // ---------- bottom bar: sliding glass lens ----------
  function positionLens(animate) {
    const nav = document.querySelector('.bottom-nav');
    if (!nav) return;
    let lens = nav.querySelector('.nav-lens');
    if (!lens) { lens = document.createElement('span'); lens.className = 'nav-lens'; nav.prepend(lens); }
    const active = nav.querySelector('a.active') || nav.querySelector('a');
    if (!active) return;
    const navRect = nav.getBoundingClientRect(); const r = active.getBoundingClientRect();
    if (!r.width) return;
    if (animate === false) lens.style.transition = 'none';
    lens.style.width = r.width + 'px';
    lens.style.setProperty('--lens-x', (r.left - navRect.left) + 'px');
    if (animate === false) { void lens.offsetWidth; lens.style.transition = ''; }
    nav.classList.add('lens-ready');
  }
  positionLens(false);
  window.addEventListener('resize', () => positionLens(false), { passive: true });
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => positionLens(false));
  // when a nav item is tapped, slide the lens immediately so navigation feels instant
  document.addEventListener('pointerdown', (e) => {
    const a = e.target.closest('.bottom-nav a');
    if (!a || a.classList.contains('active')) return;
    const nav = a.closest('.bottom-nav');
    nav.querySelectorAll('a').forEach((x) => x.classList.toggle('active', x === a));
    positionLens(true);
  }, { passive: true });

  // ---------- top bar shadow on scroll ----------
  function bindTopbar() {
    const topbar = document.querySelector('.topbar');
    if (!topbar || topbar.dataset.bound) return;
    topbar.dataset.bound = '1';
    const onScroll = () => topbar.classList.toggle('scrolled', window.scrollY > 4);
    window.addEventListener('scroll', onScroll, { passive: true }); onScroll();
  }
  bindTopbar();

  // ---------- tap haptics ----------
  document.addEventListener('pointerdown', (e) => {
    const b = e.target.closest('.btn, .fchip, .icon-btn, .pcard, .quick a, .bottom-nav a, .stepper button, .list-item');
    if (!b) return;
    if (b.matches('.bottom-nav a, .fchip, .stepper button')) haptic.select(); else haptic.light();
  }, { passive: true });

  // ---------- steppers ----------
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-step]');
    if (!btn) return;
    const input = btn.parentElement.querySelector('input[type="number"]') || btn.parentElement.querySelector('input:not([type=hidden])');
    if (!input) return;
    const step = parseInt(btn.dataset.step, 10);
    const min = parseInt(input.min || '1', 10), max = parseInt(input.max || '999999', 10);
    let v = parseInt(input.value || '0', 10) + step;
    if (v < min) { v = min; input.classList.add('invalid'); setTimeout(() => input.classList.remove('invalid'), 400); haptic.error(); }
    if (v > max) { v = max; input.classList.add('invalid'); setTimeout(() => input.classList.remove('invalid'), 400); haptic.error(); }
    input.value = v; input.dispatchEvent(new Event('input', { bubbles: true })); input.dispatchEvent(new Event('change', { bubbles: true }));
  });

  // ---------- copy to clipboard ----------
  document.addEventListener('click', (e) => {
    const c = e.target.closest('[data-copy]');
    if (!c) return;
    navigator.clipboard && navigator.clipboard.writeText(c.dataset.copy).then(() => toast(c.dataset.copiedText || 'Copied', 'ok', 1400));
  });

  // ---------- gallery dots + lightbox ----------
  document.addEventListener('scroll', (e) => {
    const track = e.target;
    if (!(track instanceof Element) || !track.classList.contains('gallery-track')) return;
    const i = Math.round(track.scrollLeft / track.clientWidth);
    const g = track.closest('.gallery');
    g && g.querySelectorAll('.gallery-dots span').forEach((d, k) => d.classList.toggle('active', k === i));
    const thumbs = document.querySelector('.thumbs');
    thumbs && thumbs.querySelectorAll('img').forEach((d, k) => d.classList.toggle('active', k === i));
  }, true);
  document.addEventListener('click', (e) => {
    const th = e.target.closest('.thumbs img');
    if (th) { const track = document.querySelector('.gallery-track'); track && track.scrollTo({ left: th.dataset.index * track.clientWidth, behavior: 'smooth' }); return; }
    const z = e.target.closest('[data-lightbox]');
    if (z) {
      const src = z.dataset.lightbox; const lb = document.createElement('div'); lb.className = 'lightbox';
      lb.innerHTML = '<img src="' + src + '" alt=""><button class="close" aria-label="close"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg></button>';
      lb.addEventListener('click', () => lb.remove()); document.body.appendChild(lb); haptic.medium();
    }
  });

  // ---------- bottom sheets ----------
  window.openSheet = function (id) { const s = document.getElementById(id); if (!s) return; s.hidden = false; haptic.light(); };
  window.closeSheet = function (id) {
    const s = document.getElementById(id); if (!s) return;
    s.querySelectorAll('.sheet,.sheet-backdrop').forEach((x) => x.classList.add('closing'));
    setTimeout(() => { s.hidden = true; s.querySelectorAll('.closing').forEach((x) => x.classList.remove('closing')); }, 240);
  };
  document.addEventListener('click', (e) => { const o = e.target.closest('[data-open-sheet]'); if (o) openSheet(o.dataset.openSheet); const c = e.target.closest('[data-close-sheet]'); if (c) closeSheet(c.dataset.closeSheet); });

  // ---------- countdowns ----------
  function tickCountdowns() {
    document.querySelectorAll('[data-countdown]').forEach((el) => {
      const end = new Date(el.dataset.countdown).getTime(); let s = Math.max(0, Math.floor((end - Date.now()) / 1000));
      const d = Math.floor(s / 86400); s -= d * 86400; const h = Math.floor(s / 3600); s -= h * 3600; const m = Math.floor(s / 60); s -= m * 60;
      const pad = (n) => String(n).padStart(2, '0');
      const cells = el.querySelectorAll('[data-u]');
      if (cells.length) {
        cells.forEach((c) => { const u = c.dataset.u; const v = u === 'd' ? d : u === 'h' ? h : u === 'm' ? m : s; const t = c.firstChild; if (t && t.nodeValue !== pad(v)) t.nodeValue = pad(v); });
      } else el.textContent = (d ? d + 'd ' : '') + pad(h) + ':' + pad(m) + ':' + pad(s);
      el.classList.toggle('urgent', end - Date.now() < 120000 && end > Date.now());
      if (end <= Date.now() && !el.dataset.ended) { el.dataset.ended = '1'; document.dispatchEvent(new CustomEvent('countdown:ended', { detail: { el } })); }
    });
  }
  setInterval(tickCountdowns, 1000); tickCountdowns();

  // ---------- confetti ----------
  function confetti() {
    const box = document.createElement('div'); box.className = 'confetti';
    const colors = ['#1E4FD6', '#1A7F4B', '#B7791F', '#13161C', '#5B8CFF', '#C2362F'];
    for (let i = 0; i < 70; i++) { const p = document.createElement('i'); p.style.left = Math.random() * 100 + 'vw'; p.style.background = colors[i % colors.length]; p.style.animationDelay = Math.random() * .6 + 's'; p.style.transform = 'rotate(' + Math.random() * 360 + 'deg)'; box.appendChild(p); }
    document.body.appendChild(box); haptic.success(); setTimeout(() => box.remove(), 2600);
  }

  // ---------- SSE helper (auction live state) ----------
  window.liveAuction = function (id, onState) {
    if (!window.EventSource) return setInterval(() => fetch('/api/auctions/' + id + '/state').then((r) => r.json()).then(onState), 3000);
    let es; let retry = 1000;
    function connect() {
      es = new EventSource('/api/auctions/' + id + '/stream');
      es.addEventListener('state', (e) => { retry = 1000; onState(JSON.parse(e.data)); });
      es.addEventListener('bid', (e) => onState(JSON.parse(e.data)));
      es.addEventListener('ended', (e) => onState(JSON.parse(e.data)));
      es.onerror = () => { es.close(); setTimeout(connect, retry); retry = Math.min(retry * 2, 15000); };
    }
    connect();
    return es;
  };

  // ---------- Telegram helpers for templates ----------
  window.NUHD = { booted: true, tg, haptic, toast, confetti, progressStart, progressDone, setTheme, resolvedTheme,
    requestContact(cb) {
      if (tg && tg.requestContact) { tg.requestContact((ok) => cb(!!ok)); } else cb(false);
    },
    mainButton(text, onClick) {
      if (!tg || !tg.MainButton) return null;
      tg.MainButton.setText(text); tg.MainButton.show(); tg.MainButton.onClick(onClick); return tg.MainButton;
    },
    hideMainButton() { try { tg && tg.MainButton.hide(); } catch (e) {} },
  };
})();

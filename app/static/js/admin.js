(function(){
  const csrf = document.querySelector('meta[name="csrf"]')?.content || '';
  document.addEventListener('htmx:configRequest', e => { e.detail.headers['X-CSRF'] = csrf; });
  // toasts
  function toast(msg, type, ms){ let box=document.querySelector('.toasts'); if(!box){box=document.createElement('div');box.className='toasts';document.body.appendChild(box);} const el=document.createElement('div'); el.className='toast '+(type||''); el.textContent=msg; box.appendChild(el); setTimeout(()=>{el.classList.add('out');setTimeout(()=>el.remove(),300);}, ms||3200); }
  window.toast = toast;
  document.addEventListener('toast', e => { const d=e.detail||{}; toast(d.msg||d.value, d.type); });
  document.addEventListener('htmx:responseError', e => { toast((e.detail.xhr && e.detail.xhr.responseText && e.detail.xhr.responseText.length<200 ? e.detail.xhr.responseText : 'Error '+e.detail.xhr.status), 'bad'); });
  const params = new URLSearchParams(location.search);
  if (params.get('flash')) { toast(params.get('flash'), params.get('flash_kind')||'ok'); params.delete('flash'); params.delete('flash_kind'); const qs = params.toString(); history.replaceState({}, '', location.pathname + (qs ? '?' + qs : '') + location.hash); }
  // confirm dialogs
  document.addEventListener('submit', e => { const f=e.target; if (f.dataset.confirm && !confirm(f.dataset.confirm)) e.preventDefault(); });
  document.addEventListener('htmx:confirm', e => { const el=e.detail.elt; if (el.dataset.confirm) { e.preventDefault(); if (confirm(el.dataset.confirm)) e.detail.issueRequest(); } });
  // sidebar on mobile
  document.querySelector('.menu-btn')?.addEventListener('click', () => document.querySelector('.sidebar').classList.toggle('open'));
  // language tabs for i18n fields: <div class="i18n" data-i18n><div class="lang-tabs">..</div><div class="pane" data-lang="uz">..
  document.querySelectorAll('[data-i18n]').forEach(box => {
    const tabs = box.querySelectorAll('.lang-tabs button'), panes = box.querySelectorAll('.pane');
    tabs.forEach(b => b.addEventListener('click', ev => { ev.preventDefault(); tabs.forEach(x=>x.classList.toggle('active', x===b)); panes.forEach(p=>p.hidden = p.dataset.lang !== b.dataset.lang); }));
  });
  // generic repeater: [data-repeater] with template
  document.addEventListener('click', e => {
    const add = e.target.closest('[data-add-row]'); if (add) { e.preventDefault(); const box=document.getElementById(add.dataset.addRow); const tpl=box.querySelector('template'); box.insertBefore(tpl.content.cloneNode(true), tpl); }
    const rm = e.target.closest('[data-remove-row]'); if (rm) { e.preventDefault(); rm.closest('.rrow').remove(); }
    const tab = e.target.closest('[data-tab]'); if (tab) { e.preventDefault(); const g=tab.closest('[data-tabs]'); g.querySelectorAll('[data-tab]').forEach(x=>x.classList.toggle('active',x===tab)); document.querySelectorAll('[data-tabpane]').forEach(p=>{ if(p.closest('[data-tabs-for]')?.dataset.tabsFor===g.dataset.tabs||!p.closest('[data-tabs-for]')) p.hidden = p.dataset.tabpane !== tab.dataset.tab; }); }
  });
  // warranty defaults by condition on product form
  const cond = document.querySelector('select[name="condition"]');
  if (cond) {
    const defaults = { new: [12, 36], used: [6, 0], refresh: [6, 0] };
    cond.addEventListener('change', () => {
      const d = defaults[cond.value]; if (!d) return;
      const sw = document.querySelector('input[name="seller_warranty_months"]'), fw = document.querySelector('input[name="factory_warranty_months"]');
      if (sw && !sw.dataset.touched) sw.value = d[0]; if (fw && !fw.dataset.touched) fw.value = d[1];
      const lbl = document.getElementById('label-model-row'); if (lbl) lbl.hidden = cond.value !== 'refresh';
    });
    document.querySelectorAll('input[name="seller_warranty_months"],input[name="factory_warranty_months"]').forEach(i => i.addEventListener('input', () => i.dataset.touched = '1'));
  }
  // auction live price (SSE)
  document.querySelectorAll('[data-live-auction]').forEach(el => {
    const id = el.dataset.liveAuction;
    if (!window.EventSource) return;
    const es = new EventSource('/api/auctions/' + id + '/stream');
    const apply = d => { const p=el.querySelector('[data-cur]'); if (p && p.textContent !== d.current_total) { p.textContent = d.current_total; p.classList.remove('price-bump'); void p.offsetWidth; p.classList.add('price-bump'); } const b=el.querySelector('[data-bids]'); if(b) b.textContent=d.bids; const s=el.querySelector('[data-st]'); if(s) s.textContent=d.status; if (d.type==='bid' || d.type==='ended') { const list=document.getElementById('bids-list'); list && htmx.trigger(list, 'refresh'); } };
    es.addEventListener('state', e => apply(JSON.parse(e.data))); es.addEventListener('bid', e => apply(JSON.parse(e.data))); es.addEventListener('ended', e => apply(JSON.parse(e.data)));
  });
  // countdowns
  setInterval(() => document.querySelectorAll('[data-countdown]').forEach(el => { let s=Math.max(0,Math.floor((new Date(el.dataset.countdown)-Date.now())/1000)); const d=Math.floor(s/86400); s-=d*86400; const h=Math.floor(s/3600); s-=h*3600; const m=Math.floor(s/60); s-=m*60; el.textContent=(d?d+'d ':'')+String(h).padStart(2,'0')+':'+String(m).padStart(2,'0')+':'+String(s).padStart(2,'0'); }), 1000);
  // clickable rows
  document.addEventListener('click', e => { const tr = e.target.closest('tr.clickable'); if (tr && !e.target.closest('a,button,input,select,form')) location.href = tr.dataset.href; });
  // keyboard: "/" focuses search
  document.addEventListener('keydown', e => { if (e.key === '/' && !/input|textarea|select/i.test(document.activeElement.tagName)) { const s=document.querySelector('input[name="q"]'); if (s) { e.preventDefault(); s.focus(); } } });
  // image drag reorder
  document.querySelectorAll('.sortable').forEach(box => {
    let drag=null;
    box.querySelectorAll('.img-card').forEach(c => { c.draggable = true; c.addEventListener('dragstart', () => drag=c); c.addEventListener('dragover', e => { e.preventDefault(); if (drag && drag!==c) { const r=c.getBoundingClientRect(); box.insertBefore(drag, (e.clientX - r.left) > r.width/2 ? c.nextSibling : c); } }); });
    box.addEventListener('drop', () => { const ids=[...box.querySelectorAll('.img-card')].map(c=>c.dataset.id); fetch(box.dataset.reorderUrl, {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded','X-CSRF':csrf}, body:'order='+ids.join(',')}).then(r=>r.ok?toast(box.dataset.savedText||'OK','ok'):toast('Error','bad')); });
  });
  // file input preview count
  document.querySelectorAll('input[type=file][multiple]').forEach(i => i.addEventListener('change', () => { const l=i.closest('label'); if (l) l.querySelector('[data-count]') && (l.querySelector('[data-count]').textContent = i.files.length ? '('+i.files.length+')' : ''); }));
})();

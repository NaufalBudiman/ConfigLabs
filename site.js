/* ConfigLabs — single source of truth for version numbers.
   Change them here only; every page reads them from this file. */
window.CL = { version: '7.11.0', wifi: '5.30', topo: '2.1', rack: '1.3' };
(function () {
  function fill() {
    document.querySelectorAll('[data-cl-version]').forEach(function (e) { e.textContent = 'v' + CL.version; });
    document.querySelectorAll('[data-cl-wifi]').forEach(function (e) {
      var p = e.getAttribute('data-cl-wifi');
      e.textContent = (p || 'v') + CL.wifi;
    });
    document.querySelectorAll('[data-cl-rack]').forEach(function (e) { e.textContent = 'v' + CL.rack; });
    document.querySelectorAll('[data-cl-topo]').forEach(function (e) { e.textContent = 'v' + CL.topo; });
    document.querySelectorAll('[data-cl-title]').forEach(function (e) { e.title = (e.getAttribute('data-cl-title') || '') + CL.version; });
    document.querySelectorAll('[data-cl-year]').forEach(function (e) { e.textContent = new Date().getFullYear(); });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fill); else fill();
})();
/* The one top nav, rendered into <div id="cl-nav"></div> on every page (styles in site.css).
   It keeps the hooks older page code expects: a hidden #theme-btn and #auth-nav, the page's own
   toggleTheme() and authOpenModal() when they exist, and the 'clab_theme' / 'clab_token' keys. */
(function () {
  var I = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">';
  var LINKS = [
    ['/', 'Home', '<path d="M3 12L12 3l9 9M5 10v10h14V10"/>', ['/', '/index.html']],
    ['/dashboard.html', 'Dashboard', '<rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>', ['/dashboard.html', '/dashboard']],
    ['/builder.html', 'Builder', '<path d="M13 2L3 14h7l-1 8 10-12h-7l1-8z"/>', ['/builder.html', '/builder']],
    ['/translate.html', 'Translator', '<path d="M4 7h13l-3-3M20 17H7l3 3"/>', ['/translate.html', '/translator']],
    ['/wifi.html', 'WiFi Planner', '<path d="M5 12.55a11 11 0 0 1 14.08 0"/><path d="M1.42 9a16 16 0 0 1 21.16 0"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><circle cx="12" cy="20" r="1"/>', ['/wifi.html', '/wifi']],
    ['/topology.html', 'Topology', '<rect x="9" y="3" width="6" height="5" rx="1"/><rect x="3" y="16" width="6" height="5" rx="1"/><rect x="15" y="16" width="6" height="5" rx="1"/><path d="M12 8v4M6 16v-4h12v4"/>', ['/topology.html', '/topology', '/topology-editor.html', '/topology-auto.html']],
    ['/rack.html', 'Rack Builder', '<rect x="5" y="2" width="14" height="20" rx="1.5"/><path d="M5 7h14M5 12h14M5 17h14"/>', ['/rack.html', '/rack', '/rack-editor.html']],
    ['/about.html', 'About', '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>', ['/about.html', '/about']]
  ];
  var NEXT = ['/', '/dashboard.html', '/builder.html', '/translate.html', '/wifi.html', '/about.html'];   // ConfigLab.py AUTH_NEXT
  var JWT = /^[\w-]+\.[\w-]+\.[\w-]+$/;
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  function $(id) { return document.getElementById(id); }
  var path = location.pathname.replace(/\/+$/, '') || '/';

  function theme() { var b = document.body, h = document.documentElement; return (b && b.dataset.theme) || h.dataset.theme || 'dark'; }
  function applyTheme(t) { document.documentElement.dataset.theme = t; if (document.body) document.body.dataset.theme = t; var b = $('cl-theme'); if (b) b.setAttribute('aria-label', t === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'); }
  function toggle() {
    var before = theme();
    if (typeof window.toggleTheme === 'function') { try { window.toggleTheme(); } catch (e) {} }
    var t = theme(); if (t === before) t = before === 'light' ? 'dark' : 'light';
    applyTheme(t); set('clab_theme', t);
  }

  function render() {
    var slot = $('cl-nav'); if (!slot || slot.getAttribute('data-ready')) return;
    slot.setAttribute('data-ready', '1');
    var links = LINKS.map(function (l) {
      var on = l[3].indexOf(path) >= 0;
      return '<a href="' + l[0] + '" class="cl-link' + (on ? ' on" aria-current="page' : '') + '">' + I + l[2] + '</svg>' + l[1] + '</a>';
    }).join('');
    slot.innerHTML = '<header class="cl-top">' +
      '<a href="/" class="cl-brand" aria-label="ConfigLabs home"><span class="cl-logo"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 2v7.527a2 2 0 0 1-.211.896L4.72 20.55a1 1 0 0 0 .9 1.45h12.76a1 1 0 0 0 .9-1.45l-5.069-10.127A2 2 0 0 1 14 9.527V2"/><path d="M8.5 2h7"/><path d="M7 16h10"/></svg></span><span>Config<em>Labs</em></span></a>' +
      '<div class="cl-links" role="navigation" aria-label="Main">' + links + '</div>' +
      '<div class="cl-actions">' +
        '<button class="cl-ibtn" id="cl-theme" type="button" title="Theme">' +
          '<svg class="cl-i-moon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/></svg>' +
          '<svg class="cl-i-sun" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/></svg>' +
        '</button>' +
        '<div class="cl-acct" id="cl-acct"></div>' +
        '<span id="theme-btn" hidden></span><div id="auth-nav" hidden></div>' +   // hooks for older page scripts
      '</div></header>';
    $('cl-theme').addEventListener('click', toggle);
    var saved = get('clab_theme') || get('configlabs-theme');
    if (saved === 'light' || saved === 'dark') applyTheme(saved); else applyTheme(theme());
    account();
  }

  // ---- account: Log in button, or the avatar with a small menu ----
  var who = null, tok = null;
  function login() {
    if (typeof window.authOpenModal === 'function') { try { window.authOpenModal(); return; } catch (e) {} }
    location.href = '/auth/google?next=' + encodeURIComponent(NEXT.indexOf(path) >= 0 ? path : '/dashboard.html');
  }
  function paint() {
    var a = $('cl-acct'); if (!a) return;
    if (!who) { a.innerHTML = tok ? '<span class="cl-av cl-sk" aria-hidden="true"></span>' : '<button class="cl-login" type="button" id="cl-login">Log in</button>'; var l = $('cl-login'); if (l) l.addEventListener('click', login); return; }
    var name = String(who.name || who.email || 'Account').slice(0, 80), pic = typeof who.avatar_url === 'string' && /^https:\/\//.test(who.avatar_url) ? who.avatar_url : '';
    a.innerHTML = '<button class="cl-av" id="cl-av" type="button" aria-haspopup="true" aria-expanded="false" aria-controls="cl-menu" aria-label="Account: ' + esc(name) + '">' + esc(name.charAt(0).toUpperCase()) +
      (pic ? '<img src="' + esc(pic) + '" alt="" referrerpolicy="no-referrer">' : '') + '</button>' +
      '<div class="cl-menu" id="cl-menu" hidden><div class="cl-m-head"><b>' + esc(name) + '</b><span>' + esc(who.email || '') + '</span></div>' +
      '<a class="cl-m-item" href="/dashboard.html">Dashboard</a><button class="cl-m-item cl-danger" type="button" id="cl-logout">Log out</button></div>';
    var img = a.querySelector('img'); if (img) img.addEventListener('error', function () { img.remove(); });
    $('cl-av').addEventListener('click', function (e) { e.stopPropagation(); menu(); });
    $('cl-logout').addEventListener('click', function () {
      try { localStorage.removeItem('clab_token'); } catch (e) {}
      if (typeof window.authLogout === 'function') { try { window.authLogout(); } catch (e) {} }
      location.reload();
    });
  }
  function menu(open) {
    var m = $('cl-menu'), b = $('cl-av'); if (!m || !b) return;
    if (open === undefined) open = m.hidden;
    m.hidden = !open; b.setAttribute('aria-expanded', open ? 'true' : 'false');
  }
  document.addEventListener('click', function (e) { if (!e.target.closest || !e.target.closest('#cl-acct')) menu(false); });
  document.addEventListener('keydown', function (e) { var m = $('cl-menu'); if (e.key === 'Escape' && m && !m.hidden) { menu(false); $('cl-av').focus(); } });
  function account() {
    var t = get('clab_token'); t = t && JWT.test(t) ? t : null;
    if (t === tok && (who || !t)) { paint(); return; }
    tok = t; who = null; paint();
    if (!t) return;
    fetch('/api/me', { headers: { Authorization: 'Bearer ' + t } }).then(function (r) { return r.ok ? r.json() : null; }).then(function (u) {
      if (t !== tok) return;
      if (u && typeof u === 'object') who = u; else tok = null;
      paint();
    }).catch(function () { if (t === tok) { tok = null; paint(); } });
  }
  // pages store the login token at different moments (inline script, DOMContentLoaded, window load)
  window.addEventListener('load', account);
  window.addEventListener('storage', function (e) { if (e.key === 'clab_token' || e.key === null) account(); if (e.key === 'clab_theme' && (e.newValue === 'light' || e.newValue === 'dark')) applyTheme(e.newValue); });
  window.addEventListener('focus', account);
  window.clNavRefresh = account;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', render); else render();
})();
/* Google Analytics 4 (gtag.js), loaded once here for every page. */
(function () {
  var id = 'G-28G67DQ3DL';
  var s = document.createElement('script');
  s.async = true;
  s.src = 'https://www.googletagmanager.com/gtag/js?id=' + id;
  document.head.appendChild(s);
  window.dataLayer = window.dataLayer || [];
  window.gtag = function () { dataLayer.push(arguments); };
  gtag('js', new Date());
  gtag('config', id);
})();

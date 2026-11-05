/* ConfigLabs — single source of truth for version numbers.
   Change them here only; every page reads them from this file. */
window.CL = { version: '7.8.0', wifi: '5.30', topo: '2.1', rack: '1.3' };
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

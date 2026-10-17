/* ConfigLabs — single source of truth for version numbers.
   Change them here only; every page reads them from this file. */
window.CL = { version: '6.2.1', wifi: '5.30', topo: '1.0' };
(function () {
  function fill() {
    document.querySelectorAll('[data-cl-version]').forEach(function (e) { e.textContent = 'v' + CL.version; });
    document.querySelectorAll('[data-cl-wifi]').forEach(function (e) {
      var p = e.getAttribute('data-cl-wifi');
      e.textContent = (p || 'v') + CL.wifi;
    });
    document.querySelectorAll('[data-cl-topo]').forEach(function (e) { e.textContent = 'v' + CL.topo; });
    document.querySelectorAll('[data-cl-title]').forEach(function (e) { e.title = (e.getAttribute('data-cl-title') || '') + CL.version; });
    document.querySelectorAll('[data-cl-year]').forEach(function (e) { e.textContent = new Date().getFullYear(); });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fill); else fill();
})();

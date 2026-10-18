/* ConfigLabs Rack Builder: constants and equipment library (shared by the Rack pages).
   Model record: id, vendor, name, cat, u, d (depth mm), kg, w {typ,max}, air, psu, front[], rear[], ver, src, note.
   ver: 'datasheet' = values taken from the vendor's published hardware guide / data sheet,
        'partial'   = some values are estimates or come from a reseller page quoting the vendor,
        'typical'   = generic placeholder values, replace with your own. */
(function () {
  'use strict';
  const RK = window.RK = window.RK || {};
  RK.UMM = 44.45; RK.RACKW = 482.6; RK.SCHEMA = 1;
  RK.GROUPS = [['sw', 'Switches', ['switch']], ['rt', 'Routers & firewalls', ['router', 'firewall']], ['srv', 'Servers', ['server']], ['sto', 'Storage', ['storage']],
    ['pp', 'Passive', ['patch', 'manager', 'blank']], ['pw', 'Power', ['pdu', 'ups']], ['ot', 'KVM & other', ['kvm']]];
  RK.CATS = { switch: 'Switch', router: 'Router', firewall: 'Firewall', server: 'Server', storage: 'Storage', patch: 'Patch panel', manager: 'Cable manager', blank: 'Blanking panel', pdu: 'PDU', ups: 'UPS', kvm: 'KVM' };
  RK.PORTS = { rj45: 'RJ45', sfp: 'SFP', 'sfp+': 'SFP+', qsfp: 'QSFP', lc: 'LC', usb: 'USB', con: 'Console' };
  RK.AIR = { p2s: 'Port side to PSU side', s2p: 'PSU side to port side', f2b: 'Front to back', b2f: 'Back to front', side: 'Side to side', tray: 'Depends on fan tray', passive: 'Passive (no fan)', unk: 'Not stated' };
  RK.VER = { datasheet: 'Datasheet', partial: 'Partial', typical: 'Typical' };
  RK.PRESETS_U = [12, 18, 22, 24, 27, 32, 36, 42, 45, 47, 48, 52];
  RK.PDU_PRESETS = [['3680', '16 A, 230 V single phase (3.68 kW)'], ['7360', '32 A, 230 V single phase (7.36 kW)'], ['11040', '16 A, 400 V three phase (11.0 kW)'], ['22170', '32 A, 400 V three phase (22.2 kW)']];

  const P = (t, n, r) => ({ k: 'p', t, n, r: r || 1 });
  const BAY = (n, c) => ({ k: 'bay', n, c });
  const PSU = n => ({ k: 'psu', n });
  const FAN = n => ({ k: 'fan', n });
  const OUT = n => ({ k: 'out', n });
  const M = (id, vendor, name, cat, o) => Object.assign({ id, vendor, name, cat, u: 1, d: 450, kg: 5, w: { typ: null, max: 100 }, air: 'unk', psu: 1, ver: 'typical', src: '', note: '' }, o);
  const H3C = 'https://www.h3c.com/en/';
  const L = [
    /* ---- H3C switches (hardware guides) ---- */
    M('h3c-s5130s-28s-ei', 'H3C', 'S5130S-28S-EI', 'switch', { u: 1, d: 160, kg: 2.5, w: { typ: null, max: 24 }, air: 'unk', psu: 1, front: [P('rj45', 24, 2), P('sfp+', 4, 1)], ver: 'datasheet', src: H3C + 'd_202211/1719936_294551_0.htm', note: 'Fixed power supply. Weight is a maximum; airflow is not stated in the guide.' }),
    M('h3c-s5130s-52p-ei', 'H3C', 'S5130S-52P-EI', 'switch', { u: 1, d: 230, kg: 3.5, w: { typ: null, max: 41 }, air: 'side', psu: 1, front: [P('rj45', 48, 2), P('sfp', 4, 1)], ver: 'datasheet', src: H3C + 'd_202211/1719936_294551_0.htm', note: 'Air enters at the sides and leaves at the power supply side.' }),
    M('h3c-s5130s-52s-ei', 'H3C', 'S5130S-52S-EI', 'switch', { u: 1, d: 230, kg: 3.5, w: { typ: null, max: 44 }, air: 'side', psu: 1, front: [P('rj45', 48, 2), P('sfp+', 4, 1)], ver: 'datasheet', src: H3C + 'd_202211/1719936_294551_0.htm', note: 'Air enters at the sides and leaves at the power supply side.' }),
    M('h3c-s5130s-52p-pwr-ei', 'H3C', 'S5130S-52P-PWR-EI', 'switch', { u: 1, d: 400, kg: 6, w: { typ: null, max: 467 }, air: 'side', psu: 1, front: [P('rj45', 48, 2), P('sfp', 4, 1)], ver: 'datasheet', src: H3C + 'd_202211/1719936_294551_0.htm', note: 'Maximum power includes PoE. PoE budget 370 W (AC).' }),
    M('h3c-s5560x-30f-ei', 'H3C', 'S5560X-30F-EI', 'switch', { u: 1, d: 360, kg: 6.6, w: { typ: null, max: 122 }, air: 'tray', psu: 2, front: [P('sfp', 24, 2), P('sfp+', 4, 1)], ver: 'partial', src: H3C + 'd_202011/1353168_294551_0.htm', note: 'Depth, weight and power from the hardware guide. Airflow depends on the fan tray fitted. PSU count assumed 2 (modular).' }),
    M('h3c-s5560x-54c-ei', 'H3C', 'S5560X-54C-EI', 'switch', { u: 1, d: 360, kg: 7, w: { typ: null, max: 96 }, air: 'tray', psu: 2, front: [P('rj45', 48, 2), P('sfp+', 4, 1)], ver: 'partial', src: H3C + 'd_202011/1353168_294551_0.htm', note: 'Depth, weight and power from the hardware guide. Airflow depends on the fan tray fitted. PSU count assumed 2 (modular).' }),
    M('h3c-s5560x-54f-ei', 'H3C', 'S5560X-54F-EI', 'switch', { u: 1, d: 360, kg: 6.7, w: { typ: null, max: 140 }, air: 'tray', psu: 2, front: [P('sfp', 48, 2), P('sfp+', 4, 1)], ver: 'partial', src: H3C + 'd_202011/1353168_294551_0.htm', note: 'Depth, weight and power from the hardware guide. Airflow depends on the fan tray fitted. PSU count assumed 2 (modular).' }),
    M('h3c-s5560x-34s-ei', 'H3C', 'S5560X-34S-EI', 'switch', { u: 1, d: 260, kg: 3.6, w: { typ: null, max: 57 }, air: 'unk', psu: 1, front: [P('rj45', 28, 2), P('sfp+', 4, 1), P('qsfp', 2, 1)], ver: 'partial', src: H3C + 'd_202011/1353168_294551_0.htm', note: 'Depth, weight and power from the hardware guide. Fixed fans and power supply assumed.' }),
    M('h3c-s6860-30hf', 'H3C', 'S6860-30HF', 'switch', { u: 1, d: 400, kg: 10, w: { typ: 87, max: 134 }, air: 'tray', psu: 2, front: [P('sfp+', 24, 2), P('qsfp', 6, 1)], ver: 'datasheet', src: H3C + 'd_202206/1633360_294551_0.htm', note: 'Power shown for PSR250-12A, dual AC input. Fan tray LSPM1FANSA: PSU side to port side. LSPM1FANSB: port side to PSU side.' }),
    M('h3c-s6860-54hf', 'H3C', 'S6860-54HF', 'switch', { u: 1, d: 400, kg: 10, w: { typ: 96, max: 178 }, air: 'tray', psu: 2, front: [P('sfp+', 48, 2), P('qsfp', 6, 1)], ver: 'datasheet', src: H3C + 'd_202206/1633360_294551_0.htm', note: 'Power shown for PSR250-12A, dual AC input. Fan tray LSPM1FANSA: PSU side to port side. LSPM1FANSB: port side to PSU side.' }),
    M('h3c-s6860-54ht', 'H3C', 'S6860-54HT', 'switch', { u: 1, d: 460, kg: 10, w: { typ: 212, max: 258 }, air: 'p2s', psu: 2, front: [P('rj45', 48, 2), P('qsfp', 6, 1)], ver: 'datasheet', src: H3C + 'd_202206/1633360_294551_0.htm', note: 'Power shown for PSR450-12A, dual AC input. Ships with fan tray LSPM1FANSB (port side to PSU side).' }),
    /* ---- H3C server ---- */
    M('h3c-r4900-g5', 'H3C', 'UniServer R4900 G5', 'server', { u: 2, d: 748, kg: 42.1, w: { typ: 350, max: 800 }, air: 'f2b', psu: 2, front: [BAY(8, 4)], rear: [P('rj45', 2, 1), PSU(2)], ver: 'partial', src: H3C + 'd_202107/1425601_294551_0.htm', note: 'Depth 748 mm (776 mm with security bezel) and 42.1 kg maximum weight come from the user guide. Power depends on the configuration and is an estimate here: enter your own figure.' }),
    /* ---- Cisco ---- */
    M('cisco-c9200l-48p-4x', 'Cisco', 'Catalyst C9200L-48P-4X', 'switch', { u: 1, d: 287, kg: 4.8, w: { typ: null, max: 1000 }, air: 'unk', psu: 2, front: [P('rj45', 48, 2), P('sfp+', 4, 1)], ver: 'partial', src: 'https://cdn.cablesandkits.com/static/assets/C9200L-48P-4X-E-Datasheet-1.pdf', note: 'Dimensions and weight from the data sheet. Power shown is the 1000 W default supply rating (PoE budget 740 W); real draw is lower.' }),
    M('cisco-c9300-48p', 'Cisco', 'Catalyst C9300-48P', 'switch', { u: 1, d: 409, kg: 7.59, w: { typ: null, max: 715 }, air: 'unk', psu: 2, front: [P('rj45', 48, 2), P('sfp+', 4, 1)], ver: 'partial', src: 'https://cdn.cablesandkits.com/static/assets/C9300-48P-A-Datasheet.pdf', note: 'Dimensions and weight from the data sheet (model C9300-48P-A). Power shown is the 715 W default supply rating (PoE budget 437 W); real draw is lower. Uplinks are modular.' }),
    M('cisco-n9k-c93180yc-fx', 'Cisco', 'Nexus N9K-C93180YC-FX', 'switch', { u: 1, d: 571, kg: 7.9, w: { typ: 260, max: 425 }, air: 'tray', psu: 2, front: [P('sfp+', 48, 2), P('qsfp', 6, 1)], ver: 'partial', src: 'https://www.layer23-switch.com/n9k-c93180yc-fx.html', note: 'Values quoted from a reseller page citing Cisco. Weight excludes power supplies and fans. Airflow is port-side intake or port-side exhaust, set by the fan and PSU modules.' }),
    M('cisco-fpr-2110', 'Cisco', 'Firepower 2110', 'firewall', { u: 1, d: 502, kg: 7.3, w: { typ: null, max: 250 }, air: 'unk', psu: 1, front: [P('rj45', 12, 2), P('sfp', 4, 1)], ver: 'partial', src: 'https://www.connection.com/media/x3kjimmt/cisco-firepower-2100-data-sheet.pdf?la=en', note: 'Dimensions and weight from the data sheet. Power shown is the integrated 250 W supply rating.' }),
    /* ---- generic equipment (typical values, replace with yours) ---- */
    M('gen-sw-48g', '', 'Generic 48-port 1G access switch', 'switch', { u: 1, d: 300, kg: 4, w: { typ: 40, max: 80 }, psu: 1, front: [P('rj45', 48, 2), P('sfp+', 4, 1)] }),
    M('gen-sw-48x10', '', 'Generic 48-port 10G ToR switch', 'switch', { u: 1, d: 450, kg: 9, w: { typ: 150, max: 250 }, psu: 2, front: [P('sfp+', 48, 2), P('qsfp', 6, 1)] }),
    M('gen-sw-core2u', '', 'Generic 2U core switch', 'switch', { u: 2, d: 600, kg: 20, w: { typ: 400, max: 800 }, psu: 2, front: [P('sfp+', 32, 2), P('qsfp', 8, 2)] }),
    M('gen-fw-1u', '', 'Generic 1U firewall', 'firewall', { u: 1, d: 450, kg: 8, w: { typ: 80, max: 150 }, psu: 1, front: [P('rj45', 8, 2), P('sfp+', 4, 1)] }),
    M('gen-rt-1u', '', 'Generic 1U router', 'router', { u: 1, d: 400, kg: 5, w: { typ: 40, max: 90 }, psu: 1, front: [P('rj45', 4, 1), P('sfp', 2, 1)] }),
    M('gen-srv-1u', '', 'Generic 1U server', 'server', { u: 1, d: 700, kg: 15, w: { typ: 250, max: 400 }, air: 'f2b', psu: 2, front: [BAY(4, 4)], rear: [P('rj45', 2, 1), PSU(2)] }),
    M('gen-srv-2u', '', 'Generic 2U server', 'server', { u: 2, d: 750, kg: 28, w: { typ: 350, max: 600 }, air: 'f2b', psu: 2, front: [BAY(8, 4)], rear: [P('rj45', 4, 2), PSU(2)] }),
    M('gen-srv-4u', '', 'Generic 4U server', 'server', { u: 4, d: 800, kg: 45, w: { typ: 600, max: 1000 }, air: 'f2b', psu: 2, front: [BAY(24, 8)], rear: [P('rj45', 4, 2), PSU(2)] }),
    M('gen-sto-2u', '', 'Generic 2U storage array (12 bay)', 'storage', { u: 2, d: 600, kg: 30, w: { typ: 450, max: 700 }, air: 'f2b', psu: 2, front: [BAY(12, 4)], rear: [P('rj45', 2, 1), PSU(2)] }),
    M('gen-sto-4u', '', 'Generic 4U storage array (24 bay)', 'storage', { u: 4, d: 700, kg: 55, w: { typ: 700, max: 1200 }, air: 'f2b', psu: 2, front: [BAY(24, 8)], rear: [P('rj45', 2, 1), PSU(2)] }),
    M('gen-pp-24', '', 'Patch panel 24-port Cat6', 'patch', { u: 1, d: 60, kg: 0.7, w: { typ: 0, max: 0 }, psu: 0, front: [P('rj45', 24, 1)] }),
    M('gen-pp-48', '', 'Patch panel 48-port Cat6', 'patch', { u: 2, d: 60, kg: 1.4, w: { typ: 0, max: 0 }, psu: 0, front: [P('rj45', 48, 2)] }),
    M('gen-pp-fo24', '', 'Fiber patch panel 24 LC', 'patch', { u: 1, d: 250, kg: 1.5, w: { typ: 0, max: 0 }, psu: 0, front: [P('lc', 24, 1)] }),
    M('gen-cm-1u', '', 'Cable manager 1U', 'manager', { u: 1, d: 80, kg: 0.6, w: { typ: 0, max: 0 }, psu: 0 }),
    M('gen-cm-2u', '', 'Cable manager 2U', 'manager', { u: 2, d: 80, kg: 1, w: { typ: 0, max: 0 }, psu: 0 }),
    M('blank-1u', '', 'Blanking panel 1U', 'blank', { u: 1, d: 5, kg: 0.15, w: { typ: 0, max: 0 }, psu: 0 }),
    M('blank-2u', '', 'Blanking panel 2U', 'blank', { u: 2, d: 5, kg: 0.3, w: { typ: 0, max: 0 }, psu: 0 }),
    M('blank-4u', '', 'Blanking panel 4U', 'blank', { u: 4, d: 5, kg: 0.6, w: { typ: 0, max: 0 }, psu: 0 }),
    M('gen-pdu-1u', '', 'Rack PDU 1U (8 outlets)', 'pdu', { u: 1, d: 60, kg: 2.2, w: { typ: 0, max: 0 }, psu: 0, front: [OUT(8)], note: 'Draws 1U in the rack. Feed capacity is set under Rack, not by this device.' }),
    M('gen-ups-2u', '', 'UPS 2U rack (3 kVA)', 'ups', { u: 2, d: 600, kg: 30, w: { typ: 0, max: 0 }, psu: 0, note: 'Conversion losses are not counted. Weight is typical for a 3 kVA unit with batteries.' }),
    M('gen-kvm-1u', '', 'KVM console 1U', 'kvm', { u: 1, d: 500, kg: 12, w: { typ: 40, max: 60 }, psu: 1 })
  ];
  L.forEach(m => { if (m.ver === 'datasheet' || m.ver === 'partial') m.verified = '2026-10'; });
  RK.BUILTIN = L;

  /* ---- custom models (this browser, synced with the account later) ---- */
  const ls = { get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }, set(k, v) { try { localStorage.setItem(k, v); return true; } catch (e) { return false; } } };
  const num = (v, d, lo, hi) => { v = parseFloat(v); if (!isFinite(v)) v = d; return Math.min(hi, Math.max(lo, v)); };
  const str = (v, n) => String(v == null ? '' : v).replace(/[\u0000-\u001f]/g, ' ').slice(0, n);
  const idOk = v => /^[\w.\-]{1,60}$/.test(String(v || '')) ? String(v) : '';
  const KINDS = ['p', 'bay', 'psu', 'fan', 'out'];
  function cleanArt(a) {
    const out = []; (Array.isArray(a) ? a : []).slice(0, 8).forEach(b => {
      if (!b || KINDS.indexOf(b.k) < 0) return;
      if (b.k === 'p') out.push({ k: 'p', t: RK.PORTS[b.t] ? b.t : 'rj45', n: num(b.n, 1, 1, 96) | 0, r: num(b.r, 1, 1, 4) | 0 });
      else if (b.k === 'bay') out.push({ k: 'bay', n: num(b.n, 4, 1, 48) | 0, c: num(b.c, 4, 1, 12) | 0 });
      else out.push({ k: b.k, n: num(b.n, 1, 1, 24) | 0 });
    }); return out;
  }
  RK.cleanModel = function (m) {
    if (!m || typeof m !== 'object') return null; const id = idOk(m.id); if (!id) return null;
    const o = { id, vendor: str(m.vendor, 40), name: str(m.name, 60) || 'Custom device', cat: RK.CATS[m.cat] ? m.cat : 'server', u: num(m.u, 1, 1, 52) | 0, d: num(m.d, 450, 5, 1500), kg: num(m.kg, 5, 0, 500),
      w: { typ: m.w && m.w.typ != null && m.w.typ !== '' ? num(m.w.typ, 0, 0, 30000) : null, max: num(m.w && m.w.max, 100, 0, 30000) }, air: RK.AIR[m.air] ? m.air : 'unk', psu: num(m.psu, 1, 0, 6) | 0,
      ver: RK.VER[m.ver] ? m.ver : 'typical', src: /^https?:\/\/[^\s"'<>]{1,300}$/.test(String(m.src || '')) ? String(m.src) : '', note: str(m.note, 300) };
    if (m.verified) o.verified = str(m.verified, 12);
    const f = cleanArt(m.front), r = cleanArt(m.rear); if (f.length) o.front = f; if (r.length) o.rear = r; return o;
  };
  RK.custom = function () { let a = []; try { a = JSON.parse(ls.get('cl_rk_lib') || '[]'); } catch (e) {} return (Array.isArray(a) ? a : []).map(RK.cleanModel).filter(Boolean).map(m => (m.custom = true, m)); };
  RK.saveCustom = function (list) { return ls.set('cl_rk_lib', JSON.stringify(list.map(m => { const c = Object.assign({}, m); delete c.custom; return c; }))); };
  RK.all = function () { return RK.BUILTIN.concat(RK.custom()); };
  RK.find = function (id, project) { if (project && project.models && project.models[id]) return project.models[id]; return RK.all().find(m => m.id === id) || null; };
  RK.groupOf = cat => { const g = RK.GROUPS.find(x => x[2].indexOf(cat) >= 0); return g ? g[0] : 'ot'; };
})();

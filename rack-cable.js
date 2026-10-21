/* ConfigLabs Rack Builder: cabling (v7.3), power cabling and integrations (v7.4).
   Needs rack-lib.js, rack-calc.js, rack-render.js and rack-art.js first. No DOM except the two hand-off helpers at the bottom. */
(function () {
  'use strict';
  const RK = window.RK, RC = window.RC, RR = window.RR, RCB = window.RCB = {};
  const esc = s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  const UMM = RK.UMM, n1 = v => Math.round(v * 10) / 10;
  const lumHex = h => { const c = String(h).replace('#', ''); if (c.length !== 6) return 1; const v = [0, 2, 4].map(i => parseInt(c.substr(i, 2), 16) / 255); return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]; };
  const FIB = { sfp: 1, 'sfp+': 1, qsfp: 1, lc: 1 };

  /* ---------- ports ---------- */
  const cache = new Map();
  function ports(m, faceKey) {
    const k = m.id + '|' + faceKey + '|' + JSON.stringify([m.front, m.rear, m.cat, m.psu, m.u, m.air]);
    let v = cache.get(k); if (v) return v;
    v = {}; (RR.portMap(m, faceKey) || []).forEach(p => { v[p.id] = p; });
    if (cache.size > 300) cache.clear(); cache.set(k, v); return v;
  }
  /* info about one end: { d, m, port (or null), face } */
  RCB.end = function (P, e) {
    const d = RC.dev(P, e.d); if (!d) return null;
    const m = RC.model(P, d.modelId), face = e.p[0] === 'f' ? 'front' : 'rear';
    return { d, m, port: ports(m, face)[e.p] || null, face, p: e.p };
  };
  RCB.portName = function (m, face, p) {
    const f = face === 'front' ? 'Front' : 'Rear';
    if (!p) return f + ' (port missing)';
    if (p.label) return f + ' ' + p.label;
    const t = { rj45: 'RJ45', sfp: 'SFP', 'sfp+': 'SFP+', qsfp: 'QSFP', lc: 'LC', out: 'Outlet', psu: 'PSU', con: 'Console', usb: 'USB' }[p.t] || p.t;
    return f + ' ' + (p.n ? '#' + p.n : t) + (p.n ? ' (' + t + ')' : '');
  };
  /* suggested interface name for network gear (best effort; the hardware guide of the exact model is the authority) */
  RCB.ifName = function (m, face, p) {
    if (!p || !(m.cat === 'switch' || m.cat === 'router' || m.cat === 'firewall')) return '';
    const h3 = m.vendor === 'H3C', nexus = /nexus|n9k/i.test(m.name);
    if (face === 'rear') return p.id === 'rmgmt' ? (h3 ? 'M-GigabitEthernet0/0/0' : 'mgmt0') : '';
    if (!p.n) return '';
    if (h3) return ({ rj45: 'GigabitEthernet1/0/', sfp: 'GigabitEthernet1/0/', 'sfp+': 'Ten-GigabitEthernet1/0/', qsfp: 'FortyGigE1/0/' }[p.t] || 'GigabitEthernet1/0/') + p.n;
    if (nexus) return 'Ethernet1/' + p.n;
    const nRj = (m.front || []).filter(b => b.k === 'p' && b.t === 'rj45').reduce((t, b) => t + b.n, 0);
    if (p.t === 'rj45') return 'GigabitEthernet1/0/' + p.n;
    return (p.t === 'qsfp' ? 'FortyGigabitEthernet1/1/' : 'TenGigabitEthernet1/1/') + Math.max(1, p.n - nRj);
  };
  RCB.endText = function (P, e) {
    const x = RCB.end(P, e); if (!x) return '?';
    return (x.d.hostname || x.m.name) + ' ' + RCB.portName(x.m, x.face, x.port);
  };

  /* ---------- rules ---------- */
  /* Returns a list of problems for one cable: [{ rule, sev, msg }] */
  RCB.check = function (P, c) {
    const out = [], A = RCB.end(P, c.a), B = RCB.end(P, c.b); if (!A || !B) return out;
    const T = RC.CABLES[c.type] || RC.CABLES.cat6, ta = A.port && A.port.t, tb = B.port && B.port.t, fam = T.fam;
    if (!A.port || !B.port) { out.push({ rule: 'cablebad', sev: 'warn', msg: 'a port on this cable does not exist on the device model any more.' }); return out; }
    const both = f => f(ta) && f(tb);
    if (fam === 'cu') { if (!both(t => t === 'rj45')) out.push({ rule: 'cabletype', sev: 'warn', msg: T.n + ' needs an RJ45 port at both ends (found ' + ta + ' and ' + tb + ').' }); }
    else if (fam === 'dac') { if (!both(t => t === 'sfp+' || t === 'qsfp' || t === 'sfp')) out.push({ rule: 'cabletype', sev: 'warn', msg: T.n + ' needs SFP or QSFP cages at both ends (found ' + ta + ' and ' + tb + ').' }); else if (ta !== tb) out.push({ rule: 'cabletype', sev: 'warn', msg: T.n + ' joins an ' + ta.toUpperCase() + ' and a ' + tb.toUpperCase() + ' port: both ends of a DAC/AOC must be the same type (or use a breakout cable).' }); }
    else if (fam === 'fb') {
      if (!both(t => FIB[t])) out.push({ rule: 'cabletype', sev: 'warn', msg: T.n + ' needs an optical port (SFP, SFP+, QSFP or LC) at both ends (found ' + ta + ' and ' + tb + ').' });
      else if ((ta === 'qsfp') !== (tb === 'qsfp') && ta !== 'lc' && tb !== 'lc') out.push({ rule: 'cabletype', sev: 'info', msg: 'a QSFP port is joined to a ' + (ta === 'qsfp' ? tb : ta).toUpperCase() + ' port: this needs a breakout cable or matching speed.' });
      else if ((ta === 'sfp') !== (tb === 'sfp') && ta !== 'lc' && tb !== 'lc' && ta !== 'qsfp' && tb !== 'qsfp') out.push({ rule: 'cabletype', sev: 'info', msg: 'an SFP (1G) port is joined to an SFP+ (10G) port: the link will run at 1G only with matching optics.' });
    } else if (fam === 'con') { if (!(ta === 'con' || tb === 'con')) out.push({ rule: 'cabletype', sev: 'warn', msg: 'a console cable needs a console port at one end.' }); }
    else if (fam === 'pwr') { if (!(both(t => t === 'psu' || t === 'out') && ta !== tb)) out.push({ rule: 'cabletype', sev: 'warn', msg: 'a power cord joins a device PSU inlet to a PDU or UPS outlet.' }); }
    else if (fam === 'usb') { if (!both(t => t === 'usb' || t === 'usbc' || t === 'con')) out.push({ rule: 'cabletype', sev: 'warn', msg: 'a USB cable needs USB ports at both ends.' }); }
    /* power cords must not land on data ports, and data cables must not land on power ports */
    if (fam !== 'pwr' && (ta === 'psu' || tb === 'psu' || ta === 'out' || tb === 'out')) out.push({ rule: 'cabletype', sev: 'warn', msg: 'a ' + T.n + ' is plugged into a power port.' });
    let lim = T.max; if (c.type === 'om3' && (ta === 'qsfp' || tb === 'qsfp')) lim = 100; if (c.type === 'om4' && (ta === 'qsfp' || tb === 'qsfp')) lim = 150;
    if (c.len != null && c.len > lim) out.push({ rule: 'cablelen', sev: 'warn', msg: 'is ' + c.len + ' m long, over the ' + lim + ' m limit for ' + T.n + '.' });
    return out;
  };

  RC.RULES.cablebad = 'Cable port'; RC.RULES.cableport = 'Port in use'; RC.RULES.cabletype = 'Cable type'; RC.RULES.cablelen = 'Cable length'; RC.RULES.cablepwr = 'Power cabling'; RC.RULES.pduload = 'PDU load';
  RC.hooks.push(function (P, add) {
    if (!P.cables || !P.cables.length) return;
    const used = {};
    P.cables.forEach(c => { [c.a, c.b].forEach(e => { const k = e.d + '|' + e.p; (used[k] = used[k] || []).push(c); }); });
    Object.keys(used).forEach(k => { const a = used[k]; if (a.length > 1) { const e = a[0].a.d + '|' + a[0].a.p === k ? a[0].a : a[0].b, x = RCB.end(P, e); if (x) a.forEach(c => add('cableport', 'crit', x.d.rackId, x.d.id, (x.d.hostname || x.m.name) + ' ' + RCB.portName(x.m, x.face, x.port) + ' has ' + a.length + ' cables plugged in.', c.id)); } });
    P.cables.forEach(c => {
      const A = RCB.end(P, c.a); if (!A) return;
      RCB.check(P, c).forEach(r => add(r.rule, r.sev, A.d.rackId, A.d.id, (c.label ? c.label + ': ' : RCB.endText(P, c.a) + ' to ' + RCB.endText(P, c.b) + ' ') + r.msg, c.id));
    });
    /* load on each PDU, from the power cords plugged into it (a device's draw is shared by its cords) */
    P.devices.forEach(o => {
      const om = RC.model(P, o.modelId); if (om.cat !== 'pdu' && om.cat !== 'ups') return;
      const cords = P.cables.filter(c => c.type === 'power' && (c.a.d === o.id || c.b.d === o.id)); if (!cords.length) return;
      let w = 0; cords.forEach(c => { const e = c.a.d === o.id ? c.b : c.a, dv = RC.dev(P, e.d); if (!dv) return; const n = P.cables.filter(x => x.type === 'power' && (x.a.d === dv.id || x.b.d === dv.id)).length; w += RC.watts(P, dv) / Math.max(1, n); });
      const rack = RC.rack(P, o.rackId), cap = o.pduCap || (o.pduFeed && rack.pdus[o.pduFeed] ? rack.pdus[o.pduFeed].cap : 0), lab = o.hostname || om.name; if (!cap) return;
      const pct = w / cap * 100; if (pct >= P.settings.crit) add('pduload', 'crit', o.rackId, o.id, lab + ' is at ' + Math.round(pct) + '% (' + Math.round(w) + ' of ' + cap + ' W) from the power cords plugged into it.');
      else if (pct >= P.settings.warn) add('pduload', 'warn', o.rackId, o.id, lab + ' is at ' + Math.round(pct) + '% (' + Math.round(w) + ' of ' + cap + ' W), above the ' + P.settings.warn + '% planning limit.');
    });
    /* power cabling: feeds come from the PDU a PSU is plugged into */
    P.devices.forEach(d => {
      const m = RC.model(P, d.modelId); if (!(m.psu > 0)) return;
      const pc = P.cables.filter(c => c.type === 'power' && (c.a.d === d.id || c.b.d === d.id));
      if (pc.length && pc.length < Math.min(2, m.psu) && RC.watts(P, d) > 0) add('cablepwr', 'info', d.rackId, d.id, (d.hostname || m.name) + ' has ' + m.psu + ' power supplies but only ' + pc.length + ' power cord' + (pc.length > 1 ? 's' : '') + ' drawn.');
    });
  });

  /* ---------- length estimate (metres), rounded up to a standard cable length ---------- */
  const STD = [0.3, 0.5, 1, 1.5, 2, 3, 5, 7, 10, 15, 20, 25, 30, 40, 50, 75, 100];
  RCB.estimate = function (P, c) {
    const A = RC.dev(P, c.a.d), B = RC.dev(P, c.b.d); if (!A || !B) return null;
    const ra = RC.rack(P, A.rackId), rb = RC.rack(P, B.rackId), ha = RC.h(P, A), hb = RC.h(P, B);
    const ua = A.u + ha / 2, ub = B.u + hb / 2; let m;
    if (ra.id === rb.id) { m = Math.abs(ua - ub) * UMM / 1000 + 0.5 + (c.a.p[0] !== c.b.p[0] ? ra.d / 1000 : 0); }
    else {
      const topA = (ra.u - ua) * UMM / 1000, topB = (rb.u - ub) * UMM / 1000;
      const A1 = RC.rackRect(ra), B1 = RC.rackRect(rb);
      const run = A1 && B1 ? (Math.abs((A1.x + A1.w / 2) - (B1.x + B1.w / 2)) + Math.abs((A1.y + A1.h / 2) - (B1.y + B1.h / 2))) / 1000 : 6;
      m = topA + topB + run + 1.5;
    }
    if (c.type === 'power') m = Math.min(m, 3);
    for (let i = 0; i < STD.length; i++) if (STD[i] >= m) return STD[i];
    return Math.ceil(m / 10) * 10;
  };

  /* ---------- geometry: where is a port on screen ---------- */
  function fkOf(d, face) { return (face === 'front') !== !!d.rev ? 'front' : 'rear'; }
  /* port rectangle in rack drawing coordinates, or null when that face is not the one shown */
  RCB.portRect = function (P, rack, geo, face, e) {
    const d = RC.dev(P, e.d); if (!d || d.rackId !== rack.id) return null;
    const m = RC.model(P, d.modelId), pf = e.p[0] === 'f' ? 'front' : 'rear'; if (fkOf(d, face) !== pf) return null;
    const p = ports(m, pf)[e.p]; if (!p) return null; const h = m.u, y = RR.slotTop(rack, d.u, h, geo.topY);
    return { x: geo.x0 + p.x, y: y + p.y, w: p.w, h: p.h, cx: geo.x0 + p.x + p.w / 2, cy: y + p.y + p.h / 2, p, d, m };
  };
  /* which port is under a point (rack drawing coordinates)? */
  RCB.hit = function (P, rack, geo, face, x, y) {
    let best = null;
    P.devices.filter(d => d.rackId === rack.id).forEach(d => {
      const m = RC.model(P, d.modelId), h = m.u, top = RR.slotTop(rack, d.u, h, geo.topY); if (y < top || y > top + h * UMM) return;
      const pf = fkOf(d, face), pm = ports(m, pf);
      Object.keys(pm).forEach(id => { const p = pm[id], px = geo.x0 + p.x, py = top + p.y, t = 1.2; if (x >= px - t && x <= px + p.w + t && y >= py - t && y <= py + p.h + t) { const dd = Math.abs(x - (px + p.w / 2)) + Math.abs(y - (py + p.h / 2)); if (!best || dd < best.dd) best = { dd, d, m, p, face: pf, e: { d: d.id, p: p.id } }; } });
    });
    return best;
  };

  /* ---------- overlay: cables drawn over the rack ---------- */
  RCB.overlay = function (P, rack, geo, face, o) {
    o = o || {}; if (o.show === false && !o.pending) return '';
    const pal = RR.pal(o.pal), cs = o.show === false ? [] : (P.cables || []);
    const segs = []; let stubs = '';
    cs.forEach(c => {
      const a = RCB.portRect(P, rack, geo, face, c.a), b = RCB.portRect(P, rack, geo, face, c.b);
      if (a && b) segs.push({ c, a, b, y0: Math.min(a.cy, b.cy), y1: Math.max(a.cy, b.cy) });
      else if (a || b) { const r = a || b; stubs += stub(P, c, r, !!(a ? c.b : c.a) && (a ? c.b : c.a), o); }
    });
    /* greedy lane assignment so parallel cables do not sit on top of each other */
    segs.sort((p, q) => p.y0 - q.y0); const lanes = [];
    segs.forEach(sg => { let l = 0; while (lanes[l] != null && lanes[l] > sg.y0 - 2) l++; lanes[l] = sg.y1; sg.lane = l % 8; });
    let s = '<g id="cabl" font-family="JetBrains Mono,Consolas,monospace">';
    segs.forEach(sg => {
      const lx = 4 + sg.lane * 4.2, sel = o.sel === sg.c.id, ax = sg.a.x, bx = sg.b.x;
      const side = (r) => { const left = r.cx < geo.x0 + RK.RACKW / 2; return left ? [r.x - 0.5, lx + geo.x0 * 0 + 0] : [r.x + r.w + 0.5, geo.x0 + RK.RACKW + 4 + sg.lane * 4.2]; };
      /* run to the nearest rail: left rail for ports in the left half, right rail for the others */
      const la = sg.a.cx < geo.x0 + RK.RACKW / 2, lb = sg.b.cx < geo.x0 + RK.RACKW / 2;
      const xa = la ? lx : geo.x0 + RK.RACKW + 4 + sg.lane * 4.2, xb = lb ? lx : geo.x0 + RK.RACKW + 4 + sg.lane * 4.2;
      let d;
      if (la === lb) d = 'M' + n1(sg.a.cx) + ' ' + n1(sg.a.cy) + 'L' + n1(xa) + ' ' + n1(sg.a.cy) + 'L' + n1(xb) + ' ' + n1(sg.b.cy) + 'L' + n1(sg.b.cx) + ' ' + n1(sg.b.cy);
      else { const my = (sg.a.cy + sg.b.cy) / 2 + ((sg.lane % 4) - 1.5) * 1.6; d = 'M' + n1(sg.a.cx) + ' ' + n1(sg.a.cy) + 'L' + n1(xa) + ' ' + n1(sg.a.cy) + 'L' + n1(xa) + ' ' + n1(my) + 'L' + n1(xb) + ' ' + n1(my) + 'L' + n1(xb) + ' ' + n1(sg.b.cy) + 'L' + n1(sg.b.cx) + ' ' + n1(sg.b.cy); }
      const col = sg.c.color, tip = esc((sg.c.label ? sg.c.label + ': ' : '') + RCB.endText(P, sg.c.a) + '  ↔  ' + RCB.endText(P, sg.c.b) + '  (' + (RC.CABLES[sg.c.type] || {}).n + (sg.c.len != null ? ', ' + sg.c.len + ' m' : '') + ')');
      s += `<g data-cable="${esc(sg.c.id)}" style="cursor:pointer"><title>${tip}</title>`;
      if (sel) s += `<path d="${d}" fill="none" stroke="${pal.acc}" stroke-width="7" stroke-linejoin="round" stroke-linecap="round" opacity=".55"/>`;
      const dk = lumHex(col) < 0.12; s += `<path d="${d}" fill="none" stroke="${dk ? '#aab4c4' : '#000'}" stroke-width="${dk ? 4.6 : 4.2}" stroke-linejoin="round" stroke-linecap="round" opacity="${dk ? '.7' : '.45'}"/><path d="${d}" fill="none" stroke="${col}" stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round"${sg.c.status === 'planned' ? ' stroke-dasharray="0"' : ''}/>`;
      s += `<path d="${d}" fill="none" stroke="transparent" stroke-width="9" stroke-linejoin="round" pointer-events="stroke"/>`;
      s += `<circle cx="${n1(sg.a.cx)}" cy="${n1(sg.a.cy)}" r="2.3" fill="${col}" stroke="#000" stroke-width=".6"/><circle cx="${n1(sg.b.cx)}" cy="${n1(sg.b.cy)}" r="2.3" fill="${col}" stroke="#000" stroke-width=".6"/>`;
      if (sg.c.label && o.labels !== false) { const ty = (sg.a.cy + sg.b.cy) / 2; s += `<text x="${n1(la ? lx + 3 : xa - 3)}" y="${n1(ty)}" font-size="5" fill="${pal.ink}" text-anchor="${la ? 'start' : 'end'}" stroke="${pal.bg}" stroke-width="1.6" paint-order="stroke">${esc(sg.c.label)}</text>`; }
      s += '</g>';
    });
    s += stubs;
    if (o.pending) { const r = RCB.portRect(P, rack, geo, face, o.pending); if (r) s += `<rect x="${n1(r.x - 1.5)}" y="${n1(r.y - 1.5)}" width="${n1(r.w + 3)}" height="${n1(r.h + 3)}" rx="2" fill="none" stroke="${pal.acc}" stroke-width="1.6"><animate attributeName="opacity" values="1;.35;1" dur="1.1s" repeatCount="indefinite"/></rect>`; }
    if (o.hover) { const r = RCB.portRect(P, rack, geo, face, o.hover); if (r) s += `<rect x="${n1(r.x - 1)}" y="${n1(r.y - 1)}" width="${n1(r.w + 2)}" height="${n1(r.h + 2)}" rx="1.5" fill="${pal.acc}" fill-opacity=".25" stroke="${pal.acc}" stroke-width="1" pointer-events="none"/>`; }
    return s + '</g>';
  };
  /* a cable whose other end is in another rack or on the other face: short stub to the rail with a tag */
  function stub(P, c, r, other, o) {
    const pal = RR.pal(o.pal), rect = r, left = r.cx < (rect.x + rect.w / 2) + 9999; const toLeft = r.x < 300; const x2 = toLeft ? 5 : 482.6 + 36 + 31;
    const sel = o.sel === c.id, col = c.color, oe = c.a.d === r.d.id && c.a.p === r.p.id ? c.b : c.a;
    const d = 'M' + n1(r.cx) + ' ' + n1(r.cy) + 'L' + n1(x2) + ' ' + n1(r.cy);
    const tip = esc((c.label ? c.label + ': ' : '') + RCB.endText(P, c.a) + '  ↔  ' + RCB.endText(P, c.b));
    const od = RC.dev(P, oe.d), tag = od ? (od.hostname || RC.model(P, od.modelId).name) : '?';
    return `<g data-cable="${esc(c.id)}" style="cursor:pointer"><title>${tip}</title>` + (sel ? `<path d="${d}" stroke="${pal.acc}" stroke-width="7" opacity=".55" fill="none"/>` : '') + `<path d="${d}" stroke="${lumHex(col) < 0.12 ? '#aab4c4' : '#000'}" stroke-width="4.2" opacity=".6" fill="none"/><path d="${d}" stroke="${col}" stroke-width="2.6" stroke-dasharray="5 2.5" fill="none"/><path d="${d}" stroke="transparent" stroke-width="9" fill="none" pointer-events="stroke"/><circle cx="${n1(r.cx)}" cy="${n1(r.cy)}" r="2.3" fill="${col}" stroke="#000" stroke-width=".6"/><text x="${toLeft ? 2 : 482.6 + 36 + 34}" y="${n1(r.cy - 2.2)}" font-size="4.6" fill="${pal.ink}" text-anchor="${toLeft ? 'start' : 'end'}" stroke="${pal.bg}" stroke-width="1.4" paint-order="stroke">${esc(('→ ' + tag).slice(0, 12))}</text></g>`;
  }

  /* ---------- schedule ---------- */
  const cell = v => { v = String(v == null ? '' : v); if (/^[=+\-@\t\r]/.test(v)) v = "'" + v; return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
  const cname = h => { const f = RC.CCOL.find(x => x[0] === String(h).toLowerCase()); return f ? f[1] : String(h || ''); };
  RCB.rows = function (P) {
    const ord = P.racks.reduce((m, r, i) => (m[r.id] = i, m), {});
    const rows = (P.cables || []).map(c => {
      const A = RCB.end(P, c.a), B = RCB.end(P, c.b); if (!A || !B) return null; const ra = RC.rack(P, A.d.rackId), rb = RC.rack(P, B.d.rackId);
      return { c, A, B, ra, rb };
    }).filter(Boolean);
    rows.sort((x, y) => (ord[x.ra.id] - ord[y.ra.id]) || (y.A.d.u - x.A.d.u) || String(x.A.p.id).localeCompare(String(y.A.p.id), undefined, { numeric: true }));
    return rows.map((r, i) => Object.assign(r, { no: 'C' + String(i + 1).padStart(3, '0') }));
  };
  const endCols = (P, x) => [x.ra.label, x.d.u, x.d.hostname || x.m.name, RCB.portName(x.m, x.face, x.port), RCB.ifName(x.m, x.face, x.port)];
  RCB.csv = function (P) {
    const L = [['Cable', 'Label', 'Type', 'Colour', 'Length m', 'Status', 'From rack', 'From U', 'From device', 'From port', 'From interface', 'To rack', 'To U', 'To device', 'To port', 'To interface', 'Notes']];
    RCB.rows(P).forEach(r => { const a = endCols(P, { ra: r.ra, d: r.A.d, m: r.A.m, face: r.A.face, port: r.A.port }), b = endCols(P, { ra: r.rb, d: r.B.d, m: r.B.m, face: r.B.face, port: r.B.port }); L.push([r.no, r.c.label, RC.CABLES[r.c.type].n, cname(r.c.color), r.c.len == null ? '' : r.c.len, r.c.status].concat(a, b, [r.c.note])); });
    return L.map(r => r.map(cell).join(',')).join('\r\n');
  };
  /* purchase list: type and length with a count */
  RCB.bom = function (P) {
    const m = {}; (P.cables || []).forEach(c => { const k = c.type + '|' + (c.len == null ? '?' : c.len); m[k] = m[k] || { type: c.type, len: c.len, qty: 0 }; m[k].qty++; });
    return Object.keys(m).map(k => m[k]).sort((a, b) => a.type.localeCompare(b.type) || (a.len || 0) - (b.len || 0));
  };
  /* the schedule as an SVG table page (so it exports to PNG and PDF like everything else) */
  RCB.scheduleSVG = function (P, o) {
    o = o || {}; const pal = RR.pal(o.pal), rows = RCB.rows(P), W = 1500, RH = 22, H0 = 100;
    const cols = [['No', 0, 60], ['Label', 60, 150], ['Type', 210, 170], ['Len m', 380, 70], ['From', 450, 400], ['To', 850, 400], ['Status', 1250, 90]];
    const bom = RCB.bom(P), H = H0 + 30 + rows.length * RH + 70 + bom.length * 20 + 40; let s = '';
    s += `<rect width="${W}" height="${H}" fill="${pal.bg}"/><text x="30" y="44" font-family="Geist,Segoe UI,sans-serif" font-size="26" font-weight="700" fill="${pal.ink}">${esc(P.name)} · Cable schedule</text><text x="30" y="70" font-family="JetBrains Mono,Consolas,monospace" font-size="13" fill="${pal.sub}">${rows.length} cable${rows.length === 1 ? '' : 's'} · ${new Date().toISOString().slice(0, 10)}</text>`;
    const T = (x, y, t, f, w, c) => `<text x="${x}" y="${y}" font-family="JetBrains Mono,Consolas,monospace" font-size="${f || 12}"${w ? ` font-weight="${w}"` : ''} fill="${c || pal.ink}">${esc(String(t).slice(0, 60))}</text>`;
    let y = H0; s += `<rect x="20" y="${y - 16}" width="${W - 40}" height="24" rx="4" fill="${pal.frame}"/>`; cols.forEach(c => { s += T(30 + c[1], y, c[0], 12, 700, pal.sub); });
    rows.forEach((r, i) => {
      y += RH; if (i % 2) s += `<rect x="20" y="${y - 15}" width="${W - 40}" height="${RH}" fill="${pal.frame}" opacity=".35"/>`;
      const f = x => x.ra.label + ' U' + x.d.u + ' · ' + (x.d.hostname || x.m.name) + ' · ' + RCB.portName(x.m, x.face, x.port).replace(/^(Front|Rear) /, (q, w) => w[0] + ' ');
      s += T(30, y, r.no, 12, 700) + T(90, y, r.c.label) + `<rect x="${210 + 22}" y="${y - 10}" width="12" height="12" rx="3" fill="${r.c.color}" stroke="${pal.edge}" stroke-width=".6"/>` + T(262 + 6, y, RC.CABLES[r.c.type].n.replace(/ \(.*/, '')) + T(410, y, r.c.len == null ? '-' : r.c.len) + T(480, y, f({ ra: r.ra, d: r.A.d, m: r.A.m, face: r.A.face, port: r.A.port })) + T(880, y, f({ ra: r.rb, d: r.B.d, m: r.B.m, face: r.B.face, port: r.B.port })) + T(1280, y, r.c.status, 12, 0, r.c.status === 'installed' ? pal.led : pal.plan);
    });
    y += 50; s += T(30, y, 'Purchase list', 15, 700);
    bom.forEach(b => { y += 20; s += T(30, y, b.qty + ' ×', 12, 700) + T(90, y, RC.CABLES[b.type].n + (b.len != null ? ', ' + b.len + ' m' : ', length not set')); });
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">${s}</svg>`;
  };

  /* ---------- power: feeds derived from power cords ---------- */
  /* A power cord from a device PSU to a PDU/UPS outlet gives that device a feed when the PDU/UPS has one (field feed on the device: 'A' or 'B'). */
  RC.derive = (P, d) => RCB.derivedFeeds(P, d);
  RCB.derivedFeeds = function (P, d) {
    const f = [];
    (P.cables || []).forEach(c => { if (c.type !== 'power') return; const mine = c.a.d === d.id ? c.b : c.b.d === d.id ? c.a : null; if (!mine) return; const o = RC.dev(P, mine.d); if (o && (o.pduFeed === 'A' || o.pduFeed === 'B') && f.indexOf(o.pduFeed) < 0) f.push(o.pduFeed); });
    return f;
  };

  /* ---------- Topology export ---------- */
  const TT = { switch: 'l2sw', router: 'router', firewall: 'fw', server: 'server', storage: 'nas' };
  RCB.toTopology = function (P) {
    const items = [], links = [], map = {}, devs = [];
    P.racks.forEach(r => RC.devsOf(P, r.id).filter(d => TT[RC.model(P, d.modelId).cat]).sort((a, b) => b.u - a.u).forEach(d => { devs.push({ d, r, m: RC.model(P, d.modelId) }); map[d.id] = 1; }));
    /* follow a cable through patch panels: front port n continues on rear port n */
    const other = (c, e) => (c.a.d === e.d && c.a.p === e.p) ? c.b : c.a;
    function far(c, from) {
      let e = other(c, from), guard = 0;
      while (guard++ < 6) { const d = RC.dev(P, e.d); if (!d || RC.model(P, d.modelId).cat !== 'patch') return e; const op = (e.p[0] === 'f' ? 'r' : 'f') + e.p.slice(1); const nx = P.cables.find(x => x.id !== c.id && ((x.a.d === e.d && x.a.p === op) || (x.b.d === e.d && x.b.p === op))); if (!nx) return null; c = nx; e = other(nx, { d: e.d, p: op }); }
      return null;
    }
    const seen = {};
    (P.cables || []).forEach(c => {
      if (c.type === 'power' || c.type === 'console' || c.type === 'usb') return;
      [c.a, c.b].forEach(from => {
        const fd = RC.dev(P, from.d); if (!fd || !map[fd.id]) return; const to = far(c, from); if (!to || !map[to.d] || to.d === from.d) return;
        const key = [from.d + from.p, to.d + to.p].sort().join('~'); if (seen[key]) return; seen[key] = 1;
        const A = RCB.end(P, from), B = RCB.end(P, to); const fam = (RC.CABLES[c.type] || {}).fam;
        links.push({ id: 'l_' + c.id + '_' + links.length, a: from.d, b: to.d, type: fam === 'cu' ? 'copper' : 'fiber', route: 'orth', la: RCB.ifName(A.m, A.face, A.port) || RCB.portName(A.m, A.face, A.port), lb: RCB.ifName(B.m, B.face, B.port) || RCB.portName(B.m, B.face, B.port), label: c.label || '', c: '', wd: 0 });
      });
    });
    /* tiered layout: firewalls and routers on top, then by distance from them along the cables; unlinked devices at the bottom */
    const adj = {}; links.forEach(l => { (adj[l.a] = adj[l.a] || []).push(l.b); (adj[l.b] = adj[l.b] || []).push(l.a); });
    const tier = {}; let q = devs.filter(x => (x.m.cat === 'firewall' || x.m.cat === 'router') && adj[x.d.id]).map(x => x.d.id);
    if (!q.length) { const top = devs.filter(x => adj[x.d.id]).sort((a, b) => adj[b.d.id].length - adj[a.d.id].length)[0]; if (top) q = [top.d.id]; }
    q.forEach(id => { tier[id] = 0; }); for (let h = 0; h < q.length; h++) (adj[q[h]] || []).forEach(n => { if (tier[n] == null) { tier[n] = tier[q[h]] + 1; q.push(n); } });
    let maxT = 0; Object.keys(tier).forEach(k2 => { maxT = Math.max(maxT, tier[k2]); });
    devs.forEach(x => { if (tier[x.d.id] == null) tier[x.d.id] = adj[x.d.id] ? maxT + 1 : maxT + 2; });
    const rows = {}; devs.forEach(x => { (rows[tier[x.d.id]] = rows[tier[x.d.id]] || []).push(x); });
    const widest = Math.max(1, ...Object.keys(rows).map(k2 => rows[k2].length));
    Object.keys(rows).sort((a, b) => a - b).forEach((t, ti) => rows[t].forEach((x, i) => {
      let tt = TT[x.m.cat]; if (x.m.cat === 'switch' && /s5560|s6\d{3}|c9300|n9k|nexus|s7\d{3}|s12\d{3}|s10\d{3}/i.test(x.m.name)) tt = 'l3sw';
      items.push({ id: x.d.id, k: 'dev', t: tt, x: 120 + (i + (widest - rows[t].length) / 2) * 200, y: 80 + ti * 190, label: x.d.hostname || x.m.name, vendor: x.m.vendor || '', model: x.m.name, ip: x.d.mgmtIp || '', note: (x.d.role ? x.d.role + ' · ' : '') + x.r.label + ' U' + x.d.u, s: 1, c: '' });
    }));
    return { name: P.name + ' (from Rack Builder)', items, links };
  };
  /* write it into the Topology store of this browser (same format as the Topology page) and return the diagram id */
  RCB.sendToTopology = function (P) {
    const doc = RCB.toTopology(P), id = 'rk' + Date.now().toString(36) + Math.random().toString(36).slice(2, 5), now = Date.now();
    localStorage.setItem('cl_tg_d_' + id, JSON.stringify({ id, name: doc.name, items: doc.items, links: doc.links }));
    let a = []; try { a = JSON.parse(localStorage.getItem('cl_tg_idx') || '[]'); if (!Array.isArray(a)) a = []; } catch (e) {}
    a.unshift({ id, name: doc.name, desc: 'Created from the Rack Builder', created: now, updated: now, n: doc.items.filter(i => i.k === 'dev').length, l: doc.links.length });
    localStorage.setItem('cl_tg_idx', JSON.stringify(a)); return { id, doc };
  };

  /* ---------- Config Builder hand-off ---------- */
  RCB.toBuilder = function (P, devId) {
    const d = RC.dev(P, devId); if (!d) return null; const m = RC.model(P, d.modelId); if (!(m.cat === 'switch' || m.cat === 'router' || m.cat === 'firewall')) return null;
    const vendor = m.vendor === 'Cisco' ? 'cisco' : 'h3c', os = vendor === 'h3c' ? 'comware' : /nexus|n9k/i.test(m.name) ? 'nxos' : 'iosxe';
    const intf = [], seen = {};
    (P.cables || []).forEach(c => { [c.a, c.b].forEach((e, i) => { if (e.d !== d.id) return; const x = RCB.end(P, e), o = RCB.end(P, i ? c.a : c.b); if (!x || !o || !x.port) return; const nm = RCB.ifName(x.m, x.face, x.port); if (!nm || seen[nm]) return; seen[nm] = 1;
      const to = o.d.hostname || o.m.name, op = RCB.ifName(o.m, o.face, o.port) || RCB.portName(o.m, o.face, o.port);
      intf.push({ interface: nm, description: ('to ' + to + ' ' + op).replace(/[^\w .:/\-]/g, '').slice(0, 80), mode: 'access' }); }); });
    intf.sort((p, q) => p.interface.localeCompare(q.interface, undefined, { numeric: true }));
    const data = { system: { hostname: d.hostname || '' }, interfaces: intf };
    return { vendor, os, data, from: (d.hostname || m.name) };
  };
})();

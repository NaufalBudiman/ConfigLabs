/* ConfigLabs Rack Builder: realistic device faceplates (v7.2).
   Draws the front and rear of each device in SVG at true scale (1 unit = 1 mm), from the model's port spec.
   Port counts and types come from the model record; exact positions of LEDs, console and fan modules are
   illustrative and follow the common layout of each product family. Replaces RR.faceSVG (the old version is kept as a fallback).
   Also collects every port position (o.collect) so cables can attach to the same ports in the next version. */
(function () {
  'use strict';
  const RK = window.RK, RR = window.RR; if (!RR || !RR.faceSVG) return;
  const basic = RR.faceSVG, esc = RR.esc, UMM = RK.UMM, EAR = 14, MONO = 'JetBrains Mono,Consolas,monospace';
  const n1 = v => (Math.round(v * 10) / 10);
  const R = (x, y, w, h, fill, stroke, sw, rx, extra) => `<rect x="${n1(x)}" y="${n1(y)}" width="${n1(Math.max(0, w))}" height="${n1(Math.max(0, h))}"${rx ? ` rx="${rx}"` : ''} fill="${fill}"${stroke ? ` stroke="${stroke}" stroke-width="${sw || 0.5}"` : ''}${extra || ''}/>`;
  const C = (x, y, r, fill, stroke, sw, extra) => `<circle cx="${n1(x)}" cy="${n1(y)}" r="${n1(r)}" fill="${fill}"${stroke ? ` stroke="${stroke}" stroke-width="${sw || 0.5}"` : ''}${extra || ''}/>`;
  const T = (x, y, str, size, fill, anchor, w) => `<text x="${n1(x)}" y="${n1(y)}" font-family="${MONO}" font-size="${size}" fill="${fill}"${anchor ? ` text-anchor="${anchor}"` : ''}${w ? ` font-weight="${w}"` : ''}>${esc(str)}</text>`;
  const BRAND = { H3C: { c: '#d8262f', t: 'H3C' }, Cisco: { c: '#1ba0d7', t: 'cisco' } };
  const DIM = { rj45: [13, 12], sfp: [12, 8], 'sfp+': [12, 8], qsfp: [16, 9], lc: [9, 11], usb: [10, 5], con: [9, 7] };
  const GAP = 1.8, BG = 7;
  /* display options (the editor sets these): catTag = thin category colour line on top, bezel = front bezel on H3C servers */
  RR.art = RR.art || { catTag: true, bezel: false };
  const TAG = { switch: '#4f8fe0', router: '#8d6fe0', firewall: '#e05a55', server: '#aab3c2', storage: '#4fb27d', patch: '#aab3c2', manager: '#8a919c', pdu: '#e0b34f', ups: '#e0b34f', kvm: '#4fb8c8' };
  const lum = h => { const c = h.replace('#', ''); const v = [0, 2, 4].map(i => parseInt(c.substr(i, 2), 16) / 255); return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]; };
  /* real chassis colour by vendor: H3C is black, Cisco is grey. Other vendors keep the category colour. */
  function look(m, pal) {
    const light = pal.bg === '#ffffff', cat = m.cat, net = cat === 'switch' || cat === 'router' || cat === 'firewall', srv = cat === 'server' || cat === 'storage';
    let body = pal.cat[cat] || pal.cat.server, p = pal;
    if (m.vendor === 'H3C' && (net || srv)) body = light ? '#2b2e34' : '#202328';
    else if (m.vendor === 'Cisco' && net) body = /nexus|n9k/i.test(m.name) ? (light ? '#6c747f' : '#4a515b') : (light ? '#b2b9c3' : '#68717c');
    if (body !== (pal.cat[cat] || pal.cat.server)) {
      const dk = lum(body) < 0.45;
      p = Object.assign({}, pal, { ink: dk ? '#e8edf5' : '#10141a', sub: dk ? '#a2adbd' : '#2b3340', edge: dk ? '#07080a' : '#5a6370' });
      if (dk) { p.port = '#090b0e'; p.portIn = '#2a313b'; p.slot = '#0e1115'; }
      p.cat = Object.assign({}, pal.cat, { server: dk ? '#2e3239' : '#9aa2ad' });
    }
    return { body, pal: p };
  }
  const family = m => /s6860/i.test(m.id) ? 's6860' : /s5130s/i.test(m.id) ? 's5130s' : '';
  /* serial number label with a small barcode */
  function sticker(x, y, w, h, pal) {
    let s = R(x, y, w, h, '#e9ecef', '', 0, 0.6, ' opacity=".9"');
    for (let i = 0; i < Math.floor((w - 3) / 1.4); i++) s += R(x + 1.5 + i * 1.4, y + 1.2, (i % 3 === 0 ? 0.9 : 0.5), h - 2.4 - (h > 6 ? 2 : 0), '#111', '', 0, 0);
    return s;
  }
  const cols = b => Math.ceil(b.n / Math.max(1, b.r));
  const pw = b => { const c = cols(b), d = DIM[b.t] || DIM.rj45; return c * (d[0] + GAP) + (b.t === 'rj45' ? Math.floor((c - 1) / 4) * 2.5 : 0); };
  /* is the area (px, py, pw, ph) free enough for the port numbers? */

  /* ---------- single port parts ---------- */
  function rj45(x, y, w, h, pal, led) {
    let s = R(x, y, w, h, pal.port, pal.portIn, 0.5, 1);
    s += R(x + w * 0.2, y + h * 0.3, w * 0.6, h * 0.62, pal.portIn);
    s += R(x + w * 0.34, y + h * 0.08, w * 0.32, h * 0.26, pal.portIn);
    for (let i = 0; i < 4; i++) s += R(x + w * 0.28 + i * w * 0.13, y + h * 0.78, 0.7, h * 0.14, '#c9a24a', '', 0, 0, ' opacity=".75"');
    if (led) s += R(x + 1, y + 1, 2, 1.1, pal.led, '', 0, 0, ' opacity=".45"');
    return s;
  }
  function sfp(x, y, w, h, pal, plus, led) {
    let s = R(x, y, w, h, '#7c8594', pal.portIn, 0.5, 1, ' opacity=".9"');
    s += R(x + 1.3, y + 1.3, w - 2.6, h - 2.6, pal.port, '', 0, 0.6);
    s += R(x + 2.4, y + h * 0.5, w - 4.8, h * 0.28, plus ? '#46699a' : pal.portIn, '', 0, 0.4);
    if (led) s += R(x + 1, y - 1.1, 2, 0.9, pal.led, '', 0, 0, ' opacity=".45"');
    return s;
  }
  function qsfp(x, y, w, h, pal) {
    let s = R(x, y, w, h, '#7c8594', pal.portIn, 0.5, 1, ' opacity=".9"');
    s += R(x + 1.3, y + 1.3, w - 2.6, h - 2.6, pal.port, '', 0, 0.6);
    s += R(x + 2.4, y + h * 0.5, w - 4.8, h * 0.28, '#46699a', '', 0, 0.4);
    s += R(x + w * 0.4, y + 0.3, w * 0.2, 0.9, pal.sub, '', 0, 0, ' opacity=".6"');
    return s;
  }
  function lc(x, y, w, h, pal) {
    return R(x, y, w, h, pal.port, pal.portIn, 0.4, 1.2) + C(x + w / 2, y + h * 0.5, Math.min(w, h) * 0.26, pal.portIn);
  }
  function ear(W, H, pal, s0) {
    let s = '';
    for (let i = 0; i < Math.max(1, Math.round(H / UMM)); i++) {
      const cy = i * UMM + UMM / 2;
      s += R(EAR / 2 - 2.6, cy - 1.7, 5.2, 3.4, pal.slot, '', 0, 1.7) + R(W - EAR / 2 - 2.6, cy - 1.7, 5.2, 3.4, pal.slot, '', 0, 1.7);
    }
    return s;
  }
  function chassis(W, H, body, pal) {
    let s = R(0, 0, W, H, body, pal.edge, 1, 1.5);
    s += R(EAR, 0, W - 2 * EAR, 1, '#fff', '', 0, 0, ' opacity=".10"') + R(EAR, H - 1, W - 2 * EAR, 1, '#000', '', 0, 0, ' opacity=".25"');
    s += R(0, 0, EAR, H, '#000', '', 0, 0, ' opacity=".20"') + R(W - EAR, 0, EAR, H, '#000', '', 0, 0, ' opacity=".20"');
    s += R(EAR, 0, 0.8, H, '#000', '', 0, 0, ' opacity=".35"') + R(W - EAR - 0.8, 0, 0.8, H, '#000', '', 0, 0, ' opacity=".35"');
    return s;
  }
  function vents(x, y, w, h, pal, step) {
    let s = ''; step = step || 3;
    for (let xx = x; xx < x + w - 1; xx += step) s += R(xx, y, 1.1, h, pal.portIn, '', 0, 0.5, ' opacity=".85"');
    return s;
  }
  function iec(x, y, w, h, pal) { /* AC inlet */
    return R(x, y, w, h, pal.port, pal.portIn, 0.5, 1) + R(x + w * 0.18, y + h * 0.2, w * 0.64, h * 0.6, pal.portIn, '', 0, 0.8) + R(x + w * 0.28, y + h * 0.34, w * 0.1, h * 0.28, '#b8b8b8', '', 0, 0, ' opacity=".6"') + R(x + w * 0.62, y + h * 0.34, w * 0.1, h * 0.28, '#b8b8b8', '', 0, 0, ' opacity=".6"');
  }
  function psuMod(x, y, w, h, pal, handleRight) {
    let s = R(x, y, w, h, pal.port, pal.portIn, 0.7, 1.5);
    s += R(x + 1.5, y + 1.5, w - 3, h - 3, pal.cat.server, '', 0, 1, ' opacity=".55"');
    s += vents(x + 3, y + 3, w * 0.38, h - 6, pal, 2.6);
    s += iec(x + w * 0.52, y + h * 0.22, w * 0.3, h * 0.56, pal);
    s += R(handleRight ? x + w - 6 : x + 2, y + h * 0.3, 4, h * 0.4, pal.portIn, pal.edge, 0.4, 1);
    s += C(x + w * 0.86, y + h * 0.5, 1.4, pal.led, '', 0, ' opacity=".8"');
    return s;
  }
  function fanMod(x, y, w, h, pal) {
    let s = R(x, y, w, h, pal.port, pal.portIn, 0.7, 1.5);
    const r = Math.min(w, h) * 0.38, cx = x + w / 2, cy = y + h / 2;
    s += C(cx, cy, r, pal.portIn, pal.edge, 0.5) + C(cx, cy, r * 0.28, pal.port);
    for (let a = 0; a < 6; a++) { const t = a * Math.PI / 3; s += `<line x1="${n1(cx)}" y1="${n1(cy)}" x2="${n1(cx + Math.cos(t) * r * 0.92)}" y2="${n1(cy + Math.sin(t) * r * 0.92)}" stroke="${pal.edge}" stroke-width=".7" opacity=".7"/>`; }
    s += R(x + w - 3.2, y + h * 0.35, 2, h * 0.3, pal.sub, '', 0, 0.6, ' opacity=".5"');
    return s;
  }

  /* ---------- layout engine for rows of port blocks ---------- */
  /* Draw port blocks left to right in the area. Returns svg; pushes to collect. */
  function drawPorts(blocks, area, sc, pal, ctx) {
    let s = '', x = area.x;
    const ahh = area.h;
    blocks.forEach(b => {
      const d = DIM[b.t] || DIM.rj45, w = d[0] * sc, h = Math.min(d[1] * sc, (ahh - (b.r - 1) * GAP) / b.r), c = cols(b), rows = b.r;
      const top = area.y + (ahh - (rows * h + (rows - 1) * GAP * sc)) / 2 + (ctx.numbers ? 1.2 : 0);
      if (b.t === 'lc') { /* duplex LC adapters: two ports per shell */ }
      for (let i = 0; i < b.n; i++) {
        const col = Math.floor(i / rows), row = i % rows;
        const cx = x + col * (w + GAP * sc) + (b.t === 'rj45' ? Math.floor(col / 4) * 2.5 * sc : 0), cy = top + row * (h + GAP * sc);
        ctx.num += 1; const id = ctx.face + ctx.num;
        ctx.collect && ctx.collect.push({ id, n: ctx.num, t: b.t, x: n1(cx), y: n1(cy), w: n1(w), h: n1(h) });
        s += `<g data-port="${id}" data-pt="${b.t}">`;
        if (b.t === 'rj45') s += rj45(cx, cy, w, h, pal, ctx.detail);
        else if (b.t === 'sfp' || b.t === 'sfp+') s += sfp(cx, cy, w, h, pal, b.t === 'sfp+', ctx.detail);
        else if (b.t === 'qsfp') s += qsfp(cx, cy, w, h, pal);
        else if (b.t === 'lc') s += lc(cx, cy, w, h, pal);
        else s += R(cx, cy, w, h, pal.port, pal.portIn, 0.5, 1);
        s += '</g>';
        if (ctx.numbers && row === 0 && sc > 0.55) s += T(cx + w / 2, cy - 0.9, String(ctx.num), 2.7, pal.sub, 'middle');
      }
      x += pw(b) * sc + BG * sc;
    });
    return s;
  }

  /* ---------- per category ---------- */
  function netFront(m, W, H, pal, o, ctx, fam) {
    let s = '', brand = BRAND[m.vendor];
    const strip = 9, ax = EAR + 5, aw = W - 2 * EAR - 10, ay = strip, ah = H - strip - 3;
    const blocks = (m.front || []).filter(b => b.k === 'p');
    /* brand and LED module on the left */
    const bw = fam === 's6860' ? 36 : 62;
    if (ah > 8) {
      s += R(ax, ay + 1, bw, ah - 2, '#000', '', 0, 1.5, ' opacity=".18"');
      if (brand) { s += R(ax + 3, ay + 3.2, 2.4, 5.8, brand.c, '', 0, 0.8); s += T(ax + 8, ay + 9, brand.t, 7, pal.ink, '', 700); }
      else s += T(ax + 4, ay + 9, 'SWITCH', 5, pal.sub, '', 600);
      const ly = ay + ah - 6;
      (fam === 's6860' ? ['SYS'] : ['PWR', 'SYS', 'ACT', 'MODE']).forEach((n, i) => { s += C(ax + 5 + i * 8.5, ly, 1.3, i < 2 ? pal.led : pal.sub, '', 0, i < 2 ? ' opacity=".8"' : ' opacity=".35"'); if (ctx.detail && ah > 20) s += T(ax + 5 + i * 8.5, ly + 4.2, n, 2.3, pal.sub, 'middle'); });
      if (fam === 's5130s' && ah > 14) { s += R(ax + 54, ay + ah - 12, 5, 3.4, pal.port, pal.portIn, 0.4, 0.8) + T(ax + 56.5, ay + ah - 13.4, 'USB', 2.2, pal.sub, 'middle'); }
      if (fam !== 's6860' && ah > 14) { s += R(ax + 40, ay + ah - 14, 12, 8.5, pal.port, pal.portIn, 0.5, 1) + R(ax + 42, ay + ah - 12, 8, 4.5, '#2b5b8a', '', 0, 0.5) + T(ax + 46, ay + ah - 15.5, 'CON', 2.5, pal.sub, 'middle'); if (ctx.collect) ctx.collect.push({ id: 'fcon', n: 0, t: 'con', x: ax + 40, y: ay + ah - 14, w: 12, h: 8.5, label: 'Console' }); }
    }
    /* ports */
    const px = ax + bw + 5, pwid = aw - bw - 5;
    let fw = blocks.reduce((t, b) => t + pw(b), 0) + Math.max(0, blocks.length - 1) * BG, sc = fw > pwid ? Math.max(0.35, pwid / fw) : 1;
    const dense = blocks.length > 1;
    if (dense) {
      const last = blocks[blocks.length - 1], rest = blocks.slice(0, -1), restW = rest.reduce((t, b) => t + pw(b) * sc, 0) + (rest.length) * BG * sc;
      s += drawPorts(rest, { x: px, y: ay, w: pwid, h: ah }, sc, pal, ctx);
      s += drawPorts([last], { x: Math.max(px + restW, px + pwid - pw(last) * sc), y: ay, w: pwid, h: ah }, sc, pal, ctx);
    } else s += drawPorts(blocks, { x: px, y: ay, w: pwid, h: ah }, sc, pal, ctx);
    return s;
  }
  function netRear(m, W, H, pal, o, ctx, fam) {
    let s = '';
    const ay = 7, ah = H - ay - 3, ax = EAR + 6, aw = W - 2 * EAR - 12;
    if (fam === 's6860') { /* console, management and USB on the rear; four fan trays; two PSU slots */
      let x = ax + aw; const mh = Math.min(ah, 36), my = ay + (ah - mh) / 2;
      for (let i = 0; i < 2; i++) { x -= 78; s += psuMod(x, my, 78, mh, pal, i === 0); x -= 4; }
      for (let i = 0; i < 4; i++) { x -= 28; s += fanMod(x, my, 28, mh, pal); x -= 2.5; }
      const lx = ax + 2;
      s += R(lx, ay, 118, ah, '#000', '', 0, 1.5, ' opacity=".18"');
      const pr = (px, py, w, h, lab, id, t) => { s += R(px, py, w, h, pal.port, pal.portIn, 0.5, 1) + R(px + w * 0.2, py + h * 0.3, w * 0.6, h * 0.55, pal.portIn) + T(px + w / 2, py - 1, lab, 2.4, pal.sub, 'middle'); if (ctx.collect) ctx.collect.push({ id, n: 0, t, x: px, y: py, w, h, label: lab }); };
      const py = ay + Math.max(3, ah * 0.28);
      pr(lx + 4, py, 11, 9, 'CON', 'rcon', 'con'); pr(lx + 20, py, 11, 9, 'MGMT', 'rmgmt', 'rj45');
      s += R(lx + 36, py, 12, 8, pal.port, pal.portIn, 0.5, 1) + T(lx + 42, py - 1, 'MGMT SFP', 2.2, pal.sub, 'middle');
      s += R(lx + 53, py + 2, 6, 3.6, pal.port, pal.portIn, 0.4, 0.8) + R(lx + 63, py + 2, 8, 4, pal.port, pal.portIn, 0.4, 0.8) + T(lx + 56, py - 1, 'USB', 2.2, pal.sub, 'middle');
      s += C(lx + 80, py + 3, 1.3, pal.led, '', 0, ' opacity=".8"') + T(lx + 80, py + 8, 'SYS', 2.2, pal.sub, 'middle') + C(lx + 90, py + 3, 1.1, pal.led, '', 0, ' opacity=".6"') + C(lx + 96, py + 3, 1.1, '#f4a23c', '', 0, ' opacity=".4"') + T(lx + 93, py + 8, 'MGMT', 2.2, pal.sub, 'middle');
      s += sticker(lx + 4, ay + ah - 7, 22, 5, pal) + C(lx + 108, ay + ah - 4, 2, pal.sub, pal.edge, 0.4, ' opacity=".6"') + T(lx + 104, ay + ah - 6.5, 'GND', 2.2, pal.sub);
      return s;
    }
    const tray = m.air === 'tray' || m.psu >= 2, nP = Math.max(0, m.psu || 0);
    let x = ax + aw;
    const mh = Math.min(ah, 36);
    const my = ay + (ah - mh) / 2;
    if (tray) {
      for (let i = 0; i < Math.max(1, nP); i++) { x -= 86; s += psuMod(x, my, 86, mh, pal, i % 2 === 0); x -= 4; }
      const nf = m.cat === 'switch' ? 2 : 2;
      for (let i = 0; i < nf; i++) { x -= 34; s += fanMod(x, my, 34, mh, pal); x -= 3; }
    } else if (nP > 0) {
      x -= 40; s += iec(x, my + mh * 0.12, 40, mh * 0.76, pal); x -= 6;
    }
    if (x - ax > 20) s += vents(ax, ay + 3, Math.min(x - ax - 8, 180), ah - 6, pal, 3.2);
    s += C(ax + 6, ay + ah - 5, 2.2, pal.sub, pal.edge, 0.4, ' opacity=".6"') + T(ax + 11, ay + ah - 3.8, 'GND', 2.6, pal.sub);
    if (ah > 12) s += sticker(ax + 24, ay + ah - 7, 24, 5, pal);
    return s;
  }
  function srvFront(m, W, H, pal, o, ctx) {
    let s = '', brand = BRAND[m.vendor], h3 = m.vendor === 'H3C';
    const ay = 9, ah = H - 12, ax = EAR + 3, aw = W - 2 * EAR - 6, dy = Math.min(9, ah * 0.3);
    const cw = 30, rw = 22;
    /* ear blocks. H3C UniServer: left = VGA, Type-C management, USB; right = power button, UID, health, system power, OCP LED. Others: power left, USB/VGA right. */
    const ioBlock = (x) => {
      let t = R(x, ay, rw, ah, '#000', '', 0, 1.5, ' opacity=".2"');
      if (h3) {
        t += R(x + 3, ay + 3, 7, 4.4, pal.port, pal.portIn, 0.4, 0.6) + T(x + 6.5, ay + 2.2, 'VGA', 2, pal.sub, 'middle');
        t += R(x + 12, ay + 3.4, 6, 3, pal.port, pal.portIn, 0.4, 1.4) + T(x + 15, ay + 2.2, 'C', 2, pal.sub, 'middle');
        if (ah > 14) t += R(x + 3, ay + ah - 8, 7, 4, '#1a5a9a', pal.portIn, 0.4, 0.5) + R(x + 12, ay + ah - 8, 7, 4, '#1a5a9a', pal.portIn, 0.4, 0.5);
        if (ctx.collect) ctx.collect.push({ id: 'fmgmt', n: 0, t: 'usbc', x: x + 12, y: ay + 3.4, w: 6, h: 3, label: 'HDM Type-C' });
      } else {
        for (let i = 0; i < 2; i++) t += R(x + 4 + i * 8, ay + 4, 6.5, 3.4, '#1a5a9a', pal.portIn, 0.4, 0.5);
        if (ah > 14) t += R(x + 4, ay + ah - 8, 14, 5, '#2a4a8a', pal.portIn, 0.4, 1);
      }
      return t;
    };
    const ctlBlock = (x) => {
      let t = R(x, ay, cw, ah, '#000', '', 0, 1.5, ' opacity=".2"');
      t += C(x + 7, ay + dy, 3, pal.port, pal.led, 0.7, '') + C(x + 7, ay + dy, 0.9, pal.led, '', 0, ' opacity=".7"');
      t += C(x + 17, ay + dy, 1.2, pal.led, '', 0, ' opacity=".5"') + C(x + 23, ay + dy, 1.2, '#4aa3ff', '', 0, ' opacity=".4"');
      if (h3 && ah > 16) t += C(x + 17, ay + dy + 6, 1.2, '#7cf4c7', '', 0, ' opacity=".5"') + C(x + 23, ay + dy + 6, 1.2, '#f4a23c', '', 0, ' opacity=".35"') + T(x + 7, ay + dy + 7.2, 'PWR', 1.9, pal.sub, 'middle') + T(x + 20, ay + dy + 14, 'UID  HLTH  OCP', 1.7, pal.sub, 'middle');
      if (brand && ah > 18) t += T(x + 3, ay + ah - 3, brand.t, 5.5, pal.sub, '', 700);
      return t;
    };
    s += h3 ? ioBlock(ax) + ctlBlock(ax + aw - cw) : ctlBlock(ax) + ioBlock(ax + aw - rw);
    const lw = h3 ? rw : cw, rwid = h3 ? cw : rw;
    const bx = ax + lw + 3, bw = aw - lw - rwid - 6;
    const bays = (m.front || []).filter(b => b.k === 'bay')[0];
    if (h3 && RR.art.bezel) { /* intelligent security bezel: perforated black grille with the logo */
      s += R(bx, ay, bw, ah, '#15171a', pal.edge, 0.6, 2);
      for (let yy = ay + 2; yy < ay + ah - 1.5; yy += 2.4) for (let xx = bx + 3; xx < bx + bw - 2; xx += 2.4) s += C(xx, yy, 0.62, '#050607', '', 0);
      if (brand) s += R(bx + bw / 2 - 17, ay + ah / 2 - 5, 3, 10, brand.c, '', 0, 0.8) + T(bx + bw / 2 - 12, ay + ah / 2 + 3.2, brand.t, 9, '#e8edf5', '', 700);
      return s;
    }
    if (bays) {
      const c = bays.c, rows = Math.ceil(bays.n / c), g = 1.6, cw2 = (bw - (c - 1) * g) / c, ch = Math.min((ah - (rows - 1) * g) / rows, 30), oy = ay + (ah - (rows * ch + (rows - 1) * g)) / 2;
      for (let i = 0; i < bays.n; i++) {
        const cc = i % c, rr = Math.floor(i / c), x = bx + cc * (cw2 + g), y = oy + rr * (ch + g);
        s += R(x, y, cw2, ch, pal.port, pal.portIn, 0.5, 1) + R(x + 1, y + 1, cw2 - 2, ch - 2, pal.cat.server, '', 0, 0.6, ' opacity=".55"');
        if (ctx.detail) s += vents(x + 2, y + 2.2, cw2 * 0.58, Math.max(1, ch - 4.4), pal, 2.2);
        if (ctx.detail && ch > 8) s += R(x + 1.6, y + ch - 3, 5, 1.4, '#e9ecef', '', 0, 0.3, ' opacity=".5"');
        s += R(x + cw2 - 7, y + ch * 0.2, 5, ch * 0.6, pal.portIn, pal.edge, 0.4, 1) + C(x + cw2 - 3.5, y + ch * 0.32, 0.8, pal.led, '', 0, ' opacity=".7"') + C(x + cw2 - 3.5, y + ch * 0.68, 0.8, '#f4a23c', '', 0, ' opacity=".35"');
      }
      if (ctx.detail && ah > 10) s += sticker(bx + bw - 24, ay + ah + 0.6, 22, 2.2, pal);
    } else s += vents(bx, ay + 2, bw, ah - 4, pal, 3);
    return s;
  }
  function srvRear(m, W, H, pal, o, ctx) {
    let s = '';
    const ay = 9, ah = H - 12, ax = EAR + 4, aw = W - 2 * EAR - 8;
    let x = ax + aw;
    const nP = Math.max(1, m.psu || 1), mh = Math.min(ah, 36);
    for (let i = 0; i < nP; i++) { x -= 86; s += psuMod(x, ay + (ah - mh) / 2, 86, mh, pal, i % 2 === 0); x -= 3; }
    /* io: ports from spec (LOM), mgmt, vga, usb */
    const lom = (m.rear || []).filter(b => b.k === 'p'), sc = Math.min(1, (ah - 4) / 26 > 0.4 ? 1 : 0.6);
    let ix = ax; const iy = ay, ih = ah;
    s += R(ix, iy, 126, ih, '#000', '', 0, 1.5, ' opacity=".18"');
    let px = ix + 4;
    s += drawPorts(lom, { x: px, y: iy + (ih > 30 ? 2 : 0), w: 100, h: Math.min(ih, 34) }, sc, pal, ctx);
    if (ih > 18) { const mgx = ix + 4; s += R(mgx, iy + ih - 13, 13, 11, pal.port, '#4a8fd0', 0.6, 1) + T(mgx + 6.5, iy + ih - 14.4, m.vendor === 'H3C' ? 'HDM' : 'MGMT', 2.4, pal.sub, 'middle'); if (ctx.collect) ctx.collect.push({ id: 'rmgmt', n: 0, t: 'rj45', x: mgx, y: iy + ih - 13, w: 13, h: 11, label: 'MGMT' }); }
    s += R(ix + 100, iy + 3, 6.5, 3.4, '#1a5a9a', pal.portIn, 0.4, 0.5) + R(ix + 109, iy + 3, 6.5, 3.4, '#1a5a9a', pal.portIn, 0.4, 0.5);
    if (ih > 14) s += R(ix + 100, iy + ih - 9, 15, 6, '#2a4a8a', pal.portIn, 0.4, 1);
    ix += 130;
    /* pcie slots */
    const room = x - ix - 2, slots = Math.max(0, Math.min(m.u === 1 ? 2 : m.u === 2 ? 3 : 5, Math.floor(room / 40)));
    if (slots) {
      const sw = Math.min(70, room / slots - 2);
      for (let i = 0; i < slots; i++) { const sx = ix + i * (sw + 2); s += R(sx, iy, sw, ih, pal.portIn, pal.edge, 0.5, 1) + vents(sx + 3, iy + ih * 0.3, sw - 6, ih * 0.4, pal, 3) + R(sx + 1.5, iy + 1.5, 3, 1.4, pal.sub, '', 0, 0.5, ' opacity=".4"') + (ctx.detail ? T(sx + sw / 2, iy + ih - 2, (m.vendor === 'H3C' ? 'RISER ' : 'PCIe ') + (i + 1), 2.3, pal.sub, 'middle') : ''); }
    }
    return s;
  }
  function storRear(m, W, H, pal, o, ctx) { return srvRear(m, W, H, pal, o, ctx); }
  function patch(m, W, H, pal, o, ctx) {
    let s = '';
    const ax = EAR + 6, aw = W - 2 * EAR - 12, ay = 9, ah = H - ay - 3;
    const b = (m.front || [])[0]; if (!b) return s;
    if (b.t === 'lc') {
      const adapters = b.n / 2, aw1 = Math.min(24, (aw - 8) / adapters - 1.5), x0 = ax + (aw - adapters * (aw1 + 1.5)) / 2;
      for (let i = 0; i < adapters; i++) {
        const x = x0 + i * (aw1 + 1.5), y = ay + (ah - 15) / 2;
        s += R(x, y, aw1, 15, pal.port, pal.portIn, 0.4, 1.5);
        for (let k = 0; k < 2; k++) { ctx.num += 1; const id = ctx.face + ctx.num; ctx.collect && ctx.collect.push({ id, n: ctx.num, t: 'lc', x: n1(x + 2 + k * (aw1 / 2 - 1)), y: n1(y + 2), w: n1(aw1 / 2 - 1.5), h: 11 }); s += `<g data-port="${id}" data-pt="lc">` + R(x + 2 + k * (aw1 / 2 - 1), y + 2, aw1 / 2 - 1.5, 11, pal.portIn, '', 0, 1) + C(x + 2 + k * (aw1 / 2 - 1) + (aw1 / 2 - 1.5) / 2, y + 7.5, 1.6, pal.port) + '</g>'; }
        if (ctx.detail) s += T(x + aw1 / 2, y - 1.3, String(i + 1), 2.6, pal.sub, 'middle');
      }
      return s;
    }
    const rows = b.r, c = Math.ceil(b.n / rows), jw = Math.min(14, (aw - 6) / (c + c / 6) - 0.4), jh = Math.min(15, (ah - (rows - 1) * 2.5) / rows);
    const total = c * jw + (c - 1) * 0.4 + Math.floor((c - 1) / 6) * 3, x0 = ax + (aw - total) / 2, y0 = ay + (ah - (rows * jh + (rows - 1) * 2.5)) / 2;
    for (let i = 0; i < b.n; i++) {
      const col = Math.floor(i / rows), row = i % rows, x = x0 + col * (jw + 0.4) + Math.floor(col / 6) * 3, y = y0 + row * (jh + 2.5);
      ctx.num += 1; const id = ctx.face + ctx.num; ctx.collect && ctx.collect.push({ id, n: ctx.num, t: 'rj45', x: n1(x), y: n1(y), w: n1(jw), h: n1(jh) });
      s += `<g data-port="${id}" data-pt="rj45">` + R(x, y, jw, jh, pal.port, pal.portIn, 0.4, 0.8) + R(x + jw * 0.2, y + jh * 0.32, jw * 0.6, jh * 0.55, pal.portIn) + '</g>';
      if (ctx.detail && row === 0) s += T(x + jw / 2, y - 1.2, String(ctx.num), 2.6, pal.sub, 'middle');
    }
    return s;
  }
  function pdu(m, W, H, pal, o, ctx) {
    let s = '';
    const ay = 9, ah = H - 13, ax = EAR + 6, aw = W - 2 * EAR - 12, n = ((m.front || [])[0] || {}).n || 8;
    s += R(ax, ay, 34, ah, '#06140d', pal.portIn, 0.5, 1.5) + T(ax + 17, ay + ah * 0.68, '0.0 A', Math.min(9, ah * 0.5), pal.led, 'middle', 700);
    s += R(ax + 38, ay + ah * 0.25, 9, ah * 0.5, '#d8262f', pal.edge, 0.4, 1.2) + T(ax + 42.5, ay + ah * 0.25 - 1, 'MCB', 2.6, pal.sub, 'middle');
    const ox = ax + 54, ow = aw - 54, sw = Math.min(26, ow / n - 3);
    for (let i = 0; i < n; i++) {
      const x = ox + i * (sw + 3) + (ow - n * (sw + 3)) / 2, y = ay + (ah - 15) / 2;
      ctx.num += 1; const id = ctx.face + ctx.num; ctx.collect && ctx.collect.push({ id, n: ctx.num, t: 'out', x: n1(x), y: n1(y), w: n1(sw), h: 15 });
      s += `<g data-port="${id}" data-pt="out">` + R(x, y, sw, 15, pal.port, pal.portIn, 0.5, 2) + R(x + sw * 0.18, y + 3, sw * 0.64, 9, pal.portIn, '', 0, 1) + R(x + sw * 0.28, y + 6, sw * 0.12, 3.4, '#b8b8b8', '', 0, 0, ' opacity=".55"') + R(x + sw * 0.6, y + 6, sw * 0.12, 3.4, '#b8b8b8', '', 0, 0, ' opacity=".55"') + '</g>';
    }
    return s;
  }
  function ups(m, W, H, pal) {
    let s = '';
    const ay = 9, ah = H - 13, ax = EAR + 6, aw = W - 2 * EAR - 12;
    s += R(ax, ay, 60, ah, '#0a1d2a', pal.portIn, 0.6, 2) + R(ax + 4, ay + 4, 52, ah - 8, '#1b4f6b', '', 0, 1, ' opacity=".7"') + T(ax + 30, ay + ah / 2 + 3, '100%  ONLINE', 5, '#bfe9ff', 'middle', 600);
    for (let i = 0; i < 4; i++) s += C(ax + 72 + i * 9, ay + ah / 2, 2.4, pal.port, pal.portIn, 0.6);
    s += vents(ax + 120, ay + 5, aw - 124, ah - 10, pal, 3.4);
    return s;
  }
  function kvm(m, W, H, pal) {
    let s = '';
    const ay = 9, ah = H - 13, ax = EAR + 6, aw = W - 2 * EAR - 12;
    s += R(ax, ay, aw, ah, '#000', pal.portIn, 0.5, 2, ' opacity=".35"') + R(ax + aw / 2 - 30, ay + ah - 9, 60, 5, pal.portIn, pal.edge, 0.4, 2.5);
    for (let i = 0; i < 3; i++) s += C(ax + 8 + i * 6, ay + 6, 1.3, i === 0 ? pal.led : pal.sub, '', 0, ' opacity=".6"');
    return s;
  }
  function manager(m, W, H, pal) {
    let s = '';
    const ay = 9, ah = H - 12, ax = EAR + 6, aw = W - 2 * EAR - 12;
    for (let x = ax; x < ax + aw - 8; x += 14) s += R(x, ay, 10, ah, pal.port, pal.portIn, 0.4, 3);
    return s;
  }

  /* ---------- main entry ---------- */
  RR.faceSVG = function (m, faceKey, W, H, pal, o) {
    o = o || {};
    const cat = m.cat;
    if (['switch', 'router', 'firewall', 'server', 'storage', 'patch', 'pdu', 'ups', 'kvm', 'manager', 'blank'].indexOf(cat) < 0) return basic(m, faceKey, W, H, pal, o);
    const detail = !o.compact, lk = look(m, pal), body = lk.body, collect = o.collect || null; pal = lk.pal;
    const ctx = { num: 0, face: faceKey === 'rear' ? 'r' : 'f', collect, detail, numbers: detail && H >= UMM * 0.95 };
    let s = chassis(W, H, body, pal) + ear(W, H, pal);
    if (RR.art.catTag && cat !== 'blank' && TAG[cat]) s += R(EAR, 0, W - 2 * EAR, Math.min(1.8, H * 0.08), TAG[cat], '', 0, 0, ' opacity=".85"');
    if (cat === 'blank') return s + R(EAR + 8, H / 2 - 0.4, W - 2 * EAR - 16, 0.8, pal.edge, '', 0, 0, ' opacity=".5"');
    /* hostname label */
    const lab = o.label || m.name, fs = Math.min(7, Math.max(4.5, H * 0.16)), maxc = Math.floor((W - 2 * EAR - 16) / (fs * 0.62)), shown = lab.length > maxc ? lab.slice(0, Math.max(1, maxc - 1)) + '…' : lab;
    s += T(EAR + 5, fs + 2.2, shown, fs, pal.ink, '', 600);
    if (o.status) s += C(W - EAR - 6, fs / 2 + 3, 2.4, o.status === 'installed' ? pal.led : pal.plan);
    const rear = faceKeyIsRear(faceKey), fam = family(m);
    if (cat === 'switch' || cat === 'router' || cat === 'firewall') s += rear ? netRear(m, W, H, pal, o, ctx, fam) : netFront(m, W, H, pal, o, ctx, fam);
    else if (cat === 'server') s += rear ? srvRear(m, W, H, pal, o, ctx) : srvFront(m, W, H, pal, o, ctx);
    else if (cat === 'storage') s += rear ? storRear(m, W, H, pal, o, ctx) : srvFront(m, W, H, pal, o, ctx);
    else if (cat === 'patch') s += rear ? '' : patch(m, W, H, pal, o, ctx);
    else if (cat === 'pdu') s += pdu(m, W, H, pal, o, ctx);
    else if (cat === 'ups') s += ups(m, W, H, pal);
    else if (cat === 'kvm') s += kvm(m, W, H, pal);
    else if (cat === 'manager') s += manager(m, W, H, pal);
    return s;
  };
  function faceKeyIsRear(k) { return k === 'rear'; }
  /* port list of one face (id, type, x, y, w, h), in device mm coordinates */
  RR.portMap = function (m, faceKey, pal) {
    const list = []; RR.faceSVG(m, faceKey, RK.RACKW, m.u * UMM, pal || RR.pal('dark'), { collect: list });
    return list;
  };
  /* a self-contained SVG of one face of a model, for previews */
  RR.devicePreview = function (m, faceKey, palName, o) {
    o = o || {}; const pal = RR.pal(palName || 'dark'), W = RK.RACKW, H = m.u * UMM, pad = 4;
    const inner = RR.faceSVG(m, faceKey, W, H, pal, { label: o.label || m.name, compact: !!o.compact });
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${-pad} ${-pad} ${W + 2 * pad} ${H + 2 * pad}" width="100%" role="img" aria-label="${esc(m.name)} ${faceKey}"><g>${inner}</g></svg>`;
  };
})();

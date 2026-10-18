/* ConfigLabs Rack Builder: SVG drawing at true scale (1 unit = 1 mm). Needs rack-lib.js and rack-calc.js. */
(function () {
  'use strict';
  const RK = window.RK, RC = window.RC, RR = window.RR = window.RR || {};
  const esc = s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  RR.esc = esc;
  const UMM = RK.UMM, RW = RK.RACKW, RAIL = 36, FT = 30, EAR = 14;

  RR.PAL = {
    dark: { bg: '#0b0e13', frame: '#1b212b', rail: '#252d3a', num: '#6f7d92', ink: '#e8edf5', sub: '#9aa7ba', edge: '#0a0c10', port: '#0a0d12', portIn: '#1d2430', led: '#7cf4c7', plan: '#f4c27c', acc: '#7cf4c7', bad: '#ff7a7a', warn: '#f4c27c', slot: '#10151c', hole: '#2c3646', hatch: '#ff7a7a',
      cat: { switch: '#2c3d57', router: '#3b3359', firewall: '#58302f', server: '#363b44', storage: '#30463a', patch: '#40454d', manager: '#2b2f36', blank: '#171a20', pdu: '#4d4025', ups: '#43391f', kvm: '#2c4750' } },
    light: { bg: '#ffffff', frame: '#d5dbe4', rail: '#bcc5d1', num: '#5d6b80', ink: '#101828', sub: '#4a5568', edge: '#7b8798', port: '#2a3340', portIn: '#566274', led: '#12a574', plan: '#c98a1c', acc: '#0a8f68', bad: '#d23b3b', warn: '#c98a1c', slot: '#eef1f6', hole: '#9aa6b6', hatch: '#d23b3b',
      cat: { switch: '#bcd0ee', router: '#d2c8f0', firewall: '#f0c6c3', server: '#d4d9e1', storage: '#c4e2d0', patch: '#dadde2', manager: '#e6e8ec', blank: '#eef0f3', pdu: '#f0dfb2', ups: '#ecd9a6', kvm: '#bfe0e8' } }
  };
  RR.pal = n => RR.PAL[n] || RR.PAL.dark;
  /* y of a device's top edge inside the rack drawing */
  RR.slotTop = (rack, u, h, topY) => rack.numbering === 'top-down' ? topY + (u - 1) * UMM : topY + (rack.u - (u + h - 1)) * UMM;
  /* lowest-numbered U of an h-tall slot whose top row is topRow (0 = highest on screen) */
  RR.uFromRow = (rack, row, h) => rack.numbering === 'top-down' ? row + 1 : rack.u - row - h + 1;
  RR.rowOf = (rack, y, topY, h) => Math.round((y - topY) / UMM - h / 2);

  const PD = { rj45: [13, 12], sfp: [12, 8], 'sfp+': [12, 8], qsfp: [16, 9], lc: [9, 11], usb: [10, 5], con: [9, 7] };
  const GAP = 1.8;
  function colsOf(b) { return Math.ceil(b.n / Math.max(1, b.r)); }
  function portW(b) { const c = colsOf(b), d = PD[b.t] || PD.rj45; return c * (d[0] + GAP) + (b.t === 'rj45' ? Math.floor((c - 1) / 4) * 2.5 : 0); }
  function blockW(b) { if (b.k === 'p') return portW(b); if (b.k === 'psu') return b.n * 86 + (b.n - 1) * 4; if (b.k === 'fan') return b.n * 34; if (b.k === 'out') return b.n * 27; return 0; }

  /* One face of a device at local origin; W,H in mm. */
  RR.faceSVG = function (m, faceKey, W, H, pal, o) {
    o = o || {};
    const body = pal.cat[m.cat] || pal.cat.server; let s = '';
    s += `<rect width="${W}" height="${H}" rx="1.5" fill="${body}" stroke="${pal.edge}" stroke-width="1"/>`;
    /* rack ears */
    s += `<rect width="${EAR}" height="${H}" fill="#000" opacity=".18"/><rect x="${W - EAR}" width="${EAR}" height="${H}" fill="#000" opacity=".18"/>`;
    for (let i = 0; i < Math.max(1, Math.round(H / UMM)); i++) { const cy = i * UMM + UMM / 2; s += `<circle cx="${EAR / 2}" cy="${cy}" r="2.2" fill="${pal.slot}"/><circle cx="${W - EAR / 2}" cy="${cy}" r="2.2" fill="${pal.slot}"/>`; }
    if (m.cat === 'blank') { s += `<line x1="${EAR + 4}" y1="${H / 2}" x2="${W - EAR - 4}" y2="${H / 2}" stroke="${pal.edge}" stroke-width=".6" opacity=".5"/>`; return s; }
    let blocks = m[faceKey];
    if (!blocks && faceKey === 'rear') { /* derive a plain rear from PSU count and airflow */
      blocks = []; if (m.psu > 0) blocks.push({ k: 'psu', n: m.psu }); if (m.psu > 0 && (m.cat === 'switch' || m.cat === 'firewall' || m.cat === 'router')) blocks.push({ k: 'fan', n: 2 });
    }
    blocks = blocks || [];
    /* label strip */
    const lab = o.label || m.name, fs = Math.min(7, Math.max(4.5, H * 0.16)), strip = H > UMM * 1.5 ? fs + 6 : fs + 5;
    const maxc = Math.floor((W - 2 * EAR - 16) / (fs * 0.62)), shown = lab.length > maxc ? lab.slice(0, Math.max(1, maxc - 1)) + '…' : lab;
    s += `<text x="${EAR + 5}" y="${fs + 2.2}" font-family="JetBrains Mono,Consolas,monospace" font-size="${fs}" fill="${pal.ink}" font-weight="600">${esc(shown)}</text>`;
    if (o.status) s += `<circle cx="${W - EAR - 6}" cy="${fs / 2 + 3}" r="2.4" fill="${o.status === 'installed' ? pal.led : pal.plan}"/>`;
    const ax = EAR + 5, aw = W - 2 * EAR - 10, ay = strip, ah = H - strip - 3;
    if (ah < 6 || !blocks.length) return s;
    const fixed = blocks.filter(b => b.k !== 'bay'), bays = blocks.filter(b => b.k === 'bay');
    const BG = 7; let fw = fixed.reduce((t, b) => t + blockW(b), 0) + Math.max(0, fixed.length - 1) * BG + (bays.length && fixed.length ? BG : 0);
    let sc = 1; const minBay = bays.length ? aw * 0.35 : 0;
    if (fw > aw - minBay) sc = Math.max(0.3, (aw - minBay) / fw);
    let x = ax;
    const place = b => {
      if (b.k === 'bay') {
        const bw = Math.max(0, aw - (x - ax) - 0), cols = b.c, rows = Math.ceil(b.n / cols), g = 2, cw = (bw - (cols - 1) * g) / cols, ch = Math.min(ah, (ah - (rows - 1) * g) / rows, 26);
        const oy = ay + (ah - (rows * ch + (rows - 1) * g)) / 2; for (let i = 0; i < b.n; i++) { const c = i % cols, r = Math.floor(i / cols); s += `<rect x="${(x + c * (cw + g)).toFixed(1)}" y="${(oy + r * (ch + g)).toFixed(1)}" width="${cw.toFixed(1)}" height="${ch.toFixed(1)}" rx="1" fill="${pal.port}" stroke="${pal.portIn}" stroke-width=".6"/><rect x="${(x + c * (cw + g) + 1.5).toFixed(1)}" y="${(oy + r * (ch + g) + ch - 3.2).toFixed(1)}" width="${(cw * 0.3).toFixed(1)}" height="1.4" fill="${pal.led}" opacity=".7"/>`; }
        x += bw; return;
      }
      if (b.k === 'p') {
        const d = PD[b.t] || PD.rj45, pw = d[0] * sc, ph = Math.min(d[1] * sc, (ah - (b.r - 1) * GAP) / b.r), cols = colsOf(b), rows = b.r, oy = ay + (ah - (rows * ph + (rows - 1) * GAP * sc)) / 2;
        for (let i = 0; i < b.n; i++) {
          const c = Math.floor(i / rows), r = i % rows, cx = x + c * (pw + GAP * sc) + (b.t === 'rj45' ? Math.floor(c / 4) * 2.5 * sc : 0), cy = oy + r * (ph + GAP * sc);
          s += `<rect x="${cx.toFixed(1)}" y="${cy.toFixed(1)}" width="${pw.toFixed(1)}" height="${ph.toFixed(1)}" rx="${b.t === 'rj45' ? 1 : 1.6}" fill="${pal.port}" stroke="${pal.portIn}" stroke-width=".5"/>`;
          if (b.t === 'rj45') s += `<rect x="${(cx + pw * 0.22).toFixed(1)}" y="${(cy + ph * 0.18).toFixed(1)}" width="${(pw * 0.56).toFixed(1)}" height="${(ph * 0.4).toFixed(1)}" fill="${pal.portIn}"/>`;
        }
        x += portW(b) * sc; return;
      }
      if (b.k === 'psu') { const pw = 86 * sc, ph = Math.min(ah, 36); for (let i = 0; i < b.n; i++) { const px = x + i * (pw + 4 * sc), py = ay + (ah - ph) / 2; s += `<rect x="${px.toFixed(1)}" y="${py.toFixed(1)}" width="${pw.toFixed(1)}" height="${ph}" rx="1.5" fill="${pal.port}" stroke="${pal.portIn}" stroke-width=".7"/><rect x="${(px + pw * 0.12).toFixed(1)}" y="${(py + ph * 0.32).toFixed(1)}" width="${(pw * 0.2).toFixed(1)}" height="${(ph * 0.36).toFixed(1)}" fill="${pal.portIn}"/><circle cx="${(px + pw * 0.8).toFixed(1)}" cy="${(py + ph / 2).toFixed(1)}" r="2" fill="${pal.led}" opacity=".8"/>`; } x += blockW(b) * sc; return; }
      if (b.k === 'fan') { const fd = Math.min(30, ah) * sc; for (let i = 0; i < b.n; i++) { const cx = x + i * 34 * sc + 17 * sc, cy = ay + ah / 2; s += `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="${(fd / 2).toFixed(1)}" fill="${pal.port}" stroke="${pal.portIn}" stroke-width=".7"/><circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="${(fd / 5).toFixed(1)}" fill="${pal.portIn}"/>`; } x += blockW(b) * sc; return; }
      if (b.k === 'out') { const q = Math.min(20, ah) * sc; for (let i = 0; i < b.n; i++) { const cx = x + i * 27 * sc; s += `<rect x="${cx.toFixed(1)}" y="${(ay + (ah - q) / 2).toFixed(1)}" width="${q.toFixed(1)}" height="${q.toFixed(1)}" rx="3" fill="${pal.port}" stroke="${pal.portIn}" stroke-width=".6"/>`; } x += blockW(b) * sc; return; }
    };
    fixed.forEach((b, i) => { place(b); x += BG * sc; });
    bays.forEach(place);
    return s;
  };

  /* A whole rack. Returns { svg (fragment), w, h, x0, topY }. opts: face, sel, ghost{u,h,ok}, pal, compact, gaps, title, pid, labels */
  RR.rackSVG = function (P, rackId, opts) {
    opts = opts || {}; const rack = RC.rack(P, rackId), pal = RR.pal(opts.pal), face = opts.face === 'rear' ? 'rear' : 'front', compact = !!opts.compact;
    const TITLE = opts.title ? 58 : 0, FW = RW + 2 * RAIL, FH = rack.u * UMM + 2 * FT, x0 = RAIL, topY = TITLE + FT, W = FW, H = FH + TITLE;
    const pid = (opts.pid || 'g') + rackId.replace(/[^\w]/g, ''); let s = '';
    s += `<defs><pattern id="${pid}" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="8" height="8" fill="${pal.hatch}" opacity=".08"/><line x1="0" y1="0" x2="0" y2="8" stroke="${pal.hatch}" stroke-width="2.4" opacity=".35"/></pattern></defs>`;
    if (opts.title) s += `<text x="0" y="22" font-family="Geist,Segoe UI,sans-serif" font-size="22" font-weight="700" fill="${pal.ink}">${esc(rack.label)}</text><text x="0" y="46" font-family="JetBrains Mono,Consolas,monospace" font-size="13" fill="${pal.sub}">${rack.u}U · ${rack.w} × ${rack.d} mm · ${face.toUpperCase()}</text>`;
    s += `<g data-rack="${esc(rack.id)}"><rect x="0" y="${TITLE}" width="${FW}" height="${FH}" rx="6" fill="${pal.frame}" stroke="${pal.edge}" stroke-width="1.2"/>`;
    s += `<rect x="${x0}" y="${topY}" width="${RW}" height="${rack.u * UMM}" fill="${pal.bg}"/>`;
    s += `<rect x="0" y="${topY}" width="${RAIL}" height="${rack.u * UMM}" fill="${pal.rail}"/><rect x="${x0 + RW}" y="${topY}" width="${RAIL}" height="${rack.u * UMM}" fill="${pal.rail}"/>`;
    for (let i = 0; i < rack.u; i++) {
      const y = topY + i * UMM, u = rack.numbering === 'top-down' ? i + 1 : rack.u - i;
      s += `<line x1="${x0}" y1="${y}" x2="${x0 + RW}" y2="${y}" stroke="${pal.hole}" stroke-width=".5" opacity=".7"/>`;
      if (!compact) s += `<text x="${RAIL / 2}" y="${y + UMM / 2 + 4}" text-anchor="middle" font-family="JetBrains Mono,Consolas,monospace" font-size="11" fill="${pal.num}">${u}</text><text x="${x0 + RW + RAIL / 2}" y="${y + UMM / 2 + 4}" text-anchor="middle" font-family="JetBrains Mono,Consolas,monospace" font-size="11" fill="${pal.num}">${u}</text>`;
    }
    if (opts.gaps) RC.freeRuns(P, rack, true).forEach(g => { const y = RR.slotTop(rack, g.u, g.h, topY); s += `<rect x="${x0}" y="${y}" width="${RW}" height="${g.h * UMM}" fill="url(#${pid})"/>`; });
    P.devices.filter(d => d.rackId === rack.id).forEach(d => {
      const m = RC.model(P, d.modelId), h = m.u; if (d.u < 1 || d.u + h - 1 > rack.u) return;
      const y = RR.slotTop(rack, d.u, h, topY), hh = h * UMM, sd = d.side || 'full', off = sd !== 'full' && sd !== face, fk = (face === 'front') !== !!d.rev ? 'front' : 'rear';
      const lab = opts.labels === false ? ' ' : (d.hostname || m.name);
      s += `<g data-dev="${esc(d.id)}" transform="translate(${x0},${y})"${off ? ' opacity=".28"' : ''}>`;
      s += RR.faceSVG(m, fk, RW, hh, pal, { label: lab, status: compact ? '' : d.status });
      if (sd !== 'full') s += `<text x="${RW - EAR - 6}" y="${hh - 5}" text-anchor="end" font-family="JetBrains Mono,monospace" font-size="6" fill="${pal.sub}">${sd === 'front' ? 'FRONT HALF' : 'REAR HALF'}</text>`;
      s += `</g>`;
    });
    if (opts.sel) { const d = RC.dev(P, opts.sel); if (d && d.rackId === rack.id) { const h = RC.h(P, d), y = RR.slotTop(rack, d.u, h, topY); s += `<rect x="${x0 - 2}" y="${y - 2}" width="${RW + 4}" height="${h * UMM + 4}" rx="2" fill="none" stroke="${pal.acc}" stroke-width="3" pointer-events="none"/>`; } }
    if (opts.ghost) { const g = opts.ghost, y = RR.slotTop(rack, g.u, g.h, topY), c = g.ok ? pal.acc : pal.bad; s += `<rect x="${x0}" y="${y}" width="${RW}" height="${g.h * UMM}" rx="2" fill="${c}" fill-opacity=".22" stroke="${c}" stroke-width="2.4" stroke-dasharray="8 5" pointer-events="none"/>`; }
    s += `</g>`;
    return { svg: s, w: W, h: H, x0, topY, rack };
  };

  /* Ready-to-use svg element, one rack (thumbnails) */
  RR.thumbSVG = function (P, pxH, palName) {
    const r = P.racks[0], o = RR.rackSVG(P, r.id, { compact: true, labels: false, pal: palName || 'dark', pid: 't' });
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${o.w} ${o.h}" height="${pxH}" preserveAspectRatio="xMidYMid meet">${o.svg}</svg>`;
  };

  /* Sheet for export: racks side by side. opts: ids[], faces ['front','rear'], pal, scale px per mm, footer */
  RR.sheetSVG = function (P, opts) {
    opts = opts || {}; const pal = RR.pal(opts.pal), ids = (opts.ids && opts.ids.length ? opts.ids : P.racks.map(r => r.id)), faces = opts.faces && opts.faces.length ? opts.faces : ['front'], sc = opts.scale || 0.9, G = 70, HEAD = 96, FOOT = 40;
    let x = 30, rowH = 0, parts = '', y = HEAD;
    faces.forEach((f, fi) => {
      x = 30; let h = 0;
      ids.forEach(id => { const o = RR.rackSVG(P, id, { face: f, pal: opts.pal, title: true, pid: 'e' + fi, gaps: opts.gaps, sel: null }); parts += `<g transform="translate(${x},${y})">${o.svg}</g>`; x += o.w + G; h = Math.max(h, o.h); });
      y += h + (fi < faces.length - 1 ? 50 : 0); rowH = Math.max(rowH, x);
    });
    const W = Math.max(rowH - G + 30, 700), H = y + FOOT, date = new Date().toISOString().slice(0, 10);
    const head = `<text x="30" y="44" font-family="Geist,Segoe UI,sans-serif" font-size="30" font-weight="700" fill="${pal.ink}">${esc(P.name)}</text><text x="30" y="72" font-family="JetBrains Mono,Consolas,monospace" font-size="14" fill="${pal.sub}">${esc(P.site ? P.site + ' · ' : '')}${P.racks.length} rack${P.racks.length === 1 ? '' : 's'} · ${P.devices.length} devices · ${date}</text>`;
    const foot = `<text x="30" y="${H - 14}" font-family="JetBrains Mono,Consolas,monospace" font-size="12" fill="${pal.sub}">ConfigLabs Rack Builder · configlabs.online · drawn to scale · values marked Typical are placeholders</text>`;
    const w = Math.round(W * sc), hh = Math.round(H * sc);
    return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${hh}" viewBox="0 0 ${W} ${H}"><rect width="${W}" height="${H}" fill="${pal.bg === '#ffffff' ? '#ffffff' : pal.bg}"/>${head}${parts}${foot}</svg>`;
  };
})();

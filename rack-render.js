/* ConfigLabs Rack Builder: SVG drawing at true scale (1 unit = 1 mm). Needs rack-lib.js and rack-calc.js. */
(function () {
  'use strict';
  const RK = window.RK, RC = window.RC, RR = window.RR = window.RR || {};
  const esc = s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  RR.esc = esc;
  const UMM = RK.UMM, RW = RK.RACKW, RAIL = 36, FT = 30, EAR = 14;

  RR.PAL = {
    dark: { bg: '#0b0e13', frame: '#1b212b', rail: '#252d3a', num: '#6f7d92', ink: '#e8edf5', sub: '#9aa7ba', edge: '#0a0c10', port: '#0a0d12', portIn: '#1d2430', led: '#7cf4c7', plan: '#f4c27c', acc: '#7cf4c7', bad: '#ff7a7a', warn: '#f4c27c', slot: '#10151c', hole: '#2c3646', hatch: '#ff7a7a', lok: '#2f7d5c', lwarn: '#b8872f', lbad: '#a93d3d', cold: '#4f9dff', hot: '#ff6b5e', crac: '#27566f',
      cat: { switch: '#2c3d57', router: '#3b3359', firewall: '#58302f', server: '#363b44', storage: '#30463a', patch: '#40454d', manager: '#2b2f36', blank: '#171a20', pdu: '#4d4025', ups: '#43391f', kvm: '#2c4750' } },
    light: { bg: '#ffffff', frame: '#d5dbe4', rail: '#bcc5d1', num: '#5d6b80', ink: '#101828', sub: '#4a5568', edge: '#7b8798', port: '#2a3340', portIn: '#566274', led: '#12a574', plan: '#c98a1c', acc: '#0a8f68', bad: '#d23b3b', warn: '#c98a1c', slot: '#eef1f6', hole: '#9aa6b6', hatch: '#d23b3b', lok: '#a9dcc3', lwarn: '#f2d28b', lbad: '#f0a3a3', cold: '#2f7fe0', hot: '#e0473a', crac: '#a9cfe2',
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

  /* ================= ROOM PLAN (2D) ================= */
  RR.rackLoad = function (P, rack, mode) {
    const st = RC.stats(P, rack), S = P.settings; let pct = null;
    if (mode === 'power') { const a = rack.pdus.A.cap, b = rack.pdus.B.cap, c = Math.max(st.feed.A / (a || Infinity), st.feed.B / (b || Infinity)); pct = isFinite(c) && (a || b) ? c * 100 : null; }
    else if (mode === 'fill') pct = st.pct; else if (mode === 'weight') pct = st.kg / rack.loadRating * 100;
    return { pct, st };
  };
  RR.loadColor = function (P, rack, mode, pal) {
    if (mode === 'plain' || !mode) return pal.cat.server; const l = RR.rackLoad(P, rack, mode).pct, S = P.settings; if (l == null) return pal.cat.server;
    const w = mode === 'power' ? S.warn : 90, c = mode === 'power' ? S.crit : 100; return l >= c ? pal.lbad : l >= w ? pal.lwarn : pal.lok;
  };
  /* opts: pal, color, sel {t,id}, clear, grid, title */
  RR.roomSVG = function (P, opts) {
    opts = opts || {}; const pal = RR.pal(opts.pal), R = P.room, S = P.settings, MG = 900, TOP = opts.title ? 700 : 0, W = R.w + 2 * MG, H = R.l + 2 * MG + TOP; let s = '';
    const sel = opts.sel || {}, mono = 'JetBrains Mono,Consolas,monospace';
    s += `<g transform="translate(${MG},${MG + TOP})"><rect x="0" y="0" width="${R.w}" height="${R.l}" fill="${pal.bg}"/>`;
    if (opts.grid !== false) { let g = ''; for (let x = 600; x < R.w; x += 600) g += `M${x} 0V${R.l}`; for (let y = 600; y < R.l; y += 600) g += `M0 ${y}H${R.w}`; s += `<path d="${g}" stroke="${pal.hole}" stroke-width="6" opacity=".45" fill="none"/>`; }
    RC.aisles(P).forEach(a => { const c = a.kind === 'cold' ? pal.cold : pal.hot; s += `<rect x="${a.x}" y="${a.y}" width="${a.w}" height="${a.h}" fill="${c}" opacity=".14"/><text x="${a.x + a.w / 2}" y="${a.y + a.h / 2 + 45}" text-anchor="middle" font-family="${mono}" font-size="110" fill="${c}" opacity=".8">${a.w > 900 || a.h > 900 ? (a.kind === 'cold' ? 'COLD AISLE' : 'HOT AISLE') : ''}</text>`; });
    s += `<rect x="-60" y="-60" width="${R.w + 120}" height="${R.l + 120}" fill="none" stroke="${pal.edge}" stroke-width="120"/>`;
    /* clearance zones */
    if (opts.clear) P.racks.map(RC.rackRect).filter(Boolean).forEach(A => {
      [[1, S.clearFront], [-1, S.clearRear]].forEach(z => { const f = RC.DIR[A.rot], dx = f[0] * z[0], dy = f[1] * z[0], L = z[1]; let r;
        if (dy !== 0) r = { x: A.x, w: A.w, y: dy > 0 ? A.y + A.h : A.y - L, h: L }; else r = { y: A.y, h: A.h, x: dx > 0 ? A.x + A.w : A.x - L, w: L };
        s += `<rect x="${r.x}" y="${r.y}" width="${r.w}" height="${r.h}" fill="${z[0] > 0 ? pal.acc : pal.warn}" fill-opacity=".07" stroke="${z[0] > 0 ? pal.acc : pal.warn}" stroke-width="10" stroke-dasharray="40 30" opacity=".8"/>`; });
    });
    /* objects */
    R.objs.forEach(o => {
      const r = RC.objRect(o), cx = r.x + r.w / 2, cy = r.y + r.h / 2, on = sel.t === 'obj' && sel.id === o.id; let g = `<g data-obj="${esc(o.id)}">`;
      if (o.type === 'door') { const f = RC.DIR[o.rot], L = Math.max(o.w, o.d); let hx, hy, ex, ey; /* hinge at one end, leaf open into the room */
        if (f[1] !== 0) { hx = r.x; hy = f[1] > 0 ? r.y + r.h : r.y; ex = r.x + r.w; ey = hy; g += `<path d="M${hx} ${hy}L${hx} ${hy + f[1] * L}A${L} ${L} 0 0 ${f[1] > 0 ? 0 : 1} ${ex} ${ey}" fill="${pal.acc}" fill-opacity=".08" stroke="${pal.sub}" stroke-width="12"/>`; }
        else { hx = f[0] > 0 ? r.x + r.w : r.x; hy = r.y; ex = hx; ey = r.y + r.h; g += `<path d="M${hx} ${hy}L${hx + f[0] * L} ${hy}A${L} ${L} 0 0 ${f[0] > 0 ? 1 : 0} ${ex} ${ey}" fill="${pal.acc}" fill-opacity=".08" stroke="${pal.sub}" stroke-width="12"/>`; }
        g += `<rect x="${r.x}" y="${r.y}" width="${r.w}" height="${r.h}" fill="${pal.bg}" stroke="${pal.sub}" stroke-width="14"/>`; }
      else if (o.type === 'text') g += `<text x="${r.x}" y="${r.y + r.h * 0.75}" font-family="Geist,Segoe UI,sans-serif" font-size="${Math.max(120, Math.min(r.h, 400))}" font-weight="600" fill="${pal.ink}">${esc(o.label || 'Label')}</text><rect x="${r.x}" y="${r.y}" width="${r.w}" height="${r.h}" fill="none" stroke="${on ? pal.acc : 'none'}" stroke-width="14" stroke-dasharray="40 30"/>`;
      else if (o.type === 'col') g += `<rect x="${r.x}" y="${r.y}" width="${r.w}" height="${r.h}" fill="${pal.edge}" stroke="${pal.sub}" stroke-width="12"/><path d="M${r.x} ${r.y}L${r.x + r.w} ${r.y + r.h}M${r.x + r.w} ${r.y}L${r.x} ${r.y + r.h}" stroke="${pal.sub}" stroke-width="10"/>`;
      else { const crac = o.type === 'crac'; g += `<rect x="${r.x}" y="${r.y}" width="${r.w}" height="${r.h}" rx="20" fill="${crac ? pal.crac : pal.cat.manager}" stroke="${pal.sub}" stroke-width="14"${crac ? '' : ' stroke-dasharray="50 30"'}/><text x="${cx}" y="${cy - 10}" text-anchor="middle" font-family="${mono}" font-size="150" font-weight="700" fill="${pal.ink}">${crac ? 'AC' : ''}${crac ? '' : esc((o.label || 'Equip.').slice(0, 14))}</text>${crac ? `<text x="${cx}" y="${cy + 160}" text-anchor="middle" font-family="${mono}" font-size="120" fill="${pal.ink}">${o.cap} kW</text>` : ''}`;
        if (crac && o.label) g += `<text x="${cx}" y="${r.y - 40}" text-anchor="middle" font-family="${mono}" font-size="110" fill="${pal.sub}">${esc(o.label.slice(0, 18))}</text>`; }
      if (on && o.type !== 'text') g += `<rect x="${r.x - 30}" y="${r.y - 30}" width="${r.w + 60}" height="${r.h + 60}" rx="30" fill="none" stroke="${pal.acc}" stroke-width="26" pointer-events="none"/>`;
      s += g + '</g>';
    });
    /* racks */
    P.racks.map(RC.rackRect).filter(Boolean).forEach(A => {
      const rk = A.rack, ld = RR.rackLoad(P, rk, opts.color), fill = RR.loadColor(P, rk, opts.color, pal), on = sel.t === 'rack' && sel.id === rk.id, f = RC.DIR[A.rot];
      let g = `<g data-rack="${esc(rk.id)}"><rect x="${A.x}" y="${A.y}" width="${A.w}" height="${A.h}" rx="14" fill="${fill}" stroke="${pal.edge}" stroke-width="14"/>`;
      /* front edge marker */
      const t = 56; let fx, fy, fw, fh; if (f[1] !== 0) { fx = A.x; fw = A.w; fh = t; fy = f[1] > 0 ? A.y + A.h - t : A.y; } else { fy = A.y; fh = A.h; fw = t; fx = f[0] > 0 ? A.x + A.w - t : A.x; }
      g += `<rect x="${fx}" y="${fy}" width="${fw}" height="${fh}" fill="${pal.acc}"/>`;
      const fs = Math.max(60, Math.min(130, Math.min(A.w, A.h) / 6)), mc = Math.max(3, Math.floor((A.w - 40) / (fs * 0.6))), nl = rk.label.length > mc ? rk.label.slice(0, mc - 1) + '…' : rk.label, cx = A.x + A.w / 2, cy = A.y + A.h / 2, kw = ld.st.watts / 1000;
      g += `<text x="${cx}" y="${cy - 10}" text-anchor="middle" font-family="Geist,Segoe UI,sans-serif" font-size="${fs}" font-weight="700" fill="${pal.ink}">${esc(nl)}</text><text x="${cx}" y="${cy + fs * 0.95}" text-anchor="middle" font-family="${mono}" font-size="${fs * 0.62}" fill="${pal.ink}" opacity=".85">${rk.u}U ${kw.toFixed(1)}kW</text>`;
      if (opts.color && opts.color !== 'plain' && ld.pct != null) g += `<text x="${cx}" y="${cy + fs * 1.85}" text-anchor="middle" font-family="${mono}" font-size="${fs * 0.62}" font-weight="700" fill="${pal.ink}">${Math.round(ld.pct)}%</text>`;
      if (on) g += `<rect x="${A.x - 30}" y="${A.y - 30}" width="${A.w + 60}" height="${A.h + 60}" rx="30" fill="none" stroke="${pal.acc}" stroke-width="26" pointer-events="none"/>`;
      s += g + '</g>';
    });
    /* dimensions */
    s += `<text x="${R.w / 2}" y="-210" text-anchor="middle" font-family="${mono}" font-size="170" fill="${pal.sub}">${R.w} mm</text><text transform="translate(-230 ${R.l / 2}) rotate(-90)" text-anchor="middle" font-family="${mono}" font-size="170" fill="${pal.sub}">${R.l} mm</text>`;
    s += `<g id="rgh" pointer-events="none"></g></g>`;
    if (opts.title) s += `<text x="${MG}" y="330" font-family="Geist,Segoe UI,sans-serif" font-size="300" font-weight="700" fill="${pal.ink}">${esc(P.name)}</text><text x="${MG}" y="560" font-family="${mono}" font-size="150" fill="${pal.sub}">${esc(P.site ? P.site + ' · ' : '')}Room plan ${R.w} × ${R.l} mm · ${P.racks.filter(r => r.x != null).length} of ${P.racks.length} racks placed</text>`;
    return { svg: s, w: W, h: H, ox: MG, oy: MG + TOP };
  };
  RR.planSheetSVG = function (P, opts) {
    opts = opts || {}; const pal = RR.pal(opts.pal), o = RR.roomSVG(P, { pal: opts.pal, color: opts.color, clear: opts.clear, title: true }), sc = (opts.scale || 0.09), w = Math.round(o.w * sc), h = Math.round(o.h * sc + 30);
    const leg = `<text x="900" y="${o.h + 330}" font-family="JetBrains Mono,Consolas,monospace" font-size="130" fill="${pal.sub}">Green edge = rack front · blue = cold aisle · red = hot aisle · grid 600 mm · ConfigLabs Rack Builder</text>`;
    return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${Math.round((o.h + 450) * sc)}" viewBox="0 0 ${o.w} ${o.h + 450}"><rect width="${o.w}" height="${o.h + 450}" fill="${pal.bg}"/>${o.svg}${leg}</svg>`;
  };

  /* ================= ROOM 3D (own projection, no libraries) ================= */
  const hexRGB = h => { h = String(h).replace('#', ''); if (h.length === 3) h = h.replace(/./g, '$&$&'); return [parseInt(h.slice(0, 2), 16) || 0, parseInt(h.slice(2, 4), 16) || 0, parseInt(h.slice(4, 6), 16) || 0]; };
  const shade = (hex, f) => { const c = hexRGB(hex).map(v => Math.max(0, Math.min(255, Math.round(v * f)))); return 'rgb(' + c.join(',') + ')'; };
  /* opts: pal, yaw, pitch (degrees), zoom, w, h (px), color, sel */
  RR.room3D = function (P, opts) {
    opts = opts || {}; const pal = RR.pal(opts.pal), R = P.room, W = opts.w || 900, H = opts.h || 600, yaw = (opts.yaw == null ? -35 : opts.yaw) * Math.PI / 180, pit = Math.max(8, Math.min(90, opts.pitch == null ? 42 : opts.pitch)) * Math.PI / 180;
    const cy0 = R.w / 2, cy1 = R.l / 2, cosY = Math.cos(yaw), sinY = Math.sin(yaw), cosP = Math.cos(pit), sinP = Math.sin(pit), k = (opts.zoom || 1) * Math.min(W, H) * 0.9 / Math.hypot(R.w, R.l), zc = R.h * 0.35;
    const rot = (x, y) => [(x - cy0) * cosY - (y - cy1) * sinY, (x - cy0) * sinY + (y - cy1) * cosY];
    const pr = (x, y, z) => { const r = rot(x, y); return [W / 2 + r[0] * k, H * 0.52 + (r[1] * sinP - (z - zc) * cosP) * k]; };
    const vis = (nx, ny, nz) => { const r = nx * cosY - ny * sinY, q = nx * sinY + ny * cosY; return q * cosP + nz * sinP > 0.001; };
    const poly = (pts, fill, extra) => `<polygon points="${pts.map(p => p.map(v => v.toFixed(1)).join(',')).join(' ')}" fill="${fill}" ${extra || 'stroke="' + pal.edge + '" stroke-width="0.8" stroke-linejoin="round"'}/>`;
    let s = `<rect width="${W}" height="${H}" fill="${pal.bg}"/>`;
    /* floor + grid */
    s += poly([pr(0, 0, 0), pr(R.w, 0, 0), pr(R.w, R.l, 0), pr(0, R.l, 0)], pal.slot, `stroke="${pal.edge}" stroke-width="1.2"`);
    const step = Math.max(600, Math.ceil(Math.max(R.w, R.l) / 24 / 600) * 600); let gl = ''; for (let x = step; x < R.w; x += step) { const a = pr(x, 0, 0), b = pr(x, R.l, 0); gl += `M${a[0].toFixed(1)} ${a[1].toFixed(1)}L${b[0].toFixed(1)} ${b[1].toFixed(1)}`; } for (let y = step; y < R.l; y += step) { const a = pr(0, y, 0), b = pr(R.w, y, 0); gl += `M${a[0].toFixed(1)} ${a[1].toFixed(1)}L${b[0].toFixed(1)} ${b[1].toFixed(1)}`; }
    s += `<path d="${gl}" stroke="${pal.hole}" stroke-width=".6" opacity=".6" fill="none"/>`;
    RC.aisles(P).forEach(a => { s += poly([pr(a.x, a.y, 1), pr(a.x + a.w, a.y, 1), pr(a.x + a.w, a.y + a.h, 1), pr(a.x, a.y + a.h, 1)], a.kind === 'cold' ? pal.cold : pal.hot, 'opacity=".22"'); });
    /* back walls: outward normal faces away from camera */
    [[0, 0, R.w, 0, 0, -1], [R.w, 0, R.w, R.l, 1, 0], [R.w, R.l, 0, R.l, 0, 1], [0, R.l, 0, 0, -1, 0]].forEach(w => { if (!vis(w[4], w[5], 0)) s += poly([pr(w[0], w[1], 0), pr(w[2], w[3], 0), pr(w[2], w[3], R.h), pr(w[0], w[1], R.h)], pal.frame, `opacity=".42" stroke="${pal.edge}" stroke-width="1"`); });
    /* boxes */
    const items = [];
    P.racks.map(RC.rackRect).filter(Boolean).forEach(A => items.push({ r: A, z: A.rack.u * RK.UMM + 120, c: RR.loadColor(P, A.rack, opts.color, pal), rack: A.rack }));
    R.objs.forEach(o => { const r = RC.objRect(o); if (o.type === 'text') return; items.push({ r, z: o.type === 'door' ? 8 : o.type === 'col' ? R.h : o.type === 'crac' ? 1900 : 1800, c: o.type === 'door' ? pal.sub : o.type === 'crac' ? pal.crac : o.type === 'col' ? pal.rail : pal.cat.manager, obj: o }); });
    items.forEach(it => { const c = rot(it.r.x + it.r.w / 2, it.r.y + it.r.h / 2); it.d = c[1]; }); items.sort((a, b) => a.d - b.d);
    const sel = opts.sel || {};
    items.forEach(it => {
      const r = it.r, x0 = r.x, x1 = r.x + r.w, y0 = r.y, y1 = r.y + r.h, z = it.z, id = it.rack ? it.rack.id : it.obj.id, on = (sel.t === 'rack' && it.rack && sel.id === id) || (sel.t === 'obj' && it.obj && sel.id === id);
      const faces = [[[0, 0, 1], [[x0, y0, z], [x1, y0, z], [x1, y1, z], [x0, y1, z]]], [[0, -1, 0], [[x0, y0, 0], [x1, y0, 0], [x1, y0, z], [x0, y0, z]]], [[1, 0, 0], [[x1, y0, 0], [x1, y1, 0], [x1, y1, z], [x1, y0, z]]], [[0, 1, 0], [[x1, y1, 0], [x0, y1, 0], [x0, y1, z], [x1, y1, z]]], [[-1, 0, 0], [[x0, y1, 0], [x0, y0, 0], [x0, y0, z], [x0, y1, z]]]];
      let g = `<g ${it.rack ? 'data-rack' : 'data-obj'}="${esc(id)}">`; const f = it.rack ? RC.DIR[r.rot] : null;
      faces.forEach(fc => { const n = fc[0]; if (!vis(n[0], n[1], n[2])) return; const rx = n[0] * cosY - n[1] * sinY, ry = n[0] * sinY + n[1] * cosY, sh = n[2] ? 1.05 : 0.6 + 0.22 * (rx + 1) / 2 + 0.18 * Math.max(0, ry); const front = f && n[0] === f[0] && n[1] === f[1];
        g += poly(fc[1].map(p => pr(p[0], p[1], p[2])), shade(it.c, front ? sh * 1.25 : sh)); if (front && z > 300) { for (let i = 1; i < 6; i++) { const t = i / 6, a = fc[1][0], b = fc[1][1], p0 = [a[0] + (fc[1][3][0] - a[0]) * 0, 0]; const A0 = fc[1][0], B0 = fc[1][1], A1 = fc[1][3], B1 = fc[1][2]; const pa = pr(A0[0] + (A1[0] - A0[0]) * t, A0[1] + (A1[1] - A0[1]) * t, A0[2] + (A1[2] - A0[2]) * t), pb = pr(B0[0] + (B1[0] - B0[0]) * t, B0[1] + (B1[1] - B0[1]) * t, B0[2] + (B1[2] - B0[2]) * t); g += `<line x1="${pa[0].toFixed(1)}" y1="${pa[1].toFixed(1)}" x2="${pb[0].toFixed(1)}" y2="${pb[1].toFixed(1)}" stroke="${pal.edge}" stroke-width=".5" opacity=".55"/>`; } } });
      if (on) { const top = [pr(x0, y0, z), pr(x1, y0, z), pr(x1, y1, z), pr(x0, y1, z)]; g += poly(top, 'none', `stroke="${pal.acc}" stroke-width="2.6"`); }
      if (it.rack || (it.obj && it.obj.type === 'crac')) { const c = pr(r.x + r.w / 2, r.y + r.h / 2, z), lab = it.rack ? it.rack.label : 'AC ' + it.obj.cap + ' kW'; g += `<text x="${c[0].toFixed(1)}" y="${(c[1] + 3).toFixed(1)}" text-anchor="middle" font-family="Geist,Segoe UI,sans-serif" font-size="${Math.max(9, Math.min(13, r.w * k * 0.2))}" font-weight="700" fill="${pal.ink}" stroke="${pal.bg}" stroke-width="2.6" paint-order="stroke" pointer-events="none">${esc(lab.slice(0, 14))}</text>`; }
      s += g + '</g>';
    });
    return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" id="r3d">${s}</svg>`;
  };
})();

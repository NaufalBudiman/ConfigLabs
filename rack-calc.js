/* ConfigLabs Rack Builder: project model, validation and calculations (no DOM). Needs rack-lib.js first. */
(function () {
  'use strict';
  const RK = window.RK, RC = window.RC = window.RC || {};
  const num = (v, d, lo, hi) => { v = parseFloat(v); if (!isFinite(v)) v = d; return Math.min(hi, Math.max(lo, v)); };
  const str = (v, n) => String(v == null ? '' : v).replace(/[\u0000-\u001f]/g, ' ').slice(0, n);
  const idOk = v => /^[\w.\-]{1,60}$/.test(String(v || '')) ? String(v) : '';
  const oneOf = (v, a, d) => a.indexOf(v) >= 0 ? v : d;
  const ipv4 = s => { const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(String(s || '').trim()); return !!m && m.slice(1).every(x => +x <= 255); };
  RC.ipv4 = ipv4;
  let seq = 0;
  RC.uid = p => (p || 'x') + Date.now().toString(36) + (seq++).toString(36) + Math.random().toString(36).slice(2, 5);

  /* ---------- defaults ---------- */
  RC.defaults = () => ({ units: 'metric', powerBasis: 'max', warn: 80, crit: 100, floorRating: 1220, clearFront: 1200, clearRear: 900 });
  RC.defaultRoom = () => ({ w: 8000, l: 6000, h: 3000, objs: [] });
  RC.OBJ = { door: 'Door', crac: 'Cooling unit', col: 'Column', box: 'Other equipment', text: 'Label' };
  RC.OBJ_DEF = { door: { w: 900, d: 120 }, crac: { w: 900, d: 900 }, col: { w: 400, d: 400 }, box: { w: 800, d: 800 }, text: { w: 1200, d: 300 } };
  RC.newRack = function (label, u) {
    return { id: RC.uid('r'), label: str(label || 'Rack 1', 40), u: u || 42, w: 600, d: 1000, numbering: 'bottom-up', frame: 'cabinet', x: null, y: null, rot: 0, emptyKg: 90, loadRating: 1000, pdus: { A: { cap: 7360 }, B: { cap: 7360 } } };
  };
  RC.newProject = function (name) {
    const r = RC.newRack('Rack 1', 42);
    return { schemaVersion: RK.SCHEMA, id: RC.uid('p'), name: str(name || 'Untitled rack project', 80), site: '', settings: RC.defaults(), room: RC.defaultRoom(), racks: [r], devices: [], models: {}, ack: {} };
  };

  /* ---------- sanitiser: every loaded or imported project goes through here ---------- */
  RC.cleanProject = function (raw) {
    if (!raw || typeof raw !== 'object') return null;
    const s = raw.settings || {}, d = RC.defaults();
    const P = { schemaVersion: RK.SCHEMA, id: idOk(raw.id) || RC.uid('p'), name: str(raw.name, 80) || 'Untitled rack project', site: str(raw.site, 80),
      settings: { units: oneOf(s.units, ['metric', 'imperial'], d.units), powerBasis: oneOf(s.powerBasis, ['max', 'typ'], d.powerBasis), warn: num(s.warn, d.warn, 10, 100), crit: num(s.crit, d.crit, 10, 150),
        floorRating: num(s.floorRating, d.floorRating, 100, 20000), clearFront: num(s.clearFront, d.clearFront, 0, 5000), clearRear: num(s.clearRear, d.clearRear, 0, 5000) },
      room: RC.defaultRoom(), racks: [], devices: [], models: {}, ack: {} };
    if (P.settings.warn > P.settings.crit) P.settings.warn = P.settings.crit;
    const rids = {};
    (Array.isArray(raw.racks) ? raw.racks : []).slice(0, 40).forEach(r => {
      if (!r || typeof r !== 'object') return; let id = idOk(r.id); if (!id || rids[id]) id = RC.uid('r'); rids[id] = 1;
      const pd = r.pdus || {}, pc = k => ({ cap: num(pd[k] && pd[k].cap, 0, 0, 100000) });
      P.racks.push({ id, label: str(r.label, 40) || 'Rack', u: num(r.u, 42, 1, 60) | 0, w: oneOf(+r.w, [482, 600, 700, 750, 800], 600), d: num(r.d, 1000, 300, 2000), numbering: oneOf(r.numbering, ['bottom-up', 'top-down'], 'bottom-up'),
        frame: oneOf(r.frame, ['cabinet', 'open', 'wall'], 'cabinet'), x: r.x == null || r.x === '' ? null : num(r.x, 0, -1e5, 1e5), y: r.y == null || r.y === '' ? null : num(r.y, 0, -1e5, 1e5), rot: oneOf(+r.rot, [0, 90, 180, 270], 0), emptyKg: num(r.emptyKg, 90, 0, 1000), loadRating: num(r.loadRating, 1000, 10, 5000), pdus: { A: pc('A'), B: pc('B') } });
    });
    if (!P.racks.length) P.racks.push(RC.newRack('Rack 1', 42));
    P.racks.forEach(r => { if (r.x == null || r.y == null) { r.x = null; r.y = null; } });
    const rm0 = raw.room && typeof raw.room === 'object' ? raw.room : {};
    P.room = { w: num(rm0.w, 8000, 1500, 60000), l: num(rm0.l, 6000, 1500, 60000), h: num(rm0.h, 3000, 2000, 10000), objs: [] };
    const oids = {};
    (Array.isArray(rm0.objs) ? rm0.objs : []).slice(0, 300).forEach(o => {
      if (!o || typeof o !== 'object' || !RC.OBJ[o.type]) return; let id = idOk(o.id); if (!id || oids[id]) id = RC.uid('o'); oids[id] = 1;
      P.room.objs.push({ id, type: o.type, x: num(o.x, 0, -1e5, 1e5), y: num(o.y, 0, -1e5, 1e5), w: num(o.w, RC.OBJ_DEF[o.type].w, 50, 20000), d: num(o.d, RC.OBJ_DEF[o.type].d, 50, 20000), rot: oneOf(+o.rot, [0, 90, 180, 270], 0), label: str(o.label, 60), cap: num(o.cap, 0, 0, 5000) });
    });
    const rm = {}; P.racks.forEach(r => rm[r.id] = r);
    const mids = {};
    if (raw.models && typeof raw.models === 'object') Object.keys(raw.models).slice(0, 200).forEach(k => { const m = RK.cleanModel(raw.models[k]); if (m && m.id === k) { delete m.custom; P.models[k] = m; } });
    const dids = {};
    (Array.isArray(raw.devices) ? raw.devices : []).slice(0, 2000).forEach(v => {
      if (!v || typeof v !== 'object') return; let id = idOk(v.id); if (!id || dids[id]) id = RC.uid('d'); const rid = String(v.rackId || ''); if (!rm[rid]) return;
      const mid = idOk(v.modelId); if (!mid) return; dids[id] = 1;
      const feeds = (Array.isArray(v.feeds) ? v.feeds : []).filter((x, i, a) => (x === 'A' || x === 'B') && a.indexOf(x) === i);
      const o = { id, rackId: rid, modelId: mid, u: num(v.u, 1, 1, 60) | 0, side: oneOf(v.side, ['full', 'front', 'rear'], 'full'), rev: !!v.rev, hostname: str(v.hostname, 63), role: str(v.role, 40),
        ips: (Array.isArray(v.ips) ? v.ips : []).slice(0, 8).map(x => str(x, 45).trim()).filter(Boolean), mgmtIp: str(v.mgmtIp, 45).trim(), vlan: str(v.vlan, 40), serial: str(v.serial, 60), asset: str(v.asset, 60),
        status: oneOf(v.status, ['planned', 'installed'], 'planned'), feeds, notes: str(v.notes, 500) };
      if (v.watts != null && v.watts !== '') o.watts = num(v.watts, 0, 0, 30000);
      if (v.kg != null && v.kg !== '') o.kg = num(v.kg, 0, 0, 500);
      P.devices.push(o);
    });
    if (raw.ack && typeof raw.ack === 'object') Object.keys(raw.ack).slice(0, 500).forEach(k => { if (/^[\w.\-:]{1,140}$/.test(k) && raw.ack[k]) P.ack[k] = 1; });
    return P;
  };

  /* ---------- lookups and numbers ---------- */
  RC.model = (P, id) => RK.find(id, P) || { id, name: 'Unknown model (' + id + ')', vendor: '', cat: 'server', u: 1, d: 450, kg: 0, w: { typ: null, max: 0 }, air: 'unk', psu: 1, ver: 'typical', missing: true };
  RC.rack = (P, id) => P.racks.find(r => r.id === id);
  RC.dev = (P, id) => P.devices.find(d => d.id === id);
  RC.h = (P, dev) => RC.model(P, dev.modelId).u;
  RC.top = (P, dev) => dev.u + RC.h(P, dev) - 1;
  RC.watts = function (P, dev) {
    if (dev.watts != null) return dev.watts; const m = RC.model(P, dev.modelId);
    return P.settings.powerBasis === 'typ' ? (m.w.typ != null ? m.w.typ : m.w.max) : m.w.max;
  };
  RC.kg = (P, dev) => dev.kg != null ? dev.kg : RC.model(P, dev.modelId).kg;
  RC.devsOf = (P, rackId) => P.devices.filter(d => d.rackId === rackId);
  RC.overlap = (a, b) => a === 'full' || b === 'full' || a === b;
  /* first device that would collide with a placement (excluding one id), or null */
  RC.collides = function (P, rackId, ex, u, h, side) {
    return RC.devsOf(P, rackId).find(d => d.id !== ex && RC.overlap(d.side, side || 'full') && d.u <= u + h - 1 && u <= RC.top(P, d)) || null;
  };
  RC.fits = (P, rack, u, h) => u >= 1 && u + h - 1 <= rack.u;
  /* nearest free slot for h starting at a wanted u (searches outward) */
  RC.nearestFree = function (P, rack, ex, want, h, side) {
    for (let k = 0; k <= rack.u; k++) for (const u of (k ? [want - k, want + k] : [want])) if (RC.fits(P, rack, u, h) && !RC.collides(P, rack.id, ex, u, h, side)) return u;
    return null;
  };
  /* free runs inside the used span (internal gaps) and all free runs */
  RC.freeRuns = function (P, rack, internalOnly) {
    const used = new Array(rack.u + 2).fill(false); RC.devsOf(P, rack.id).forEach(d => { for (let i = d.u; i <= RC.top(P, d); i++) if (i >= 1 && i <= rack.u) used[i] = true; });
    let lo = 1, hi = rack.u; if (internalOnly) { lo = used.indexOf(true); hi = used.lastIndexOf(true); if (lo < 0) return []; }
    const runs = []; let s = 0; for (let i = lo; i <= hi + 1; i++) { if (i <= hi && !used[i]) { if (!s) s = i; } else if (s) { runs.push({ u: s, h: i - s }); s = 0; } } return runs;
  };
  RC.stats = function (P, rack) {
    const ds = RC.devsOf(P, rack.id), used = new Array(rack.u + 2).fill(false); let w = { A: 0, B: 0, none: 0 }, kg = rack.emptyKg, total = 0, solo = { A: 0, B: 0 }, dual = 0;
    ds.forEach(d => {
      for (let i = d.u; i <= RC.top(P, d); i++) if (i >= 1 && i <= rack.u) used[i] = true;
      const x = RC.watts(P, d), f = d.feeds; total += x; kg += RC.kg(P, d);
      if (f.length === 2) { w.A += x / 2; w.B += x / 2; dual += x; } else if (f.length === 1) { w[f[0]] += x; solo[f[0]] += x; } else w.none += x;
    });
    const usedU = used.filter(Boolean).length;
    return { usedU, freeU: rack.u - usedU, pct: Math.round(usedU / rack.u * 100), watts: total, feed: w, solo, dual, kg, devices: ds.length, footprint: rack.w / 1000 * rack.d / 1000 };
  };

  /* ---------- validation ---------- */
  RC.RULES = { collision: 'Overlap', range: 'Out of rack', gap: 'Open gap', host: 'Duplicate hostname', ipdup: 'IP conflict', ipbad: 'Invalid IP', pwr: 'Power', redund: 'Feed redundancy', single: 'Single-fed', nofeed: 'No feed', weight: 'Rack weight', floor: 'Floor loading', depth: 'Depth', missing: 'Unknown model', rwall: 'Outside room', rhit: 'Overlap (room)', rclear: 'Clearance', rair: 'Airflow', rdoor: 'Door', rcool: 'Cooling', runpl: 'Not placed' };
  RC.validate = function (P) {
    const out = [], S = P.settings;
    const add = (rule, sev, rackId, devId, msg, objId) => { const key = rule + ':' + (objId || devId || rackId); out.push({ key, rule, sev, rackId, devId: devId || null, objId: objId || null, msg, ack: !!P.ack[key] }); };
    const hosts = {}, ips = {};
    P.racks.forEach(rack => {
      const ds = RC.devsOf(P, rack.id), name = rack.label;
      ds.forEach(d => {
        const m = RC.model(P, d.modelId), h = m.u, lab = (d.hostname || m.name);
        if (m.missing) add('missing', 'warn', rack.id, d.id, lab + ': model is not in the library. Using placeholder values.');
        if (d.u < 1 || d.u + h - 1 > rack.u) add('range', 'crit', rack.id, d.id, lab + ' does not fit inside ' + name + ' (' + rack.u + 'U).');
        const o = ds.find(e => e.id < d.id && RC.overlap(e.side, d.side) && e.u <= d.u + h - 1 && d.u <= RC.top(P, e));
        if (o) add('collision', 'crit', rack.id, d.id, lab + ' overlaps ' + (o.hostname || RC.model(P, o.modelId).name) + ' in ' + name + '.');
        if (m.d > rack.d - 50 && m.cat !== 'blank') add('depth', m.d > rack.d ? 'crit' : 'warn', rack.id, d.id, lab + ' is ' + m.d + ' mm deep in a ' + rack.d + ' mm rack' + (m.d > rack.d ? ': it will not close.' : ': little room for cables and PDUs.'));
        if (d.hostname) { const k = d.hostname.toLowerCase(); (hosts[k] = hosts[k] || []).push(d); }
        [d.mgmtIp].concat(d.ips).filter(Boolean).forEach(ip => { if (!ipv4(ip)) add('ipbad', 'warn', rack.id, d.id, lab + ': "' + ip + '" is not a valid IPv4 address.'); else (ips[ip] = ips[ip] || []).push(d); });
        const w = RC.watts(P, d);
        if (w > 0 && m.psu >= 2 && d.feeds.length === 1) add('single', 'warn', rack.id, d.id, lab + ' has ' + m.psu + ' power supplies but is wired to feed ' + d.feeds[0] + ' only.');
        if (w > 0 && !d.feeds.length && (rack.pdus.A.cap || rack.pdus.B.cap)) add('nofeed', 'info', rack.id, d.id, lab + ' is not assigned to a PDU feed, so its ' + Math.round(w) + ' W is not in the feed totals.');
      });
      /* gaps */
      RC.freeRuns(P, rack, true).forEach(g => add('gap', 'info', rack.id, null, 'U' + g.u + (g.h > 1 ? '–U' + (g.u + g.h - 1) : '') + ' in ' + name + ' is open between equipment: fit a blanking panel to stop hot air recirculating.'));
      /* power */
      const st = RC.stats(P, rack);
      ['A', 'B'].forEach(f => {
        const cap = rack.pdus[f].cap, l = st.feed[f]; if (!cap) { if (l > 0) add('pwr', 'crit', rack.id, null, name + ': ' + Math.round(l) + ' W is assigned to feed ' + f + ' but that feed has no capacity set.'); return; }
        const pct = l / cap * 100;
        if (pct >= S.crit) add('pwr', 'crit', rack.id, null, name + ' feed ' + f + ' is at ' + Math.round(pct) + '% (' + Math.round(l) + ' of ' + cap + ' W).');
        else if (pct >= S.warn) add('pwr', 'warn', rack.id, null, name + ' feed ' + f + ' is at ' + Math.round(pct) + '% (' + Math.round(l) + ' of ' + cap + ' W), above the ' + S.warn + '% planning limit.');
      });
      if (rack.pdus.A.cap && rack.pdus.B.cap) {
        const la = st.solo.A + st.dual, lb = st.solo.B + st.dual;
        if (lb > 0 || la > 0) {
          if (la > rack.pdus.A.cap) add('redund', 'warn', rack.id, null, name + ': if feed B fails, feed A carries ' + Math.round(la) + ' W against ' + rack.pdus.A.cap + ' W capacity.');
          if (lb > rack.pdus.B.cap) add('redund', 'warn', rack.id, null, name + ': if feed A fails, feed B carries ' + Math.round(lb) + ' W against ' + rack.pdus.B.cap + ' W capacity.');
        }
      }
      /* weight */
      if (st.kg > rack.loadRating) add('weight', 'crit', rack.id, null, name + ' weighs ' + Math.round(st.kg) + ' kg against a ' + rack.loadRating + ' kg load rating.');
      else if (st.kg > rack.loadRating * 0.9) add('weight', 'warn', rack.id, null, name + ' weighs ' + Math.round(st.kg) + ' kg, over 90% of its ' + rack.loadRating + ' kg load rating.');
      const fl = st.kg / st.footprint;
      if (fl > S.floorRating) add('floor', 'warn', rack.id, null, name + ' puts ' + Math.round(fl) + ' kg/m² on the floor, above the ' + S.floorRating + ' kg/m² rating you set.');
    });
    Object.keys(hosts).forEach(k => { const a = hosts[k]; if (a.length > 1) a.forEach(d => add('host', 'warn', d.rackId, d.id, 'Hostname "' + d.hostname + '" is used ' + a.length + ' times in this project.')); });
    Object.keys(ips).forEach(k => { const a = ips[k]; if (a.length > 1) a.forEach(d => add('ipdup', 'crit', d.rackId, d.id, 'IP ' + k + ' is used by ' + a.length + ' devices.')); });
    RC.validateRoom(P, add);
    const ord = { crit: 0, warn: 1, info: 2 }; out.sort((a, b) => ord[a.sev] - ord[b.sev]);
    return out;
  };


  /* ---------- room plan geometry (all mm; x east, y south; rot = direction the rack front faces: 0 south, 90 west, 180 north, 270 east) ---------- */
  RC.DIR = { 0: [0, 1], 90: [-1, 0], 180: [0, -1], 270: [1, 0] };
  const swapRot = r => r === 90 || r === 270;
  RC.rackRect = function (rack) { if (rack.x == null) return null; const sw = swapRot(rack.rot); return { kind: 'rack', id: rack.id, solid: true, x: rack.x, y: rack.y, w: sw ? rack.d : rack.w, h: sw ? rack.w : rack.d, rot: rack.rot, rack }; };
  RC.objRect = function (o) { const sw = swapRot(o.rot); return { kind: 'obj', id: o.id, type: o.type, solid: o.type !== 'door' && o.type !== 'text', x: o.x, y: o.y, w: sw ? o.d : o.w, h: sw ? o.w : o.d, rot: o.rot, obj: o }; };
  RC.rects = P => P.racks.map(RC.rackRect).filter(Boolean).concat(P.room.objs.map(RC.objRect));
  const hit = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
  RC.hit = hit;
  /* free distance from an item's edge to the nearest solid thing (or wall) in direction (dx,dy) */
  RC.gap = function (P, R, dx, dy) {
    let best = dx > 0 ? P.room.w - (R.x + R.w) : dx < 0 ? R.x : dy > 0 ? P.room.l - (R.y + R.h) : R.y, who = null;
    RC.rects(P).forEach(o => {
      if (o.id === R.id || !o.solid) return; let g = null;
      if (dy !== 0) { if (o.x < R.x + R.w && o.x + o.w > R.x) g = dy > 0 ? o.y - (R.y + R.h) : R.y - (o.y + o.h); }
      else if (o.y < R.y + R.h && o.y + o.h > R.y) g = dx > 0 ? o.x - (R.x + R.w) : R.x - (o.x + o.w);
      if (g != null && g >= -1 && g < best) { best = g; who = o; }
    });
    return { gap: Math.max(0, best), who };
  };
  RC.firstFree = function (P, w, h, step) {
    step = step || 300; const rects = RC.rects(P), M = Math.ceil(900 / step) * step, G = step;
    for (let y = M; y + h <= P.room.l - M + 1; y += step) for (let x = M; x + w <= P.room.w - M + 1; x += step) { const r = { x: x - G, y: y - G, w: w + 2 * G, h: h + 2 * G }; if (!rects.some(o => o.solid && hit(r, o))) return { x, y }; }
    for (let y = 0; y + h <= P.room.l; y += step) for (let x = 0; x + w <= P.room.w; x += step) { const r = { x, y, w, h }; if (!rects.some(o => o.solid && hit(r, o))) return { x, y }; }
    return null;
  };
  /* cold aisles (fronts facing) and hot aisles (backs facing) as rectangles for the plan */
  RC.aisles = function (P) {
    const out = [], seen = {};
    P.racks.map(RC.rackRect).filter(Boolean).forEach(A => {
      [1, -1].forEach(sgn => {
        const f = RC.DIR[A.rot], dx = f[0] * sgn, dy = f[1] * sgn, g = RC.gap(P, A, dx, dy), B = g.who; if (!B || B.kind !== 'rack' || g.gap > 3000 || g.gap < 1) return;
        const fb = RC.DIR[B.rot]; if (fb[0] !== -f[0] || fb[1] !== -f[1]) return; const key = [A.id, B.id].sort().join('|'); if (seen[key]) return; seen[key] = 1;
        let r; if (dy !== 0) { const x0 = Math.max(A.x, B.x), x1 = Math.min(A.x + A.w, B.x + B.w); r = { x: x0, y: dy > 0 ? A.y + A.h : B.y + B.h, w: x1 - x0, h: g.gap }; }
        else { const y0 = Math.max(A.y, B.y), y1 = Math.min(A.y + A.h, B.y + B.h); r = { y: y0, x: dx > 0 ? A.x + A.w : B.x + B.w, h: y1 - y0, w: g.gap }; }
        r.kind = sgn === 1 ? 'cold' : 'hot'; out.push(r);
      });
    });
    return out;
  };
  /* arrange all racks in paired rows: fronts face each other (cold aisle), backs face the next pair (hot aisle) */
  RC.autoLayout = function (P) {
    const s = P.settings, room = P.room, T = 600, up = v => Math.ceil(v / T) * T, M = 1200, rd = Math.max(...P.racks.map(r => r.d)), aisleF = up(rd + s.clearFront);
    let x = M, y = M, endY = 0, maxX = 0;
    const pairs = []; for (let i = 0; i < P.racks.length; i += 2) pairs.push([P.racks[i], P.racks[i + 1]]);
    pairs.forEach(pr => {
      const w = up(Math.max(pr[0].w, pr[1] ? pr[1].w : 0));
      if (x + w > room.w - M && x > M) { x = M; y += aisleF + up(rd) + up(s.clearRear); }
      pr[0].x = x; pr[0].y = y; pr[0].rot = 0; if (pr[1]) { pr[1].x = x; pr[1].y = y + aisleF; pr[1].rot = 180; }
      endY = Math.max(endY, pr[1] ? y + aisleF + pr[1].d : y + pr[0].d); x += w; maxX = Math.max(maxX, x);
    });
    room.w = Math.min(60000, Math.max(room.w, up(maxX + M))); room.l = Math.min(60000, Math.max(room.l, up(endY + M)));
  };
  RC.roomStats = function (P) {
    const placed = P.racks.filter(r => r.x != null); let w = 0, kg = 0; P.racks.forEach(r => { const st = RC.stats(P, r); w += st.watts; kg += st.kg; });
    const cool = P.room.objs.filter(o => o.type === 'crac').reduce((t, o) => t + o.cap, 0);
    return { placed: placed.length, total: P.racks.length, watts: w, btu: w * 3.412, kg, coolKw: cool, coolUnits: P.room.objs.filter(o => o.type === 'crac').length, area: P.room.w / 1000 * P.room.l / 1000, aisles: RC.aisles(P) };
  };
  RC.validateRoom = function (P, add) {
    const S = P.settings, rooms = P.room, rs = RC.rects(P), racks = P.racks.map(RC.rackRect).filter(Boolean), nm = r => r.rack ? r.rack.label : (RC.OBJ[r.obj.type] + (r.obj.label ? ' "' + r.obj.label + '"' : ''));
    if (!racks.length && !rooms.objs.length) return;
    P.racks.forEach(r => { if (r.x == null && racks.length) add('runpl', 'info', r.id, null, r.label + ' is not placed in the room plan.', r.id); });
    rs.forEach((A, i) => {
      if (A.kind === 'obj' && A.obj.type === 'text') return;
      if (A.x < 0 || A.y < 0 || A.x + A.w > rooms.w || A.y + A.h > rooms.l) add('rwall', 'crit', null, null, nm(A) + ' extends outside the room walls.', A.id);
      if (A.solid) rs.forEach((B, j) => { if (j > i && B.solid && hit(A, B)) add('rhit', 'crit', null, null, nm(A) + ' overlaps ' + nm(B) + '.', A.id + '+' + B.id); });
      if (A.kind === 'rack') {
        const f = RC.DIR[A.rot], fr = RC.gap(P, A, f[0], f[1]), rr = RC.gap(P, A, -f[0], -f[1]);
        if (fr.gap < S.clearFront) add('rclear', fr.gap < 600 ? 'crit' : 'warn', null, null, nm(A) + ': front has ' + Math.round(fr.gap) + ' mm clear, ' + S.clearFront + ' mm planned for opening doors and moving equipment' + (fr.who ? ' (' + nm(fr.who) + ' is in the way).' : ' (wall).'), A.id + ':f');
        if (rr.gap < S.clearRear) add('rclear', rr.gap < 600 ? 'crit' : 'warn', null, null, nm(A) + ': rear has ' + Math.round(rr.gap) + ' mm clear, ' + S.clearRear + ' mm planned for cabling and service' + (rr.who ? ' (' + nm(rr.who) + ' is in the way).' : ' (wall).'), A.id + ':r');
        if (fr.who && fr.who.kind === 'rack' && fr.gap < 3000) { const fb = RC.DIR[fr.who.rot]; if (fb[0] === f[0] && fb[1] === f[1]) add('rair', 'warn', null, null, nm(A) + ' faces the back of ' + nm(fr.who) + ': that rack blows hot exhaust into its intake. Turn one row around to form hot and cold aisles.', A.id); }
      }
      if (A.kind === 'obj' && A.obj.type === 'door') {
        const f = RC.DIR[A.rot], L = Math.max(A.obj.w, A.obj.d); let z;
        if (f[1] !== 0) z = { x: A.x, w: A.w, y: f[1] > 0 ? A.y + A.h : A.y - L, h: L }; else z = { y: A.y, h: A.h, x: f[0] > 0 ? A.x + A.w : A.x - L, w: L };
        const b = rs.find(o => o.solid && hit(z, o)); if (b) add('rdoor', 'warn', null, null, nm(A) + ' swing area is blocked by ' + nm(b) + '.', A.id);
      }
    });
    const st = RC.roomStats(P);
    if (st.watts > 0 && racks.length) {
      if (!st.coolUnits) add('rcool', 'info', null, null, 'No cooling unit is placed in the room plan. Add one (Objects) and set its capacity in kW to check the heat load.', 'room');
      else {
        const cap = st.coolKw, pct = cap ? st.watts / 1000 / cap * 100 : 999, caps = P.room.objs.filter(o => o.type === 'crac').map(o => o.cap);
        if (pct > 100) add('rcool', 'crit', null, null, 'Heat load ' + (st.watts / 1000).toFixed(1) + ' kW is above the ' + cap + ' kW of cooling in the room.', 'room');
        else if (pct > 80) add('rcool', 'warn', null, null, 'Cooling is at ' + Math.round(pct) + '% (' + (st.watts / 1000).toFixed(1) + ' of ' + cap + ' kW). Leave headroom for growth.', 'room');
        if (caps.length > 1 && cap - Math.max.apply(null, caps) < st.watts / 1000) add('rcool', 'warn', null, null, 'No cooling redundancy: if the largest unit fails, ' + (cap - Math.max.apply(null, caps)) + ' kW is left for ' + (st.watts / 1000).toFixed(1) + ' kW of heat.', 'room-n1');
        else if (caps.length === 1) add('rcool', 'info', null, null, 'Only one cooling unit: if it stops there is no cooling at all (no N+1).', 'room-n1');
      }
    }
  };


  /* ---------- equipment summary ---------- */
  RC.SUM_GROUPS = [['server', 'Servers', ['server']], ['storage', 'Storage', ['storage']], ['network', 'Network', ['switch', 'router', 'firewall']], ['passive', 'Patching and blanking', ['patch', 'manager', 'blank']], ['power', 'Power', ['pdu', 'ups']], ['other', 'Other', ['kvm']]];
  RC.summary = function (P, rackId) {
    const out = { total: 0, groups: {}, names: [] }; RC.SUM_GROUPS.forEach(g => out.groups[g[0]] = 0);
    P.devices.forEach(d => { if (rackId && d.rackId !== rackId) return; const m = RC.model(P, d.modelId), g = RC.SUM_GROUPS.find(x => x[2].indexOf(m.cat) >= 0) || RC.SUM_GROUPS[5]; out.groups[g[0]]++; out.total++; if (g[0] === 'server') out.names.push(d.hostname || m.name); });
    out.servers = out.groups.server; return out;
  };

  /* ---------- blanking panels ---------- */
  RC.autoBlank = function (P, rackId, all) {
    const rack = RC.rack(P, rackId); let n = 0;
    RC.freeRuns(P, rack, !all).forEach(g => {
      let u = g.u, left = g.h;
      while (left > 0) { const h = left >= 4 ? 4 : left >= 2 ? 2 : 1; P.devices.push({ id: RC.uid('d'), rackId, modelId: 'blank-' + h + 'u', u, side: 'full', rev: false, hostname: '', role: '', ips: [], mgmtIp: '', vlan: '', serial: '', asset: '', status: 'planned', feeds: [], notes: '' }); u += h; left -= h; n++; }
    });
    return n;
  };

  /* ---------- BOM ---------- */
  RC.bom = function (P) {
    const rows = {}; P.devices.forEach(d => { const m = RC.model(P, d.modelId), r = rows[m.id] = rows[m.id] || { model: m, qty: 0, w: 0, kg: 0, u: 0 }; r.qty++; r.w += RC.watts(P, d); r.kg += RC.kg(P, d); r.u += m.u; });
    return Object.keys(rows).map(k => rows[k]).sort((a, b) => (RK.groupOf(a.model.cat) + a.model.name).localeCompare(RK.groupOf(b.model.cat) + b.model.name));
  };
  const cell = v => { v = String(v == null ? '' : v); if (/^[=+\-@\t\r]/.test(v)) v = "'" + v; return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
  RC.bomCSV = function (P) {
    const L = [['Rack', 'U', 'Height U', 'Vendor', 'Model', 'Category', 'Hostname', 'Role', 'Mgmt IP', 'Serial', 'Asset tag', 'Status', 'Power W', 'Weight kg', 'Feeds', 'Data quality']];
    P.racks.forEach(r => RC.devsOf(P, r.id).sort((a, b) => b.u - a.u).forEach(d => { const m = RC.model(P, d.modelId); L.push([r.label, d.u, m.u, m.vendor, m.name, RK.CATS[m.cat], d.hostname, d.role, d.mgmtIp, d.serial, d.asset, d.status, Math.round(RC.watts(P, d)), +RC.kg(P, d).toFixed(1), d.feeds.join('+'), RK.VER[m.ver]]); }));
    return L.map(r => r.map(cell).join(',')).join('\r\n');
  };

  /* ---------- starter layouts ---------- */
  const mk = (rackId, modelId, u, o) => Object.assign({ id: RC.uid('d'), rackId, modelId, u, side: 'full', rev: false, hostname: '', role: '', ips: [], mgmtIp: '', vlan: '', serial: '', asset: '', status: 'planned', feeds: [], notes: '' }, o || {});
  RC.TEMPLATES = [['blank', 'Blank rack', '42U cabinet, no equipment'], ['closet', 'Small closet', '18U: patch panel, firewall, switch, UPS'], ['core', 'Network core', '42U: core pair, ToR, firewalls, patching'], ['compute', 'Compute rack', '42U: ToR pair and 2U servers']];
  RC.fromTemplate = function (key, name) {
    const P = RC.newProject(name), r = P.racks[0], id = r.id, D = P.devices;
    if (key === 'closet') { r.u = 18; r.label = 'Closet'; r.pdus = { A: { cap: 3680 }, B: { cap: 0 } }; r.loadRating = 600; r.emptyKg = 45;
      D.push(mk(id, 'gen-pp-24', 18), mk(id, 'gen-cm-1u', 17), mk(id, 'gen-fw-1u', 16, { hostname: 'FW1', role: 'Edge firewall', feeds: ['A'] }), mk(id, 'gen-sw-48g', 15, { hostname: 'SW1', role: 'Access', feeds: ['A'] }), mk(id, 'gen-sw-48g', 14, { hostname: 'SW2', role: 'Access', feeds: ['A'] }), mk(id, 'gen-ups-2u', 1)); }
    else if (key === 'core') { r.label = 'Core rack';
      D.push(mk(id, 'gen-fw-1u', 41, { hostname: 'FW1', role: 'Firewall', feeds: ['A', 'B'] }), mk(id, 'gen-fw-1u', 40, { hostname: 'FW2', role: 'Firewall', feeds: ['A', 'B'] }), mk(id, 'gen-cm-1u', 39), mk(id, 'h3c-s6860-54hf', 38, { hostname: 'CORE1', role: 'Core', feeds: ['A', 'B'] }), mk(id, 'h3c-s6860-54hf', 37, { hostname: 'CORE2', role: 'Core', feeds: ['A', 'B'] }),
        mk(id, 'gen-cm-1u', 36), mk(id, 'h3c-s5560x-54c-ei', 35, { hostname: 'DIST1', role: 'Distribution', feeds: ['A', 'B'] }), mk(id, 'h3c-s5560x-54c-ei', 34, { hostname: 'DIST2', role: 'Distribution', feeds: ['A', 'B'] }), mk(id, 'gen-pp-48', 31), mk(id, 'gen-pp-fo24', 30), mk(id, 'gen-pdu-1u', 1, { notes: 'Feed A' }), mk(id, 'gen-pdu-1u', 2, { notes: 'Feed B' })); }
    else if (key === 'compute') { r.label = 'Compute rack';
      D.push(mk(id, 'h3c-s6860-54hf', 42, { hostname: 'TOR-A', role: 'ToR', feeds: ['A', 'B'] }), mk(id, 'h3c-s6860-54hf', 41, { hostname: 'TOR-B', role: 'ToR', feeds: ['A', 'B'] }), mk(id, 'gen-cm-1u', 40));
      for (let i = 0; i < 8; i++) D.push(mk(id, 'h3c-r4900-g5', 38 - i * 2, { hostname: 'SRV' + (i + 1), role: 'Hypervisor', feeds: ['A', 'B'] }));
      D.push(mk(id, 'gen-sto-2u', 20, { hostname: 'NAS1', role: 'Storage', feeds: ['A', 'B'] }), mk(id, 'gen-pdu-1u', 1), mk(id, 'gen-pdu-1u', 2)); }
    return P;
  };
})();

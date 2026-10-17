/* Topology editor: export (PNG, JPEG, WebP, SVG, PDF, draw.io, JSON). Loaded after the editor script. */
const LIGHT = { '--bg': '#ffffff', '--surface': '#ffffff', '--surface-2': '#f1ede3', '--text': '#1a1a1a', '--text-dim': '#4a4a4a', '--text-muted': '#8a8a8a', '--border': '#e4dfd0', '--border-strong': '#cfc8b4', '--accent': '#0f766e' };
function resolveVars(s, light) { const cs = getComputedStyle(document.body); return s.replace(/var\((--[a-z0-9-]+)\)/g, (m, n) => (light && LIGHT[n]) || cs.getPropertyValue(n).trim() || '#888'); }
function download(name, blob) { const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000); }
const safeName = () => (S.doc.name || 'diagram').replace(/[^\w\-]+/g, '_').slice(0, 50) || 'diagram';
const xesc = s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

/* o: { light:bool, transparent:bool, title:bool } */
function exportSVG(o) {
  if (o === true) o = { light: true, title: true }; o = Object.assign({ light: false, transparent: false, title: true }, o || {});
  const b = allBounds(); if (!b) return null;
  const pad = o.title ? 48 : 28, usedT = [...new Set(links().map(l => l.type))], hdr = o.title ? 40 : 0, ftr = o.title ? (usedT.length ? 46 : 28) : 0;
  const W = Math.ceil(b.w + pad * 2), H = Math.ceil(b.h + pad * 2 + hdr + ftr), W2 = o.title ? Math.max(W, 420) : W;
  let leg = '', lx = pad;
  if (o.title) usedT.forEach(t => { const T = LT[t]; leg += `<line x1="${lx}" y1="${H - 34}" x2="${lx + 26}" y2="${H - 34}" stroke="${T.c}" stroke-width="${T.w}" ${T.d ? `stroke-dasharray="${T.d}"` : ''} stroke-linecap="round"/><text x="${lx + 32}" y="${H - 30}" font-size="11" fill="var(--text-dim)" font-family="${F_SANS}">${T.n}</text>`; lx += 52 + T.n.length * 6.4; });
  const dx = o.title ? pad - b.x : pad - b.x + (W2 - W) / 2, dy = pad + hdr - b.y;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W2}" height="${H}" viewBox="0 0 ${W2} ${H}">${o.transparent ? '' : `<rect width="${W2}" height="${H}" fill="var(--bg)"/>`}${o.title ? `<text x="${pad}" y="34" font-size="20" font-weight="700" fill="var(--text)" font-family="${F_SANS}">${esc(S.doc.name)}</text>` : ''}<g transform="translate(${dx},${dy})">${sceneMarkup()}</g>${leg}${o.title ? `<text x="${W2 - pad}" y="${H - 14}" text-anchor="end" font-size="10" fill="var(--text-muted)" font-family="${F_MONO}">ConfigLabs.online · ${new Date().toISOString().slice(0, 10)}</text>` : ''}</svg>`;
  return resolveVars(svg, o.light);
}
const svgSize = svg => { const m = /width="(\d+)" height="(\d+)"/.exec(svg); return { w: +m[1], h: +m[2] }; };
function svgToCanvas(svg, scale, fill) {
  return new Promise((res, rej) => {
    const z = svgSize(svg), sc = Math.min(scale, 12000 / Math.max(z.w, z.h)), img = new Image();
    img.onload = () => { const c = document.createElement('canvas'); c.width = Math.round(z.w * sc); c.height = Math.round(z.h * sc); const x = c.getContext('2d'); if (fill) { x.fillStyle = fill; x.fillRect(0, 0, c.width, c.height); } x.drawImage(img, 0, 0, c.width, c.height); res(c); };
    img.onerror = () => rej(new Error('render')); img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
  });
}
const canvasBlob = (c, type, q) => new Promise((res, rej) => c.toBlob(b => b ? res(b) : rej(new Error('encode')), type, q));

/* ---- minimal PDF writer: one page, one JPEG image ---- */
function makePDF(jpeg, iw, ih, pw, ph, margin, title) {
  const enc = new TextEncoder(), parts = [], off = []; let len = 0;
  const push = b => { if (typeof b === 'string') b = enc.encode(b); parts.push(b); len += b.length; };
  const obj = (n, body) => { off[n] = len; push(`${n} 0 obj\n`); push(body); push('\nendobj\n'); };
  const s = Math.min((pw - 2 * margin) / iw, (ph - 2 * margin) / ih), w = iw * s, h = ih * s, x = (pw - w) / 2, y = (ph - h) / 2, f = v => v.toFixed(2);
  push('%PDF-1.4\n%\xE2\xE3\xCF\xD3\n');
  obj(1, '<< /Type /Catalog /Pages 2 0 R >>'); obj(2, '<< /Type /Pages /Kids [3 0 R] /Count 1 >>');
  obj(3, `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${f(pw)} ${f(ph)}] /Resources << /XObject << /Im0 5 0 R >> /ProcSet [/PDF /ImageC] >> /Contents 4 0 R >>`);
  const cs = `q ${f(w)} 0 0 ${f(h)} ${f(x)} ${f(y)} cm /Im0 Do Q`; obj(4, `<< /Length ${cs.length} >>\nstream\n${cs}\nendstream`);
  off[5] = len; push(`5 0 obj\n<< /Type /XObject /Subtype /Image /Width ${iw} /Height ${ih} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${jpeg.length} >>\nstream\n`); push(jpeg); push('\nendstream\nendobj\n');
  const safeT = String(title || 'Diagram').replace(/[^\x20-\x7E]/g, '?').replace(/[()\\]/g, '');
  obj(6, `<< /Title (${safeT}) /Producer (ConfigLabs.online) /CreationDate (D:${new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14)}Z) >>`);
  const xr = len; push(`xref\n0 7\n0000000000 65535 f \n`); for (let i = 1; i <= 6; i++) push(String(off[i]).padStart(10, '0') + ' 00000 n \n');
  push(`trailer\n<< /Size 7 /Root 1 0 R /Info 6 0 R >>\nstartxref\n${xr}\n%%EOF`);
  const out = new Uint8Array(len); let p = 0; parts.forEach(a => { out.set(a, p); p += a.length; }); return out;
}
const PAGES = { a4: [595.28, 841.89], a3: [841.89, 1190.55], letter: [612, 792] };

/* ---- draw.io (.drawio, uncompressed mxGraph XML) ---- */
function exportDrawio() {
  let id = 2; const ids = {}, cells = [];
  const hex = c => /^#[0-9a-f]{6}$/i.test(c) ? c : '#9aa3af';
  items().filter(i => i.k === 'box').forEach(i => { const c = hex(i.c); cells.push(`<mxCell id="c${id++}" value="${xesc(i.label)}" style="rounded=1;arcSize=6;dashed=1;fillColor=${c};fillOpacity=8;strokeColor=${c};verticalAlign=top;align=left;spacingLeft=10;spacingTop=4;fontStyle=1;fontColor=${c};html=1;" vertex="1" parent="1"><mxGeometry x="${Math.round(i.x)}" y="${Math.round(i.y)}" width="${Math.round(i.w)}" height="${Math.round(i.h)}" as="geometry"/></mxCell>`); });
  items().filter(i => i.k === 'dev').forEach(i => {
    const T = TYPES[i.t] || TYPES.generic, c = hex(i.c || T.c), s = (i.s || 1) * 56, sub = devSubs(i).map(xesc).join('&lt;br&gt;');
    const v = `${xesc(i.label)}${sub ? '&lt;br&gt;&lt;font style=&quot;font-size:9px&quot;&gt;' + sub + '&lt;/font&gt;' : ''}`; ids[i.id] = 'c' + id;
    cells.push(`<mxCell id="c${id++}" value="${v}" style="rounded=1;arcSize=22;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=${c};strokeWidth=2;fontStyle=1;fontSize=12;verticalLabelPosition=bottom;verticalAlign=top;labelPosition=center;align=center;" vertex="1" parent="1"><mxGeometry x="${Math.round(i.x - s / 2)}" y="${Math.round(i.y - s / 2)}" width="${Math.round(s)}" height="${Math.round(s)}" as="geometry"/></mxCell>`);
    cells.push(`<mxCell id="c${id++}" value="${xesc(T.n)}" style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;fontSize=10;fontColor=${c};" vertex="1" parent="${ids[i.id]}"><mxGeometry x="0" y="0" width="${Math.round(s)}" height="${Math.round(s)}" as="geometry"/></mxCell>`);
  });
  items().filter(i => i.k === 'txt').forEach(i => { cells.push(`<mxCell id="c${id++}" value="${xesc(i.text).replace(/\n/g, '&lt;br&gt;')}" style="text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=top;fontSize=${Math.round((i.size || 16) * .75)};" vertex="1" parent="1"><mxGeometry x="${Math.round(i.x)}" y="${Math.round(i.y - (i.size || 16))}" width="${Math.round(bb(i).w)}" height="${Math.round(bb(i).h)}" as="geometry"/></mxCell>`); });
  links().forEach(l => {
    if (!ids[l.a] || !ids[l.b]) return; const T = LT[l.type] || LT.copper, c = hex(l.c || T.c), w = l.wd || T.w, eid = 'c' + id++, rt = l.route || 'orth';
    const st = `${rt === 'orth' ? 'edgeStyle=orthogonalEdgeStyle;' : rt === 'curve' ? 'curved=1;' : ''}rounded=0;html=1;endArrow=none;startArrow=none;strokeColor=${c};strokeWidth=${w};${T.d ? 'dashed=1;dashPattern=' + T.d + ';' : ''}fontColor=${c};fontStyle=1;fontSize=10;`;
    cells.push(`<mxCell id="${eid}" value="${xesc(l.label)}" style="${st}" edge="1" parent="1" source="${ids[l.a]}" target="${ids[l.b]}"><mxGeometry relative="1" as="geometry"/></mxCell>`);
    [[l.la, -.78], [l.lb, .78]].forEach(p => { if (p[0]) cells.push(`<mxCell id="c${id++}" value="${xesc(p[0])}" style="edgeLabel;html=1;align=center;verticalAlign=middle;resizable=0;points=[];fontSize=9;labelBackgroundColor=#ffffff;" vertex="1" connectable="0" parent="${eid}"><mxGeometry x="${p[1]}" relative="1" as="geometry"><mxPoint as="offset"/></mxGeometry></mxCell>`); });
  });
  return `<?xml version="1.0" encoding="UTF-8"?>\n<mxfile host="ConfigLabs.online" version="1"><diagram name="${xesc(S.doc.name)}" id="configlabs-${Date.now().toString(36)}"><mxGraphModel dx="1200" dy="800" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="0" pageScale="1" math="0" shadow="0"><root><mxCell id="0"/><mxCell id="1" parent="0"/>${cells.join('')}</root></mxGraphModel></diagram></mxfile>`;
}

/* ---- dialog ---- */
const XF = { png: { n: 'PNG', ext: 'png', d: 'Sharp raster image, supports transparency' }, jpeg: { n: 'JPEG', ext: 'jpg', d: 'Small file for slides and chat' }, webp: { n: 'WebP', ext: 'webp', d: 'Modern, small, supports transparency' }, svg: { n: 'SVG', ext: 'svg', d: 'Vector, editable in Illustrator, Inkscape, Visio' }, pdf: { n: 'PDF', ext: 'pdf', d: 'Document with a page size of your choice' }, drawio: { n: 'draw.io', ext: 'drawio', d: 'Open and edit in diagrams.net (draw.io)' }, json: { n: 'Diagram file', ext: 'json', d: 'ConfigLabs backup, import it again later' } };
const XS = { fmt: 'png', scale: 2, theme: 'cur', transp: false, title: true, q: 90, page: 'auto', orient: 'auto' };
try { Object.assign(XS, JSON.parse(localStorage.getItem('cl_tg_exp') || '{}')); } catch (e) {}
let _xt;
function openExport() {
  if (!items().length) { toast('Nothing to export yet'); return; }
  let ov = $('xov'); if (!ov) { ov = document.createElement('div'); ov.id = 'xov'; ov.className = 'ov'; ov.innerHTML = '<div class="md" id="xmd"></div>'; document.body.appendChild(ov); ov.addEventListener('pointerdown', e => { if (e.target === ov) ov.classList.remove('on'); }); }
  ov.classList.add('on'); drawXDlg();
}
function xOpts() { return { light: XS.theme === 'light', transparent: XS.transp && ['png', 'webp', 'svg'].includes(XS.fmt), title: XS.title }; }
function drawXDlg() {
  const f = XS.fmt, ras = ['png', 'jpeg', 'webp', 'pdf'].includes(f), vis = ['png', 'jpeg', 'webp', 'pdf', 'svg'].includes(f);
  const row = (l, h) => `<div class="xr"><label>${l}</label><div>${h}</div></div>`;
  const opt = (v, cur, t) => `<option value="${v}" ${String(cur) === String(v) ? 'selected' : ''}>${t}</option>`;
  $('xmd').innerHTML = `<h3>Export diagram</h3>
   <div class="xfm">${Object.keys(XF).map(k => `<button data-xf="${k}" class="${k === f ? 'on' : ''}">${XF[k].n}</button>`).join('')}</div>
   <div class="note" style="margin:-4px 0 12px">${XF[f].d}</div>
   ${vis ? `<div class="xprev" id="xprev"><span class="note">Rendering preview…</span></div>` : ''}
   ${vis ? row('Theme', `<select data-xo="theme">${opt('cur', XS.theme, 'Current (' + document.body.dataset.theme + ')')}${opt('light', XS.theme, 'Light, good for print and documents')}</select>`) : ''}
   ${['png', 'webp', 'svg'].includes(f) ? row('Background', `<select data-xo="transp">${opt('false', XS.transp, 'Solid')}${opt('true', XS.transp, 'Transparent')}</select>`) : ''}
   ${vis ? row('Title and legend', `<select data-xo="title">${opt('true', XS.title, 'Include')}${opt('false', XS.title, 'Diagram only')}</select>`) : ''}
   ${ras ? row('Resolution', `<select data-xo="scale">${[1, 2, 3, 4].map(n => opt(n, XS.scale, n + 'x' + (n === 2 ? ' (recommended)' : ''))).join('')}</select>`) : ''}
   ${f === 'jpeg' || f === 'webp' || f === 'pdf' ? row('Quality', `<input type="range" data-xo="q" min="50" max="100" step="5" value="${XS.q}"> <span class="note" id="xq">${XS.q}%</span>`) : ''}
   ${f === 'pdf' ? row('Page size', `<select data-xo="page">${opt('auto', XS.page, 'Fit the diagram (no margins)')}${opt('a4', XS.page, 'A4')}${opt('a3', XS.page, 'A3')}${opt('letter', XS.page, 'Letter')}</select>`) + row('Orientation', `<select data-xo="orient">${opt('auto', XS.orient, 'Automatic')}${opt('landscape', XS.orient, 'Landscape')}${opt('portrait', XS.orient, 'Portrait')}</select>`) : ''}
   ${f === 'drawio' ? '<div class="note">Devices become boxes with their labels, cables keep type, colour, ports and route. The icons are replaced by plain boxes.</div>' : ''}
   ${row('File name', `<input type="text" id="xname" value="${esc(safeName())}" maxlength="60">`)}
   <div class="note" id="xinfo"></div>
   <div class="ft"><button class="btn" id="x-cancel">Close</button><button class="btn pri" id="x-go">Download ${XF[f].n}</button></div>`;
  $('x-cancel').onclick = () => $('xov').classList.remove('on'); $('x-go').onclick = doExportNow;
  $('xmd').querySelectorAll('[data-xf]').forEach(b => b.onclick = () => { XS.fmt = b.dataset.xf; if (XS.fmt === 'jpeg' || XS.fmt === 'pdf') XS.transp = false; saveXS(); drawXDlg(); });
  $('xmd').querySelectorAll('[data-xo]').forEach(el => el.addEventListener('input', () => { const k = el.dataset.xo; let v = el.value; if (k === 'transp' || k === 'title') v = v === 'true'; else if (k === 'scale' || k === 'q') v = +v; XS[k] = v; if (k === 'q') $('xq').textContent = v + '%'; saveXS(); clearTimeout(_xt); _xt = setTimeout(xPreview, 120); }));
  xPreview();
}
function saveXS() { try { localStorage.setItem('cl_tg_exp', JSON.stringify(XS)); } catch (e) {} }
function xPreview() {
  const f = XS.fmt, el = $('xprev'), info = $('xinfo'); if (!info) return;
  if (!el) { info.textContent = ''; return; }
  const svg = exportSVG(xOpts()), z = svgSize(svg), sc = ['png', 'jpeg', 'webp', 'pdf'].includes(f) ? Math.min(XS.scale, 12000 / Math.max(z.w, z.h)) : 1;
  el.style.background = XS.transp && ['png', 'webp', 'svg'].includes(f) ? 'repeating-conic-gradient(#8883 0 25%,transparent 0 50%) 0 0/16px 16px' : 'var(--bg)';
  el.innerHTML = `<img alt="Preview" src="data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}">`;
  info.textContent = ['png', 'jpeg', 'webp', 'pdf'].includes(f) ? `${Math.round(z.w * sc)} × ${Math.round(z.h * sc)} px${sc < XS.scale ? ' (reduced to stay under the browser limit)' : ''}` : `${z.w} × ${z.h} units, scales without losing quality`;
}
async function doExportNow() {
  const f = XS.fmt, nm = ($('xname').value.trim() || safeName()).replace(/[\\/:*?"<>|]+/g, '_'), file = nm + '.' + XF[f].ext, btn = $('x-go');
  try {
    btn.disabled = true; btn.textContent = 'Working…';
    if (f === 'json') download(file, new Blob([JSON.stringify({ app: 'configlabs-topology', v: 1, name: S.doc.name, items: S.doc.items, links: S.doc.links }, null, 1)], { type: 'application/json' }));
    else if (f === 'drawio') download(file, new Blob([exportDrawio()], { type: 'application/vnd.jgraph.mxfile+xml' }));
    else {
      const o = xOpts(), svg = exportSVG(o);
      if (f === 'svg') download(file, new Blob([svg], { type: 'image/svg+xml' }));
      else {
        const fill = (f === 'jpeg' || f === 'pdf' || !o.transparent) ? (o.light ? '#ffffff' : getComputedStyle(document.body).getPropertyValue('--bg').trim() || '#0b0d10') : null, c = await svgToCanvas(svg, XS.scale, fill), q = XS.q / 100;
        if (f === 'png') download(file, await canvasBlob(c, 'image/png'));
        else if (f === 'jpeg') download(file, await canvasBlob(c, 'image/jpeg', q));
        else if (f === 'webp') { const b = await canvasBlob(c, 'image/webp', q); if (b.type !== 'image/webp') { toast('This browser cannot save WebP, saved as PNG instead'); download(nm + '.png', await canvasBlob(c, 'image/png')); } else download(file, b); }
        else if (f === 'pdf') {
          const jb = await canvasBlob(c, 'image/jpeg', Math.max(.85, q)), jpeg = new Uint8Array(await jb.arrayBuffer()); let pw, ph, m = 0;
          if (XS.page === 'auto') { pw = c.width * .75 / XS.scale * (XS.scale > 1 ? 1 : 1); pw = svgSize(svg).w * .75; ph = svgSize(svg).h * .75; }
          else { const P = PAGES[XS.page], land = XS.orient === 'landscape' || (XS.orient === 'auto' && c.width >= c.height); pw = land ? P[1] : P[0]; ph = land ? P[0] : P[1]; m = 28; }
          download(file, new Blob([makePDF(jpeg, c.width, c.height, pw, ph, m, S.doc.name)], { type: 'application/pdf' }));
        }
      }
    }
    toast(XF[f].n + ' saved'); $('xov').classList.remove('on');
  } catch (e) { toast('Export failed. Try SVG, or a lower resolution'); btn.disabled = false; btn.textContent = 'Download ' + XF[f].n; }
}

/* Shared by the Topology pages: SVG to canvas, image blobs and a one-page PDF writer. */
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


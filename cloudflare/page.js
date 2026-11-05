// The page a link opens: one tap starts AR Quick Look on an iPhone (Safari).
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export function renderPage(id, meta) {
  const usdz = `/f/${id}/model.usdz#allowsContentScaling=0`;   // stops pinch-resizing (Apple's Quick Look example)
  const thumb = meta.has_thumb ? `/f/${id}/thumb.png` : "/icon.svg";
  const steps = (meta.steps || []).map((s) => `<li>${esc(s)}</li>`).join("");
  const size = meta.parts_size_cm ? `<p class="size">部品の大きさ ${meta.parts_size_cm.map((v) => esc(v)).join(" × ")} cm</p>` : "";
  return `<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>${esc(meta.title || "AR")}</title>
<style>
:root{--bg:#f4f2ec;--ink:#1e2b26;--sub:#56615c;--accent:#2457c5;--warn:#b4741a}
@media (prefers-color-scheme:dark){:root{--bg:#141816;--ink:#e8ece9;--sub:#a5afaa;--accent:#7aa2ff;--warn:#e0a24c}}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 -apple-system,"Hiragino Sans",sans-serif}
main{max-width:520px;margin:0 auto;padding:20px 16px 40px}
h1{font-size:22px;margin:0 0 4px}.size{color:var(--sub);margin:0 0 16px}
a.ar{display:block;border-radius:14px;overflow:hidden;background:#fff;box-shadow:0 2px 10px #0002}
a.ar img{display:block;width:100%;height:auto}
.btn{display:block;text-align:center;margin:12px 0 20px;padding:14px;border-radius:12px;background:var(--accent);color:#fff;font-weight:700;text-decoration:none}
ol{padding-left:22px}li{margin:6px 0}.no{display:none;color:var(--warn);font-weight:700}
.foot{color:var(--sub);font-size:13px;margin-top:24px}
</style></head><body><main>
<h1>${esc(meta.title || "AR で確かめる")}</h1>${size}
<a class="ar" rel="ar" href="${usdz}"><img src="${thumb}" alt="タップすると AR で開きます"></a>
<a class="btn" href="${usdz}">AR で開く</a>
<p class="no" id="no">この画面では AR を開けません。iPhone の Safari でこのリンクを開いてください。</p>
<ol>${steps}</ol>
<p class="foot">${esc(meta.expires_text || "")}</p>
</main><script>
if(!document.createElement("a").relList.supports("ar")){document.getElementById("no").style.display="block";}
</script></body></html>`;
}

export const ICON_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 260"><rect width="400" height="260" fill="#e8eef9"/><path d="M200 60l90 45v70l-90 45-90-45v-70z" fill="none" stroke="#2457c5" stroke-width="10" stroke-linejoin="round"/><path d="M110 105l90 45 90-45M200 150v70" fill="none" stroke="#2457c5" stroke-width="10" stroke-linejoin="round"/></svg>`;

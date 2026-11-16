"""Builds the app: encrypted book, icons, manifest, service worker.
Usage: python3 construire.py  (password read from .motdepasse, chapters from src/*.js)"""
import json, os, base64, glob, pathlib, hashlib
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from PIL import Image, ImageDraw, ImageFilter

site = pathlib.Path("site"); site.mkdir(exist_ok=True)
mdp = pathlib.Path(".motdepasse").read_text().strip()

# --- book ---
chapitres = []
for f in sorted(glob.glob("src/[0-9][0-9].js")):
    s = pathlib.Path(f).read_text()
    chapitres.append(json.loads(s[s.index("(") + 1:s.rindex(")")]))
chapitres.sort(key=lambda c: c["n"])
clair = json.dumps({"chapitres": chapitres}, ensure_ascii=False).encode()
salt, iv, it = os.urandom(16), os.urandom(12), 310000
cle = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=it).derive(mdp.encode())
ct = AESGCM(cle).encrypt(iv, clair, None)
e = lambda b: base64.b64encode(b).decode()
(site / "livre.enc").write_text(json.dumps({"v": 1, "iter": it, "salt": e(salt), "iv": e(iv), "ct": e(ct)}))

# --- icons: black cloth, brass hexagram 64, red band ---
def icone(n, marge=0.0):
    S = 1024
    im = Image.new("RGB", (S, S), "#151413")
    d = ImageDraw.Draw(im)
    for y in range(0, S, 6):  # cloth weave
        d.line([(0, y), (S, y)], fill="#1c1b1a", width=2)
    halo = Image.new("L", (S, S), 0)
    ImageDraw.Draw(halo).ellipse([S*.18, S*.08, S*.82, S*.72], fill=70)
    halo = halo.filter(ImageFilter.GaussianBlur(120))
    im = Image.composite(Image.new("RGB", (S, S), "#4a3a22"), im, halo)
    d = ImageDraw.Draw(im)
    k = 1 - marge
    cx, top, w, h, gap = S/2, S*(0.20 + marge*0.3), S*0.46*k, S*0.052*k, S*0.042*k
    for i in range(6):
        y = top + i*(h+gap)
        if i % 2 == 0:
            d.rectangle([cx-w/2, y, cx+w/2, y+h], fill="#b9975b")
        else:
            d.rectangle([cx-w/2, y, cx-w*0.09, y+h], fill="#b9975b")
            d.rectangle([cx+w*0.09, y, cx+w/2, y+h], fill="#b9975b")
    by = S*(0.70 - marge*0.12)
    d.rectangle([0, by, S, by + S*0.13*k], fill="#8a1c18")
    d.line([(S*(0.12+marge*.3), by + S*0.065*k), (S*(0.88-marge*.3), by + S*0.065*k)], fill="#ebe2cd", width=max(2, int(6*k)))
    return im.resize((n, n), Image.LANCZOS)

icone(180).save(site / "icone-180.png")
icone(192).save(site / "icone-192.png")
icone(512).save(site / "icone-512.png")
icone(512, marge=0.18).save(site / "icone-maskable.png")

(site / "manifest.webmanifest").write_text(json.dumps({
    "name": "Le Maître du Haut-Château · Saison 5", "short_name": "MDHC S5",
    "start_url": "./", "scope": "./", "display": "standalone", "orientation": "any",
    "background_color": "#0d0c0b", "theme_color": "#0d0c0b", "lang": "fr",
    "icons": [{"src": "icone-192.png", "sizes": "192x192", "type": "image/png"},
              {"src": "icone-512.png", "sizes": "512x512", "type": "image/png"},
              {"src": "icone-maskable.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}]
}, ensure_ascii=False, indent=1))

version = hashlib.sha1((site / "index.html").read_bytes() + (site / "livre.enc").read_bytes()).hexdigest()[:10]
(site / "sw.js").write_text("""const C="mdhc-%s";
const BASE=["./","index.html","livre.enc","manifest.webmanifest","icone-180.png","icone-192.png","icone-512.png"];
self.addEventListener("install",e=>{ self.skipWaiting(); e.waitUntil(caches.open(C).then(c=>c.addAll(BASE)).catch(()=>{})); });
self.addEventListener("activate",e=>{ e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==C).map(k=>caches.delete(k)))).then(()=>self.clients.claim())); });
self.addEventListener("fetch",e=>{
  if(e.request.method!=="GET") return;
  const u=new URL(e.request.url);
  if(u.origin===location.origin){
    e.respondWith(fetch(e.request).then(r=>{ if(r.ok){ const c=r.clone(); caches.open(C).then(x=>x.put(e.request,c)); } return r; })
      .catch(()=>caches.match(e.request,{ignoreSearch:true}).then(m=>m||caches.match("index.html"))));
  }else if(/fonts\\.(googleapis|gstatic)\\.com$/.test(u.host)){
    e.respondWith(caches.match(e.request).then(m=>m||fetch(e.request).then(r=>{ const c=r.clone(); caches.open(C).then(x=>x.put(e.request,c)); return r; })));
  }
});
""" % version)
(site / ".nojekyll").write_text("")
print("chapitres:", [c["n"] for c in chapitres], "version", version)

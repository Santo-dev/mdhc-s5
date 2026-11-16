"""Turns the artifact reader (src/index.html) into the home-screen app page (site/index.html)."""
import re, pathlib
src = pathlib.Path("src/index.html").read_text()
voix = pathlib.Path("voix.js.part").read_text()

def rep(old, new, count=1):
    global src
    assert src.count(old) == count, (old[:60], src.count(old))
    src = src.replace(old, new)

# head: app on the home screen
rep('<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">',
    '<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, viewport-fit=cover">\n'
    '<meta name="apple-mobile-web-app-capable" content="yes">\n'
    '<meta name="mobile-web-app-capable" content="yes">\n'
    '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">\n'
    '<meta name="apple-mobile-web-app-title" content="MDHC S5">\n'
    '<meta name="theme-color" content="#0d0c0b">\n'
    '<meta name="robots" content="noindex, nofollow">\n'
    '<link rel="manifest" href="manifest.webmanifest">\n'
    '<link rel="apple-touch-icon" href="icone-180.png">\n'
    '<link rel="icon" href="icone-192.png">\n'
    '<script>(function(){var d=document.documentElement;function maj(){var st=navigator.standalone||(window.matchMedia&&matchMedia("(display-mode: standalone)").matches),h=window.innerHeight;'
    'if(st){var g=Math.max(screen.width,screen.height),c=Math.min(screen.width,screen.height),H=innerWidth>innerHeight?c:g;if(H>h&&H-h<170)h=H;}'
    'd.style.setProperty("--H",h+"px");}maj();addEventListener("resize",maj);'
    'addEventListener("orientationchange",function(){setTimeout(function(){maj();dispatchEvent(new Event("resize"));},400);});'
    'document.addEventListener("focusout",function(e){if(!e.target||!/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName))return;'
    'setTimeout(function(){var b=document.body;b.style.display="none";void b.offsetHeight;b.style.display="";maj();dispatchEvent(new Event("resize"));},160);});'
    '})();</script>')

# safe areas (notch, home indicator)
rep('#scene{position:fixed;inset:0;', '#scene{position:fixed;inset:0;top:env(safe-area-inset-top);')
rep('position:fixed;left:0;right:0;bottom:0;height:50px;z-index:20;',
    'position:fixed;left:0;right:0;bottom:0;height:calc(50px + env(safe-area-inset-bottom));padding-bottom:env(safe-area-inset-bottom)!important;z-index:20;')
rep('position:fixed;left:50%;bottom:58px;', 'position:fixed;left:50%;bottom:calc(58px + env(safe-area-inset-bottom));max-height:calc(100vh - 90px - env(safe-area-inset-bottom) - env(safe-area-inset-top));overflow:auto;')
rep('const vw=scene.clientWidth, vh=scene.clientHeight, barre=50;',
    'const vw=scene.clientWidth, vh=scene.clientHeight, barre=($("barre").offsetHeight||50);')

# extra styles
rep('</style>', '''#b-voix.charge svg{animation:souffle 1s ease-in-out infinite}
@keyframes souffle{50%{opacity:.25}}
#toast{position:fixed;left:50%;bottom:calc(60px + env(safe-area-inset-bottom));transform:translate(-50%,8px);z-index:40;
  width:max-content;max-width:calc(100vw - 32px);padding:10px 14px;border-radius:4px;opacity:0;pointer-events:none;
  background:rgba(22,20,18,.95);border:1px solid rgba(185,151,91,.5);color:var(--papier);
  font:400 13px/1.35 var(--f-machine);transition:opacity .25s, transform .25s;
  -webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px)}
#toast.vu{opacity:1;transform:translate(-50%,0)}
#panneau .h4v{margin-top:18px;padding-top:14px;border-top:1px solid rgba(185,151,91,.3)}
#panneau .etat-voix,#panneau .note{margin:0 0 8px;font-size:12px;color:rgba(235,226,205,.75)}
#panneau .note{margin:10px 0 0}
#panneau .champ{display:flex;align-items:center;gap:10px;margin-top:8px}
#panneau .champ span{flex:0 0 84px;font-size:12px;letter-spacing:.06em;color:var(--laiton)}
#panneau input,#panneau select{flex:1;min-width:0;height:40px;padding:0 10px;font:400 16px/1 var(--f-machine);color:var(--papier);
  background:rgba(0,0,0,.35);border:1px solid rgba(185,151,91,.42);border-radius:3px;-webkit-appearance:none;appearance:none}
#panneau .rangee{display:flex;gap:8px}
#panneau .rangee button{justify-content:center}
#panneau button.discret{justify-content:center;opacity:.8;font-size:12px}
#verrou{position:fixed;inset:0;z-index:60;display:flex;align-items:center;justify-content:center;padding:24px;
  background:radial-gradient(95% 75% at 50% 46%, #2b2622 0%, #151312 68%, #090808 100%)}
#verrou[hidden]{display:none}
#verrou form{width:min(340px,100%);text-align:center;color:var(--papier)}
#verrou .t1{font:400 11px/1 var(--f-machine);letter-spacing:.3em;text-transform:uppercase;color:var(--laiton)}
#verrou h1{margin:14px 0 6px;font:800 44px/.92 var(--f-titre);text-transform:uppercase}
#verrou p{margin:0 0 22px;font:italic 400 17px/1.4 var(--f-texte);color:rgba(235,226,205,.7)}
#verrou input{width:100%;height:46px;padding:0 12px;font:400 16px/1 var(--f-machine);color:var(--papier);text-align:center;
  background:rgba(0,0,0,.4);border:1px solid rgba(185,151,91,.5);border-radius:3px}
#verrou button{margin-top:10px;width:100%;height:46px;font:800 18px/1 var(--f-titre);letter-spacing:.2em;text-transform:uppercase;
  color:var(--papier);background:var(--sang);border:0;border-radius:3px}
#verrou .err{min-height:18px;margin-top:10px;font:400 12px/1.4 var(--f-machine);color:#e28b84}
</style>''')

rep('html,body{height:100%;margin:0}', 'html{height:100%;margin:0;overflow:hidden;background:#151312}\nbody{position:relative;margin:0;height:var(--H,100%);min-height:100%;overflow:hidden}')
rep('#decor{position:fixed;', '#decor{position:absolute;')
rep('#scene{position:fixed;', '#scene{position:absolute;')
rep('position:fixed;left:0;right:0;bottom:0;height:calc(50px', 'position:absolute;left:0;right:0;bottom:0;height:calc(50px')
rep('position:fixed;left:50%;bottom:calc(58px', 'position:absolute;left:50%;bottom:calc(58px')
rep('#toast{position:fixed;', '#toast{position:absolute;')
rep('#verrou{position:fixed;', '#verrou{position:absolute;')

# toast + lock screen elements
rep('<script>window.LIVRE={chapitres:[]};</script>\n<script src="chapitres/01.js"></script>',
    '''<div id="toast" role="status" aria-live="polite"></div>
<div id="verrou" hidden>
  <form id="f-verrou" autocomplete="off">
    <div class="t1">Fanfiction · Saison 5</div>
    <h1>Le Maître du Haut-Château</h1>
    <p>Édition à un seul exemplaire.</p>
    <input id="mdp" type="password" placeholder="Mot de passe" autocapitalize="off" spellcheck="false">
    <button type="submit">Ouvrir le livre</button>
    <div class="err" id="mdp-err"></div>
  </form>
</div>
<script>window.LIVRE={chapitres:[]};</script>''')

# the reader starts only once the book is decrypted
rep('<script>\n(function(){\n"use strict";\nconst chapitres', '<script>\nwindow.demarrerLivre=function(){\n"use strict";\nconst chapitres')
assert src.rstrip().endswith('})();\n</script>\n</body>\n</html>'), src[-80:]
idx = src.rstrip().rfind('})();\n</script>')
src = src[:idx] + '};\n</script>' + src[idx + len('})();\n</script>'):]

# keyboard shortcuts must not fire while typing in a field
rep('document.addEventListener("keydown",e=>{\n', 'document.addEventListener("keydown",e=>{\n  if(e.target && /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)) return;\n')

# voice settings at the bottom of the contents panel
rep('  panneau.innerHTML=h; panneau.classList.add("ouvert");', '  h+=htmlReglages();\n  panneau.innerHTML=h; panneau.classList.add("ouvert");')

# replace the voice module
a = src.index('/* ---- lecture à voix haute (voix française de l\'appareil) ---- */')
b = src.index('/* ---- ouverture : on reprend là où la lecture s\'était arrêtée ---- */')
src = src[:a] + voix + src[b:]

# loader: password, decryption, service worker
loader = pathlib.Path("chargeur.js.part").read_text()
src = src.replace('</body>', '<script>\n' + loader + '</script>\n</body>')

pathlib.Path("site").mkdir(exist_ok=True)
pathlib.Path("site/index.html").write_text(src)
print("ok", len(src))

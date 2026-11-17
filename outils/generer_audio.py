"""Records the book once with a Gemini voice (runs on GitHub Actions).

Reads livre.enc (decrypted with LIVRE_MDP), cuts each chapter into pieces of a few
paragraphs (same cut as the app), asks Gemini to read each piece, encodes it to AAC,
encrypts it and writes audio/NN/KKK.bin + audio/index.json. Already-recorded pieces are
skipped, so the job can stop (quota, timeout) and resume later.

Env: GEMINI_API_KEY, LIVRE_MDP, VOIX (default Charon), MODELE (default gemini-3.8-flash-tts),
     CHAPITRES ("" = all, or "1,2"), FAUX=1 (offline test: sine wave instead of Gemini).
"""
import base64, json, os, re, subprocess, sys, time, math, struct, pathlib, hashlib
from collections import defaultdict
import requests
from bs4 import BeautifulSoup, Tag
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

RACINE = pathlib.Path(os.environ.get("RACINE", "."))
STYLE = "calm, expressive audiobook narration with natural pauses; Japanese and German words pronounced in their own language"
LIMITE = 1400
VOIX = os.environ.get("VOIX") or ""      # empty = keep the voice already used for the book
MODELE = os.environ.get("MODELE") or ""
FAUX = os.environ.get("FAUX") == "1"
CLE_API = os.environ.get("GEMINI_API_KEY", "")
MDP = os.environ["LIVRE_MDP"]
DUREE_MAX = float(os.environ.get("DUREE_MAX_MIN", "300")) * 60
t0 = time.time()


def derive(salt, it):
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=it).derive(MDP.encode())


# ---------- book ----------
p = json.loads((RACINE / "livre.enc").read_text())
b = lambda s: base64.b64decode(s)
livre = json.loads(AESGCM(derive(b(p["salt"]), p["iter"])).decrypt(b(p["iv"]), b(p["ct"]), None))
chapitres = sorted(livre["chapitres"], key=lambda c: c["n"])


def nettoyer(s):
    s = re.sub(r"[  ]", " ", s)
    s = re.sub(r"^\s*[—–]\s*", "", s)
    s = re.sub(r"\s[—–]\s", ", ", s)
    return re.sub(r"\s+", " ", s).strip()


def textes(c):
    """Same list as textes() in the app: one entry per top-level block, the chapter heading first."""
    out = ["Chapitre %d. %s." % (c["n"], c["titre"])]
    for el in BeautifulSoup(c["html"], "html.parser").contents:
        if not isinstance(el, Tag):
            continue
        if "bloc" in (el.get("class") or []):
            h = el.find("h3")
            lieu = h.get_text().lower() if h else ""
            reste = " ".join(x.get_text() for x in el.children if isinstance(x, Tag) and x is not h)
            out.append((nettoyer(lieu[:1].upper() + lieu[1:]) + ". " if lieu else "") + nettoyer(reste))
        else:
            out.append(nettoyer(el.get_text()))
    return out


def morceaux(t):
    res, b0 = [], 0
    while b0 < len(t):
        b1, n = b0, len(t[b0])
        while b1 + 1 < len(t) and n + len(t[b1 + 1]) + 2 <= LIMITE:
            b1 += 1
            n += len(t[b1]) + 2
        res.append((b0, b1))
        b0 = b1 + 1
    return res


# ---------- Gemini ----------
class Quota(Exception):
    pass


def trouver_audio(o):
    if isinstance(o, dict):
        d = o.get("data")
        if isinstance(d, str) and len(d) > 200:
            return d, o.get("mime_type") or o.get("mimeType") or ""
        for v in o.values():
            r = trouver_audio(v)
            if r:
                return r
    elif isinstance(o, list):
        for v in o:
            r = trouver_audio(v)
            if r:
                return r
    return None


def gemini(texte):
    if FAUX:
        rate, n = 24000, int(24000 * max(1.0, len(texte) / 60))
        return b"".join(struct.pack("<h", int(2500 * math.sin(i / 18))) for i in range(n)), rate
    tete = {"Content-Type": "application/json", "x-goog-api-key": CLE_API}
    api = "https://generativelanguage.googleapis.com/v1beta/"
    for essai in range(8):
        r = requests.post(api + "interactions", headers=tete, timeout=300, json={
            "model": MODELE,
            "input": [{"type": "user_input", "content": [{"type": "text", "text": texte,
                       "annotations": [{"type": "speech_metadata", "style": STYLE}]}]}],
            "response_format": {"type": "audio"},
            "generation_config": {"speech_config": [{"voice": VOIX}]}})
        if r.status_code not in (200, 429, 401, 403) and r.status_code < 500:
            r = requests.post(api + "models/%s:generateContent" % MODELE, headers=tete, timeout=300, json={
                "contents": [{"parts": [{"text": "Read aloud as " + STYLE + ":\n\n" + texte}]}],
                "generationConfig": {"responseModalities": ["AUDIO"],
                                     "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOIX}}}}})
        if r.status_code == 200:
            a = trouver_audio(r.json())
            if not a:
                raise RuntimeError("réponse sans audio: " + r.text[:300])
            data = base64.b64decode(a[0])
            if data[:4] == b"RIFF":
                rate = struct.unpack("<I", data[24:28])[0]
                i = data.find(b"data")
                return data[i + 8:], rate
            m = re.search(r"rate=(\d+)", a[1])
            return data, int(m.group(1)) if m else 24000
        if r.status_code == 429:
            txt = r.text
            if "PerDay" in txt or "per day" in txt.lower() or essai >= 5:
                raise Quota(txt[:400])
            time.sleep(20 * (essai + 1))
            continue
        if r.status_code >= 500:
            time.sleep(15 * (essai + 1))
            continue
        raise RuntimeError("Gemini %d: %s" % (r.status_code, r.text[:400]))
    raise Quota("trop d'essais")


def aac(pcm, rate):
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        src, out = os.path.join(d, "a.raw"), os.path.join(d, "a.m4a")
        open(src, "wb").write(pcm)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "s16le", "-ar", str(rate), "-ac", "1", "-i", src,
                        "-c:a", "aac", "-b:a", "56k", "-movflags", "+faststart", out], check=True)
        return open(out, "rb").read()


# ---------- main ----------
def h(x):
    return hashlib.sha256(x.encode("utf-8")).hexdigest()[:20]


dossier = RACINE / "audio"
dossier.mkdir(exist_ok=True)
fi = dossier / "index.json"
index = json.loads(fi.read_text()) if fi.exists() else {}
if "salt" not in index:
    index = {"v": 2, "iter": 310000, "salt": base64.b64encode(os.urandom(16)).decode(), "chapitres": {}}
index["v"] = 2
anciens = [e for e in index["chapitres"].values() if e.get("voix")]
VOIX = VOIX or (anciens[0]["voix"] if anciens else "Charon")
MODELE = MODELE or (anciens[0].get("modele") if anciens else "") or "gemini-3.8-flash-tts"
cle = AESGCM(derive(b(index["salt"]), index["iter"]))


def ecrire_index():
    fi.write_text(json.dumps(index, ensure_ascii=False))


def plan(t, ph, vieux):
    """Cut the chapter into pieces, reusing every old piece whose paragraphs are unchanged.
    Old pieces are found by content (paragraph hashes), so an edit only costs the pieces it touches."""
    cands = defaultdict(list)
    for m in vieux:
        if len(m) >= 5 and m[4] and (RACINE / m[2]).exists():
            cands[m[4][0]].append(m)

    def trouve(i):
        for m in cands.get(ph[i], []):
            if ph[i:i + len(m[4])] == m[4]:
                return m
        return None

    res, i = [], 0
    while i < len(t):
        m = trouve(i)
        if m:
            res.append((i, i + len(m[4]) - 1, m))
            i += len(m[4])
            continue
        j, n = i, len(t[i])
        while j + 1 < len(t) and n + len(t[j + 1]) + 2 <= LIMITE and not trouve(j + 1):
            j += 1
            n += len(t[j]) + 2
        res.append((i, j, None))
        i = j + 1
    return res


voulus = {int(x) for x in os.environ.get("CHAPITRES", "").replace(" ", "").split(",") if x}
presents = {str(c["n"]) for c in chapitres}
for n in list(index["chapitres"]):
    if n not in presents:
        del index["chapitres"][n]
arret, faits, repris = None, 0, 0
for c in chapitres:
    if voulus and c["n"] not in voulus:
        continue
    t = textes(c)
    ph = [h(x) for x in t]
    nn = "%02d" % c["n"]
    (dossier / nn).mkdir(exist_ok=True)
    ent = index["chapitres"].get(str(c["n"])) or {}
    vieux = ent.get("morceaux", []) if ent.get("voix") == VOIX and ent.get("modele") == MODELE else []
    pl = plan(t, ph, vieux)
    garde = [[b0, b1, m[2], m[3], ph[b0:b1 + 1]] for b0, b1, m in pl if m]
    repris += len(garde)
    ent = {"voix": VOIX, "modele": MODELE, "total": len(pl), "complet": False, "texte": h("\n\n".join(t)), "morceaux": garde}
    index["chapitres"][str(c["n"])] = ent
    ecrire_index()
    for k, (b0, b1, m) in enumerate(pl):
        if m:
            continue
        if time.time() - t0 > DUREE_MAX:
            arret = "temps écoulé"
            break
        texte = "\n\n".join(t[b0:b1 + 1])
        th = h(texte)
        f = "audio/%s/%s.bin" % (nn, th)
        if not (RACINE / f).exists():
            try:
                pcm, rate = gemini(texte)
            except Quota as e:
                arret = "quota Gemini: " + str(e)[:200]
                break
            iv = os.urandom(12)
            (RACINE / f).write_bytes(iv + cle.encrypt(iv, aac(pcm, rate), None))
            faits += 1
            if not FAUX:
                time.sleep(3)
        ent["morceaux"].append([b0, b1, f, th, ph[b0:b1 + 1]])
        ent["morceaux"].sort(key=lambda x: x[0])
        ecrire_index()
        print("chapitre %d : morceau %d/%d" % (c["n"], k + 1, len(pl)), flush=True)
    ent["complet"] = len(ent["morceaux"]) == len(pl)
    ecrire_index()
    if arret:
        break

# files no longer used by any version of the text
utiles = {m[2] for e in index["chapitres"].values() for m in e["morceaux"]}
suppr = 0
for f in dossier.glob("*/*.bin"):
    if str(f.relative_to(RACINE)) not in utiles:
        f.unlink()
        suppr += 1

print("morceaux réutilisés : %d, enregistrés cette fois : %d, fichiers périmés supprimés : %d" % (repris, faits, suppr))
for n, e in sorted(index["chapitres"].items(), key=lambda x: int(x[0])):
    print("chapitre %s : %d/%d %s" % (n, len(e["morceaux"]), e["total"], "complet" if e["complet"] else ""))
if arret:
    print("ARRÊT :", arret)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a").write("Arrêt : %s\n\nRelancez plus tard, l'enregistrement reprendra où il s'est arrêté.\n" % arret)

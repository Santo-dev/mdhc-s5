"""Records the book once with a Gemini voice (runs on GitHub Actions).

Reads livre.enc (decrypted with LIVRE_MDP), cuts each chapter into pieces of a few
paragraphs (same cut as the app), asks Gemini to read each piece, encodes it to AAC,
encrypts it and writes audio/NN/KKK.bin + audio/index.json. Already-recorded pieces are
skipped, so the job can stop (quota, timeout) and resume later.

Env: GEMINI_API_KEY, LIVRE_MDP, VOIX (default Charon), MODELE (default gemini-3.8-flash-tts),
     CHAPITRES ("" = all, or "1,2"), FAUX=1 (offline test: sine wave instead of Gemini).
"""
import base64, json, os, re, subprocess, sys, time, math, struct, pathlib
import requests
from bs4 import BeautifulSoup, Tag
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

RACINE = pathlib.Path(os.environ.get("RACINE", "."))
STYLE = "calm, expressive audiobook narration with natural pauses; Japanese and German words pronounced in their own language"
LIMITE = 1400
VOIX = os.environ.get("VOIX") or "Charon"
MODELE = os.environ.get("MODELE") or "gemini-3.8-flash-tts"
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
dossier = RACINE / "audio"
dossier.mkdir(exist_ok=True)
fi = dossier / "index.json"
index = json.loads(fi.read_text()) if fi.exists() else {}
if "salt" not in index:
    index = {"v": 1, "iter": 310000, "salt": base64.b64encode(os.urandom(16)).decode(), "chapitres": {}}
cle = AESGCM(derive(b(index["salt"]), index["iter"]))

voulus = {int(x) for x in os.environ.get("CHAPITRES", "").replace(" ", "").split(",") if x}
arret = None
faits = 0
for c in chapitres:
    if voulus and c["n"] not in voulus:
        continue
    t = textes(c)
    ms = morceaux(t)
    nn = "%02d" % c["n"]
    ent = index["chapitres"].get(str(c["n"]))
    if not ent or ent.get("voix") != VOIX or ent.get("modele") != MODELE or [m[:2] for m in ent["morceaux"]] != [list(x) for x in ms][:len(ent["morceaux"])]:
        ent = {"voix": VOIX, "modele": MODELE, "total": len(ms), "complet": False, "morceaux": []}
    ent["total"] = len(ms)
    deja = {tuple(m[:2]) for m in ent["morceaux"]}
    (dossier / nn).mkdir(exist_ok=True)
    for k, (b0, b1) in enumerate(ms):
        if (b0, b1) in deja and (RACINE / ent["morceaux"][k][2]).exists():
            continue
        if time.time() - t0 > DUREE_MAX:
            arret = "temps écoulé"
            break
        texte = "\n\n".join(t[b0:b1 + 1])
        try:
            pcm, rate = gemini(texte)
        except Quota as e:
            arret = "quota Gemini: " + str(e)[:200]
            break
        f = "audio/%s/%03d.bin" % (nn, k)
        iv = os.urandom(12)
        (RACINE / f).write_bytes(iv + cle.encrypt(iv, aac(pcm, rate), None))
        ent["morceaux"] = [m for m in ent["morceaux"] if tuple(m[:2]) != (b0, b1)] + [[b0, b1, f]]
        ent["morceaux"].sort(key=lambda m: m[0])
        index["chapitres"][str(c["n"])] = ent
        fi.write_text(json.dumps(index, ensure_ascii=False))
        faits += 1
        print("chapitre %d : morceau %d/%d" % (c["n"], k + 1, len(ms)), flush=True)
        if not FAUX:
            time.sleep(3)
    ent["complet"] = len(ent["morceaux"]) == len(ms)
    index["chapitres"][str(c["n"])] = ent
    fi.write_text(json.dumps(index, ensure_ascii=False))
    if arret:
        break

print("morceaux enregistrés cette fois :", faits)
for n, e in sorted(index["chapitres"].items(), key=lambda x: int(x[0])):
    print("chapitre %s : %d/%d %s" % (n, len(e["morceaux"]), e["total"], "complet" if e["complet"] else ""))
if arret:
    print("ARRÊT :", arret)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a").write("Arrêt : %s\n\nRelancez plus tard, l'enregistrement reprendra où il s'est arrêté.\n" % arret)

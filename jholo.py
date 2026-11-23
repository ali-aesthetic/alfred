"""jholo — голограмма на весь экран Mac (как в кино): реалистичная форма, движение и данные.

  jholo.py - <<'JSON'                 показать (спецификация ниже)
  {...}
  JSON
  jholo.py loading "Мегалодон"        сразу показать «сканирую архивы…», пока ищешь модель
  jholo.py clear                      убрать голограмму
  jholo.py lib                        что уже есть в библиотеке моделей (мгновенно)
  jholo.py save <имя> <url|путь> [motion]   положить найденную модель в библиотеку
  jholo.py depth <url|путь>           проверить, что фото превращается в объём (печатает OK)

Спецификация (JSON):
  title, subtitle, summary, kicker, color ("#57e3ff"), env ("ocean"|"space"|"lab"), duration (сек, 180)
  facts:    [{"label":"Длина","value":"до 18 м"}, …]   до 6
  callouts: [{"at":"head","text":"…"}, …]              до 4; точки: у моделей top, bottom, front, back, left, right, center
  scale_m, depth_m
  Форма — одно из:
    "model": "имя из библиотеки" | URL .glb/.gltf | путь .glb     — настоящая 3D-модель (с её анимацией)
    "image": URL|путь фото, "relief": true                        — фото → объём (нейросеть глубины на Mac)
    "archetype": megalodon|shark|whale|dolphin|orca|fish|planet|solar_system|dna|atom  (+ "params")
    "code": "JS-код сцены на three.js"                            — для всего остального
  motion: swim | fly | walk | turntable | float | static
"""
import base64
import getpass
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HOME = Path(__file__).resolve().parent
USER = getpass.getuser()
SPEC = HOME / "data" / f"holo-{USER}.json"
CACHE = HOME / "data" / "holo_cache"
LIB = HOME / "data" / "holo_lib"
DEPTH_MODEL = HOME / "models" / "depth" / "depth_anything_v2_small_q.onnx"
DEPTH_URL = "https://huggingface.co/onnx-community/depth-anything-v2-small/resolve/main/onnx/model_quantized.onnx"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) Alfred-Hologram/1.0"}


def _mk(p):
    p.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p, 0o777)
    except OSError:
        pass
    return p


def fetch(src, max_mb=60):
    """URL или путь → локальный файл (с кэшем)."""
    s = str(src)
    if s.startswith(("http://", "https://")):
        _mk(CACHE)
        ext = os.path.splitext(s.split("?")[0])[1][:6] or ".bin"
        out = CACHE / (hashlib.md5(s.encode()).hexdigest()[:16] + ext)
        if not out.exists() or out.stat().st_size == 0:
            req = urllib.request.Request(s, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read(max_mb * 1024 * 1024 + 1)
            if len(data) > max_mb * 1024 * 1024:
                raise SystemExit(f"Файл больше {max_mb} МБ — возьми модель полегче.")
            out.write_bytes(data)
        return out
    p = Path(os.path.expanduser(s)).resolve()
    if not p.exists():
        raise SystemExit(f"Файл не найден: {p}")
    return p


def data_uri(path, mime):
    return f"data:{mime};base64," + base64.b64encode(Path(path).read_bytes()).decode()


B3 = "https://raw.githubusercontent.com/mrdoob/three.js/r128/examples/models/gltf/"
BK = "https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/main/Models/"


def _k(name):
    return f"{BK}{name}/glTF-Binary/{name}.glb"


# Встроенная библиотека: настоящие 3D-модели со свободной лицензией (качаются один раз и потом показываются мгновенно)
BUILTIN = [
    (["лошадь", "конь", "скакун", "horse", "ot", "otni"], B3 + "Horse.glb", "walk", "three.js"),
    (["фламинго", "flamingo"], B3 + "Flamingo.glb", "fly", "three.js"),
    (["попугай", "parrot", "to'tiqush", "totiqush"], B3 + "Parrot.glb", "fly", "three.js"),
    (["аист", "stork", "laylak", "птица", "bird", "qush"], B3 + "Stork.glb", "fly", "three.js"),
    (["солдат", "soldier", "askar"], B3 + "Soldier.glb", "turntable", "three.js"),
    (["робот", "robot"], B3 + "RobotExpressive/RobotExpressive.glb", "turntable", "three.js / Tomás Laulhé CC0"),
    (["человек", "human", "odam", "манекен"], B3 + "Xbot.glb", "turntable", "three.js / Mixamo"),
    (["токио", "город", "tokyo", "city", "shahar"], B3 + "LittlestTokyo.glb", "turntable", "Glen Fox, CC-BY"),
    (["феррари", "ferrari", "спорткар", "суперкар", "sports car", "supercar", "гоночн", "hypercar", "car", "bugatti", "lamborghini", "porsche", "mclaren", "koenigsegg", "pagani", "bmw", "mercedes", "audi", "tesla", "mashina"], B3 + "ferrari.glb", "turntable", "three.js"),
    (["лиса", "лис", "fox", "tulki"], _k("Fox"), "walk", "PixelMannen CC0 / tomkranis CC-BY"),
    (["шлем", "helmet", "dubulg'a"], _k("DamagedHelmet"), "turntable", "theblueturtle_, CC-BY-NC"),
    (["игрушечная машинка", "toy car"], _k("ToyCar"), "turntable", "Guido Odendahl, CC-BY"),
    (["грузовик", "truck", "yuk mashinasi", "фура"], _k("CesiumMilkTruck"), "turntable", "Cesium, CC-BY"),
    (["утка", "утёнок", "duck", "o'rdak"], _k("Duck"), "turntable", "Sony"),
    (["авокадо", "avocado"], _k("Avocado"), "turntable", "Microsoft, CC0"),
    (["фотоаппарат", "камера старинная", "antique camera", "fotoapparat"], _k("AntiqueCamera"), "turntable", "Maximilian Kamps, CC-BY"),
    (["часы", "хронограф", "watch", "soat"], _k("ChronographWatch"), "turntable", "Eric Chadwick, CC-BY"),
    (["кресло", "стул", "chair", "stul", "kreslo"], _k("SheenChair"), "turntable", "Wayfair, CC-BY"),
    (["диван", "sofa", "divan"], _k("GlamVelvetSofa"), "turntable", "Wayfair, CC-BY"),
    (["дракон", "dragon", "ajdar", "ajdarho"], _k("DragonAttenuation"), "turntable", "Stanford / Khronos, CC-BY"),
    (["лампа", "светильник", "lamp", "chiroq"], _k("IridescenceLamp"), "turntable", "Wayfair, CC-BY"),
    (["очки", "солнцезащитные", "sunglasses", "ko'zoynak"], _k("SunglassesKhronos"), "turntable", "Khronos, CC-BY"),
    (["комар", "янтарь", "mosquito", "amber", "chivin"], _k("MosquitoInAmber"), "turntable", "Loïc Norgeot, CC-BY"),
    (["концепт-кар", "концепткар", "concept car", "электромобиль"], _k("CarConcept"), "turntable", "Eric Chadwick, CC-BY"),
    (["магнитофон", "бумбокс", "boombox"], _k("BoomBox"), "turntable", "Microsoft, CC0"),
    (["бутылка", "bottle", "shisha"], _k("WaterBottle"), "turntable", "Microsoft, CC0"),
    (["фонарь", "lantern", "fonar"], _k("Lantern"), "turntable", "Microsoft, CC0"),
    (["идущий человек", "пешеход", "walking man"], _k("CesiumMan"), "walk", "Cesium, CC-BY"),
]
# Готовые формы Alfred (мгновенно)
ARCHETYPES = [
    (["мегалодон", "megalodon"], "megalodon", {}), (["белая акула", "акула", "shark", "akula"], "shark", {}),
    (["синий кит", "кит", "кита", "киты", "китов", "whale", "kit"], "whale", {}), (["дельфин", "dolphin", "delfin"], "dolphin", {}),
    (["косатка", "orca"], "orca", {}), (["рыба", "fish", "baliq"], "fish", {}),
    (["солнечная система", "solar system", "quyosh tizimi", "планеты"], "solar_system", {}),
    (["сатурн", "saturn"], "planet", {"rings": True, "moons": 2, "tilt": 26.7}),
    (["юпитер", "jupiter", "yupiter"], "planet", {"moons": 4, "tilt": 3}),
    (["земля", "earth", "планета земля", "yer shari"], "planet", {"moons": 1, "tilt": 23.4}),
    (["марс", "mars"], "planet", {"moons": 2, "tilt": 25}), (["луна", "moon", "oy"], "planet", {"tilt": 6.7}),
    (["планета", "planet", "sayyora"], "planet", {}),
    (["arc reactor", "reactor", "реактор", "iron man", "fusion core", "power core"], "reactor", {}),
    (["днк", "dna", "ген", "геном"], "dna", {}), (["атом", "atom"], "atom", {}),
]


def _match(text, aliases):
    """Совпадение с учётом падежей: «лисы», «лошади», «Сатурна»."""
    import re as _re
    t = (text or "").lower().replace("’", "'").replace("ʻ", "'")
    words = _re.findall(r"[\w'-]+", t)
    for a in aliases:
        a = a.lower()
        if " " in a:
            if a in t:
                return True
            continue
        for w in words:
            # word endings (падежи) only for Cyrillic aliases — stops "chiron" matching Uzbek "chiroq" (lamp)
            if w == a or (len(a) >= 4 and _re.search(r"[а-яё]", a) and w.startswith(a[:-1]) and len(w) <= len(a) + 2):
                return True
    return False


def lib_index():
    try:
        return json.loads((LIB / "index.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def lookup(text):
    """Что есть мгновенно: своя библиотека → встроенные модели → готовые формы."""
    idx = lib_index()
    for name, e in idx.items():
        if _match(text, [name] + e.get("aliases", [])):
            return {"model": str(LIB / e["file"]), "motion": e.get("motion") or None, "source": e.get("source", "")}
    for aliases, url, motion, src in BUILTIN:
        if _match(text, aliases):
            return {"model": url, "motion": motion, "source": src}
    for aliases, arch, params in ARCHETYPES:
        if _match(text, aliases):
            return {"archetype": arch, "params": params}
    return None


# ---------------- real free 3D models (3dassets.dev, CC0, no account) ----------------
_STOP = {"a", "an", "the", "of", "3d", "model", "hologram", "show", "me", "and", "with", "in", "on"}
_BAD_CATS = {"environments"}
_BAD_TAGS = {"pixel", "kit", "modular"}


def _words(t):
    import re as _re
    return [w[:-1] if len(w) > 3 and w.endswith("s") else w for w in _re.findall(r"[a-z0-9]+", (t or "").lower()) if w not in _STOP]


def find_free_model(query, max_mb=15):
    """Best CC0 GLB whose name really matches the request, else None. ~0.5 s."""
    from urllib.parse import quote
    want = _words(query)
    if not want:
        return None
    try:
        r = _api(f"https://3dassets.dev/api/v1/assets?q={quote(' '.join(want))}&limit=12&sort=relevance", tries=1, timeout=3)
    except Exception:
        return None
    best, bscore = None, 0
    for a in r.get("data") or []:
        title = (a.get("title") or "").split("(")[0]
        tw = set(_words(title))
        if not all(w in tw for w in want):          # every word of the request must be in the model's own name
            continue
        st = a.get("stats") or {}
        tags = {t.get("slug") for t in a.get("tags") or []}
        if (a.get("category") or {}).get("slug") in _BAD_CATS or tags & _BAD_TAGS:
            continue
        if (st.get("fileSize") or 0) > max_mb * 1e6 or not a.get("cdnUrl"):
            continue
        tri = st.get("triangles") or 0
        tl = _words(title)
        extra = len(set(tl) - set(want))
        import re as _re
        full = [w[:-1] if len(w) > 3 and w.endswith("s") else w for w in _re.findall(r"[a-z0-9]+", title.lower())]
        nxt = [full[i + 1] if i + 1 < len(full) else None for i, w in enumerate(full) if w == want[-1]]
        keep = {None, "with", "on", "in", "and", "at", "from", "for", "set", "pair", "bull", "cow", "calf", "adult", "young", "male", "female", "hd", "model"}
        if not any(n in keep for n in nxt):              # "elephant seal" is a seal, "guitar stand" is a stand
            continue
        head = 6 if full and full[-1] == want[-1] else 2
        sc = 12 + head - 3 * extra + (2 if "realistic" in tags else 0) + (2 if 3000 <= tri <= 250000 else 0) - (3 if tri < 800 else 0)
        if sc > bscore:
            best, bscore = a, sc
    if not best:
        return None
    return {"url": best["cdnUrl"], "title": best.get("title", ""), "animated": bool((best.get("stats") or {}).get("animations")),
            "source": "3dassets.dev · CC0"}


def _sketchfab_key():
    try:
        return (HOME / "data" / "sketchfab_key").read_text().strip()
    except OSError:
        return ""


def find_sketchfab(query, max_mb=15):
    """Second library for one-offs (Eiffel Tower...): Sketchfab, free downloadable CC models.
    Needs a free personal key in data/sketchfab_key (run 'Set Sketchfab key.command'). Returns a local .glb or None."""
    key = _sketchfab_key()
    want = _words(query)
    if not key or not want:
        return None
    from urllib.parse import quote
    try:
        r = _api(f"https://api.sketchfab.com/v3/search?type=models&downloadable=true&count=12&q={quote(' '.join(want))}",
                 tries=1, timeout=4)
    except Exception:
        return None
    best, bscore = None, -99
    for m in r.get("results") or []:
        name_w = _words(m.get("name", ""))
        if not all(w in name_w for w in want):
            continue
        glb = (m.get("archives") or {}).get("glb") or {}
        size = glb.get("size") or 0
        faces = m.get("faceCount") or 0
        if not glb or size > max_mb * 1e6 or faces > 600_000:
            continue
        sc = 10 - 3 * len(set(name_w) - set(want)) + (2 if 2000 <= faces <= 300_000 else 0) + min(3, (m.get("likeCount") or 0) // 50)
        if sc > bscore:
            best, bscore = m, sc
    if not best:
        return None
    try:
        req = urllib.request.Request(f"https://api.sketchfab.com/v3/models/{best['uid']}/download",
                                     headers={"Authorization": f"Token {key}", "User-Agent": UA["User-Agent"]})
        with urllib.request.urlopen(req, timeout=8) as resp:
            dl = json.loads(resp.read().decode("utf-8"))
        url = (dl.get("glb") or {}).get("url")
        if not url:
            return None
        _mk(CACHE)
        out = CACHE / f"sketchfab_{best['uid']}.glb"
        if not out.exists():
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as resp:
                out.write_bytes(resp.read(max_mb * 1024 * 1024 + 1))
        lic = best.get("license")
        lic = (lic.get("label") if isinstance(lic, dict) else lic) or "CC"
        who = (best.get("user") or {}).get("displayName") or "Sketchfab artist"
        return {"path": str(out), "title": best.get("name", ""), "animated": bool(best.get("animationCount")),
                "source": f"Sketchfab · {who} · {lic}"}
    except Exception as e:
        print("sketchfab:", e, file=sys.stderr)
        return None


# ---------------- поиск фото (Википедия / Wikimedia Commons) ----------------
def _api(url, tries=3, timeout=12):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AlfredHologram/1.0 (personal voice assistant on macOS; python-urllib)"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and i < tries - 1:  # Википедия просит не спешить — чуть ждём
                time.sleep(0.7 * (i + 1))
                continue
            raise


def find_images(query, wiki=None):
    """Фото предмета: главная картинка статьи Википедии + лучшие файлы Commons (запросы идут параллельно)."""
    from concurrent.futures import ThreadPoolExecutor
    from urllib.parse import quote

    def wiki_img(lang):
        try:
            title = wiki
            if not title:
                r = _api(f"https://{lang}.wikipedia.org/w/api.php?action=query&list=search&srsearch={quote(query)}&srlimit=1&format=json")
                hits = r.get("query", {}).get("search", [])
                title = hits[0]["title"] if hits else None
            if not title:
                return []
            r = _api(f"https://{lang}.wikipedia.org/w/api.php?action=query&titles={quote(title)}&prop=pageimages&piprop=thumbnail&pithumbsize=900&redirects=1&format=json")
            return [(p.get("thumbnail") or {}).get("source") for p in r.get("query", {}).get("pages", {}).values()
                    if (p.get("thumbnail") or {}).get("source")]
        except Exception:
            return []

    def commons(q):
        try:
            r = _api("https://commons.wikimedia.org/w/api.php?action=query&generator=search&gsrnamespace=6&gsrlimit=12"
                     f"&gsrsearch={quote(q)}&prop=imageinfo&iiprop=url|mime&iiurlwidth=900&format=json")
        except Exception:
            return []
        bad = ("map", "diagram", "chart", "graph", "logo", "flag", "coat of arms", "locator", "range", "distribution", "plan", "interior")
        good = ("transparent", "isolated", "render", "restoration", "studio", "cutout", "3d", "white background", "side view", "profile")
        scored = []
        for p in r.get("query", {}).get("pages", {}).values():
            ii = (p.get("imageinfo") or [{}])[0]
            u, mime, t = ii.get("thumburl") or ii.get("url"), ii.get("mime", ""), p.get("title", "").lower()
            if not u or "svg" in mime or "pdf" in mime or any(b in t for b in bad):
                continue
            sc = (2 if mime == "image/png" else 0) + sum(1 for g in good if g in t) + sum(1 for w in query.lower().split() if w in t)
            scored.append((sc, -p.get("index", 0), u))
        return [u for _, _, u in sorted(scored, reverse=True)]

    with ThreadPoolExecutor(4) as ex:
        fs = [ex.submit(wiki_img, "en"), ex.submit(commons, query + " filetype:bitmap")]
        en, c1 = [f.result() for f in fs]
    ru, c2 = ([] if en else wiki_img("ru")), ([] if len(c1) >= 3 else commons(query))
    out, seen = [], set()
    for u in (en or ru) + c1 + c2:
        if u and u not in seen and not u.lower().endswith(".svg.png"):
            seen.add(u)
            out.append(u)
    return out[:5]


def lib_save(name, src, motion=None, aliases=None):
    _mk(LIB)
    p = fetch(src)
    ext = p.suffix.lower() if p.suffix.lower() in (".glb", ".gltf") else ".glb"
    dst = LIB / (name.lower().replace(" ", "_") + ext)
    dst.write_bytes(p.read_bytes())
    idx = lib_index()
    idx[name.lower()] = {"file": dst.name, "source": str(src), "motion": motion or "", "aliases": aliases or [],
                         "saved": time.strftime("%Y-%m-%d")}
    (LIB / "index.json").write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Сохранено в библиотеку: {name} → {dst.name}")


# ---------------- фото → объём ----------------
_SESS = {}


def _depth_sess():
    """Depth network loaded once and kept warm (the first load costs ~10 s on an 8 GB Mac)."""
    if "s" not in _SESS:
        import onnxruntime as ort
        if not DEPTH_MODEL.exists():
            _mk(DEPTH_MODEL.parent)
            tmp = DEPTH_MODEL.with_suffix(".part")
            urllib.request.urlretrieve(DEPTH_URL, tmp)
            tmp.replace(DEPTH_MODEL)
        o = ort.SessionOptions()
        o.intra_op_num_threads = 4
        _SESS["s"] = ort.InferenceSession(str(DEPTH_MODEL), o, providers=["CPUExecutionProvider"])
    return _SESS["s"]


def _release_later(after=120, key="cut", timer="cut_timer"):
    """Free a network a few minutes after its last use (memory matters more than 1 s of speed)."""
    import threading
    t = _SESS.get(timer)
    if t:
        t.cancel()

    def drop():
        _SESS.pop(key, None)
        import gc
        gc.collect()
    t = threading.Timer(after, drop)
    t.daemon = True
    t.start()
    _SESS[timer] = t


def _cutout(img_bgr):
    """Subject mask from a real background-removal network (IS-Net). None if unavailable."""
    try:
        if "cut" not in _SESS:
            os.environ.setdefault("U2NET_HOME", str(HOME / "models" / "u2net"))
            try:
                import rembg  # noqa: F401
            except ImportError:  # installed on first photo hologram, not at setup (keeps the kit lean)
                import subprocess
                subprocess.run([str(HOME / "bin" / "uv"), "pip", "install", "--python", sys.executable, "-q", "rembg==2.0.67"],
                               timeout=900, capture_output=True)
            from rembg import new_session
            _SESS["cut"] = new_session("isnet-general-use")
        import cv2
        import numpy as np
        from PIL import Image
        from rembg import remove
        m = remove(Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)), session=_SESS["cut"], only_mask=True)
        _release_later()
        return np.array(m.convert("L"))
    except Exception as e:
        print("cutout:", e, file=sys.stderr)
        return None


def depth_map(img_path):
    """Карта глубины (нейросеть Depth Anything V2, прямо на Mac) + маска предмета. Возвращает два PNG data-URI."""
    import cv2
    import numpy as np
    import onnxruntime as ort
    if not DEPTH_MODEL.exists():
        _mk(DEPTH_MODEL.parent)
        tmp = DEPTH_MODEL.with_suffix(".part")
        urllib.request.urlretrieve(DEPTH_URL, tmp)
        tmp.replace(DEPTH_MODEL)
    img = cv2.imread(str(img_path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise SystemExit("Не смог открыть картинку.")
    alpha = None
    if img.ndim == 3 and img.shape[2] == 4:
        alpha = img[:, :, 3]
        img = img[:, :, :3]
    elif img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    h, w = img.shape[:2]
    k = 640 / max(h, w)
    if k < 1:
        img = cv2.resize(img, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA)
        if alpha is not None:
            alpha = cv2.resize(alpha, (img.shape[1], img.shape[0]))
        h, w = img.shape[:2]
    x = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), (518, 518)).astype(np.float32) / 255.0
    x = ((x - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]).transpose(2, 0, 1)[None].astype(np.float32)
    sess = _depth_sess()
    _release_later(180, "s", "depth_timer")
    d = sess.run(None, {sess.get_inputs()[0].name: x})[0][0]
    d = cv2.resize(d, (w, h))
    d = (d - d.min()) / max(1e-6, d.max() - d.min())
    # маска: ближнее (Оцу по глубине) и/или отличие от цвета фона по краям
    d8 = (d * 255).astype(np.uint8)
    _, near = cv2.threshold(d8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    border = np.concatenate([img[0], img[-1], img[:, 0], img[:, -1]]).astype(np.float32)
    bg = np.median(border, axis=0)
    diff = np.linalg.norm(img.astype(np.float32) - bg, axis=2)
    colmask = (diff > 40).astype(np.uint8) * 255
    mask = cv2.bitwise_and(near, cv2.dilate(colmask, np.ones((5, 5), np.uint8))) if colmask.mean() > 20 else near
    cut = None if alpha is not None else _cutout(img)
    if cut is not None and (cut > 128).mean() > 0.03:
        mask = np.where(cut > 128, 255, 0).astype(np.uint8)
    if alpha is not None:
        mask = cv2.bitwise_and(mask, (alpha > 40).astype(np.uint8) * 255)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask)
    if n > 1:  # оставляем самый крупный предмет
        big = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        mask = np.where(lab == big, 255, 0).astype(np.uint8)
    mask = cv2.GaussianBlur(mask, (5, 5), 0)
    rgba = np.dstack([d8, d8, d8, mask])
    ok1, b1 = cv2.imencode(".png", rgba)
    ok2, b2 = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return ("data:image/png;base64," + base64.b64encode(b1.tobytes()).decode(),
            "data:image/jpeg;base64," + base64.b64encode(b2.tobytes()).decode(), float((mask > 128).mean()))


def normalize(spec, progress=True):
    if not isinstance(spec, dict):
        raise SystemExit("Нужен JSON-объект.")
    spec = dict(spec)
    spec["id"] = f"h{int(time.time() * 1000)}"
    query = spec.pop("search", None)
    wiki = spec.pop("wiki", None)
    if not any(spec.get(k) for k in ("model", "image", "archetype", "code")):
        hit = lookup(" ".join(filter(None, [spec.get("title"), query, wiki])))
        if hit:
            for k, v in hit.items():
                if v and not spec.get(k):
                    spec[k] = v
        elif (query or spec.get("title")) and spec.get("relief") is not True and \
                (fm := (find_free_model(query or spec.get("title")) or
                        (lambda sf: sf and {**sf, "url": sf["path"]})(find_sketchfab(wiki or query or spec.get("title"))))):
            # a real 3D model beats a photo: free CC0 library first, then Sketchfab (if you added a key)
            spec["model"] = fm["url"]
            spec.setdefault("source", fm["source"])
            spec.setdefault("motion", None if fm["animated"] else "turntable")
            try:  # keep it: next time it is instant and offline
                lib_save((query or spec.get("title")).lower(), fm["url"], spec.get("motion") or "",
                         list({(spec.get("title") or "").lower(), (query or "").lower()} - {""}))
            except Exception as e:
                print("lib save:", e, file=sys.stderr)
        elif query or wiki or spec.get("title"):
            if progress:  # сразу заставка — сэр видит, что голограмма уже строится
                write({"archetype": "loading", "title": spec.get("title", ""), "kicker": "SCANNING ARCHIVES",
                       "id": f"l{int(time.time() * 1000)}", "duration": 120})
            urls = find_images(query or wiki or spec.get("title"), wiki)
            for u in urls[:3]:
                try:
                    p = fetch(u, max_mb=25)
                    dmap, photo, cover = depth_map(p)
                except Exception:
                    continue
                if 0.06 < cover < 0.9:
                    spec.update({"depth": dmap, "image": photo, "archetype": "relief"})
                    spec.setdefault("source", "Wikimedia Commons")
                    break
            if not spec.get("archetype"):
                spec["archetype"] = "planet" if "planet" in (query or "").lower() else "loading"
    m = spec.get("model")
    if m:
        idx = lib_index()
        if str(m).lower() in idx:
            e = idx[str(m).lower()]
            m = str(LIB / e["file"])
            spec.setdefault("motion", e.get("motion") or None)
        if str(m).lower().split("?")[0].endswith(".gltf") and str(m).startswith("http"):
            spec["model"] = m  # .gltf с отдельными файлами — грузим прямо по ссылке
        else:
            p = fetch(m)
            try:  # big models: pass a file path (pasting 10 MB as text costs ~3x RAM); small ones stay inline
                rel = p.resolve().relative_to(HOME.resolve())
            except ValueError:
                rel = None
            spec["model"] = str(rel) if (rel and p.stat().st_size > 3_000_000) else data_uri(p, "model/gltf-binary")
        spec["archetype"] = "model"
    img = spec.get("image")
    if img and not str(img).startswith("data:"):
        p = fetch(img, max_mb=25)
        if spec.get("relief", True) and spec.get("archetype") in (None, "image", "relief"):
            dmap, photo, cover = depth_map(p)
            spec["depth"], spec["image"], spec["archetype"] = dmap, photo, "relief"
            if cover < 0.02:
                print("Предупреждение: на фото почти не нашёл предмет — возьми фото на однотонном фоне.", file=sys.stderr)
        else:
            mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
            spec["image"] = data_uri(p, mime)
    if spec.get("motion") is None:
        spec.pop("motion", None)
    return spec


def write(spec):
    _mk(SPEC.parent)
    tmp = SPEC.with_suffix(f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(tmp, 0o666)
    except OSError:
        pass
    tmp.replace(SPEC)


def show(spec):
    t0 = time.time()
    spec = normalize(spec)
    write(spec)
    try:  # для ночного обучения: что показывали и как
        with open(HOME / "data" / "log.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": int(time.time()), "type": "holo", "title": spec.get("title", ""),
                                "archetype": spec.get("archetype"), "seconds": round(time.time() - t0, 1)}, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return f"Голограмма на экране: {spec.get('title', '')} ({spec.get('archetype', '')})."


SOCK = Path("/tmp") / f"alfred-holo-{USER}.sock"


def serve():
    """Runs inside Alfred: keeps the depth network and libraries warm, builds holograms in ~1-3 s."""
    import socket
    import threading
    lock = threading.Lock()

    def warm():
        with lock:  # requests that arrive meanwhile simply wait for the warm network
            try:
                import cv2  # noqa: F401
                # networks are NOT preloaded: on an 8 GB Mac idle RAM matters more than 2 s on the first photo hologram
            except Exception as e:
                print("holo warm-up:", e, file=sys.stderr)
    threading.Thread(target=warm, daemon=True).start()
    if SOCK.exists():
        SOCK.unlink()  # stale socket from a previous run (not user data)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(SOCK))
    os.chmod(SOCK, 0o600)
    srv.listen(4)

    def handle(c):
        with c:
            buf = b""
            while True:
                b = c.recv(65536)
                if not b:
                    break
                buf += b
            try:
                with lock:
                    msg = show(json.loads(buf.decode("utf-8")))
            except BaseException as e:
                msg = f"Ошибка голограммы: {e}"
            try:
                c.sendall(msg.encode("utf-8"))
            except OSError:
                pass

    while True:
        c, _ = srv.accept()
        threading.Thread(target=handle, args=(c,), daemon=True).start()


def _via_server(spec):
    import socket
    if not SOCK.exists():
        return None
    try:
        c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        c.settimeout(150)
        c.connect(str(SOCK))
        c.sendall(json.dumps(spec, ensure_ascii=False).encode("utf-8"))
        c.shutdown(socket.SHUT_WR)
        out = b""
        while True:
            b = c.recv(65536)
            if not b:
                break
            out += b
        c.close()
        return out.decode("utf-8") or None
    except OSError:
        return None


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    force = "--force" in argv
    argv = [a for a in argv if a != "--force"]
    cmd = argv[0] if argv else ""
    if not force and cmd not in ("clear", "hide", "убрать", "prefetch", "save", "serve"):
        try:  # holograms are OFF by default: only on an explicit request (--force)
            import menubar
            if menubar.holo_mode() == "off":
                print("Holograms are off. Not shown (use --force only if he explicitly asked).")
                return 0
        except Exception:
            pass
    if cmd in ("clear", "hide", "убрать"):
        write({"hide": True, "id": f"x{int(time.time() * 1000)}"})
        print("Голограмма убрана.")
        return 0
    if cmd == "prefetch":  # заранее скачать модели поменьше и нейросеть глубины — чтобы всё показывалось мгновенно
        for aliases, url, motion, src in BUILTIN:
            try:
                req = urllib.request.Request(url, method="HEAD", headers=UA)
                with urllib.request.urlopen(req, timeout=20) as r:
                    size = int(r.headers.get("Content-Length") or 0)
                if size < 12_000_000:
                    fetch(url)
            except Exception as e:
                print("не скачал", url, e, file=sys.stderr)
        if not DEPTH_MODEL.exists():
            _mk(DEPTH_MODEL.parent)
            tmp = DEPTH_MODEL.with_suffix(".part")
            urllib.request.urlretrieve(DEPTH_URL, tmp)
            tmp.replace(DEPTH_MODEL)
        print("Готово: модели и нейросеть глубины на месте.")
        return 0
    if cmd == "lib":
        idx = lib_index()
        print(json.dumps(idx, ensure_ascii=False, indent=1) if idx else "Библиотека пуста.")
        return 0
    if cmd == "save":
        lib_save(argv[1], argv[2], argv[3] if len(argv) > 3 else None, argv[4].split(",") if len(argv) > 4 else None)
        return 0
    if cmd == "depth":
        _, _, cover = depth_map(fetch(argv[1], max_mb=25))
        print(f"OK, предмет занимает {cover * 100:.0f}% кадра")
        return 0
    if cmd == "loading":
        write({"archetype": "loading", "title": argv[1] if len(argv) > 1 else "", "id": f"l{int(time.time() * 1000)}",
               "kicker": "SCANNING ARCHIVES", "duration": 240})
        print("Показываю «сканирую архивы…»")
        return 0
    spec = json.loads(sys.stdin.read() if cmd == "-" else " ".join(argv))
    msg = _via_server(spec)
    print(msg or show(spec))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except json.JSONDecodeError as e:
        print(f"Ошибка JSON: {e}", file=sys.stderr)
        sys.exit(2)

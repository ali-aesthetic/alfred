#!/usr/bin/env python3
"""Alfred personal memory: local search (BM25 + title/heading/link boosts) over
Alfred's OWN copy of the user's Obsidian vault.

  brain_rag.py sync                 one-way copy ORIGINAL Brain -> brain-copy (never writes to the original)
  brain_rag.py index                (re)build the index
  brain_rag.py search "q" [-k 5]    JSON results: path, title, snippet, score
  brain_rag.py profile              short "who is the user" summary (cached in _Alfred/About the user.md)
  brain_rag.py note "title" "text"  write/append a note ONLY inside brain-copy/_Alfred/

Never deletes: stale files and old indexes are MOVED to Alfred/to delete/.
Pure standard library. Meaning-search without embeddings: EN/RU/UZ seed synonyms + PMI co-occurrence +
link graph, query expansion (x0.35), light stemming, typo-tolerant. No embedding model exists offline.
"""
import argparse, json, math, os, pickle, re, shutil, subprocess, sys, time
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.abspath(os.path.realpath(__file__)))
def _notes_folder():
    """Optional: your own notes folder (e.g. an Obsidian vault), set as "notes_folder" in config.json. Off by default. READ ONLY."""
    try:
        with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
            p = (json.load(f).get("notes_folder") or "").strip()
        return os.path.expanduser(p) if p else None
    except Exception:
        return None


ORIGINAL = _notes_folder()
COPY = os.path.join(ROOT, "data", "brain-copy")
INDEX_DIR = os.path.join(ROOT, "data", "brain-index")
INDEX_FILE = os.path.join(INDEX_DIR, "index.pkl")
TRASH = os.path.join(ROOT, "to delete")
OWN = ("_Alfred", "_User profile")          # never overwritten by sync
SKIP_DIRS = {".obsidian", ".trash", "to delete", ".git"}
SECRET = re.compile(r"sk-[A-Za-z0-9_-]{16,}|AIza[0-9A-Za-z_-]{20,}|(api[_-]?key|password|token|secret)\s*[:=]\s*\S{8,}", re.I)

STOP = set(("the a an and or of to in on for is are was were be it this that with as at by from my me i you your what when where who how do does did "
            "about next much many some any can could should would will have has had not but so if then там тут для и в во на с со по за из к о об от до как что это я мой моя мои "
            "мне у не но или же бы ли").split())
INDEX_VER = 3
EXPAND_W = 0.35        # weight of synonym / related-term expansions (original terms = 1.0)
FUZZY_W = 0.8          # weight of a typo-corrected term
NEIGHBOUR_W = 0.10     # link-graph neighbour boost (fraction of the neighbour parent's score)

RU_SUF = sorted("""ами ями ого его ому ему ыми ими ая яя ое ее ые ие ый ий ой ую юю ых их ом ем ам ям ах ях ов ев ей ою ею
ать ять ить еть ует уют ают яют ил ила или ило ал ала али ало ен ена ено ны на но ть ся сь а я о е ы и у ю ь""".split(), key=len, reverse=True)


def stem(w):
    """Light EN + RU stemmer. Cheap and consistent (price/pricing/prices -> pric)."""
    if w.isascii():
        if len(w) > 4 and w.endswith("ies"):
            w = w[:-3] + "y"
        elif len(w) > 5 and w.endswith("ing"):
            w = w[:-3]
        elif len(w) > 4 and w.endswith("ed"):
            w = w[:-2]
        elif len(w) > 4 and w.endswith("es") and w[-3] in "sxzh":
            w = w[:-2]
        elif len(w) > 3 and w.endswith("s") and not w.endswith("ss") and not w.endswith("us"):
            w = w[:-1]
        if len(w) > 5 and w.endswith("ly"):
            w = w[:-2]
        if len(w) > 3 and w[-1] == w[-2] and w[-1] not in "lsz":
            w = w[:-1]
        if len(w) > 3 and w.endswith("e"):
            w = w[:-1]
        return w
    for s in RU_SUF:
        if len(w) - len(s) >= 3 and w.endswith(s):
            return w[:-len(s)]
    return w


def tok(text):
    out = []
    for w in re.findall(r"[\w']+", text.lower()):
        w = w.strip("_'").replace("'", "").replace("ё", "е")
        if len(w) < 2 or w in STOP:
            continue
        out.append(stem(w))
    return out


# Hand-made bilingual EN / RU / UZ seed groups (every word in a group relates to the others).
SEED = """
video clip reel footage film movie ролик видео клип фильм кино reels kino
edit editing montage cut cutting trim монтаж смонтировать монтировать правки montaj tahrir
app application program software tool приложение прилож программа ilova dastur
site website web page portfolio сайт страница veb sayt
chess шахматы шахмат shaxmat uzchess
game gaming play player игра игры играть o'yin oyin
price cost pricing pay paid payment fee cheap expensive spend budget cena цена стоимость стоит цены дорого дешево narx to'lov tolov
money credit credits balance cash dollar usd деньги кредит кредиты баланс бюджет pul kredit hisob
deadline due overdue late schedule срок дедлайн сроки muddat
essay coursework assignment homework paper writing ielts report exam test study эссе задание домашка экзамен учеба vazifa imtihon insho
lecture class course lesson university uni teacher professor prof lecturer лекция урок курс универ университет преподаватель профессор dars ustoz kurs
music song track audio sound beat voice sing songs музыка песня трек звук голос аудио musiqa qo'shiq ovoz
phone iphone mobile ios android phone's телефон айфон мобильный telefon
photo picture image pic thumbnail cover photograph фото картинка изображение обложка rasm surat
cartoon animation animated kids children child kid мультик мультфильм анимация дети детский bolalar multfilm
car auto vehicle machine kia авто машина машину mashina avto
job work career hire hiring cv resume interview работа вакансия резюме собеседование ish
plan planning roadmap strategy steps checklist todo task tasks план задача задачи reja vazifalar
bug fix error broken crash problem issue fail ошибка баг проблема сломалось xato
test testing verify check qa проверка тест tekshiruv
idea ideas concept pitch brainstorm идея идеи mysl g'oya
friend friends family dad mom farm друг друзья семья папа мама оtets do'st oila
note notes vault obsidian brain memory memories заметка заметки память eslatma
voice speak speech say talk talking mic microphone голос речь говорить микрофон
ad ads advert advertising promo promotion marketing реклама промо reklama
brand logo design designer identity бренд логотип дизайн
reel reels instagram insta social tiktok shorts соцсети инстаграм
subtitle subtitles caption captions subs субтитры
render export rendering encode экспорт рендер
thumbnail preview cover youtube обложка превью
upload download send share залить скачать отправить
learn learning lesson tutorial course study учить урок обучение o'rganish
meeting call interview созвон встреча звонок uchrashuv
travel flight airline ticket airport trip uzairways путешествие билет перелет самолет
food drink burger restaurant cafe salmon еда напиток ресторан
health body gym workout sport fitness тело спорт зал
mac macbook laptop computer компьютер ноутбук
backup restore copy archive бэкап копия архив
character characters sheet персонаж персонажи герой
location scene set place локация сцена
prompt prompts instruction instructions промпт
model models ai gpt claude нейросеть модель
"""


def seed_map():
    m = defaultdict(set)
    for line in SEED.strip().splitlines():
        ws = {stem(w.replace("'", "").replace("ё", "е")) for w in line.lower().split()}
        ws = {w for w in ws if len(w) > 1}
        for w in ws:
            m[w] |= ws - {w}
    return m


def trash(src, sub):
    """Move (never delete) into Alfred/to delete/<sub>/."""
    dst_dir = os.path.join(TRASH, sub)
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, os.path.basename(src))
    if os.path.exists(dst):
        dst += time.strftime(".%Y%m%d-%H%M%S")
    shutil.move(src, dst)
    return dst


# ---------------------------------------------------------------- sync
def cmd_sync(_a):
    if not ORIGINAL or not os.path.isdir(ORIGINAL):
        sys.exit("original Brain not found")
    os.makedirs(COPY, exist_ok=True)
    ex = [f"--exclude={d}" for d in sorted(SKIP_DIRS)] + [f"--exclude=/{d}" for d in OWN]
    # no --delete, ever. Source is only read.
    r = subprocess.run(["rsync", "-a", "--itemize-changes", *ex, ORIGINAL + "/", COPY + "/"],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr)
    changed = len([l for l in r.stdout.splitlines() if l.startswith(">f")])
    # stale: in copy but gone from the original -> move to "to delete"
    stale = 0
    for dp, dns, fns in os.walk(COPY):
        rel = os.path.relpath(dp, COPY)
        dns[:] = [d for d in dns if d not in SKIP_DIRS and not (rel == "." and d in OWN)]
        for f in fns:
            p = os.path.join(dp, f)
            r2 = os.path.relpath(p, COPY)
            if not os.path.exists(os.path.join(ORIGINAL, r2)):
                trash(p, "brain-stale/" + os.path.dirname(r2).replace("/", "_"))
                stale += 1
    print(json.dumps({"updated": changed, "stale_moved_to_trash": stale}))


# ---------------------------------------------------------------- index
def parse(path, rel):
    raw = open(path, errors="ignore").read()
    fm = {}
    body = raw
    m = re.match(r"---\n(.*?)\n---\n?", raw, re.S)
    if m:
        body = raw[m.end():]
        for l in m.group(1).splitlines():
            if ":" in l:
                k, v = l.split(":", 1)
                fm[k.strip()] = v.strip()
    h1 = re.search(r"^#\s+(.+)$", body, re.M)
    base = os.path.splitext(os.path.basename(rel))[0]
    parent = os.path.basename(os.path.dirname(rel))
    title = base if base not in ("Status", "Home") else (parent or base) + " / " + base
    heads = " ".join(re.findall(r"^#{1,6}\s+(.+)$", body, re.M))
    links = [l.split("|")[0].split("#")[0].strip() for l in re.findall(r"\[\[([^\]]+)\]\]", body)]
    tags = fm.get("tags", "") + " " + fm.get("hub", "") + " " + fm.get("aliases", "") + " " + fm.get("alias", "")
    return dict(rel=rel, title=title, h1=h1.group(1) if h1 else "", heads=heads, body=body, links=links, tags=tags, mtime=os.path.getmtime(path))


def build_syn(docs, inv, names):
    """term -> {related term: weight 0..1}. Hand seed (1.0) + paragraph co-occurrence NPMI +
    title/alias/tag/[[link]]-title groupings. Built once at index time."""
    N = len(docs)
    df = {w: len(p) for w, p in inv.items()}
    maxdf = max(8, int(N * 0.25))
    keep = lambda w: 2 <= df.get(w, 0) <= maxdf and len(w) > 2
    pc, pairs, npar = Counter(), Counter(), 0

    def add_group(ts):
        nonlocal npar
        ts = sorted({t for t in ts if keep(t)}, key=lambda t: df[t])[:30]
        if len(ts) < 2:
            return
        npar += 1
        for t in ts:
            pc[t] += 1
        for x in range(len(ts)):
            for y in range(x + 1, len(ts)):
                pairs[(ts[x], ts[y])] += 1

    for d in docs:
        paras = [p for p in re.split(r"\n\s*\n|\n(?=#)", d["body"]) if len(p) > 25]
        for p in paras:
            add_group(tok(p))
        # title + headings + tags/aliases + titles of linked notes = one strong "concept" group
        meta = d["title"] + " " + d["heads"] + " " + d["tags"] + " " + " ".join(os.path.basename(l) for l in d["links"][:30])
        for _ in range(2):
            add_group(tok(meta))
    syn = defaultdict(dict)
    for (x, y), c in pairs.items():
        if c < 3:
            continue
        pxy = c / npar
        npmi = math.log(pxy / ((pc[x] / npar) * (pc[y] / npar))) / -math.log(pxy) if pxy < 1 else 0
        if npmi >= 0.4:
            syn[x][y] = syn[y][x] = round(min(0.9, npmi), 3)
    out = {}
    for w, rel in syn.items():
        out[w] = dict(sorted(rel.items(), key=lambda kv: -kv[1])[:6])
    for w, rel in seed_map().items():          # seed wins (weight 1.0), only words present in the vault vocabulary matter
        for r in rel:
            if r in inv or w in inv:
                out.setdefault(w, {})[r] = 1.0
    return out


def cmd_index(_a=None):
    t0 = time.time()
    docs = []
    for dp, dns, fns in os.walk(COPY):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for f in fns:
            if f.endswith(".md"):
                p = os.path.join(dp, f)
                docs.append(parse(p, os.path.relpath(p, COPY)))
    inv = defaultdict(list)   # term -> [(doc, weighted tf)]
    lens = []
    for i, d in enumerate(docs):
        tf = Counter()
        for w in tok(d["body"]):
            tf[w] += 1
        for w in tok(d["title"] + " " + d["rel"].replace("/", " ")):
            tf[w] += 6
        for w in tok(d["heads"] + " " + d["h1"] + " " + d["tags"]):
            tf[w] += 3
        lens.append(sum(tf.values()))
        for w, c in tf.items():
            inv[w].append((i, c))
    names = {os.path.splitext(os.path.basename(d["rel"]))[0].lower(): i for i, d in enumerate(docs)}
    inlinks = Counter()
    nbr = defaultdict(set)    # undirected [[link]] graph
    for i, d in enumerate(docs):
        for l in set(d["links"]):
            j = names.get(os.path.basename(l).lower())
            if j is not None:
                inlinks[j] += 1
                if j != i:
                    nbr[i].add(j)
                    nbr[j].add(i)
    syn = build_syn(docs, inv, names)
    slim = [{k: d[k] for k in ("rel", "title", "mtime")} | {"text": d["body"][:20000]} for d in docs]
    data = dict(ver=INDEX_VER, docs=slim, inv=dict(inv), lens=lens, inlinks=dict(inlinks),
                nbr={k: sorted(v) for k, v in nbr.items()}, syn=syn, built=time.time())
    os.makedirs(INDEX_DIR, exist_ok=True)
    if os.path.exists(INDEX_FILE):   # keep old versions (copied to trash, never deleted); swap is atomic
        d_ = os.path.join(TRASH, "brain-index-old")
        os.makedirs(d_, exist_ok=True)
        shutil.copy2(INDEX_FILE, os.path.join(d_, time.strftime("index.%Y%m%d-%H%M%S.pkl")))
    tmp = INDEX_FILE + ".tmp%d" % os.getpid()
    with open(tmp, "wb") as fh:
        pickle.dump(data, fh, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, INDEX_FILE)
    global _IDX
    _IDX = None
    print(json.dumps({"notes": len(docs), "terms": len(inv), "syn_terms": len(syn), "secs": round(time.time() - t0, 2)}))


# ---------------------------------------------------------------- search
_IDX = None
_VOC = {}


def load():
    global _IDX, _VOC
    if _IDX is None:
        ix = None
        if os.path.exists(INDEX_FILE):
            try:
                with open(INDEX_FILE, "rb") as fh:
                    ix = pickle.load(fh)
            except Exception:
                ix = None
        if not ix or ix.get("ver") != INDEX_VER:
            cmd_index()
            with open(INDEX_FILE, "rb") as fh:
                ix = pickle.load(fh)
        voc = defaultdict(list)
        for t in ix["inv"]:
            voc[len(t)].append(t)
        _VOC = voc
        _IDX = ix
    return _IDX


def _ed1(a, b):
    """True if Damerau edit distance(a, b) == 1 (a != b)."""
    la, lb = len(a), len(b)
    if la == lb:
        d = [i for i in range(la) if a[i] != b[i]]
        if len(d) == 1:
            return True
        return len(d) == 2 and d[1] == d[0] + 1 and a[d[0]] == b[d[1]] and a[d[1]] == b[d[0]]
    if la > lb:
        a, b, la, lb = b, a, lb, la
    if lb - la != 1:
        return False
    i = 0
    while i < la and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


def fuzzy(w, inv):
    if len(w) < 5:
        return []
    c = [t for L in (len(w) - 1, len(w), len(w) + 1) for t in _VOC.get(L, ()) if _ed1(w, t)]
    return sorted(c, key=lambda t: -len(inv[t]))[:3]


def snippet(text, qt, n=240):
    text = re.sub(r"\[\[([^\]|]+)\|?[^\]]*\]\]", r"\1", text)
    text = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S)
    best, bs = "", -1
    for para in re.split(r"\n\s*\n|\n(?=#)", text):
        p = para.strip()
        if not p:
            continue
        s = len(set(tok(p)) & qt) - (0.3 if p.startswith("|---") else 0)
        if s > bs:
            best, bs = p, s
    best = re.sub(r"\s+", " ", best)
    return best[:n] + ("…" if len(best) > n else "")


def expand_query(qt, inv, syn):
    """-> {term: weight}. Originals 1.0; synonyms/related 0.35*rel; typo fixes 0.8; prefix fallback 0.5."""
    wt = {}
    for w in qt:
        if w in inv:
            wt[w] = 1.0
        else:
            fz = fuzzy(w, inv)
            for t in fz:
                wt[t] = max(wt.get(t, 0), FUZZY_W)
            if not fz and len(w) >= 3:
                for t in [t for t in inv if t.startswith(w)][:5]:
                    wt[t] = max(wt.get(t, 0), 0.5)
    base = dict(wt)
    for w in list(qt) + [t for t in base if t not in qt]:
        cand = [(r, rw) for r, rw in syn.get(w, {}).items() if r in inv and r not in base]
        cand.sort(key=lambda kv: (-kv[1], -len(inv[kv[0]])))
        for r, rw in cand[:6]:
            wt[r] = max(wt.get(r, 0), EXPAND_W * rw * (base.get(w, 1.0)))
    return wt


def search(q, k=5):
    ix = load()
    docs, inv, lens = ix["docs"], ix["inv"], ix["lens"]
    N = len(docs)
    avg = sum(lens) / max(N, 1)
    qt = tok(q)
    wt = expand_query(qt, inv, ix.get("syn", {}))
    scores = defaultdict(float)
    for w, qw in wt.items():
        pl = inv[w]
        idf = math.log(1 + (N - len(pl) + 0.5) / (len(pl) + 0.5))
        for i, tf in pl:
            scores[i] += qw * idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * lens[i] / avg))
    ql = q.lower().strip()
    for i in list(scores):
        d = docs[i]
        t = d["title"].lower()
        if ql in t:
            scores[i] *= 1.6
        elif qt and all(w in tok(t + " " + d["rel"]) for w in qt):
            scores[i] *= 1.3
        tt = set(tok(t))
        th = sum(1 for w in wt if w in tt)
        if th:
            scores[i] *= 1 + 0.12 * min(th, 3)     # title contains a query term or one of its synonyms
        scores[i] *= 1 + min(ix["inlinks"].get(i, 0), 20) * 0.01
        if d["rel"].startswith("_Ali profile/"):
            scores[i] *= 1.5
        if d["rel"].startswith("_Alfred/"):
            scores[i] *= 1.1
        if os.path.basename(d["rel"]) in ("Status.md",):
            scores[i] *= 1.05
    # link graph: notes linked to the best matches get a small boost
    nbr = ix.get("nbr", {})
    best = sorted(scores.items(), key=lambda x: -x[1])[:3]
    for i, s in best:
        for j in nbr.get(i, ()):
            if j in scores:
                scores[j] += NEIGHBOUR_W * s
    top = sorted(scores.items(), key=lambda x: -x[1])[:k]
    qs = set(wt)
    return [dict(path=os.path.join(COPY, docs[i]["rel"]), note=docs[i]["title"], title=docs[i]["title"],
                 snippet=snippet(docs[i]["text"], qs), score=round(s, 3)) for i, s in top]


def cmd_search(a):
    print(json.dumps(search(a.query, a.k), ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- profile
def fmrow(text, key):
    m = re.search(r"^\|\s*" + key + r"\s*\|\s*(.+?)\s*\|", text, re.M)
    return m.group(1) if m else ""


def cmd_profile(a=None):
    P = os.path.join(COPY, "_User profile")
    def rd(n):
        try:
            return open(os.path.join(P, n), errors="ignore").read()
        except OSError:
            return ""
    prof, now, style, op = rd("me-profile.md"), rd("now.md"), rd("me-style.md"), rd("me-operating-manual.md")
    out = ["---", "tags: [alfred, profile]", f"updated: {time.strftime('%Y-%m-%d')}", "---", "# About the user", "",
           "Auto-built by brain_rag.py profile. Sources: [[me-profile]], [[now]], [[me-style]], [[me-operating-manual]] and project Status notes.", ""]
    out.append("## Basics")
    for key in ("📍", "🎓", "🗣️", "🎯"):
        for m in re.finditer(r"^\|\s*" + re.escape(key) + r"\s*\|\s*(.+?)\s*\|", prof, re.M):
            out.append("- " + m.group(1))
    out += ["", "## How to talk to him (preferences)"]
    for m in re.finditer(r"^\|\s*(?!Rule|---)[^|]*\|\s*(?!Detail\s*\|)\s*(.+?)\s*\|\s*$", style, re.M):
        if m.group(1).strip() != "Detail":
            out.append("- " + re.sub(r"\*\*", "", m.group(1))[:140])
    out += ["", "## Routines and patterns"]
    for m in re.finditer(r"^\|\s*(?!Loop|---)([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*$", op, re.M):
        if "Agent response" not in m.group(0):
            out.append(f"- {m.group(1).strip()}: {m.group(3).strip()}")
    m = re.search(r"WIP limit[^\n]*\n```\n(.*?)```", now, re.S)
    out.append("- Works in lanes: School, Job search, Social project, ONE build, Body (WIP limit 4 + 1 build)")
    out += ["", "## Projects (from Status notes)", "| Project | Status | Next step |", "|---|---|---|"]
    rows = []
    for dp, dns, fns in os.walk(COPY):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        if "Status.md" in fns and os.path.dirname(dp) == COPY:
            t = open(os.path.join(dp, "Status.md"), errors="ignore").read()
            st, nx = fmrow(t, "Status"), fmrow(t, "Next step")
            if st or nx:
                rows.append((os.path.basename(dp), st, nx))
    for n, st, nx in sorted(rows, key=lambda r: ("🟢" not in r[1], r[0])):
        out.append(f"| [[{n}/Status|{n}]] | {st[:30]} | {nx[:110]} |")
    text = "\n".join(out) + "\n"
    dst = os.path.join(COPY, "_Alfred", "About the user.md")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    open(dst, "w").write(text)
    print(text)


# ---------------------------------------------------------------- note
def cmd_note(a):
    safe = re.sub(r"[\\/:*?\"<>|#^\[\]]", " ", a.title).strip()[:80] or "note"
    d = os.path.join(COPY, "_Alfred")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, safe + ".md")
    text = a.text.strip()
    if SECRET.search(text):
        sys.exit("refused: looks like a key/password")
    stamp = time.strftime("%Y-%m-%d %H:%M")
    if os.path.exists(p):   # improve = append a dated section; never overwrite
        with open(p, "a") as fh:
            fh.write(f"\n\n## Update {stamp}\n{text}\n")
    else:
        with open(p, "w") as fh:
            fh.write(f"---\ntags: [alfred, learned]\ncreated: {stamp}\n---\n# {safe}\n\n{text}\n\nSee also [[About the user]]\n")
    cmd_index()
    print(json.dumps({"written": p}))


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("sync").set_defaults(f=cmd_sync)
    sp.add_parser("index").set_defaults(f=cmd_index)
    s = sp.add_parser("search"); s.add_argument("query"); s.add_argument("-k", type=int, default=5); s.set_defaults(f=cmd_search)
    sp.add_parser("profile").set_defaults(f=cmd_profile)
    n = sp.add_parser("note"); n.add_argument("title"); n.add_argument("text"); n.set_defaults(f=cmd_note)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()

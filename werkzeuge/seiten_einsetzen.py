"""Ersetzt eingebundene Scan-Seiten ({{SeitePR}}, <pages index=…>) durch ihren Text.
Aufruf: expand.py <korpus> <seiten-cache>"""
import os, re, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
SRC, CACHE = sys.argv[1], sys.argv[2]
UA = {"User-Agent": "EmilsHumanizer/1.0 (https://github.com/KimJongUnNK/EmilsHumanizer; style corpus)"}
os.makedirs(CACHE, exist_ok=True)

def cache_path(page):
    return os.path.join(CACHE, "".join(c if c.isalnum() else "_" for c in page)[:150] + ".wiki")

def fetch(page):
    target = cache_path(page)
    if os.path.exists(target):
        return
    for wait in (0, 10, 30, 60):
        time.sleep(wait)
        try:
            raw = urllib.request.urlopen(urllib.request.Request(
                "https://de.wikisource.org/w/index.php?action=raw&title=" + urllib.parse.quote(page.replace(" ", "_")),
                headers=UA), timeout=40).read().decode("utf-8")
            open(target, "w").write(raw)
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                open(target, "w").write("")
                break
        except Exception:
            pass
    time.sleep(0.6)

def needed(raw):
    pages = []
    for m in re.finditer(r"\{\{SeitePR\|([^|}]+)\|([^|}]+)(?:\|([^|}]*))?\}\}", raw):
        pages.append(("Seite:" + m.group(2).strip(), (m.group(3) or "").strip()))
    for m in re.finditer(r"<pages\s+([^>]*)/>", raw):
        attrs = dict(re.findall(r'(\w+)\s*=\s*"?([^"\s/]+(?: [^"\s/=]+)*)"?', m.group(1)))
        index, a, b = attrs.get("index"), attrs.get("from"), attrs.get("to")
        if index and a and b and a.isdigit() and b.isdigit() and int(b) - int(a) < 40:
            pages += [(f"Seite:{index}/{n}", "") for n in range(int(a), int(b) + 1)]
    # Für drei Auszüge zu je 400 Wörtern reichen die ersten zwei Druckseiten.
    return pages[:2]

def section(text, sec):
    if not sec:
        return text
    m = re.search(r'<section begin="?%s"?\s*/>(.*?)<section end="?%s"?\s*/>' % (re.escape(sec), re.escape(sec)), text, re.S)
    return m.group(1) if m else ""

files = []
for root, _, names in os.walk(SRC):
    files += [os.path.join(root, n) for n in names if n.endswith(".wiki")]
jobs = {}
for f in files:
    for page, _ in needed(open(f).read()):
        jobs[page] = True
print(len(files), "Dateien,", len(jobs), "Seiten zu holen", flush=True)
with ThreadPoolExecutor(4) as pool:
    for i, _ in enumerate(pool.map(fetch, jobs)):
        if i % 250 == 0:
            print(" ", i, "/", len(jobs), flush=True)
done = 0
for f in files:
    title, raw = open(f).read().split("\n", 1)
    parts = needed(raw)
    if not parts:
        continue
    text = "\n".join(section(open(cache_path(p)).read() if os.path.exists(cache_path(p)) else "", s) for p, s in parts)
    text = re.sub(r"<noinclude>.*?</noinclude>", "", text, flags=re.S)
    # Silbentrennung über Seitengrenzen: "Telegra-\n" + "phen" wieder zusammenfügen.
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
    open(f + ".expanded", "w").write(title + "\n" + text)
    done += 1
print("FERTIG", done, "Texte aufgefüllt", flush=True)

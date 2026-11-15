"""Holt Texte aus Wikisource-Kategorien über die normalen Seiten (die API drosselt zu stark).
Aufruf: fetch_cats.py <ziel> <gruppe>:<Kategorie>[:max] ..."""
import html, os, re, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
OUT = sys.argv[1]
UA = {"User-Agent": "EmilsHumanizer/1.0 (https://github.com/KimJongUnNK/EmilsHumanizer; style corpus)"}

def get(url):
    for wait in (0, 10, 30, 60, 120):
        time.sleep(wait)
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40).read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            print("  retry", e, url[:100], flush=True)
        except Exception as e:
            print("  retry", e, url[:100], flush=True)
    return None

def category(name, most):
    titles, url = [], "https://de.wikisource.org/wiki/Kategorie:" + urllib.parse.quote(name)
    while url and len(titles) < most:
        page = get(url) or ""
        seg = page[page.find('id="mw-pages"'):] if 'id="mw-pages"' in page else ""
        titles += [html.unescape(t) for t in re.findall(r'<li><a href="/wiki/[^"]+" title="([^"]+)"', seg)]
        nxt = re.search(r'href="(/w/index\.php\?title=Kategorie:[^"]*pagefrom=[^"]*)"[^>]*>nächste Seite', seg)
        url = "https://de.wikisource.org" + html.unescape(nxt.group(1)) if nxt else None
        time.sleep(3)
    return titles[:most]

seen = set()
for spec in sys.argv[2:]:
    group, cat, *rest = spec.split(":")
    most = int(rest[0]) if rest else 600
    titles = [t for t in category(cat, most) if t not in seen]
    seen.update(titles)
    folder = os.path.join(OUT, group, cat.replace(" ", "_"))
    os.makedirs(folder, exist_ok=True)
    print(group, cat, len(titles), "Texte", flush=True)

    def fetch(title, folder=folder):
        target = os.path.join(folder, "".join(c if c.isalnum() else "_" for c in title).strip("_")[:120] + ".wiki")
        if os.path.exists(target):
            return
        raw = get("https://de.wikisource.org/w/index.php?action=raw&title=" + urllib.parse.quote(title.replace(" ", "_")))
        if raw is not None:
            open(target, "w").write(title + "\n" + raw)
        time.sleep(0.6)

    with ThreadPoolExecutor(4) as pool:
        list(pool.map(fetch, titles))
    print("  fertig", cat, flush=True)
print("FERTIG", flush=True)

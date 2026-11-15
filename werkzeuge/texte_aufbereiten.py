"""Macht aus Wikisource-Rohtexten Stilvorlagen: nur Prosa, Auszüge von 150 bis 400 Wörtern, ohne Beleidigungen,
in heutiger Rechtschreibung. Aufruf: process_corpus.py <ordner mit autor/*.wiki> <zielordner>"""
import os, re, sys, unicodedata

BLOCK = re.compile(r"neger|nigger|zigeun|mohren|kaffer|hottentott|mulatt|rassen|untermensch|schwuchtel|"
                   r"hakenkreuz|hitler|judensau|judenrepublik|judenfahne|saujud|kanake|polack|itzig|weiber|weibsbild", re.I)
PSEUDONYMS = {"Peter Panter", "Theobald Tiger", "Ignaz Wrobel", "Kaspar Hauser", "Kurt Tucholsky", "Paulus Bünzly"}

def strip_markup(raw):
    t = re.sub(r"<!--.*?-->", "", raw, flags=re.S)
    t = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", "", t, flags=re.S)
    t = re.sub(r"<(noinclude|pages|poem|math|gallery|score|table)[^>]*/>", "", t)
    t = re.sub(r"<(noinclude|math|gallery|score|poem)[^>]*>.*?</\1>", "", t, flags=re.S)
    keep = re.compile(r"\{\{\s*(SperrSchrift|Sperrschrift|g|G|Kapitälchen|Antiqua|right|Right|center|Center|"
                      r"zentriert|Zentriert|Bruch|idt|idt2|Block|KapitälchenSchrift|uline)\s*\|([^{}]*)\}\}")
    for _ in range(12):
        t2 = keep.sub(lambda m: m.group(2).split("|")[0], t)
        t2 = re.sub(r"\{\{[^{}]*\}\}", "", t2)
        if t2 == t:
            break
        t = t2
    t = re.sub(r"\{\|.*?\|\}", lambda m: re.sub(r"^\s*[|!][-+}]?.*$", "", m.group(0)[2:-2], flags=re.M), t, flags=re.S)
    t = re.sub(r"\[\[(?:Kategorie|Category|Datei|File|Bild|Image):[^\]]*\]\]", "", t)
    t = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", t)
    t = re.sub(r"\[https?://\S+(?: ([^\]]*))?\]", r"\1", t)
    t = re.sub(r"'{2,}", "", t)
    t = re.sub(r"<br\s*/?>", "\n", t)
    t = re.sub(r"</?[a-zA-Z][^>]*>", "", t)
    t = t.replace("&nbsp;", " ").replace("&#160;", " ")
    t = re.sub(r"^=+.*?=+\s*$", "", t, flags=re.M)
    t = re.sub(r"^[:;*#|!]+\s*", "", t, flags=re.M)
    t = re.sub(r"\[\d+\]", "", t)
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()

def is_prose(para):
    """Gedichtzeilen sind kurz und stehen untereinander; Prosa ist ein Absatz am Stück."""
    lines = [l for l in para.split("\n") if l.strip()]
    if len(lines) == 1:
        return len(para.split()) >= 6 or para.rstrip()[-1:] in ".!?…"
    return sum(len(l) for l in lines) / len(lines) >= 70

# Lange Vokale und Doppellaute behalten ihr ß, nach kurzem Vokal wird es zu ss.
LONG = ("groß", "größ", "fuß", "füß", "saß", "säß", "maß", "mäß", "süß", "gruß", "grüß", "bloß", "spaß", "späß",
        "straß", "stoß", "stöß", "floß", "flöß", "kloß", "klöß", "soß", "ruß", "fraß", "fräß", "gefäß", "buß", "büß",
        "muße", "schoß", "schöß", "spieß", "gieß", "fließ", "schließ", "ließ", "hieß", "stieß", "grieß", "genieß",
        "verdrieß", "sprieß", "schieß", "mieß", "rieß")

def modern_word(w):
    low = w.lower()
    if "ß" not in low or any(s in low for s in LONG) or re.fullmatch(r"(?i)aßen?|äße", w):
        return w
    out = []
    for i, c in enumerate(w):
        prev = w[max(0, i - 2):i].lower()
        if c == "ß" and not re.search(r"(ei|ai|au|eu|äu|ie)$", prev):
            out.append("ss")
        else:
            out.append(c)
    return "".join(out)

OLD = {"Thür": "Tür", "thür": "tür",
       "Thee": "Tee", "thun": "tun", "thut": "tut", "Theil": "Teil", "theil": "teil", "Thier": "Tier", "thier": "tier",
       "Thal": "Tal", "Noth": "Not", "noth": "not", "Muth": "Mut", "muth": "mut", "Werth": "Wert", "werth": "wert",
       "Rath": "Rat", "Thräne": "Träne", "Thor ": "Tor ", "giebt": "gibt", "Giebt": "Gibt", "seyn": "sein",
       "Cigarre": "Zigarre", "Cigarette": "Zigarette", "Concert": "Konzert", "Couvert": "Kuvert", "Café": "Café"}

# Schreibungen des 19. Jahrhunderts, auch mitten im Wort (mittheilen, nöthig, Werthschätzung).
STEMS = [("theil", "teil"), ("Theil", "Teil"), ("thun", "tun"), ("Thun", "Tun"), ("thue", "tue"), ("thut", "tut"),
         ("thät", "tät"), ("Thät", "Tät"), ("nöth", "nöt"), ("Nöth", "Nöt"), ("noth", "not"), ("Noth", "Not"),
         ("muth", "mut"), ("Muth", "Mut"), ("wuth", "wut"), ("Wuth", "Wut"), ("werth", "wert"), ("Werth", "Wert"),
         ("thür", "tür"), ("Thür", "Tür"), ("thier", "tier"), ("Thier", "Tier"), ("thräne", "träne"),
         ("Thräne", "Träne"), ("giebt", "gibt"), ("gieng", "ging"), ("hieng", "hing"), ("Kameel", "Kamel"),
         ("Thee", "Tee"), ("Brod", "Brot")]
WORDS = {"seyn": "sein", "Seyn": "Sein", "bey": "bei", "Bey": "Bei", "drey": "drei", "frey": "frei", "zwey": "zwei",
         "sey": "sei", "Sey": "Sei", "seyd": "seid", "meynen": "meinen", "Freyheit": "Freiheit"}
# Was danach noch so aussieht, ist zu alt, um als Vorbild für heutiges Deutsch zu taugen.
ARCHAIC = re.compile(r"\b(vnd|vmb|vnnd|tzu|auff|ward|ists|itzt|jetzo|anitzo|selbiger|selbigen|dero|ihro|allhier|"
                     r"alldort|gantz|seind|fuer|wz|dz|thet|vnser|vns|soll'n|desselbigen|derohalben|nemlich|sondern's)\b|"
                     r"\b[a-zäöüß]*ey[a-zäöüß]*\b|\b(?:th|[a-zäöüß]*[aeiouäöü]th)[aeiouäöü]\w*", re.I)
MODERN_TH = re.compile(r"(?i)theat|thema|method|rhythm|apothe|biblioth|thron|kathol|athen|goethe|luther|sympath|"
                       r"mathem|ethi|ästheti|esthet|hypoth|theor|thes|orthogr|mytho|patho|thermo|katheder|thüring|"
                       r"lothring|gothi|ather|athlet|asthm|myth|zither|panther|forsythie|thomas|theo|ruth|elisabeth|"
                       r"arth|marth|beth|dorothe|bertha|thur|thor\b|methyl|ethan|äther|thymian|labyrinth|rhetor")

GERMAN = set("der die das und ist nicht ein eine zu mit von den dem des sich auf in im es er sie wir ich als auch "
              "wie so dass aber noch nur wenn schon man hat war wird sind".split())


def is_german(t):
    """Englische, lateinische oder französische Texte fallen raus: deutsche haben viele dieser kurzen Wörter."""
    words = re.findall(r"\w+", t.lower())
    return sum(w in GERMAN for w in words) / max(len(words), 1) >= 0.12


def archaic_share(t):
    hits = [m.group(0) for m in ARCHAIC.finditer(t) if not MODERN_TH.search(m.group(0))
            and not m.group(0)[:1].isupper() or re.match(r"(?i)vnd|vmb|tzu|seind|dero|ihro", m.group(0))]
    return 100 * len(hits) / max(len(t.split()), 1)

def modernize(t):
    for a, b in STEMS:
        t = t.replace(a, b)
    for a, b in WORDS.items():
        t = re.sub(r"\b%s\b" % a, b, t)
    t = t.replace("ſ", "s").replace("Telephon", "Telefon").replace("telephon", "telefon")
    t = t.replace("Bureau", "Büro").replace("bureau", "büro")
    t = re.sub(r"\b(Ae|Oe|Ue)(?=[a-zäöüß])", lambda m: {"Ae": "Ä", "Oe": "Ö", "Ue": "Ü"}[m.group(1)], t)
    for a, b in OLD.items():
        t = re.sub(r"(?<![A-Za-zäöüÄÖÜß])" + re.escape(a), b, t)
    return re.sub(r"\w*ß\w*", lambda m: modern_word(m.group(0)), t)

def excerpts(paras, low=150, high=400, most=3):
    out, cur = [], []
    for p in paras:
        if BLOCK.search(p) or p.strip() in PSEUDONYMS:
            if len(" ".join(cur).split()) >= low:
                out.append(cur)
            cur = []
            continue
        if cur and len(" ".join(cur + [p]).split()) > high:
            if len(" ".join(cur).split()) >= low:
                out.append(cur)
            cur = []
        if len(p.split()) > high:
            continue
        cur.append(p)
        if len(out) >= most:
            break
    if len(out) < most and len(" ".join(cur).split()) >= low:
        out.append(cur)
    return ["\n\n".join(e) for e in out[:most]]

def clean_enough(e):
    """Tabellen, Listen und Fußnotenreste taugen nicht als Stilvorlage."""
    tokens = e.split()
    odd = sum(1 for w in tokens if not re.search(r"[A-Za-zÄÖÜäöüß]{2}", w))
    lines = [l for l in e.split("\n") if l.strip()]
    listy = sum(1 for l in lines if re.match(r"\s*(\d+[.)]|[-–•])\s", l))
    leftover = re.search(r"\[\[|\]\]|\{\{|\}\}|\||<\w|&\w+;", e)
    return odd / max(len(tokens), 1) < 0.08 and listy <= 2 and not leftover and \
        not re.search(r"Anmerkung|Fußnote|\bS\. \d+", e)


def main(src, dst):
    seen, total = set(), 0
    for group in sorted(os.listdir(src)):
        for cat in sorted(os.listdir(os.path.join(src, group))):
            folder = os.path.join(src, group, cat)
            os.makedirs(os.path.join(dst, group), exist_ok=True)
            n = 0
            for name in sorted(n for n in os.listdir(folder) if n.endswith(".wiki")):
                path = os.path.join(folder, name)
                title, raw = open(path + ".expanded" if os.path.exists(path + ".expanded") else path).read().split("\n", 1)
                if re.match(r"#(WEITERLEITUNG|REDIRECT)", raw.strip(), re.I):
                    continue
                paras = [p.strip() for p in strip_markup(raw).split("\n\n") if p.strip()]
                prose = [p for p in paras if is_prose(p)]
                words = sum(len(p.split()) for p in paras) or 1
                if sum(len(p.split()) for p in prose) / words < 0.7:
                    continue
                for i, e in enumerate(excerpts(prose), start=1):
                    e = unicodedata.normalize("NFC", modernize(e))
                    key = re.sub(r"\W+", "", e[:300]).lower()
                    if key in seen or not clean_enough(e) or not is_german(e) or archaic_share(e) > 0.8:
                        continue
                    seen.add(key)
                    slug = re.sub(r"[^\w]+", "_", title, flags=re.UNICODE).strip("_")[:70]
                    with open(os.path.join(dst, group, f"{cat}__{slug}__{i}.txt"), "w", encoding="utf-8") as out:
                        out.write(e + "\n")
                    n += 1
            print(group, cat, n, flush=True)
            total += n
    print("gesamt", total)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

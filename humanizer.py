"""Humanizer als Desktop-App: schreibt KI-Texte lokal über Ollama so um, dass sie menschlich klingen.
Braucht nur Ollama. Als fertige Humanizer.exe oder mit Python: pythonw humanizer.py
"""
import difflib
import json
import os
import queue
import random
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
import zipfile
from xml.etree import ElementTree
from tkinter import filedialog, messagebox, scrolledtext, ttk

REPO = "KimJongUnNK/EmilsHumanizer"
RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/latest"
EXE_URL = f"https://github.com/{REPO}/releases/latest/download/Humanizer.exe"
# Beim Bauen der .exe ersetzt GitHub "dev" durch den Commit, aus dem sie gebaut wurde.
BUILD = "dev"

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
PREFERRED_MODEL = "gemma3:12b"
# Ollamas Standard-Kontext ist klein und schneidet lange Texte stillschweigend ab.
# Platz für Text, Ausgabe und Stilvorlage zusammen.
OLLAMA_CONTEXT = 16384

SYSTEM = """Du schreibst deutsche Texte so um, dass sie klingen, als hätte sie ein Mensch geschrieben. Regeln:
- Die Ausgabe ist immer Deutsch. Inhalt, Fakten, Zahlen und Zitate bleiben exakt erhalten. Erfinde nichts dazu:
  keine neuen Fakten, Zahlen, Beispiele, Ursachen oder Folgen, die nicht in der Vorlage stehen. Das gilt besonders
  neben Quellenangaben, denn was bei "(vgl. …)" steht, muss genau so aus der Vorlage stammen.
- Jede Zahl und jedes Datum aus der Vorlage steht auch in der Ausgabe, in derselben Schreibweise, mit Einheit.
- Ändere keine Ursache-Wirkung-Beziehungen und keine Zuständigkeiten. Was eine Vorschrift verlangt, bleibt eine
  Vorschrift. Was eine Studie zeigt, bleibt bei der Studie. Einschränkungen wie Orte, Zeiträume und Gruppen bleiben.
- Jede Quellenangabe bleibt bei genau der Aussage, die sie belegt. Sag nichts zweimal.
- Verbinde Aussagen nur so, wie die Vorlage sie verbindet. "obwohl", "jedoch", "trotzdem" nur bei einem Gegensatz,
  den die Vorlage nennt. "sodass", "wodurch", "daher" nur bei einer Folge, die die Vorlage nennt. Sonst neutral
  verbinden: Relativsatz, Apposition, Doppelpunkt, "und", oder zwei Sätze stehen lassen.
- Kurze Sätze bringen eine Aussage der Vorlage auf den Punkt. Sie fügen nichts hinzu, keine Sätze wie
  "Das gilt für alle Bereiche.".
- Die Länge bleibt ungefähr gleich. Lass keine Aussage weg. Wenn du eine Floskel streichst, sag dasselbe
  konkreter, statt es ersatzlos wegzulassen.
- Quellenangaben wie "(vgl. Berger 2021, S. 45)" bleiben Zeichen für Zeichen erhalten.
- Übernimm die Schreibweise der Vorlage (ß oder ss, österreichische und Schweizer Wörter bleiben, wie sie sind).
- Häng Begründungen nicht ständig mit ", weil …" an und beginne Sätze nicht ständig mit "Zudem" oder "Denn".
- Halte dich genau an den Bauplan für Satzanzahl und Satzlängen. Lange Sätze bekommen Nebensätze,
  kurze sind wirklich kurz.
- Streiche KI-Floskeln: "darüber hinaus", "des Weiteren", "zusammenfassend lässt sich sagen",
  "es ist wichtig zu beachten", "spielt eine entscheidende Rolle", "in der heutigen Zeit",
  "nicht nur ... sondern auch", "eintauchen", "nahtlos", "maßgeblich", "vielfältig", "ganzheitlich".
- Löse Nominalstil auf: Verben statt Substantivierungen, keine Substantivketten, wenig Passiv.
- Keine Dreier-Aufzählungen aus Gewohnheit, keine Gedankenstrich-Ketten, kein Fazit-Satz am Ende jedes Absatzes.
- Keine aus dem Englischen übersetzte Satzstellung. Schreib, wie man auf Deutsch wirklich formuliert.
- Nimm konkrete Wörter statt abstrakter. Sätze dürfen mit "Und" oder "Aber" anfangen.
- Wo das Register es erlaubt: Modalpartikeln (halt, eben, ja, schon, eigentlich), sparsam.
- Gib nur den umgeschriebenen Absatz aus, sonst nichts, auch keine Überschrift und keinen Kommentar."""

EXAMPLES_INTRO = """
Der folgende Absatz stammt von einem echten Menschen, der Bauplan ist ihm abgeschaut. Er zeigt, wie menschliches
Deutsch klingt: wie die Satzlängen wechseln, wo ein Satz abbricht, wann ein Gedanke springt, wie der Ton schwankt.
Übernimm Rhythmus und Ton. Übernimm NIE Inhalte, Themen, Namen, Bilder oder Formulierungen daraus.
Manche Beispiele sind über hundert Jahre alt: Nimm daraus nur den Satzbau, keine veralteten Wörter,
keine alte Rechtschreibung. Der Inhalt kommt nur aus dem Text, den du umschreibst."""

# Welche mitgelieferten Textsorten zu welchem Stil passen, die erste zählt am meisten.
STYLE_GROUPS = {
    "Natürlich": ["bericht", "locker", "sachlich"],
    "Akademisch": ["sachlich", "bericht"],
    "Locker": ["locker", "bericht"],
}

STYLE_SOURCES = ["Mitgeliefert", "Meine Texte", "Aus"]

STYLES = {
    "Natürlich": "Neutrales, natürliches Register.",
    "Akademisch": "Sachliches, akademisches Register, aber wie von einem fähigen Studenten geschrieben, "
                  "nicht wie aus dem Lehrbuch. Kein Du, keine Modalpartikeln, keine Umgangssprache.",
    "Locker": "Entspannt und im Gesprächston, wie ein Blogpost. Umgangssprache ist erlaubt.",
}

AI_TELLS = [
    "darüber hinaus", "des weiteren", "zusammenfassend", "abschließend lässt sich", "es ist wichtig zu",
    "es lässt sich festhalten", "entscheidende rolle", "zentrale rolle", "wichtige rolle",
    "in der heutigen zeit", "in der heutigen welt", "nicht nur", "eintauchen", "nahtlos", "maßgeblich",
    "vielfältig", "vielzahl", "ganzheitlich", "essenziell", "unerlässlich", "von entscheidender bedeutung",
    "im folgenden", "letztendlich", "insgesamt lässt sich", "facettenreich", "wertvolle einblicke",
    "auf ein neues level", "es gilt zu beachten", "im hinblick auf", "in bezug auf", "gewährleisten",
    "ermöglicht es", "stellt sicher", "spielt eine", "spielen eine", "ein weiterer wichtiger",
    "ist ebenfalls wichtig",
]

# Download in GB, nötiger Grafikspeicher in GB, nötiger RAM in GB ohne passende Grafikkarte. Richtwerte.
CATALOG = [
    ("gemma3:1b", 0.8, 2, 4, "Nur zum Ausprobieren. Deutsch holprig."),
    ("gemma3:4b", 3.3, 4, 8, "Schnell, brauchbares Deutsch."),
    ("gemma3:12b", 8.1, 10, 16, "Empfehlung: gutes Deutsch bei vertretbarem Tempo."),
    ("mistral-nemo:12b", 7.1, 10, 16, "Alternative zu gemma3:12b, etwas kleiner."),
    ("mistral-small3.2:24b", 15, 18, 32, "Sehr gutes Deutsch, braucht eine starke Grafikkarte."),
    ("gemma3:27b", 17, 20, 32, "Beste Qualität der Liste, auf normalen Rechnern langsam."),
]

MONTHS = "Januar|Jänner|Februar|Feber|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember"
ABBREVIATIONS = re.compile(
    r"\b(z\.\s?B|d\.\s?h|u\.\s?a|o\.\s?ä|u\.\s?U|bzw|bspw|usw|ca|Nr|vgl|etc|evtl|ggf|inkl|exkl|sog|Dr|Prof|Abb|Mio|Mrd|St|"
    r"S|Abs|Kap|Aufl|Hrsg|hrsg|Bd|Jg|Jh|Tab|ebd|Ebd|ders|f|ff|al|Std|Min|Mag|Ing|Dipl|Fa|Tel|Str|vs|"
    r"o\.\s?J|o\.\s?A|n\.\s?d|Co|Ltd|Inc|Corp|Jr|Sr|Vol|Ed|Eds|ed|eds|pp|ca)\."
)
ORDINAL_NOUNS = "Jahrhundert|Jahrtausend|Auflage|Klasse|Platz|Mal|Stock|Bezirk|Semester|Kapitel|Quartal|Lebensjahr"
NUMBER_DOT = re.compile(rf"(\d)\.(?=\d|\s+[a-zäöü]|\s+(?:{MONTHS}|{ORDINAL_NOUNS})\w*\b)")

BG, PANEL, FG, MUTED, ACCENT = "#141414", "#232323", "#f2f2f2", "#9a9a9a", "#ff4b4b"
ADDED, REMOVED = "#1f4d2e", "#5a2326"
GOOD = "#5fd38d"


def _mask(text: str) -> str:
    """Nimmt die Punkte aus Abkürzungen und Datumsangaben, damit sie kein Satzende vortäuschen."""
    return NUMBER_DOT.sub(r"\1", ABBREVIATIONS.sub(lambda m: m.group(1).replace(".", ""), text))


def raw_sentences(text: str) -> list[str]:
    """Wie sentences(), aber unverändert im Wortlaut, damit sich ein Text aus den Sätzen wieder zusammensetzen lässt."""
    keep = "\u2024"  # Platzhalter gleicher Länge für Punkte, die kein Satzende sind
    masked = ABBREVIATIONS.sub(lambda m: m.group(0).replace(".", keep), text)
    masked = NUMBER_DOT.sub(lambda m: m.group(1) + keep, masked)
    return [part.replace(keep, ".") for part in re.split(r"(?<=[.!?…])\s+", masked.strip()) if part]


def sentences(text: str) -> list[str]:
    """Zerlegt in Sätze, ohne an Abkürzungen (z. B., bzw.) oder Datumsangaben (28.09.) zu trennen.

    Die Sätze kommen maskiert zurück, also ohne diese Punkte. Zum Vergleich mit dem Original _mask() verwenden.
    """
    return [s for s in re.split(r"(?<=[.!?…])\s+", _mask(text).strip()) if s]


def burstiness(text: str) -> float:
    """Standardabweichung / Mittelwert der Satzlängen. Menschen ~0,5+, rohe KI-Texte oft <0,4."""
    lens = [len(s.split()) for s in sentences(text)]
    if len(lens) < 2:
        return 0.0
    mean = sum(lens) / len(lens)
    var = sum((l - mean) ** 2 for l in lens) / len(lens)
    return round((var ** 0.5) / mean, 2)


def tell_count(text: str) -> int:
    low = text.lower()
    return sum(low.count(t) for t in AI_TELLS) + text.count("—") + text.count(" – ")


def diff_spans(old: str, new: str) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Zeichenbereiche der Wörter, die nur im alten bzw. nur im neuen Text stehen."""
    a = [(m.start(), m.end(), m.group()) for m in re.finditer(r"\S+", old)]
    b = [(m.start(), m.end(), m.group()) for m in re.finditer(r"\S+", new)]
    matcher = difflib.SequenceMatcher(None, [w for *_, w in a], [w for *_, w in b], autojunk=False)
    gone, added = [], []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if i2 > i1:
            gone.append((a[i1][0], a[i2 - 1][1]))
        if j2 > j1:
            added.append((b[j1][0], b[j2 - 1][1]))
    return gone, added


def changed_share(new: str, added: list[tuple[int, int]]) -> int:
    """Anteil der Wörter im neuen Text, die so nicht in der Vorlage standen, in Prozent."""
    total = len(new.split())
    return round(100 * sum(len(new[s:e].split()) for s, e in added) / total) if total else 0


class OllamaError(RuntimeError):
    pass


class OllamaUnreachable(OllamaError):
    pass


class PullCancelled(OllamaError):
    pass


class UpdateError(RuntimeError):
    pass


def _request(url: str, payload: dict | None = None, timeout: int = 600, method: str | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return json.loads(body) if body.strip() else {}
    except urllib.error.HTTPError as e:
        raise OllamaError(f"Ollama meldet Fehler {e.code}: {e.read().decode(errors='replace')}") from e
    except (urllib.error.URLError, OSError) as e:
        raise OllamaUnreachable("Ollama läuft nicht. Starte die Ollama-App und dann den Humanizer neu.") from e


def list_models(url: str = OLLAMA_URL) -> list[str]:
    return sorted(m["name"] for m in _request(url + "/api/tags", timeout=5).get("models", []))


def ensure_ollama(url: str = OLLAMA_URL, wait: int = 15) -> list[str]:
    """Liefert die installierten Modelle und startet Ollama, falls es nicht läuft."""
    try:
        return list_models(url)
    except OllamaUnreachable:
        pass
    try:
        subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as e:
        raise OllamaUnreachable("Ollama ist nicht installiert. Lade es von ollama.com/download, installiere es "
                                "und starte den Humanizer neu.") from e
    for _ in range(wait):
        time.sleep(1)
        try:
            return list_models(url)
        except OllamaUnreachable:
            continue
    return list_models(url)


def unload_models(url: str = OLLAMA_URL) -> int:
    """Wirft alle geladenen Modelle aus dem Arbeits- und Grafikspeicher. Liefert, wie viele es waren."""
    loaded = [m["name"] for m in _request(url + "/api/ps", timeout=5).get("models", [])]
    for name in loaded:
        _request(url + "/api/generate", {"model": name, "keep_alive": 0}, timeout=30)
    return len(loaded)


def delete_model(name: str, url: str = OLLAMA_URL) -> None:
    _request(url + "/api/delete", {"model": name}, timeout=60, method="DELETE")


def pull_model(name: str, url: str = OLLAMA_URL, on_progress=lambda percent, status: None,
               cancel: threading.Event | None = None) -> None:
    """Lädt ein Modell über Ollama herunter und meldet den Fortschritt in Prozent.

    Ist cancel gesetzt, wird die Verbindung geschlossen; Ollama bricht den Download dann ab.
    """
    body = json.dumps({"model": name, "stream": True}).encode()
    req = urllib.request.Request(url + "/api/pull", data=body, headers={"Content-Type": "application/json"})
    layers: dict[str, tuple[int, int]] = {}
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            for line in resp:
                if cancel is not None and cancel.is_set():
                    raise PullCancelled(f"Download von {name} abgebrochen. Was schon geladen ist, bleibt liegen: "
                                        "Beim nächsten Versuch geht es dort weiter.")
                if not line.strip():
                    continue
                msg = json.loads(line)
                if "error" in msg:
                    raise OllamaError(f'Download von "{name}" fehlgeschlagen: {msg["error"]}')
                if msg.get("digest") and msg.get("total"):
                    layers[msg["digest"]] = (msg.get("completed", 0), msg["total"])
                total = sum(t for _, t in layers.values())
                on_progress(round(100 * sum(c for c, _ in layers.values()) / total) if total else 0,
                            msg.get("status", ""))
    except urllib.error.HTTPError as e:
        raise OllamaError(f"Ollama meldet Fehler {e.code}: {e.read().decode(errors='replace')}") from e
    except (urllib.error.URLError, OSError) as e:
        raise OllamaUnreachable("Die Verbindung zu Ollama ist abgebrochen. Download noch einmal starten.") from e


def latest_build(api: str = RELEASE_API) -> str:
    """Commit, aus dem die neueste veröffentlichte .exe gebaut wurde."""
    req = urllib.request.Request(api, headers={"Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.load(resp)["target_commitish"]
    except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
        raise UpdateError("GitHub ist gerade nicht erreichbar. Versuch es später noch einmal.") from e


def download_file(url: str, target: str, on_progress=lambda percent: None) -> None:
    try:
        with urllib.request.urlopen(url, timeout=60) as resp, open(target, "wb") as out:
            total, done = int(resp.headers.get("Content-Length") or 0), 0
            while chunk := resp.read(65536):
                out.write(chunk)
                done += len(chunk)
                on_progress(round(100 * done / total) if total else 0)
    except (urllib.error.URLError, OSError) as e:
        raise UpdateError("Der Download des Updates ist fehlgeschlagen. Die App bleibt, wie sie ist.") from e


def backup_path(executable: str) -> str:
    root, ext = os.path.splitext(executable)
    return root + ".old" + ext


def swap_executable(current: str, new: str) -> None:
    """Setzt new an die Stelle von current. Die bisherige Datei bleibt als .old daneben liegen.

    Windows lässt eine laufende .exe nicht überschreiben, aber umbenennen. Geht der zweite Schritt
    schief, wird zurückbenannt, damit die alte Version startbar bleibt.
    """
    old = backup_path(current)
    if os.path.exists(old):
        os.remove(old)
    os.rename(current, old)
    try:
        os.rename(new, current)
    except OSError:
        os.rename(old, current)
        raise


def cleanup_old(executable: str) -> None:
    """Räumt die Vorgängerversion weg, die ein Update liegen gelassen hat."""
    try:
        os.remove(backup_path(executable))
    except OSError:
        pass


def system_memory() -> tuple[float | None, float | None]:
    """(RAM, Grafikspeicher) dieses Rechners in GB. None, wenn sich ein Wert nicht ermitteln lässt."""
    ram = vram = None
    try:
        if os.name == "nt":
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                    (n, ctypes.c_ulonglong) for n in ("total", "avail", "page_total", "page_avail",
                                                      "virtual_total", "virtual_avail", "extended")]

            status = MemoryStatus()
            status.length = ctypes.sizeof(MemoryStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            ram = status.total / 1024 ** 3
        else:
            ram = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3
    except Exception:
        pass
    try:  # nur NVIDIA-Karten, andere bleiben unbekannt
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        vram = max(float(x) for x in out.split()) / 1024
    except Exception:
        pass
    return ram, vram


def verdict(need_vram: float, need_ram: float, ram: float | None, vram: float | None) -> str:
    """Einschätzung, wie ein Modell auf diesem Rechner läuft. Leer, wenn der RAM unbekannt ist."""
    if vram is not None and round(vram) >= need_vram:
        return "läuft flüssig"
    if ram is None:
        return ""
    return "läuft, aber langsamer" if round(ram) >= need_ram else "zu groß für diesen Rechner"


def bundled_dir() -> str:
    """Die mitgelieferten Beispieltexte, im Quelltext neben dieser Datei, in der .exe im Entpack-Ordner."""
    return os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "beispieltexte")


def user_dir() -> str:
    """Ordner für eigene Texte. Liegt nur auf diesem Rechner."""
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "EmilsHumanizer", "texte")


def settings_path() -> str:
    return os.path.join(os.path.dirname(user_dir()), "einstellungen.json")


def load_settings() -> dict:
    try:
        with open(settings_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(settings_path()), exist_ok=True)
        with open(settings_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except OSError:
        pass  # Merken ist Komfort; scheitert es, startet die App eben mit den Standardwerten.


def load_texts(folder: str) -> list[str]:
    """Alle .txt-Dateien eines Ordners, alphabetisch. Fehlt der Ordner, ist die Liste leer."""
    try:
        names = sorted(n for n in os.listdir(folder) if n.lower().endswith(".txt"))
    except OSError:
        return []
    texts = []
    for name in names:
        try:
            raw = open(os.path.join(folder, name), "rb").read()
        except OSError:
            continue
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:  # ältere Windows-Editoren speichern so
            text = raw.decode("cp1252", errors="replace")
        if text.strip():
            texts.append(text.strip())
    return texts






_bundled: dict[str, list[str]] = {}


def bundled_texts(group: str) -> list[str]:
    """Mitgelieferte Texte einer Textsorte. Sie ändern sich nicht, also nur einmal laden."""
    if group not in _bundled:
        _bundled[group] = load_texts(os.path.join(bundled_dir(), group))
    return _bundled[group]




def system_prompt(style: str, examples: list[str]) -> str:
    prompt = SYSTEM + "\nStil: " + STYLES[style]
    if examples:
        prompt += "\n" + EXAMPLES_INTRO + "".join(f"\n\n<beispiel>\n{e}\n</beispiel>" for e in examples)
    return prompt






def _chat(model: str, url: str, messages: list[dict]) -> str:
    reply = _request(url + "/api/chat", {
        "model": model,
        "stream": False,
        "options": {"num_ctx": OLLAMA_CONTEXT},
        "messages": messages,
    })
    return reply["message"]["content"].strip()






def crutches(result: str) -> list[str]:
    """Satzmuster, die sich mechanisch wiederholen und dadurch nach Maschine klingen."""
    limit = max(2, len(sentences(result)) // 8)
    found = []
    weil = len(re.findall(r",\s+weil\b", result))
    if weil > limit:
        found.append(f'{weil}-mal ", weil …" angehängt')
    starts = re.findall(r"(?:^|[.!?]\s+)(Zudem|Denn|Außerdem|Gleichzeitig|Dabei|Somit|Daher)\b", result)
    if len(starts) > limit:
        found.append(f"{len(starts)} Sätze mit " + "/".join(sorted(set(starts))) + " begonnen")
    return found




# Quellenangaben in Klammern: mit "vgl." und einer Zahl, oder mit Autorenname und Jahr bzw. "o. J." ("(Grösel, 2007,
# S. 94)", "(vgl. Britannica Editors, o. J.)", "(vgl. Koch, 1993, S. 31; Semper, 1904, S. 323 f.)"). Dazu die
# Platzhalter ⟦Qa⟧ und ⟦Za⟧, für die Quellenangaben und Zitate vor dem Modell versteckt werden.
CITATION = re.compile(
    r"\((?:vgl\.|siehe|s\.|nach|zit\. n\.)[^()]*\d[^()]*\)"
    r"|\((?:(?:vgl\.|siehe|s\.|nach|zit\.\s*n\.)\s*)?[A-ZÄÖÜ][^()]*?"
    r"(?:\b1[4-9]\d\d[a-z]?\b|\b20\d\d[a-z]?\b|\bo\.\s?J\.|\bn\.\s?d\.)[^()]*\)"
    r"|⟦[QZ][a-z]+⟧", re.I)
TOKEN = re.compile(r"⟦[QZ][a-z]+⟧")
# Direkte Zitate: „…“, »…«, "…".
QUOTE = re.compile(r"„[^„“”\n]{1,800}?[“”]|»[^»«\n]{1,800}?«|\"[^\"\n]{1,800}?\"")


def _token(kind: str, i: int) -> str:
    letters = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        letters = chr(97 + r) + letters
    return f"⟦{kind}{letters}⟧"


def protect(text: str) -> tuple[str, dict[str, str]]:
    """Ersetzt direkte Zitate und Quellenangaben durch Platzhalter, damit das Modell sie nicht verändern kann.
    Liefert den Text mit Platzhaltern und die Zuordnung Platzhalter → Original."""
    mapping: dict[str, str] = {}

    def swap(kind: str):
        def inner(m: re.Match) -> str:
            if TOKEN.fullmatch(m.group(0)):
                return m.group(0)
            token = _token(kind, sum(1 for k in mapping if k[1] == kind))
            mapping[token] = m.group(0)
            return token
        return inner
    text = QUOTE.sub(swap("Z"), text)
    text = CITATION.sub(swap("Q"), text)
    return text, mapping


# Zuordnung Platzhalter → Original des Absatzes, der gerade umgeschrieben wird. Jede Modellantwort läuft durch
# normalize_tokens(), auch die der Satz-Reparatur.
_ACTIVE: dict[str, str] = {}


def normalize_tokens(text: str, mapping: dict[str, str] | None = None) -> str:
    """Bringt Platzhalter, die das Modell leicht verändert ("[Qa]", "⟦ Qa ⟧"), in die richtige Form. Hat es statt
    eines Platzhalters das Zitat selbst wörtlich hingeschrieben, wird daraus wieder der Platzhalter."""
    text = re.sub(r"[⟦\[]\s*([QZ])\s*([a-z]+)\s*[⟧\]]", r"⟦\1\2⟧", text)
    for token, original in (_ACTIVE if mapping is None else mapping).items():
        if token not in text and original in text:
            text = text.replace(original, token, 1)
    return text


_NAMES: set[str] = set()  # Autorennamen des Absatzes, der gerade umgeschrieben wird
SUBJUNCTIVE = re.compile(
    r"\b(?:sei|seien|habe|biete|werde|könne|müsse|solle|dürfe|gebe|liege|stehe|gehe|komme|zeige|erlaube|ermögliche|"
    r"diene|gelte|bestehe|verfüge|fehle|reiche|handle|lasse|spiele|trage|führe|bilde|bringe|wirke|hänge)\b")


def author_names(text: str) -> set[str]:
    """Nachnamen aus den Quellenangaben eines Texts: "(vgl. Hendrickson und Buckhurst, 2013)" → Hendrickson, Buckhurst."""
    skip = {"S", "Vgl", "Editors", "Hrsg", "Ebd", "Ders", "Dies", "Aufl", "Bd", "Jg", "Nr"}
    return {a for c in CITATION.findall(text) if not TOKEN.fullmatch(c) for a in citation_parts(c)[0]
            if a not in skip and len(a) >= 3}


def _names_in(sentence: str, names: set[str]) -> set[str]:
    plain = CITATION.sub(" ", sentence)
    return {n for n in names if re.search(r"\b" + re.escape(n) + r"\b", plain)}


def missing_attributions(source: str, result: str, names: set[str] | None = None) -> list[str]:
    """Sätze des Originals, die einen Autor im Fließtext nennen ("Nach Koch…", "Tsuboi verweist…"), deren
    Gegenstück in der Ausgabe den Namen nicht mehr trägt. Dann wäre aus einer Wiedergabe eine eigene Behauptung
    geworden."""
    names = names if names is not None else (author_names(source) | _NAMES)
    outs = raw_sentences(result)
    lost = []
    for original in raw_sentences(source):
        for name in _names_in(original, names):
            near = [s for s in outs if overlap(original, s) >= 0.3] or outs
            if not any(name in _names_in(s, {name}) for s in near):
                lost.append(original)
                break
    return lost


def missing_subjunctive(source: str, result: str) -> list[str]:
    """Sätze des Originals in indirekter Rede ("Eine Drehscheibe biete …"), deren Gegenstück keinen Konjunktiv mehr
    hat. Aus "biete" wird sonst "bietet", und die Aussage des Autors klingt wie eine eigene."""
    outs = raw_sentences(result)
    lost = []
    for original in raw_sentences(source):
        if not SUBJUNCTIVE.search(QUOTE.sub(" ", original)):
            continue
        near = [s for s in outs if overlap(original, s) >= 0.3]
        if near and not any(SUBJUNCTIVE.search(QUOTE.sub(" ", s)) for s in near):
            lost.append(original)
    return lost


def original_hints(text: str) -> list[str]:
    """Auffälligkeiten im Original, die die App nicht anfasst: offene Klammern und doppelte Sätze."""
    hints = []
    for paragraph in paragraphs(text):
        depth, start = 0, None
        for i, ch in enumerate(paragraph):
            if ch == "(":
                if depth == 0:
                    start = i
                elif depth >= 1:
                    hints.append("Klammer nicht geschlossen: „" + paragraph[start:start + 45].strip() + "…“")
                    depth = 0
                    start = i
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)
        if depth > 0 and start is not None:
            hints.append("Klammer nicht geschlossen: „" + paragraph[start:start + 45].strip() + "…“")
    for paragraph in paragraphs(text):
        raw = {_mask(r): r for r in raw_sentences(paragraph)}
        for sentence in repeated_sentences(paragraph):
            hints.append("Satz wiederholt einen vorherigen: „" + raw.get(sentence, sentence)[:60] + "…“")
    return list(dict.fromkeys(hints))


def unprotect(text: str, mapping: dict[str, str]) -> str:
    for token, original in mapping.items():
        text = text.replace(token, original)
    return text


PLACEHOLDER = re.compile(r"\s*(?:\([^()]*\[[^\]]*\][^()]*\)|\[\s*(?:Quelle|Autor|Name|Jahr|Seite|Zitat|Beleg|Ref|Titel|Ort)[^\]]*\]"
                         r"|\(\s*(?:vgl\.|siehe)\s*(?:Quelle|Autor|o\.\s*A\.)?\s*\))", re.I)


def invented_citations(source: str, result: str) -> list[str]:
    """Quellenangaben und Platzhalter wie "(vgl. [Quelle])" in der Ausgabe, die im Original nicht stehen."""
    have = set(CITATION.findall(source))
    found = [c for c in CITATION.findall(result) if c not in have] + \
            [m.group(0).strip() for m in PLACEHOLDER.finditer(result) if m.group(0).strip() not in source]
    return list(dict.fromkeys(found))


def strip_placeholders(text: str) -> str:
    """Entfernt Platzhalter-Quellen, die das Modell erfunden hat. Echte Quellenangaben bleiben."""
    return re.sub(r"\s+([.,;:])", r"\1", PLACEHOLDER.sub("", text))


def citation_parts(citation: str) -> tuple[list[str], list[str]]:
    """Autorennamen und Zahlen (Jahr, Seite) einer Quellenangabe wie "(vgl. Hofer/Lindner 2019, S. 112)"."""
    inner = re.sub(r"^\((?:vgl\.|siehe|s\.|nach|zit\. n\.)\s*", "", citation, flags=re.I).rstrip(")")
    authors = [w for w in re.findall(r"[A-ZÄÖÜ][\wäöüß-]+", inner) if w not in ("S", "Vgl")]
    return authors, re.findall(r"\d+", inner)


def narrative_citation(citation: str, result: str) -> bool:
    """Steht die Quelle als Fließtext da, etwa "wie Hofer und Lindner (2019, S. 112) zeigen"? Das ist gültig."""
    authors, numbers = citation_parts(citation)
    return bool(authors) and any(all(a in s for a in authors) and all(n in s for n in numbers)
                                 for s in sentences(result))


def missing_citations(source: str, result: str) -> list[str]:
    """Quellenangaben wie "(vgl. Berger 2021, S. 45)", die weder wörtlich noch als Fließtext-Zitat mit denselben
    Autoren, Jahr und Seite in der Ausgabe stehen."""
    return [c for c in dict.fromkeys(CITATION.findall(source)) if c not in result and not narrative_citation(c, result)]


def doubled_citations(source: str, result: str) -> list[str]:
    """Quellenangaben, die in der Ausgabe öfter stehen als im Original."""
    return [c for c in dict.fromkeys(CITATION.findall(result)) if result.count(c) > source.count(c)]


def unchanged_sentences(source: str, result: str, threshold: float = 0.8) -> list[str]:
    """Sätze der Ausgabe, die fast wörtlich aus dem Original stammen, also gar nicht umgeschrieben wurden."""
    originals = sentences(source)
    return [s for s in sentences(result)
            if originals and max(difflib.SequenceMatcher(None, s, o).ratio() for o in originals) >= threshold]


# --- Absatz für Absatz nach Satzbau-Schablone -----------------------------------------------------------------

def paragraph_pool(texts: list[str]) -> list[tuple[int, list[int], str]]:
    """Alle Absätze echter Texte als (Wortzahl, Satzlängen, Absatz), soweit sie als Bauplan taugen."""
    pool = []
    for text in texts:
        for p in raw_paragraphs(text):
            lengths = [len(s.split()) for s in sentences(p)]
            if 2 <= len(lengths) <= 9 and all(1 <= n <= 70 for n in lengths):
                pool.append((sum(lengths), lengths, p))
    return pool


_pools: dict[str, list] = {}


def group_pool(group: str) -> list[tuple[int, list[int], str]]:
    if group not in _pools:
        _pools[group] = paragraph_pool(bundled_texts(group))
    return _pools[group]


def plan_pool(source: str, style: str, own: list[str], pool_of=group_pool) -> tuple[list, str]:
    """Woher die Baupläne kommen: eigene Texte, mitgelieferte passend zum Stil, oder gar keine."""
    if source == "Aus":
        return [], ""
    if source == "Meine Texte" and own:
        return paragraph_pool(own), ""
    pool = [entry for group in STYLE_GROUPS[style] for entry in pool_of(group)]
    note = "Im Ordner \"Meine Texte\" liegt noch nichts, ich habe die mitgelieferten Texte genommen." \
        if source == "Meine Texte" else ""
    return pool, note


def fallback_plan(words: int, strict: bool = False) -> list[int]:
    """Bauplan ohne Vorbild: lang, kurz, mittel, sehr lang, kurz … bis die Wortzahl erreicht ist."""
    shape, plan = [1.7, 0.6, 1.0, 2.1, 0.8, 1.3], []
    unit, least = max(words / 7, 4), 5 if strict else 3
    while sum(plan) < words * 0.9:
        plan.append(max(least, round(shape[len(plan) % len(shape)] * unit)))
    return plan


def sentence_plan(paragraph: str, pool: list, rng: random.Random | None = None,
                  strict: bool = False) -> tuple[list[int], str]:
    """Abfolge von Satzlängen für einen Absatz, abgenommen von einem echten Absatz ähnlicher Länge.

    Die Längen werden auf die Wortzahl des Originalabsatzes skaliert. Zurück kommen Bauplan und Vorbild-Absatz,
    ohne passendes Vorbild ein fester abwechslungsreicher Plan und kein Vorbild.
    """
    rng = rng or random
    words, count = len(paragraph.split()), len(sentences(paragraph))
    candidates = [c for c in pool if 0.75 * words <= c[0] <= 1.25 * words and abs(len(c[1]) - count) <= 2]
    rng.shuffle(candidates)
    for total, lengths, example in candidates[:60]:
        plan = [max(3, round(n * words / total)) for n in lengths]
        if usable_plan(plan, strict):
            return plan, example
    return fallback_plan(words, strict), ""


def usable_plan(plan: list[int], strict: bool = False) -> bool:
    """Abwechslungsreich, aber kein Extrem: höchstens 45 Wörter pro Satz und höchstens ein sehr kurzer.

    Streng (akademischer Stil) heißt: jeder Satz mindestens 5 Wörter, höchstens einer unter 8. Sonst verlangt der
    Bauplan Sätze aus zwei Wörtern, und das Modell schreibt Fragmente wie "38 %.".
    """
    least, short = (5, 8) if strict else (3, 6)
    return (len(plan) >= 2 and all(least <= n <= 45 for n in plan) and sum(n < short for n in plan) <= 1
            and burstiness(" ".join("x " * (n - 1) + "x." for n in plan)) >= 0.35)


def fragments(text: str) -> list[str]:
    """Sätze, die keine sind: höchstens zwei Wörter oder weniger als zwei Wörter aus Buchstaben, etwa "38 %."."""
    found = []
    for sentence in sentences(text):
        words = sentence.split()
        if len(words) <= 2 or len([w for w in words if re.search(r"[A-Za-zÄÖÜäöüß]{2}", w)]) < 2:
            found.append(sentence)
    return found


def plan_fit(plan: list[int], result: str) -> float:
    """Mittlere relative Abweichung der Satzlängen vom Bauplan, 0 heißt genau getroffen."""
    lengths = [len(s.split()) for s in sentences(result)]
    if not lengths:
        return 1.0

    def error(target: list[int]) -> float:
        missing = abs(len(target) - len(lengths))
        return (sum(abs(a - b) / a for a, b in zip(target, lengths)) + missing) / max(len(target), len(lengths))

    # Ein Satz weniger als geplant ist erlaubt: Das Streichen eines Füllsatzes soll nicht am Bauplan scheitern.
    shorter = [plan[:i] + plan[i + 1:] for i in range(len(plan))] if len(lengths) == len(plan) - 1 else []
    return min([error(plan)] + [error(t) for t in shorter])


class _CommaSplice:
    """Zwei Hauptsätze nur mit Komma: "… um 60 %, technische Innovationen können …". Zählt nur, wenn vor dem Komma
    ein vollständiger Satzteil mit Verb steht, nicht bei Aufzählungen ("weite, blühende Natur ist") oder Appositionen."""
    AFTER = re.compile(
        r", (?!(?:der|die|das|dem|den|des|denen|deren|dessen|welche\w*|wo|was|wie|wenn|weil|dass|ob|sondern|aber|und|"
        r"oder|doch|jedoch|also|bzw|z|d|u|etwa|rund|bis|vor|nach|bei|mit|von|in|im|am|an|auf|aus|zu|zur|zum|so|sowie)\b)"
        r"(?:[a-zäöüß]+ ){0,2}[A-ZÄÖÜ][\wäöüß-]+ (?:können|kann|müssen|muss|sollen|soll|sind|ist|haben|hat|werden|wird)\b")
    VERB = re.compile(r"\b(?:ist|sind|war|waren|hat|haben|wird|werden|kann|können|muss|müssen|soll|sollen|senk\w*|steig\w*|"
                      r"zeig\w*|bild\w*|lieg\w*|gilt|gelten|bleib\w*|verbind\w*|führ\w*|mach\w*|bring\w*|geh\w*|komm\w*|"
                      r"[a-zäöüß]{3,}(?:t|en))\b")
    SKIP = {"den", "dem", "des", "der", "die", "das", "einen", "einem", "einen", "einer", "unten", "oben", "eben", "seit",
            "nicht", "selten", "zuletzt", "jetzt", "meist", "sehr", "mehr", "erst", "fast", "bereits", "geschmackt"}

    def search(self, text: str):
        for match in self.AFTER.finditer(text):
            before = re.split(r"[.!?;:,–]", text[:match.start()])[-1]
            words = before.split()
            if len(words) >= 3 and words[-1][-1] not in "eEn" and any(
                    self.VERB.fullmatch(w) and w not in self.SKIP for w in words[1:]):
                return match
        return None


COMMA_SPLICE = _CommaSplice()


HABITS = [
    (re.compile(r"\bstell(?:t|en|te)\b[^.!?]{0,80}\bdar\b"), '"… stellt … dar"'),
    (re.compile(r"\b(?:ist|sind) von (?:\w+ ){0,2}Bedeutung\b"), '"ist von … Bedeutung"'),
    (re.compile(r"\bspiel(?:t|en)\b[^.!?]{0,50}\bRolle\b"), '"spielt eine … Rolle"'),
    (re.compile(r"\bsomit\b"), '"somit"'),
    (re.compile(r"\bzentrale[nrs]? (?:Aspekt|Punkt|Faktor)"), '"zentraler Aspekt/Punkt"'),
    (re.compile(r"\bwesentliche[nrs]? (?:Aspekt|Punkt|Faktor|Anforderung)"), '"wesentlicher Aspekt"'),
    (re.compile(r"\b[Ee]in(?:en)? weitere[nrs]? (?:\w+ )?(?:Punkt|Aspekt|Faktor|Bereich|Baustein)\b"), '"ein weiterer Punkt"'),
    (re.compile(r"\b[Vv]on (?:großer|zentraler|besonderer|enormer|hoher|entscheidender) (?:Wichtigkeit|Bedeutung|Relevanz)\b"),
     '"von großer Wichtigkeit"'),
    (COMMA_SPLICE, 'zwei Hauptsätze nur mit Komma verbunden'),
]


def habits(text: str) -> list[str]:
    """Wendungen in einem Absatz, die sich über den Text hinweg nicht wiederholen dürfen."""
    return [name for pattern, name in HABITS if pattern.search(text)]


def paragraph_request(paragraph: str, plan: list[int], avoid: list[str] | None = None,
                      qualifiers: list[str] | None = None) -> str:
    cited = {_mask(c): c for c in CITATION.findall(paragraph)}
    claims = "".join(f'Die Quellenangabe {c} belegt diese Aussage und bleibt bei ihr: "{CITATION.sub("", s.replace(m, "")).strip()}"\n'
                     for s in sentences(paragraph) for m, c in cited.items() if m in s)
    required = list(dict.fromkeys(CITATION.findall(paragraph) + [surface for _, _, surface in facts(paragraph)]))
    lines = "\n".join(f"Satz {i}: etwa {n} Wörter" for i, n in enumerate(plan, start=1))
    return (f"Schreib diesen Absatz um.\n\nBauplan: genau {len(plan)} Sätze.\n{lines}\n\n"
            "So kommst du auf den Bauplan: Sätze zusammenlegen, lange Sätze teilen, die Reihenfolge der Aussagen im "
            "Absatz ändern, ein anderes Subjekt wählen, aktiv statt passiv. Kein Satz darf so bleiben, wie er in der "
            "Vorlage steht. Verbinde zusammengelegte Sätze nur so, wie die Vorlage die Aussagen verbindet: kein "
            "\"obwohl\" ohne Gegensatz in der Vorlage, kein \"sodass\" ohne Folge in der Vorlage. Sonst Relativsatz, "
            "Apposition, Doppelpunkt oder \"und\". Ein kurzer Satz bringt eine Aussage der Vorlage auf den Punkt "
            "und fügt nichts hinzu.\n"
            + ("Diese Angaben müssen wörtlich vorkommen, Zahlen als Ziffern wie in der Vorlage: "
               + "; ".join(required) + "\n" if required else "")
            + ("Diese Einschränkungen müssen erhalten bleiben: " + "; ".join(qualifiers) + "\n" if qualifiers else "")
            + claims
            + ("Diese Wendungen sind verboten: " + ", ".join(avoid) + "\n" if avoid else "")
            + ("Diese Abschwächungen und Modalverben behalten ihre Bedeutung (Synonym erlaubt, \"muss\" bleibt \"muss\"): "
               + ", ".join(extract_hedges(paragraph)) + "\n" if extract_hedges(paragraph) else "")
            + ("Wer etwas sagt, bleibt genannt: Autorennamen im Satz (" + ", ".join(sorted(_names_in(paragraph, _NAMES)))
               + ") bleiben bei ihrer Aussage, indirekte Rede bleibt im Konjunktiv (biete, sei, habe).\n"
               if _names_in(paragraph, _NAMES) else "")
            + "Jeder kurze Satz trägt eine eigene Aussage der Vorlage. Wiederhole nie den Satz davor mit anderen Worten, "
              "und schreib keine Sätze, die nur werten (\"Sicherheit ist entscheidend.\"). Zwei Hauptsätze trennst du mit "
              "Punkt oder verbindest sie mit \"und\", nie nur mit Komma.\n"
            + "Füge nichts hinzu, was nicht im Absatz steht.\n\n"
            f"Absatz:\n{paragraph}")


def paragraph_problems(source: str, result: str, plan: list[int], avoid: list[str] | None = None,
                       qualifiers: list[str] | None = None, strict: bool = False) -> list[str]:
    found = []
    lost = missing_qualifiers(qualifiers or [], result)
    if lost:
        found.append("Diese Einschränkungen aus der Vorlage fehlen und müssen rein: " + "; ".join(lost) + ".")
    for citation, claim in misplaced_citations(source, result):
        found.append(f'Die Quellenangabe {citation} steht bei der falschen Aussage. Sie belegt "{claim}" '
                     "und muss bei genau diesem Inhalt stehen.")
    for sentence in repeated_sentences(result):
        found.append(f'Dieser Satz wiederholt, was schon dasteht, streich ihn oder sag etwas anderes: "{sentence[:70]}…"')
    for word, extra, where in new_connectors(source, result):
        kind = ("einen Gegensatz, den" if word in CONNECTORS["Gegensatz"] else
                "eine Folge, die" if word in CONNECTORS["Folge"] else "einen Grund, den")
        found.append(f'Mit "{word}" behauptest du {kind} die Vorlage nicht nennt: ' +
                     " / ".join(f'"{s[:80]}…"' for s in where[:3]) +
                     ". Verbinde diese Aussagen neutral oder lass zwei Sätze stehen.")
    for sentence in unsupported_sentences(source, result):
        found.append(f'Dieser Satz hat keine Grundlage in der Vorlage, streich ihn: "{sentence}"')
    repeated = [h for h in habits(result) if h in (avoid or [])]
    if repeated:
        found.append("Diese verbotenen Wendungen stehen noch drin, formuliere anders: " + ", ".join(repeated) + ".")
    if strict:
        for fragment in fragments(result):
            found.append(f'Das ist kein vollständiger Satz: "{fragment}". Bau ihn in einen Nachbarsatz ein.')
    added = added_facts(source, result)
    if added:
        found.append("Diese Angaben stehen nicht in der Vorlage und müssen raus: " + ", ".join(added) + ".")
    gone = missing_facts(source, result) + missing_citations(source, result)
    if gone:
        found.append("Diese Angaben fehlen und müssen wörtlich rein: " + "; ".join(gone) + ".")
    doubled = doubled_citations(source, result)
    if doubled:
        found.append("Diese Quellenangabe steht jetzt öfter als in der Vorlage, sie gehört nur einmal hin: " +
                     "; ".join(doubled) + ".")
    words, target = len(result.split()), len(source.split())
    if not 0.8 * target <= words <= 1.2 * target:
        found.append(f"Der Absatz hat {words} Wörter, er soll etwa {target} haben. Nichts hinzuerfinden, nichts weglassen.")
    if plan_fit(plan, result) > 0.4:
        got = [len(s.split()) for s in sentences(result)]
        found.append(f"Deine Sätze haben {', '.join(map(str, got))} Wörter. Der Bauplan verlangt {len(plan)} Sätze "
                     f"mit {', '.join(map(str, plan))} Wörtern. Halte dich an den Bauplan.")
    same = unchanged_sentences(source, result)
    if same:
        found.append("Diese Sätze hast du fast wörtlich übernommen, bau sie um: " +
                     " / ".join(f'"{s[:60]}…"' for s in same) + ".")
    left = [t for t in AI_TELLS if t in result.lower()]
    if left:
        found.append("Diese Floskeln stehen noch drin: " + ", ".join(left) + ". Formuliere sie konkret.")
    for crutch in crutches(result):
        found.append(f"Du hast {crutch}. Das wirkt mechanisch, bau diese Sätze anders.")
    return found


def paragraph_badness(source: str, result: str, plan: list[int], avoid: list[str] | None = None,
                      qualifiers: list[str] | None = None, strict: bool = False) -> float:
    words, target = len(result.split()), len(source.split())
    fidelity = 20 * len(missing_qualifiers(qualifiers or [], result)) + 25 * len(misplaced_citations(source, result)) \
        + 10 * len(repeated_sentences(result)) + 20 * sum(extra for _, extra, _ in new_connectors(source, result)) \
        + 20 * len(unsupported_sentences(source, result))
    repeated = len([h for h in habits(result) if h in (avoid or [])])
    off = max(0.0, abs(words - target) / max(target, 1) - 0.2) * 100
    return (25 * (len(missing_facts(source, result)) + len(added_facts(source, result))
                  + len(missing_citations(source, result)) + len(doubled_citations(source, result)))
            + off + 15 * min(plan_fit(plan, result), 1.0) + 18 * len(unchanged_sentences(source, result))
            + 12 * tell_count(result) + 5 * len(crutches(result)) + 12 * repeated + fidelity
            + (25 * len(fragments(result)) if strict else 0))


def flatten(paragraph: str) -> str:
    """Zeilenumbrüche, die das Modell mitten in einen Absatz setzt, werden zu Leerzeichen."""
    return normalize_tokens(re.sub(r"\s*\n+\s*", " ", paragraph).strip())


def sentence_issues(source: str, sentence: str) -> dict[str, list[str]]:
    """Was an einem einzelnen Satz der Ausgabe zu reparieren ist: Floskeln, wörtliche Übernahme, neue Verknüpfung."""
    low = sentence.lower()
    issues = {
        "floskel": [t for t in AI_TELLS if t in low] + habits(sentence),
        "wörtlich": unchanged_sentences(source, sentence)[:1],
        "verknüpfung": [connector_name(w) for words in CONNECTORS.values() for w in words
                        if re.search(r"\b%s\b" % w, sentence, re.I) and not re.search(r"\b%s\b" % w, source, re.I)],
        "unbelegt": unsupported_clauses(source, sentence) + [s for s in added_negations(source, sentence)][:1]
        + invented_citations(source, sentence),
    }
    return {k: v for k, v in issues.items() if v}


def issue_score(issues: dict[str, list[str]]) -> int:
    return (len(issues.get("floskel", [])) + 2 * len(issues.get("wörtlich", [])) + 2 * len(issues.get("verknüpfung", []))
            + 3 * len(issues.get("unbelegt", [])))


REPAIR_SYSTEM = ("Du formulierst einzelne deutsche Sätze um. Du gibst nur den neuen Satz aus, ohne Kommentar und ohne "
                 "Anführungszeichen. Du fügst keine Information hinzu und lässt keine weg. Zahlen, Namen und "
                 "Quellenangaben in Klammern bleiben Zeichen für Zeichen gleich. Platzhalter wie ⟦Qa⟧ (Quellenangabe) "
                 "oder ⟦Za⟧ (wörtliches Zitat) übernimmst du unverändert und genau einmal.")


def repair_request(sentence: str, issues: dict[str, list[str]]) -> str:
    lines = []
    if "floskel" in issues:
        lines.append("Vermeide diese Wendungen: " + ", ".join(issues["floskel"]) + ". Sag konkret, was gemeint ist.")
    if "wörtlich" in issues:
        lines.append("Der Satz ist fast unverändert aus einer Vorlage übernommen. Stell ihn um: beginne mit einem "
                     "anderen Satzteil, wähle andere Verben und Wörter. Der Inhalt bleibt gleich.")
    if "verknüpfung" in issues:
        lines.append("Die Wörter " + ", ".join(f'"{w}"' for w in issues["verknüpfung"]) + " behaupten einen "
                     "Zusammenhang, der nicht belegt ist. Verbinde die Aussagen neutral (mit \"und\", Relativsatz oder "
                     "Doppelpunkt) oder mach zwei Sätze daraus.")
    if "unbelegt" in issues:
        lines.append("Diese Teile stehen nicht in der Vorlage, lass sie weg: " + " / ".join(f'"{u}"' for u in issues["unbelegt"])
                     + ". Erfinde keine Quelle, keine Verneinung und keine Begründung.")
    # Zahlen aus Quellenangaben nicht einzeln aufzählen, sonst hängt das Modell sie als "; 2015; 67" an den Satz.
    keep = list(dict.fromkeys(CITATION.findall(sentence)
                              + [surface for _, _, surface in facts(CITATION.sub(" ", sentence))]))
    if keep:
        lines.append("Diese Angaben bleiben wörtlich: " + "; ".join(keep))
    return "Formuliere diesen Satz neu.\n" + "\n".join(lines) + "\n\nSatz: " + sentence


def keeps_content(source: str, old: str, new: str, qualifiers: list[str], loose: bool = False) -> bool:
    """Trägt die neue Fassung alles, was die alte trug, und nichts, was die Vorlage nicht hat?
    loose erlaubt mehr Spielraum bei der Länge, an Zahlen, Quellen und Einschränkungen ändert es nichts."""
    carried = [q for q in qualifiers if core_stems(q) <= core_stems(old)]
    low, high = (0.5, 2.0 * len(old.split()) + 4) if loose else (0.6, 1.6 * len(old.split()) + 3)
    return (bool(new.strip())
            and low * len(old.split()) <= len(new.split()) <= high
            and not missing_facts(old, new) and all(c in new for c in CITATION.findall(old))
            and not added_facts(source, new) and not unsupported_sentences(source, new)
            and not missing_qualifiers(carried, new) and not missing_hedges(extract_hedges(old), new)
            and _negations(new) >= _negations(old) - (1 if added_negations(source, old) else 0)
            and not added_negations(source, new) and not invented_citations(source, new)
            and keeps_statement(old, new) and not added_facts(old, new)
            and _names_in(old, _NAMES) <= _names_in(new, _NAMES)
            and (not SUBJUNCTIVE.search(QUOTE.sub(" ", old)) or bool(SUBJUNCTIVE.search(QUOTE.sub(" ", new)))))


def clean_reply(reply: str) -> str:
    reply = flatten(reply)
    reply = re.sub(r"^(?:Satz|Neuer Satz|Umformulierung)\s*:\s*", "", reply, flags=re.I)
    reply = strip_list_echo(reply)
    return reply.strip("\"„“”»«").strip()


LIST_ECHO = re.compile(r"(?:\s*;\s*[^;.()]{1,25}?\.?)+\s*$")


def strip_list_echo(text: str) -> str:
    """Entfernt Anhängsel wie "(vgl. Müller 2018, S. 23); 20." oder "…; 2015; 67.": Das Modell hängt die Liste der
    Pflichtangaben an den Satz. Ein echter Satzteil nach Semikolon hat ein Verb und bleibt."""
    match = LIST_ECHO.search(text)
    if not match:
        return text
    pieces = [p.strip(" .") for p in match.group(0).split(";") if p.strip(" .")]
    if all(len(p.split()) <= 3 and (re.search(r"\d", p) or len(p.split()) == 1) and not TOKEN.search(p) for p in pieces):
        return text[:match.start()].rstrip(" ,;") + ("." if not text[:match.start()].rstrip().endswith(".") else "")
    return text


STOCK_WORDS = [
    # Floskelwörter, die sich ohne Modell und ohne Sinnverlust tauschen lassen. Satzanfänge behalten die
    # Verbzweitstellung, weil ein anderes Adverb an derselben Stelle steht.
    (re.compile(r"\b(?:Des Weiteren|Darüber hinaus)\b"), "Außerdem"),
    (re.compile(r"\b(?:des weiteren|darüber hinaus)\b"), "außerdem"),
    (re.compile(r"\b(?:essenzielle|entscheidende|zentrale|wichtige)(n?) Rolle\b"), r"große\1 Rolle"),
    (re.compile(r"\b([Ee])ssenziell"), lambda m: ("W" if m.group(1) == "E" else "w") + "ichtig"),
    (re.compile(r"\b([Uu])nerlässlich"), lambda m: ("N" if m.group(1) == "U" else "n") + "otwendig"),
    (re.compile(r"\b([Ll])etztendlich\b"), lambda m: m.group(1) + "etztlich"),
    (re.compile(r"\bgewährleisten\b"), "sichern"),
    (re.compile(r"\b(weitere[nrs]?) wichtige[nrs]? "), r"\1 "),
]


def strip_stock_words(source: str, sentence: str, qualifiers: list[str]) -> str:
    """Tauscht einzelne Floskelwörter regelbasiert aus. Übernommen wird das nur, wenn der Satz dadurch weniger
    Mängel hat und inhaltlich gleich bleibt."""
    new = sentence
    for pattern, replacement in STOCK_WORDS:
        new = pattern.sub(replacement, new)
    new = re.sub(r"\s{2,}", " ", new)
    if new != sentence and keeps_content(source, sentence, new, qualifiers, loose=True) \
            and issue_score(sentence_issues(source, new)) < issue_score(sentence_issues(source, sentence)):
        return new
    return sentence


def repair_sentences(source: str, parts: list[str], model: str, url: str, qualifiers: list[str],
                     tries: int = 2) -> tuple[list[str], int]:
    """Repariert jeden fehlerhaften Satz einzeln. Eine Reparatur zählt nur, wenn sie den Satz messbar verbessert
    und inhaltlich nichts verliert oder hinzufügt; sonst bleibt der alte Satz. Liefert Sätze und Zahl der Reparaturen.
    Floskelwörter werden zuerst regelbasiert getauscht; Sätze mit Floskel bekommen einen zusätzlichen Versuch, bei
    dem die Länge freier sein darf."""
    done = 0
    for i, sentence in enumerate(parts):
        issues = sentence_issues(source, sentence)
        if "floskel" in issues:
            stripped = strip_stock_words(source, sentence, qualifiers)
            if stripped != sentence:
                parts[i], sentence, issues = stripped, stripped, sentence_issues(source, stripped)
                done += 1
        rounds = tries + (1 if "floskel" in issues or "wörtlich" in issues else 0)
        for attempt in range(rounds):
            if not issues:
                break
            try:
                candidate = clean_reply(_chat(model, url, [{"role": "system", "content": REPAIR_SYSTEM},
                                                           {"role": "user", "content": repair_request(sentence, issues)}]))
            except OllamaError:
                break
            new_issues = sentence_issues(source, candidate)
            loose = attempt == rounds - 1 and rounds > tries
            invents_link = len(new_issues.get("verknüpfung", [])) > len(issues.get("verknüpfung", []))
            if (keeps_content(source, sentence, candidate, qualifiers, loose) and not invents_link
                    and issue_score(new_issues) < issue_score(issues)):
                parts[i], sentence, issues = candidate, candidate, new_issues
                done += 1
    return parts, done


def drop_unfounded(source: str, parts: list[str], strict: bool) -> list[str]:
    """Streicht ohne Modell, was nicht in den Absatz gehört: Sätze ohne Grundlage in der Vorlage, die keine Angabe
    tragen, und im akademischen Stil Fragmente wie "38 %.", deren Angabe schon in einem anderen Satz steht."""
    kept = []
    for i, sentence in enumerate(parts):
        rest = " ".join(parts[:i] + parts[i + 1:])
        carries = CITATION.search(sentence) or missing_facts(sentence, rest)
        if unsupported_sentences(source, sentence) and not carries:
            continue
        if strict and fragments(sentence) and not carries:
            continue
        if sentence in filler_sentences(" ".join(parts)) and not missing_hedges(extract_hedges(sentence), rest):
            continue
        if kept and not carries and sentence in repeated_sentences(" ".join(kept + [sentence])) \
                and not missing_hedges(extract_hedges(sentence), rest):
            continue  # wiederholt nur, was schon dasteht
        kept.append(sentence)
    return kept or parts[:1]


STOCK_STEMS = ("zusamm", "festha", "lässt", "beacht", "weiter", "heutig", "aspekt", "punkt", "abschl", "letztl", "letzte",
               "zeigt", "festst", "gilt", "sagen", "rolle", "spielt")


def statement_stems(sentence: str) -> set[str]:
    """Kernwörter einer Aussage ohne Floskeln und Wertungen: Was übrig bleibt, muss in der Ausgabe wieder auftauchen."""
    low = sentence.lower()
    for tell in AI_TELLS:
        low = low.replace(tell, " ")
    return {w for w in core_stems(low) if not w.startswith(VERDICT_STEMS + STOCK_STEMS)}


CLAUSE_SPLIT = re.compile(r",\s+|:\s+|;\s+|\s+(?=und (?:es|sie|er|das|dies|man|zudem|damit|so)\b)")


def unsupported_clauses(source: str, result: str) -> list[str]:
    """Teilsätze ohne Grundlage im Original, auch in sonst passenden Sätzen: "…, und es gibt keine Belege für einen
    Zusammenhang." Zählt nur Teilsätze mit mindestens vier Wörtern und zwei Kernwörtern, von denen weniger als ein
    Drittel im Original vorkommt."""
    have = core_stems(source.lower())
    found = []
    for sentence in raw_sentences(result):
        for clause in CLAUSE_SPLIT.split(CITATION.sub(" ", PLACEHOLDER.sub(" ", sentence))):
            stems = {w for w in core_stems(clause.lower()) if not w.startswith(STOCK_STEMS)}
            if len(clause.split()) >= 4 and len(stems) >= 2 and len(stems & have) / len(stems) < 0.34:
                found.append(re.sub(r"\s+", " ", clause).strip(" .!?"))
    return found


def added_negations(source: str, result: str) -> list[str]:
    """Sätze der Ausgabe mit einer Verneinung, die ihr Gegenstück im Original nicht hat."""
    originals = raw_sentences(source)
    found = []
    for sentence in raw_sentences(result):
        if not _negations(sentence) or not originals:
            continue
        best = max(originals, key=lambda o: overlap(sentence, o))
        if not _negations(best):  # mehr Verneinungen als das Original sind oft nur "weder … noch"; erfunden ist nur eine ganz neue
            found.append(sentence)
    return found


def keeps_statement(old: str, new: str) -> bool:
    """Sagt die neue Fassung noch dasselbe wie die alte? Mindestens die Hälfte der Aussage-Kernwörter muss bleiben,
    damit eine Reparatur nicht einen ganz anderen Satz des Absatzes liefert."""
    stems = statement_stems(old)
    return len(stems) < 3 or len(stems & core_stems(new.lower())) / len(stems) >= 0.5


def doubled_clauses(sentence: str) -> tuple[str, str] | None:
    """Zwei Hälften eines Satzes, die dasselbe sagen: "… wurde durch die Loveparade deutlich und die Loveparade zeigte
    die Folgen …". Liefert (behaltene Hälfte, doppelte Hälfte) oder None."""
    for match in re.finditer(r",? und ", sentence):
        first, second = sentence[:match.start()], sentence[match.end():]
        a, b = core_stems(CITATION.sub(" ", first)), core_stems(CITATION.sub(" ", second))
        same_fact = {f for _, f, _ in facts(first)} & {f for _, f, _ in facts(second)}
        if (len(a & b) >= 4 and len(a & b) / min(len(a), len(b)) >= 0.5) or (same_fact and len(a & b) >= 2):
            return first, second
    return None


def merge_doubled(sentence: str) -> str:
    """Streicht die doppelte Hälfte eines Satzes; Zahlen und Quellenangaben der gestrichenen Hälfte wandern mit."""
    found = doubled_clauses(sentence)
    if not found:
        return sentence
    first, second = found
    if missing_facts(second, first):
        return sentence
    citations = [c for c in CITATION.findall(second) if c not in first]
    first = first.rstrip(" .,;")
    return first + (" " + " ".join(citations) if citations else "") + "."


STRAY_PAREN = re.compile(r"\s*\((?:[a-zäöüß]+(?:\s+[a-zäöüß]+)?)\)")


ECHO_PAREN = re.compile(r"\s*\(([^()\d]{12,})\)")


def strip_stray_parens(source: str, text: str) -> str:
    """Entfernt Klammer-Reste wie "(die)" und Klammern, die nur wiederholen, was im selben Satz schon steht
    ("… keine Gegensätze sind (so dass sich zeigt, dass sie keine Gegensätze sind)"). Klammern aus dem Original bleiben."""
    text = STRAY_PAREN.sub(lambda m: m.group(0) if m.group(0).strip() in source else "", text)

    def echo(m: re.Match) -> str:
        inner, rest = core_stems(m.group(1)), core_stems(text.replace(m.group(0), " "))
        return "" if m.group(0).strip() not in source and inner and len(inner & rest) / len(inner) >= 0.6 else m.group(0)
    return ECHO_PAREN.sub(echo, text)


def drop_repeats(parts: list[str]) -> list[str]:
    """Streicht am Ende Sätze, die nur einen früheren wiederholen und keine eigene Zahl, Quelle, Abschwächung oder
    Verneinung tragen."""
    kept = []
    for sentence in parts:
        rest = " ".join(kept)
        unique = missing_facts(sentence, rest) or any(c not in rest for c in CITATION.findall(sentence)) or \
            missing_hedges(extract_hedges(sentence), rest) or _negations(sentence) > _negations(rest)
        if kept and not unique and _mask(sentence).strip() in repeated_sentences(" ".join(kept + [sentence])):
            continue
        kept.append(sentence)
    return kept


def dedupe_tokens(parts: list[str]) -> list[str]:
    """Jeder Platzhalter einer Quellenangabe steht genau einmal. Setzt das Modell ihn ein zweites Mal, etwa in eckigen
    Klammern "[⟦Qa⟧]" oder angehängt "… nicht enthalten und ⟦Qa⟧.", fällt die spätere Stelle weg."""
    seen: set[str] = set()
    out = []
    for sentence in parts:
        for token in dict.fromkeys(re.findall(r"⟦Q[a-z]+⟧", sentence)):
            if token in seen:
                sentence = re.sub(r"(?:\s*,)?(?:\s+(?:und|sowie|bzw\.|oder))?\s*\[?\s*" + re.escape(token) + r"\s*\]?",
                                  "", sentence)
            seen.add(token)
        sentence = re.sub(r"\s+([.,;:!?])", r"\1", sentence).strip()
        if re.search(r"\w", sentence):
            out.append(sentence)
    return out


def strip_quote_echo(parts: list[str], mapping: dict[str, str]) -> list[str]:
    """Streicht Nebensätze, die ein direktes Zitat noch einmal ohne Anführungszeichen nacherzählen, etwa
    "… ⟦Za⟧ ⟦Qa⟧, was sie zu einer sehr einfachen Möglichkeit … macht." Der Inhalt steht ja schon im Zitat."""
    quotes = [core_stems(o) for t, o in mapping.items() if t.startswith("⟦Z") and len(core_stems(o)) >= 3]
    out = []
    for sentence in parts:
        end = sentence[-1] if sentence and sentence[-1] in ".!?" else ""
        clauses = re.split(r",\s+", sentence[:-1] if end else sentence)
        kept = clauses[:1] + [c for c in clauses[1:] if TOKEN.search(c) or not any(
            len(core_stems(c) & q) / len(q) >= 0.7 and len(core_stems(c) - q) <= 2 for q in quotes)]
        out.append(", ".join(kept) + end if len(kept) < len(clauses) else sentence)
    return out


def dropped_statements(source: str, result: str) -> list[str]:
    """Sätze des Originals, deren eigentliche Aussage in der Ausgabe so gut wie nicht mehr vorkommt."""
    have = core_stems(result.lower())
    return [o for o in raw_sentences(source)
            if len(statement_stems(o)) >= 3 and len(statement_stems(o) & have) / len(statement_stems(o)) < 0.25]


def overlap(a: str, b: str) -> float:
    stems = core_stems(a)
    return len(stems & core_stems(b)) / len(stems) if stems else 0.0


def restore_facts(source: str, parts: list[str], complete: bool = False) -> tuple[list[str], int]:
    """Stellt sicher, dass keine Zahl, kein Datum und keine Quelle fehlt, erfunden ist oder falsch steht.

    Wo die Ausgabe das nicht hält, tritt der Originalsatz an die Stelle des betroffenen Satzes. Im schlimmsten Fall
    bleibt damit ein Satz unverändert; verloren oder verfälscht ist dann nichts. Mit complete gilt dasselbe für
    Sätze mit einem neu behaupteten Gegensatz oder einer neuen Folge und für Aussagen der Vorlage, die ganz fehlen.
    Liefert Sätze und Zahl der Eingriffe.
    """
    originals = raw_sentences(source)
    parts, changes = list(parts), 0

    def put(original: str, at: int | None) -> None:
        """Setzt den Originalsatz an Stelle at oder dorthin, wo der ähnlichste Satz der Ausgabe steht."""
        nonlocal changes
        changes += 1
        if original in parts:
            return
        if at is None:
            scores = [overlap(original, p) for p in parts]
            if scores and max(scores) >= 0.5:
                at = scores.index(max(scores))
        if at is not None:
            parts[at] = original
        else:
            position = round(originals.index(original) * len(parts) / max(len(originals), 1))
            parts.insert(min(position, len(parts)), original)

    for _ in range(3 * len(originals) + 3):
        text = " ".join(parts)
        invented = next((i for i, p in enumerate(parts) if added_facts(source, p)), None)
        if invented is not None:
            best = max(originals, key=lambda o: overlap(o, parts[invented]))
            if overlap(best, parts[invented]) >= 0.3:
                put(best, invented)
            else:
                del parts[invented]
                changes += 1
            continue
        moved = misplaced_citations(source, text)
        if moved:
            citation = moved[0][0]
            at = next((i for i, p in enumerate(parts) if citation in p), None)
            put(next(o for o in originals if citation in o), at)
            continue
        missing = missing_citations(source, text) + missing_facts(source, text)
        if missing:
            original = next((o for o in originals if missing[0] in o), None)
            if original is None or original in parts:
                break
            put(original, None)
            continue
        if not complete:
            break
        # Ein Satz, der mit "obwohl" oder "sodass" einen Zusammenhang behauptet, den die Vorlage nicht kennt.
        linked = next((i for i, p in enumerate(parts) if p not in originals and sentence_issues(source, p).get("verknüpfung")), None)
        if linked is not None:
            put(max(originals, key=lambda o: overlap(o, parts[linked])), linked)
            continue
        # Eine Aussage der Vorlage, von der in der Ausgabe so gut wie nichts mehr steht, eine verlorene Verneinung
        # ("sind keine Gegensätze") oder eine verlorene Abschwächung ("gilt häufig", "muss").
        lost = [o for o in dropped_statements(source, text) + missing_negations(source, text)
                + missing_attributions(source, text) + missing_subjunctive(source, text) if o not in parts]
        bad = next((i for i, p in enumerate(parts) if p not in originals and (added_negations(source, p)
                                                                              or invented_citations(source, p))), None)
        if bad is not None and not lost:
            put(max(originals, key=lambda o: overlap(o, parts[bad])), bad)
            continue
        for hedge in missing_hedges(extract_hedges(source), text):
            lost += [o for o in originals if hedge in extract_hedges(o) and o not in parts][:1]
        if not lost:
            break
        put(lost[0], None)
    return parts, changes


def split_longest(source: str, parts: list[str], model: str, url: str, qualifiers: list[str], spread) -> tuple[list[str], int]:
    """Teilt den längsten Satz in einen kurzen und einen längeren."""
    lengths = [len(p.split()) for p in parts]
    i = lengths.index(max(lengths))
    if lengths[i] < 16:
        return parts, 0
    request = ("Teile diesen Satz in genau zwei Sätze: einen kurzen mit höchstens 8 Wörtern und einen längeren. "
               "Beide sind vollständige Sätze. Kein \"obwohl\", \"sodass\", \"daher\", \"weil\", \"da\". Alle Zahlen und "
               "Quellenangaben bleiben wörtlich.\n\nSatz: " + parts[i])
    try:
        reply = clean_reply(_chat(model, url, [{"role": "system", "content": REPAIR_SYSTEM},
                                               {"role": "user", "content": request}]))
    except OllamaError:
        return parts, 0
    pieces = raw_sentences(reply)
    new_lengths = lengths[:i] + [len(p.split()) for p in pieces] + lengths[i + 1:]
    fine = (len(pieces) == 2 and not fragments(reply) and keeps_content(source, parts[i], reply, qualifiers)
            and spread(new_lengths) > spread(lengths)
            and issue_score(sentence_issues(source, reply)) <= issue_score(sentence_issues(source, parts[i])))
    return (parts[:i] + pieces + parts[i + 1:], 1) if fine else (parts, 0)


def merge_pair(source: str, parts: list[str], i: int, model: str, url: str, qualifiers: list[str]) -> tuple[list[str], int]:
    """Legt Satz i und i+1 zusammen, wenn dabei nichts verloren geht und kein neuer Zusammenhang entsteht."""
    pair = parts[i] + " " + parts[i + 1]
    request = ("Verbinde diese zwei Sätze zu einem einzigen Satz. Verbinde neutral: mit \"und\", einem Relativsatz, "
               "einem Doppelpunkt oder einem Semikolon. Kein \"obwohl\", \"sodass\", \"daher\", \"weil\", \"da\". Alle Zahlen und "
               "Quellenangaben bleiben wörtlich.\n\nSätze: " + pair)
    try:
        merged = clean_reply(_chat(model, url, [{"role": "system", "content": REPAIR_SYSTEM},
                                                {"role": "user", "content": request}]))
    except OllamaError:
        return parts, 0
    fine = (len(raw_sentences(merged)) == 1 and keeps_content(source, pair, merged, qualifiers)
            and issue_score(sentence_issues(source, merged)) <= issue_score(sentence_issues(source, parts[i]))
            + issue_score(sentence_issues(source, parts[i + 1])))
    return (parts[:i] + [merged] + parts[i + 2:], 1) if fine else (parts, 0)


def vary_rhythm(source: str, parts: list[str], model: str, url: str, qualifiers: list[str],
                attempts: int = 3) -> tuple[list[str], int]:
    """Sind die Sätze eines Absatzes zu gleich lang, probiert die App der Reihe nach, was am meisten bringt: zwei
    Nachbarn zusammenlegen oder den längsten Satz teilen. Der erste Eingriff, bei dem nichts verloren geht und kein
    neuer Zusammenhang behauptet wird, gilt. Höchstens attempts Anfragen an das Modell."""
    def spread(lengths: list[int]) -> float:
        return burstiness(" ".join("x " * (n - 1) + "x." for n in lengths))

    lengths = [len(p.split()) for p in parts]
    if len(parts) < 2 or spread(lengths) >= 0.50:  # Abstand zur Prüfschwelle 0,45
        return parts, 0
    options = sorted(((spread(lengths[:i] + [lengths[i] + lengths[i + 1]] + lengths[i + 2:]), i)
                      for i in range(len(parts) - 1) if lengths[i] + lengths[i + 1] <= 45), reverse=True) \
        if len(parts) >= 3 else []
    steps = [lambda i=i: merge_pair(source, parts, i, model, url, qualifiers)
             for gain, i in options if gain > spread(lengths)]
    # Teilen kommt nach dem besten Zusammenlegen, vor den schwächeren Varianten.
    steps.insert(1 if steps else 0, lambda: split_longest(source, parts, model, url, qualifiers, spread))
    for step in steps[:attempts]:
        new, done = step()
        if done:
            return new, done
    return parts, 0


def rewrite_paragraph(paragraph: str, style: str, model: str, url: str, pool: list, retries: int = 1,
                      rng: random.Random | None = None, avoid: list[str] | None = None) -> tuple[str, int, list[str]]:
    """Versteckt Zitate und Quellenangaben hinter Platzhaltern, schreibt den Absatz um und setzt sie danach Zeichen
    für Zeichen wieder ein. Das Modell kann sie so weder umformulieren noch übersetzen."""
    masked, mapping = protect(paragraph)
    quotes = {t: o for t, o in mapping.items() if t.startswith("⟦Z")}
    legend = ("Platzhalter: ⟦Qa⟧, ⟦Qb⟧ … sind Quellenangaben, ⟦Za⟧, ⟦Zb⟧ … wörtliche Zitate. Übernimm jeden genau "
              "einmal und unverändert, im Satz mit derselben Aussage. Schreib nie den Zitattext selbst hin. Zur "
              "Orientierung, was die Zitate sagen:\n" + "\n".join(f"{t} = {o}" for t, o in quotes.items()) + "\n\n"
              if mapping else "")
    _ACTIVE.clear()
    _ACTIVE.update(mapping)
    _NAMES.clear()
    _NAMES.update(author_names(paragraph))
    try:
        text, extra, qualifiers = _rewrite_masked(masked, style, model, url, pool, retries, rng, avoid, legend, mapping)
    finally:
        _ACTIVE.clear()
        _NAMES.clear()
    text = normalize_tokens(text, mapping)
    if not text.strip() or any(t not in text for t in mapping):  # Sicherheitsnetz: lieber das Original
        return paragraph, extra, [unprotect(q, mapping) for q in qualifiers]
    return unprotect(text, mapping), extra, [unprotect(q, mapping) for q in qualifiers]


def _rewrite_masked(paragraph: str, style: str, model: str, url: str, pool: list, retries: int = 1,
                    rng: random.Random | None = None, avoid: list[str] | None = None, legend: str = "",
                    mapping: dict[str, str] | None = None) -> tuple[str, int, list[str]]:
    """Schreibt einen Absatz nach Bauplan um und repariert ihn danach Satz für Satz.

    1. Entwurf nach Bauplan; ist er grob daneben, höchstens retries neue Entwürfe mit Rückmeldung.
    2. Sätze ohne Grundlage und Fragmente streichen.
    3. Jeden Satz mit Floskel, wörtlicher Übernahme oder neuer Verknüpfung einzeln reparieren.
    4. Fehlende, erfundene oder verrutschte Zahlen und Quellen, neu behauptete Zusammenhänge und ganz fehlende
       Aussagen durch den Originalsatz ersetzen, und diese Sätze noch einmal einzeln reparieren.
    5. Zu gleichförmige Satzlängen durch Zusammenlegen zweier Sätze auflockern.
    Jeder Schritt wird nur übernommen, wenn er nichts verschlechtert. Zurück kommen der Absatz, die Zahl der
    Eingriffe und die Einschränkungen (Orte, Zeiträume, Gruppen), die erhalten bleiben sollten.
    """
    qualifiers = extract_qualifiers(paragraph)
    strict = style == "Akademisch"
    plan, example = sentence_plan(paragraph, pool, rng, strict)
    messages = [{"role": "system", "content": system_prompt(style, [example] if example else [])},
                {"role": "user", "content": legend + paragraph_request(paragraph, plan, avoid, qualifiers)}]
    draft = flatten(_chat(model, url, messages))
    score, extra = paragraph_badness(paragraph, draft, plan, avoid, qualifiers, strict), 0
    for _ in range(retries):
        if score < 60:  # nur bei groben Mängeln neu ansetzen, alles andere reparieren die Schritte unten gezielter
            break
        issues = paragraph_problems(paragraph, draft, plan, avoid, qualifiers, strict)
        again = flatten(_chat(model, url, messages + [
            {"role": "assistant", "content": draft},
            {"role": "user", "content": "Das passt noch nicht:\n- " + "\n- ".join(issues) +
             "\n\nGib nur den verbesserten Absatz aus."}]))
        extra += 1
        if paragraph_badness(paragraph, again, plan, avoid, qualifiers, strict) < score:
            draft, score = again, paragraph_badness(paragraph, again, plan, avoid, qualifiers, strict)

    parts = drop_unfounded(paragraph, raw_sentences(draft), strict)
    parts, repaired = repair_sentences(paragraph, parts, model, url, qualifiers)
    parts, restored = restore_facts(paragraph, parts, complete=True)
    if restored:  # zurückgesetzte Originalsätze bekommen ihre eigene Chance, umformuliert zu werden
        parts, more = repair_sentences(paragraph, parts, model, url, qualifiers)
        repaired += more
    parts, merged = vary_rhythm(paragraph, parts, model, url, qualifiers)
    for a, b in echo_pairs(" ".join(parts))[:2]:  # zwei Nachbarn im selben Satzmuster werden ein Satz
        if a in parts and b in parts and parts.index(b) == parts.index(a) + 1:
            parts, done = merge_pair(paragraph, parts, parts.index(a), model, url, qualifiers)
            merged += done
    parts, again = restore_facts(paragraph, parts)
    stripped = drop_repeats(strip_quote_echo(dedupe_tokens([strip_list_echo(strip_stray_parens(
        paragraph, merge_doubled(strip_placeholders(strip_stock_words(paragraph, p, qualifiers))))) for p in parts]),
        mapping or {}))
    again += sum(a != b for a, b in zip(stripped, parts)) + abs(len(parts) - len(stripped))
    return " ".join(stripped), extra + repaired + restored + merged + again, qualifiers


def chunks(paragraph: str) -> list[str]:
    """Teilt einen langen Absatz (ab 6 Sätzen) in Stücke zu 3 bis 4 Sätzen. Ein lokales Modell hält bei kurzen
    Stücken Aussagen, Zahlen und Quellen deutlich verlässlicher fest. Zitate werden nie zerschnitten."""
    masked, mapping = protect(paragraph)
    parts = raw_sentences(masked)
    count = max(1, round(len(parts) / 3.5))
    if count == 1:
        return [paragraph]
    size, extra = divmod(len(parts), count)
    out, start = [], 0
    for k in range(count):
        end = start + size + (1 if k < extra else 0)
        out.append(unprotect(" ".join(parts[start:end]), mapping))
        start = end
    return out


def rewrite_block(paragraph: str, style: str, model: str, url: str, pool: list, retries: int = 1,
                  rng: random.Random | None = None, avoid: list[str] | None = None) -> tuple[str, int, list[str]]:
    """Schreibt einen Absatz um, lange Absätze Stück für Stück."""
    avoid = list(avoid or [])
    texts, extra, qualifiers = [], 0, []
    for piece in chunks(paragraph):
        if not needs_rewrite(piece):
            texts.append(piece)
            continue
        text, more, found = rewrite_paragraph(piece, style, model, url, pool, retries, rng, avoid)
        texts.append(text)
        extra += more
        qualifiers += found
        avoid += [h for h in habits(text) if h not in avoid]
    return " ".join(texts), extra, qualifiers


def needs_rewrite(paragraph: str) -> bool:
    """Überschriften und Einzeiler bleiben, wie sie sind."""
    return len(paragraph.split()) >= 12 and len(sentences(paragraph)) >= 2


def humanize_checked(text: str, style: str, model: str, url: str = OLLAMA_URL, pool: list | None = None,
                     retries: int = 1, progress=lambda done, total: None,
                     rng: random.Random | None = None) -> tuple[str, int, list[str]]:
    """Schreibt den Text Absatz für Absatz um.

    Zurück kommen der Text, 1 plus die Zahl der Nachbesserungen und alle Einschränkungen, die erhalten bleiben sollten.
    """
    paras, seps = split_blocks(text)
    todo = [i for i, p in enumerate(paras) if needs_rewrite(p)]
    # Die Wendungen sind von Anfang an verboten, nicht erst nach ihrem ersten Auftreten.
    out, extra, used, qualifiers = list(paras), 0, [name for _, name in HABITS], []
    for step, i in enumerate(todo, start=1):
        progress(step, len(todo))
        out[i], more, found = rewrite_block(paras[i], style, model, url, pool or [], retries, rng, used)
        extra += more
        qualifiers += found
        used += [h for h in habits(out[i]) if h not in used]
    return "".join(p + sep for p, sep in zip(out, seps)).strip(), 1 + extra, qualifiers


FACT = re.compile(r"\d+(?:[.,:/-]\d+)*")


NUMBER_WORDS = dict(zip(map(str, range(2, 13)), "zwei drei vier fünf sechs sieben acht neun zehn elf zwölf".split()))


UNITS = (r"%|Prozent|‰|Promille|€|Euro|dB\(A\)|km|kWh|MWh|GWh|Gigawattstunden|Megawattstunden|Kilowattstunden|"
         r"km/h|Minuten|Minute|Stunden|Stunde|Tagen|Tage|Tag|Wochen|Woche|Monaten|Monate|Monat|Jahren|Jahre|Jahr|"
         r"Personen|Person|Prozentpunkte|Metern|Meter|Watt")
FACT_WITH_UNIT = re.compile(r"(\d+(?:[.,:/-]\d+)*)(?:\s?(%s))?(?![\w(])" % UNITS)
SAME_UNIT = {"Prozent": "%", "Promille": "‰", "Euro": "€", "GWh": "giga", "MWh": "mega", "kWh": "kilo"}


def facts(text: str) -> list[tuple[str, str, str]]:
    """Zahlen mit ihrer Einheit als (Zahl, vereinheitlichte Einheit, wie es dasteht).

    "60 %" und "60 Prozent" bekommen dieselbe Einheit, Wort-Einheiten werden über ihre ersten drei Buchstaben
    verglichen, damit "Tag", "Tage" und "Tagen" gleich zählen.
    """
    found = []
    for m in FACT_WITH_UNIT.finditer(text):
        unit = m.group(2) or ""
        unit = SAME_UNIT.get(unit, unit if not unit[:1].isalpha() or unit in ("dB(A)", "km/h") else unit.lower()[:3])
        found.append((m.group(1), unit, m.group(0)))
    return found


def missing_facts(source: str, result: str) -> list[str]:
    """Zahlen und Daten aus dem Original, die in der Ausgabe fehlen oder ihre Einheit verloren haben.

    "60 %" fehlt, wenn nur noch "60" dasteht. Eine Zahl ohne Einheit zählt als vorhanden, egal mit welcher Einheit
    sie in der Ausgabe steht. Eine ausgeschriebene kleine Zahl ("zwei" statt "2") zählt als vorhanden, sonst
    verlangt die Nachbesserung eine Zahl, die längst dasteht, und das Modell dichtet einen Satz dazu.
    """
    have = {(n, u) for n, u, _ in facts(result)}
    numbers = {n for n, _ in have}
    missing = []
    # Zahlen in Quellenangaben prüft missing_citations(), sonst zählt eine fehlende Quelle doppelt.
    for number, unit, surface in facts(CITATION.sub(" ", source)):
        spelled = number in NUMBER_WORDS and re.search(r"\b%s\b" % NUMBER_WORDS[number], result, re.I)
        if number == "1":  # "1 Tag" -> "einen Tag"; "ein" allein steht überall, deshalb nur mit dem Wort danach
            after = re.escape(surface.split(None, 1)[1][:4]) if " " in surface else ""
            spelled = bool(after) and re.search(r"\bein(?:e[nmrs]?)?\s+%s" % after, result, re.I)
        present = (number, unit) in have if unit else number in numbers
        if not present and not spelled and surface not in missing:
            missing.append(surface)
    return missing


def added_facts(source: str, result: str) -> list[str]:
    """Zahlen und Daten in der Ausgabe, die das Original nicht enthält, also vom Modell erfunden sind.

    Zahlen aus Quellenangaben zählen nur dort: Macht das Modell aus "(vgl. Berger 2021)" ein "seit 2021" im Fließtext,
    ist das eine erfundene Aussage.
    """
    have = set(FACT.findall(CITATION.sub(" ", source)))
    for citation in CITATION.findall(source):
        # Nur wenn die Klammer-Angabe aufgelöst wurde; steht sie noch da, ist ein "seit 2021" daneben erfunden.
        if citation not in result and narrative_citation(citation, result):
            have.update(citation_parts(citation)[1])
    added = []
    for fact in FACT.findall(CITATION.sub(" ", result)):
        if fact not in have and fact not in added:
            added.append(fact)
    return added


STOPWORDS = set("""der die das den dem des ein eine einer einem einen eines und oder aber auch als wie bei mit von vom
zum zur für auf aus nach über unter vor hinter neben zwischen durch gegen ohne um bis seit sich ist sind war waren wird
werden wurde wurden hat haben kann können muss müssen soll sollen nicht nur noch schon sehr mehr dass wenn weil denn
diese dieser dieses diesen diesem jede jeder jedes jeden allen alle immer heute dabei damit somit dort hier""".split())


def core_stems(text: str) -> set[str]:
    """Kernwörter als Stämme aus den ersten sechs Buchstaben, ohne Füllwörter und Quellenangaben."""
    words = re.findall(r"[A-Za-zÄÖÜäöüß]{4,}", CITATION.sub(" ", text))
    return {w.lower()[:6] for w in words if w.lower() not in STOPWORDS}


CONNECTORS = {
    "Gegensatz": ["obwohl", "obgleich", "obschon", "trotzdem", "dennoch", "jedoch", "allerdings", "wenngleich"],
    "Folge": ["sodass", "so dass", "wodurch", "dadurch", "daher", "deshalb", "deswegen", "folglich", "somit", "weshalb", "infolgedessen"],
    # "da" nur als Bindewort nach Komma, sonst träfe es jedes "da ist"
    "Grund": ["weil", "denn", "(?<=, )da"],
}


def connector_name(pattern: str) -> str:
    return re.sub(r"\(.*?\)", "", pattern)


def new_connectors(source: str, result: str) -> list[tuple[str, int, list[str]]]:
    """Gegensatz- und Folge-Wörter, die die Ausgabe öfter benutzt als die Vorlage. Liefert (Wort, wie oft mehr, Sätze).

    Ein neues "obwohl" behauptet einen Gegensatz, ein neues "sodass" eine Folge, die vielleicht nirgends steht.
    """
    found = []
    for words in CONNECTORS.values():
        for word in words:
            pattern = re.compile(r"\b%s\b" % word, re.I)
            extra = len(pattern.findall(result)) - len(pattern.findall(source))
            if extra > 0:
                found.append((connector_name(word), extra, [s for s in sentences(result) if pattern.search(s)]))
    return found


def unsupported_sentences(source: str, result: str) -> list[str]:
    """Sätze der Ausgabe, deren Kernwörter zu weniger als einem Drittel in der Vorlage vorkommen, also
    hinzugedichtet sind, etwa "Das gilt für alle Bereiche."."""
    # Als Teil eines zusammengesetzten Worts zählt ein Stamm auch: "Veranstalter" steckt in "Festivalveranstalter".
    text = _mask(source).lower()
    numbers = {n for n, _, _ in facts(source)}
    found = []
    for sentence in sentences(result):
        stems = core_stems(sentence)
        if any(n in numbers for n, _, _ in facts(sentence)):
            continue  # trägt eine Zahl aus dem Original, ist also belegt
        if len(stems) >= 2 and sum(st in text for st in stems) / len(stems) < 1 / 3:
            found.append(sentence)
    return found


def misplaced_citations(source: str, result: str) -> list[tuple[str, str]]:
    """Quellenangaben, die jetzt bei einer anderen Aussage stehen als im Original. Liefert (Quelle, Originalsatz).

    Verglichen werden die Kernwörter des Satzes, in dem die Quelle im Original steht, mit dem Satz, in dem sie jetzt
    steht. Teilen beide weniger als 40 %, belegt die Quelle offensichtlich etwas anderes.
    """
    found = []
    src_sentences, out_sentences = sentences(source), sentences(result)
    for citation in dict.fromkeys(CITATION.findall(source)):
        masked = _mask(citation)
        before = next((s for s in src_sentences if masked in s), None)
        after = next((s for s in out_sentences if masked in s), None)
        if before is None or after is None:
            continue
        stems = core_stems(before)
        if stems and len(stems & core_stems(after)) / len(stems) < 0.4:
            found.append((citation, CITATION.sub("", before.replace(masked, "")).strip()))
    return found


def repeated_sentences(result: str) -> list[str]:
    """Sätze, die inhaltlich einen früheren Satz desselben Texts wiederholen."""
    seen, repeated = [], []
    for sentence in sentences(result):
        stems = core_stems(sentence)
        if len(stems) >= 4 and any(len(stems & s) / min(len(stems), len(s)) >= 0.6 for s in seen):
            repeated.append(sentence)
        if len(stems) >= 4:
            seen.append(stems)
    return repeated


# Wendungen, die eine Aussage genau machen oder einschränken: wo, bei wem, wofür, seit wann.
QUALIFIER_PP = re.compile(
    r"\b(?:[Ii]n|[Ii]m|[Aa]m|[Bb]ei|[Bb]eim|[Pp]ro|[Jj]e|[Ss]eit|[Aa]us|[Ii]nnerhalb|[Aa]ußerhalb|[Ff]ür)\s+"
    r"(?:(?:der|dem|den|des|die|das|einem|einer|eines)\s+)?(?:(?!denen|deren|dessen|welche)[a-zäöüß]+(?:en|em|er|es|e)\s+)?[A-ZÄÖÜ][\wäöüß-]*[\wäöüß]\b(?!-)")
QUALIFIER_ADJ = re.compile(
    r"\b(?:europä|österreich|deutsch|schweizer|amerikan|asiat|afrikan|internation|national|region|kommunal|städt|"
    r"ländl|bundes|landes|öffentl|privat|gesetzl|behördl|mehrtäg|eintäg|jährl|monatl|wöchentl|tägl)[a-zäöüß]*"
    r"\s+[A-ZÄÖÜ][\wäöüß-]+")
GENERIC_NOUNS = {"bereich", "rahmen", "hinblick", "bezug", "zeit", "folge", "lage", "weise", "laufe", "fall", "zuge",
                 "regel", "allgemeinen", "grunde", "wesentlichen", "prinzip", "zusammenhang", "jahr"}


def extract_qualifiers(paragraph: str) -> list[str]:
    """Einschränkungen eines Absatzes, die beim Umschreiben nicht verloren gehen dürfen.

    Zum Beispiel "In Österreich", "am Mischpult", "bei einem mehrtägigen Festival", "europäischen
    Festivalveranstalter". Allgemeine Wendungen wie "im Bereich" oder "in der Regel" zählen nicht.
    """
    found = [m.group(0) for m in QUALIFIER_PP.finditer(paragraph)] + \
            [m.group(0) for m in QUALIFIER_ADJ.finditer(paragraph)]
    kept, stems = [], []
    for item in found:
        core = core_stems(item)
        if item.split()[-1].lower() in GENERIC_NOUNS or not core or any(core <= other for other in stems):
            continue
        kept.append(item)
        stems.append(core)
    return kept


def missing_qualifiers(qualifiers: list[str], result: str) -> list[str]:
    """Einschränkungen, von denen mindestens ein Kernwort in der Ausgabe fehlt."""
    have = core_stems(result)
    return [q for q in qualifiers if not core_stems(q) <= have]


# Abschwächungen, Gradangaben und Modalverben: Wörter einer Gruppe gelten als gleichwertig ("rund" = "etwa").
HEDGE_GROUPS = [
    ("häufig", ["häufig", "oft", "meist", "meistens", "vielfach", "in der Regel", "üblicherweise", "in vielen Fällen"]),
    ("etwa", ["etwa", "rund", "circa", "ca.", "ungefähr", "annähernd", "knapp"]),
    ("bis zu", ["bis zu", "maximal", "höchstens", "nicht mehr als"]),
    ("mindestens", ["mindestens", "wenigstens", "nicht weniger als"]),
    ("zunehmend", ["zunehmend", "immer mehr", "immer stärker", "verstärkt", "wachsend", "steigend"]),
    ("bereits", ["bereits", "schon"]),
    ("deutlich", ["deutlich", "erheblich", "spürbar", "merklich", "stark", "klar", "wesentlich"]),
    ("kaum", ["kaum", "selten", "wenig"]),
    ("nicht immer", ["nicht immer", "nicht in jedem Fall", "nicht jedes Mal"]),
    ("teilweise", ["teilweise", "zum Teil", "teils", "mitunter", "manchmal", "gelegentlich"]),
    ("überwiegend", ["überwiegend", "weitgehend", "größtenteils", "mehrheitlich", "meist"]),
    ("vermutlich", ["vermutlich", "möglicherweise", "wahrscheinlich", "vielleicht", "eventuell", "dürfte", "dürften"]),
    ("muss", ["muss", "müssen", "müsste", "müssten", "musste", "mussten", "erforderlich", "notwendig", "nötig",
              "verpflichtet", "unumgänglich", "zwingend", "ist zu", "sind zu", "gilt es"]),
    ("kann", ["kann", "können", "könnte", "könnten", "konnte", "lässt sich", "lassen sich", "möglich", "ermöglich"]),
    ("soll", ["soll", "sollen", "sollte", "sollten", "empfiehlt", "empfehlen", "ratsam"]),
    ("darf", ["darf", "dürfen", "durfte", "erlaubt", "zulässig", "gestattet"]),
]


def _has_any(words: list[str], text: str) -> bool:
    return any(re.search(r"(?<![\wäöüß])" + re.escape(w) + r"(?![äöüß]|\w)" if not w.endswith("ermöglich")
                         else re.escape(w), text, re.I) for w in words)


def extract_hedges(paragraph: str) -> list[str]:
    """Abschwächungen und Modalverben eines Absatzes, nach Gruppen. Aus "gilt häufig" wird "häufig", aus "muss" "muss".
    Ein "nicht immer" zählt nicht zusätzlich als Verneinung."""
    found = []
    for name, words in HEDGE_GROUPS:
        # Nur die eigentlichen Signalwörter starten eine Gruppe; Umschreibungen ("notwendig") zählen nur als Ersatz.
        if _has_any(words[:4] if name in ("muss", "kann", "soll", "darf") else words[:1], paragraph):
            found.append(name)
    return found


def missing_hedges(hedges: list[str], result: str) -> list[str]:
    """Abschwächungen, für die in der Ausgabe kein Wort derselben Gruppe mehr steht. "muss" → "sollte" fehlt also."""
    groups = dict(HEDGE_GROUPS)
    return [h for h in hedges if not _has_any(groups[h], result)]


NEGATION = re.compile(r"\b(?:nicht|kein\w*|nie|niemals|weder|nirgends)\b", re.I)
# Verneinungen, die nur eine Redewendung sind und positiv umschrieben werden dürfen ("nicht mehr wegzudenken" =
# "gehört dazu"), sowie "nicht nur … sondern auch" und "nicht immer" (das zählt als Abschwächung).
NEGATION_IDIOMS = re.compile(
    r"\b(?:nicht|kaum) (?:nur|immer|zuletzt|einmal|mehr wegzudenken|wegzudenken|zu unterschätzen|zu vernachlässigen|"
    r"umsonst|ohne Grund|selten|unerheblich|unbedeutend|unwesentlich)\b", re.I)


def _negations(text: str) -> int:
    text = NEGATION_IDIOMS.sub(" ", text)
    return len(NEGATION.findall(text))


def missing_negations(source: str, result: str) -> list[str]:
    """Sätze des Originals mit Verneinung ("sind keine Gegensätze"), deren Gegenstück in der Ausgabe keine mehr hat."""
    outs = raw_sentences(result)
    lost = []
    for original in raw_sentences(source):
        if not _negations(original):
            continue
        near = [s for s in outs if overlap(original, s) >= 0.3]
        if any(_negations(s) for s in near):
            continue
        # Auch umgestellt zählt: "keine Gegensätze" steht noch, nur in einem anders gebauten Satz.
        phrases = [m.group(0) for m in re.finditer(r"\b(?:nicht|kein\w*|nie|weder)\s+(?:\w+\s+){0,1}\w+", original, re.I)]
        kept = any(_negations(s) and core_stems(" ".join(p.split()[1:])) and core_stems(" ".join(p.split()[1:])) <= core_stems(s)
                   for p in phrases for s in outs)
        if not kept:
            lost.append(original)
    return lost


VERDICT_STEMS = ("entsch", "wichti", "zentra", "bedeut", "essenz", "releva", "wesent", "notwen", "unerlä", "maßgeb",
                 "großer", "groß", "beacht", "unverz", "unabdi", "elemen", "grundl", "kritis", "heraus")


def filler_sentences(result: str) -> list[str]:
    """Kurze Sätze ohne eigene Aussage: nur eine Wertung ("Sicherheit ist entscheidend.") oder nichts, was nicht schon
    im Satz davor oder danach steht. Sätze mit Zahl oder Quelle zählen nie."""
    found = []
    for paragraph in paragraphs(result):
        parts = raw_sentences(paragraph)
        for i, sentence in enumerate(parts):
            if not 3 <= len(sentence.split()) <= 12 or not sentence.endswith(".") or facts(sentence) \
                    or CITATION.search(sentence):
                continue
            content = {w for w in core_stems(sentence) if not w.startswith(VERDICT_STEMS)}
            neighbours = [parts[j] for j in (i - 1, i + 1) if 0 <= j < len(parts)]
            if not neighbours:
                continue
            # Nur Wertung ("Das ist wichtig.") oder nichts, was nicht schon nebenan steht.
            if not content or any(content <= core_stems(n) for n in neighbours):
                found.append(sentence)
    return found


def echo_pairs(result: str) -> list[tuple[str, str]]:
    """Nachbarsätze mit demselben Muster: beide kurz und mit denselben Kernwörtern im Prädikat, etwa "verbraucht viel
    Energie." / "verbrauchen viel Strom." Klingt wie eine Aufzählung in Satzform."""
    pairs = []
    for paragraph in paragraphs(result):
        parts = raw_sentences(paragraph)
        for a, b in zip(parts, parts[1:]):
            if len(a.split()) <= 12 and len(b.split()) <= 12 and len(core_stems(a) & core_stems(b)) >= 2:
                pairs.append((a, b))
    return pairs


HEADING = re.compile(r"^(?:\d+(?:\.\d+)*\.?\s+\S.*|[^.!?;:]{1,80})$")


def is_heading(line: str) -> bool:
    """Kurze Zeile ohne Satzende, gern nummeriert ("2.1 Vorformen in Antike"): Überschrift, bleibt wie sie ist."""
    line = line.strip()
    return bool(line) and len(line.split()) <= 14 and not re.search(r"[.!?]\s*$", line) and bool(HEADING.match(line))


def split_blocks(text: str) -> tuple[list[str], list[str]]:
    """Teilt einen Text in Absätze und merkt sich, was dazwischen stand. Absätze trennt eine Leerzeile oder ein
    einfacher Zeilenumbruch nach einem Satzende oder einer Überschrift, wie beim Kopieren aus Word. Ein Umbruch
    mitten im Satz bleibt im Absatz. Liefert (Absätze, Trenner danach)."""
    parts = re.split(r"(\n\s*)", text.strip())
    blocks, seps, current = [], [], ""
    for i in range(0, len(parts), 2):
        line = parts[i]
        sep = parts[i + 1] if i + 1 < len(parts) else ""
        current = (current + " " + line.strip()).strip() if current else line.strip()
        nxt = parts[i + 2] if i + 2 < len(parts) else ""
        # Geht die nächste Zeile klein weiter, war es ein Umbruch mitten im Satz, keine Überschrift.
        starts_new = bool(re.match(r"\s*[A-ZÄÖÜ0-9„\"»(]", nxt))
        ends = re.search(r"[.!?:“”\")»«]\s*$", line) or (is_heading(line) and starts_new)
        if not sep or sep.count("\n") > 1 or ends or is_heading(nxt):
            if current:
                blocks.append(current)
                seps.append("\n\n" if sep.count("\n") > 1 else ("\n" if sep else ""))
            current = ""
    return blocks, seps


def paragraphs(text: str) -> list[str]:
    return split_blocks(text)[0]


def raw_paragraphs(text: str) -> list[str]:
    """Absätze nur an Leerzeilen, für die Stilvorlagen aus Büchern mit festen Zeilenumbrüchen."""
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]




def shrinkage(source: str, result: str) -> int:
    """Um wie viel Prozent die Ausgabe kürzer ist als das Original. Negativ heißt länger."""
    before = len(source.split())
    return round(100 * (before - len(result.split())) / before) if before else 0


def warnings(source: str, result: str, qualifiers: list[str] | None = None, strict: bool = False) -> str:
    parts = []
    hints = original_hints(source)
    if hints:
        parts.append("Im Original (bleibt so): " + "; ".join(hints))
    if strict and fragments(result):
        parts.append("Satzfragment: " + " / ".join(f'"{f}"' for f in fragments(result)))
    left = habits(result)
    if left:
        parts.append("Floskel: " + ", ".join(left))
    lost = missing_qualifiers(qualifiers or [], result)
    if lost:
        parts.append("Einschränkung fehlt: " + "; ".join(lost))
    weaker = [x for a, b in zip(paragraphs(source), paragraphs(result)) for x in missing_hedges(extract_hedges(a), b)]
    if weaker:
        parts.append("Abschwächung fehlt, Aussage jetzt absoluter: " + ", ".join(dict.fromkeys(weaker)))
    pairs = list(zip(paragraphs(source), paragraphs(result)))
    for sentence in [x for a, b in pairs for x in missing_attributions(a, b)]:
        parts.append(f'Autor nicht mehr genannt, jetzt eigene Behauptung: "{sentence[:60]}"')
    for sentence in [x for a, b in pairs for x in missing_subjunctive(a, b)]:
        parts.append(f'Konjunktiv der Wiedergabe fehlt: "{sentence[:60]}"')
    changed = [q for q in QUOTE.findall(source) if q not in result]
    if changed:
        parts.append("Zitat verändert oder fehlt: " + " / ".join(changed[:3]))
    for sentence in [x for a, b in pairs for x in missing_negations(a, b)]:
        parts.append(f'Verneinung fehlt: "{sentence[:60]}"')
    for sentence in [x for a, b in pairs for x in dropped_statements(a, b)]:
        parts.append(f'Aussage fehlt: "{sentence[:60]}"')
    for clause in [x for a, b in pairs for x in unsupported_clauses(a, b)]:
        parts.append(f'Teilsatz ohne Grundlage, prüfen: "{clause[:60]}"')
    for sentence in [x for a, b in pairs for x in added_negations(a, b)]:
        parts.append(f'Verneinung dazugekommen: "{sentence[:60]}"')
    if invented_citations(source, result):
        parts.append("Quelle erfunden: " + ", ".join(invented_citations(source, result)))
    for sentence in filler_sentences(result):
        parts.append(f'Füllsatz: "{sentence}"')
    for citation, _ in misplaced_citations(source, result):
        parts.append(f"Quelle verrutscht: {citation}")
    for sentence in raw_sentences(result):
        if doubled_clauses(sentence):
            parts.append(f'Aussage doppelt im Satz: "{sentence[:60]}"')
    if repeated_sentences(result):
        parts.append(f"{len(repeated_sentences(result))} Satz/Sätze wiederholt")
    added_links = new_connectors(source, result)
    if added_links:
        parts.append("neue Begründung oder Gegensatz, prüfen: " +
                     ", ".join(f"{word} ({extra}×)" for word, extra, _ in added_links))
    invented = unsupported_sentences(source, result)
    if invented:
        parts.append("ohne Grundlage im Original: " + " / ".join(f'"{s[:50]}"' for s in invented))
    gone = missing_facts(source, result)
    if gone:
        parts.append("fehlt in der Ausgabe: " + ", ".join(gone))
    added = added_facts(source, result)
    if added:
        parts.append("neu, steht nicht im Original: " + ", ".join(added))
    shorter = shrinkage(source, result)
    if shorter > 30:  # bis 30 % kürzer ist in Ordnung, wenn nur Floskeln wegfallen
        parts.append(f"Ausgabe ist {shorter} % kürzer als das Original")
    same = unchanged_sentences(source, result)
    if len(same) > 1:
        parts.append(f"{len(same)} Sätze kaum verändert")
    return ("Achtung: " + "  ·  ".join(parts) + ". Gegenlesen oder noch einmal umschreiben.") if parts else ""


def open_folder(path: str) -> None:
    os.makedirs(path, exist_ok=True)
    if os.name == "nt":
        os.startfile(path)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class App:
    def __init__(self, root: tk.Tk, url: str = OLLAMA_URL):
        self.root, self.url = root, url
        self.events: queue.Queue = queue.Queue()
        self.installed: list[str] = []
        self.memory: tuple[float | None, float | None] = (None, None)
        self.busy = False
        self.last_style = ""
        self.pulling: str | None = None
        self.cancel_pull = threading.Event()
        self.updating = False
        self.dialog: tk.Toplevel | None = None
        root.title("Humanizer")
        root.geometry("1200x760")
        root.minsize(800, 520)
        root.configure(bg=BG)

        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=PANEL, background=PANEL, foreground=FG, arrowcolor=FG,
                        bordercolor=PANEL, lightcolor=PANEL, darkcolor=PANEL, padding=6)
        style.map("TCombobox", fieldbackground=[("readonly", PANEL)], foreground=[("readonly", FG)],
                  selectbackground=[("readonly", PANEL)], selectforeground=[("readonly", FG)])
        root.option_add("*TCombobox*Listbox.background", PANEL)
        root.option_add("*TCombobox*Listbox.foreground", FG)
        root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)

        tk.Label(root, text="HUMANIZER", bg=BG, fg=FG, font=("Segoe UI", 26, "bold")).pack(anchor="w", padx=24, pady=(18, 8))

        bar = tk.Frame(root, bg=BG)
        bar.pack(fill="x", padx=24)
        tk.Label(bar, text="Modell", bg=BG, fg=MUTED, font=("Segoe UI", 10)).pack(side="left")
        self.model = ttk.Combobox(bar, state="readonly", width=22, font=("Segoe UI", 10))
        self.model.pack(side="left", padx=8)
        tk.Button(bar, text="Modelle …", command=self.open_models, bg=PANEL, fg=FG, activebackground="#333333",
                  activeforeground=FG, relief="flat", bd=0, highlightthickness=0, font=("Segoe UI", 10),
                  padx=12, pady=4, cursor="hand2").pack(side="left", padx=(0, 24))
        tk.Label(bar, text="Stil", bg=BG, fg=MUTED, font=("Segoe UI", 10)).pack(side="left")
        self.style = ttk.Combobox(bar, state="readonly", width=14, values=list(STYLES), font=("Segoe UI", 10))
        self.settings = load_settings()
        self.style.set(self.settings.get("stil") if self.settings.get("stil") in STYLES else list(STYLES)[0])
        self.style.pack(side="left", padx=8)

        # Zweite Zeile, damit nichts abgeschnitten wird, wenn Windows auf dem Laptop hochskaliert.
        bar = tk.Frame(root, bg=BG)
        bar.pack(fill="x", padx=24, pady=(8, 0))
        tk.Label(bar, text="Stilvorlage", bg=BG, fg=MUTED, font=("Segoe UI", 10)).pack(side="left")
        self.source = ttk.Combobox(bar, state="readonly", width=14, values=STYLE_SOURCES, font=("Segoe UI", 10))
        saved = self.settings.get("stilvorlage")
        self.source.set(saved if saved in STYLE_SOURCES else "Meine Texte" if load_texts(user_dir()) else "Mitgeliefert")
        self.source.pack(side="left", padx=8)
        tk.Button(bar, text="Meine Texte …", command=self.open_own_texts, bg=PANEL, fg=FG, activebackground="#333333",
                  activeforeground=FG, relief="flat", bd=0, highlightthickness=0, font=("Segoe UI", 10),
                  padx=12, pady=4, cursor="hand2").pack(side="left")
        tk.Button(bar, text="Text laden …", command=self.load_text, bg=PANEL, fg=FG, activebackground="#333333",
                  activeforeground=FG, relief="flat", bd=0, highlightthickness=0, font=("Segoe UI", 10),
                  padx=12, pady=4, cursor="hand2").pack(side="left", padx=(16, 0))
        tk.Button(bar, text="Quellen …", command=self.add_sources, bg=PANEL, fg=FG, activebackground="#333333",
                  activeforeground=FG, relief="flat", bd=0, highlightthickness=0, font=("Segoe UI", 10),
                  padx=12, pady=4, cursor="hand2").pack(side="left", padx=(8, 0))
        self.sources_label = tk.Label(bar, text="", bg=BG, fg=MUTED, font=("Segoe UI", 10))
        self.sources_label.pack(side="left", padx=8)
        self.sources_clear = tk.Button(bar, text="Quellen leeren", command=self.clear_sources, bg=PANEL, fg=FG,
                                       activebackground="#333333", activeforeground=FG, relief="flat", bd=0,
                                       highlightthickness=0, font=("Segoe UI", 10), padx=12, pady=4, cursor="hand2")
        self.source_paths = [p for p in self.settings.get("quellen", []) if os.path.exists(p)]
        self._show_sources()

        bottom = tk.Frame(root, bg=BG)
        bottom.pack(side="bottom", fill="x", padx=24, pady=16)
        self.go = tk.Button(bottom, text="Umschreiben", command=self.run, state="disabled", bg=ACCENT, fg="white",
                            activebackground="#d93a3a", activeforeground="white", disabledforeground="#f0b0b0",
                            relief="flat", bd=0, highlightthickness=0, font=("Segoe UI", 11, "bold"), padx=22, pady=8, cursor="hand2")
        self.go.pack(side="left")
        self.copy = tk.Button(bottom, text="Kopieren", command=self.copy_output, bg=PANEL, fg=FG,
                              activebackground="#333333", activeforeground=FG, relief="flat", bd=0, highlightthickness=0,
                              font=("Segoe UI", 11), padx=18, pady=8, cursor="hand2")
        self.copy.pack(side="left", padx=10)
        self.clear = tk.Button(bottom, text="Cache leeren", command=self.clear_cache, bg=PANEL, fg=FG,
                               activebackground="#333333", activeforeground=FG, relief="flat", bd=0, highlightthickness=0,
                               font=("Segoe UI", 11), padx=18, pady=8, cursor="hand2")
        self.clear.pack(side="left")
        # Unten statt oben: Oben wird es bei Windows-Skalierung auf Laptops zu eng.
        self.update_button = tk.Button(bottom, text="Update", command=self.check_update, bg=PANEL, fg=FG,
                                       activebackground="#333333", activeforeground=FG, disabledforeground=MUTED,
                                       relief="flat", bd=0, highlightthickness=0, font=("Segoe UI", 11),
                                       padx=18, pady=8, cursor="hand2")
        self.update_button.pack(side="right")
        self.status = tk.Label(bottom, text="Suche Ollama …", bg=BG, fg=MUTED, font=("Segoe UI", 10), anchor="w")
        self.status.pack(side="left", fill="x", expand=True, padx=8)

        self.warning = tk.Label(root, text="", bg=BG, fg=ACCENT, font=("Segoe UI", 10), anchor="w", justify="left",
                                wraplength=1100)
        root.bind("<Configure>", lambda e: e.widget is root and self.warning.config(wraplength=max(400, e.width - 60)))
        self.warning.pack(side="bottom", fill="x", padx=24)

        panes = tk.Frame(root, bg=BG)
        panes.pack(fill="both", expand=True, padx=24, pady=(14, 0))
        panes.columnconfigure(0, weight=1, uniform="p")
        panes.columnconfigure(1, weight=1, uniform="p")
        panes.rowconfigure(1, weight=1)
        self.input = self._pane(panes, "Eingabe  ·  rot = gestrichen", 0)
        self.output = self._pane(panes, "Ausgabe  ·  grün = neu formuliert", 1)
        self.input.tag_config("weg", background=REMOVED)
        self.output.tag_config("neu", background=ADDED)
        # Sobald die Eingabe bearbeitet wird, stimmen die Markierungen nicht mehr.
        self.input.bind("<Key>", lambda e: self.input.tag_remove("weg", "1.0", "end"))

        for box in (self.model, self.style, self.source):
            box.bind("<<ComboboxSelected>>", lambda e: self._remember())
        root.bind("<Control-Return>", lambda e: self.run())
        threading.Thread(target=self._load_models, daemon=True).start()
        root.after(100, self._poll)

    def _pane(self, parent: tk.Frame, title: str, column: int) -> scrolledtext.ScrolledText:
        pad = (0, 8) if column == 0 else (8, 0)
        tk.Label(parent, text=title, bg=BG, fg=MUTED, font=("Segoe UI", 10)).grid(row=0, column=column, sticky="w", padx=pad)
        box = scrolledtext.ScrolledText(parent, wrap="word", bg=PANEL, fg=FG, insertbackground=FG, relief="flat",
                                        font=("Segoe UI", 11), padx=12, pady=10, undo=True, bd=0, highlightthickness=0)
        box.grid(row=1, column=column, sticky="nsew", padx=pad, pady=(4, 0))
        return box

    # Hintergrund-Threads fassen die Oberfläche nie direkt an, sie legen Ereignisse in die Queue.
    def _poll(self) -> None:
        while not self.events.empty():
            kind, value = self.events.get()
            getattr(self, "_on_" + kind)(value)
        self.root.after(100, self._poll)

    def _load_models(self) -> None:
        self.events.put(("memory", system_memory()))
        try:
            self.events.put(("models", ensure_ollama(self.url)))
        except OllamaError as e:
            self.events.put(("error", str(e)))

    def _on_memory(self, memory: tuple[float | None, float | None]) -> None:
        self.memory = memory
        self._refresh_dialog()

    def _set_models(self, models: list[str]) -> None:
        self.installed = models
        self.model.config(values=models)
        if self.model.get() not in models:
            saved = self.settings.get("modell")
            self.model.set(saved if saved in models else PREFERRED_MODEL if PREFERRED_MODEL in models
                           else models[0] if models else "")
        self._sync_go()
        self._refresh_dialog()

    def _remember(self) -> None:
        self.settings.update(modell=self.model.get(), stil=self.style.get(), stilvorlage=self.source.get())
        save_settings(self.settings)

    def _sync_go(self) -> None:
        self.go.config(state="normal" if self.installed and not self.busy else "disabled")

    def _on_models(self, models: list[str]) -> None:
        self._set_models(models)
        if models:
            self.status.config(text="Bereit. Text einfügen und Umschreiben klicken (oder Strg+Enter).", fg=MUTED)
        else:
            self.status.config(text='Kein Modell installiert. Klick oben auf "Modelle …" und lad eins herunter.', fg=ACCENT)

    def _on_error(self, message: str) -> None:
        self.status.config(text=message, fg=ACCENT)
        self.clear.config(state="normal")
        self.busy = False
        self._sync_go()

    def _machine_text(self) -> str:
        ram, vram = self.memory
        if ram is None:
            return "Dein Rechner: Speicher konnte nicht ermittelt werden."
        gpu = f"{round(vram)} GB Grafikspeicher" if vram is not None else "keine NVIDIA-Grafikkarte erkannt"
        return f"Dein Rechner: {round(ram)} GB RAM, {gpu}"

    def open_models(self) -> None:
        if self.dialog and self.dialog.winfo_exists():
            self.dialog.lift()
            return
        d = self.dialog = tk.Toplevel(self.root)
        d.title("Modelle")
        d.configure(bg=BG)
        d.transient(self.root)
        d.resizable(False, False)
        small, bold = ("Segoe UI", 10), ("Segoe UI", 10, "bold")
        tk.Label(d, text="MODELLE", bg=BG, fg=FG, font=("Segoe UI", 20, "bold")).grid(
            row=0, column=0, columnspan=5, sticky="w", padx=24, pady=(18, 0))
        self.machine = tk.Label(d, bg=BG, fg=MUTED, font=small)
        self.machine.grid(row=1, column=0, columnspan=5, sticky="w", padx=24, pady=(0, 12))
        for col, head in enumerate(["Modell", "Download", "Braucht", "Beschreibung"]):
            tk.Label(d, text=head, bg=BG, fg=MUTED, font=small).grid(row=2, column=col, sticky="w", padx=(24 if col == 0 else 10, 10))
        self.rows: dict[str, tuple[tk.Button, tk.Label]] = {}
        for i, (name, size, need_vram, need_ram, note) in enumerate(CATALOG):
            row = 3 + 2 * i
            tk.Label(d, text=name, bg=BG, fg=FG, font=bold).grid(row=row, column=0, sticky="w", padx=(24, 10), pady=(10, 0))
            tk.Label(d, text=f"{size:g} GB".replace(".", ","), bg=BG, fg=FG, font=small).grid(row=row, column=1, sticky="w", padx=10, pady=(10, 0))
            tk.Label(d, text=f"{need_vram} GB Grafikspeicher\noder {need_ram} GB RAM (langsamer)", bg=BG, fg=FG, font=small,
                     justify="left").grid(row=row, column=2, rowspan=2, sticky="nw", padx=10, pady=(10, 0))
            tk.Label(d, text=note, bg=BG, fg=FG, font=small).grid(row=row, column=3, sticky="w", padx=10, pady=(10, 0))
            fit = tk.Label(d, bg=BG, font=small)
            fit.grid(row=row + 1, column=3, sticky="w", padx=10)
            button = tk.Button(d, command=lambda n=name: self.row_action(n), bg=PANEL, fg=FG, width=14,
                               activebackground="#333333", activeforeground=FG, disabledforeground=MUTED,
                               relief="flat", bd=0, highlightthickness=0, font=small, pady=5, cursor="hand2")
            button.grid(row=row, column=4, rowspan=2, padx=(10, 24), pady=(10, 0))
            self.rows[name] = (button, fit)
        last = 3 + 2 * len(CATALOG)
        other = tk.Frame(d, bg=BG)
        other.grid(row=last, column=0, columnspan=5, sticky="we", padx=24, pady=(22, 0))
        tk.Label(other, text="Anderes Modell", bg=BG, fg=MUTED, font=small).pack(side="left")
        self.custom = tk.Entry(other, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", bd=0, highlightthickness=0, font=small, width=30)
        self.custom.pack(side="left", padx=8, ipady=4)
        self.custom_button = tk.Button(other, text="Herunterladen", command=self.custom_action,
                                       bg=PANEL, fg=FG, activebackground="#333333", activeforeground=FG,
                                       disabledforeground=MUTED, relief="flat", bd=0, highlightthickness=0,
                                       font=small, padx=12, pady=4, cursor="hand2")
        self.custom_button.pack(side="left")
        tk.Label(other, text="Name von ollama.com/library, z. B. llama3.1:8b", bg=BG, fg=MUTED, font=small).pack(side="left", padx=10)
        self.pull_status = tk.Label(d, text="", bg=BG, fg=MUTED, font=small, anchor="w", justify="left")
        self.extra = tk.Frame(d, bg=BG)
        self.extra.grid(row=last + 1, column=0, columnspan=5, sticky="we", padx=24)
        self.pull_status.grid(row=last + 2, column=0, columnspan=5, sticky="we", padx=24, pady=(12, 0))
        tk.Label(d, text="Größen und Anforderungen sind Richtwerte. Ohne passende Grafikkarte läuft ein Modell über den RAM, "
                         "nur deutlich langsamer.", bg=BG, fg=MUTED, font=("Segoe UI", 9)).grid(
            row=last + 3, column=0, columnspan=5, sticky="w", padx=24, pady=(6, 18))
        self._refresh_dialog()

    def _refresh_dialog(self) -> None:
        if not (self.dialog and self.dialog.winfo_exists()):
            return
        self.machine.config(text=self._machine_text())
        colors = {"läuft flüssig": GOOD, "läuft, aber langsamer": MUTED, "zu groß für diesen Rechner": ACCENT, "": MUTED}
        for name, _, need_vram, need_ram, _ in CATALOG:
            button, fit = self.rows[name]
            text = verdict(need_vram, need_ram, *self.memory)
            parts = (["Installiert"] if name in self.installed else []) + (["Auf deinem Rechner: " + text] if text else [])
            fit.config(text="  ·  ".join(parts), fg=colors[text])
            if self.pulling == name:
                button.config(text="Abbrechen", state="normal")
            elif name in self.installed:
                button.config(text="Löschen", state="disabled" if self.pulling else "normal")
            else:
                button.config(text="Herunterladen", state="disabled" if self.pulling else "normal")
        custom_pull = bool(self.pulling) and self.pulling not in self.rows
        self.custom_button.config(text="Abbrechen" if custom_pull else "Herunterladen",
                                  state="normal" if custom_pull or not self.pulling else "disabled")
        for child in self.extra.winfo_children():
            child.destroy()
        others = [m for m in self.installed if m not in self.rows]
        if others:
            tk.Label(self.extra, text="Weitere installierte Modelle", bg=BG, fg=MUTED,
                     font=("Segoe UI", 10)).grid(row=0, column=0, columnspan=2, sticky="w", pady=(18, 4))
        for i, name in enumerate(others, start=1):
            tk.Label(self.extra, text=name, bg=BG, fg=FG, font=("Segoe UI", 10, "bold")).grid(row=i, column=0, sticky="w", pady=3)
            tk.Button(self.extra, text="Löschen", command=lambda n=name: self.delete(n), bg=PANEL, fg=FG,
                      activebackground="#333333", activeforeground=FG, disabledforeground=MUTED, relief="flat", bd=0,
                      highlightthickness=0, font=("Segoe UI", 10), padx=12, pady=3, cursor="hand2",
                      state="disabled" if self.pulling else "normal").grid(row=i, column=1, padx=16, pady=3)

    def row_action(self, name: str) -> None:
        if self.pulling == name:
            self.cancel_pull.set()
            self._pull_message(f"{name}: Download wird abgebrochen …")
        elif name in self.installed:
            self.delete(name)
        else:
            self.start_pull(name)

    def custom_action(self) -> None:
        if self.pulling:
            self.cancel_pull.set()
            self._pull_message(f"{self.pulling}: Download wird abgebrochen …")
        else:
            self.start_pull(self.custom.get().strip())

    def delete(self, name: str) -> None:
        if self.pulling:
            return
        if self.busy:
            self._pull_message("Gerade läuft ein Umschreiben. Danach noch einmal klicken.")
            return
        size = next((" Das gibt rund " + f"{row[1]:g}".replace(".", ",") + " GB frei." for row in CATALOG if row[0] == name), "")
        parent = self.dialog if self.dialog and self.dialog.winfo_exists() else self.root
        if not messagebox.askyesno("Modell löschen", f"{name} wirklich löschen?{size}", parent=parent):
            return

        def work() -> None:
            try:
                delete_model(name, self.url)
                self.events.put(("deleted", (name, list_models(self.url))))
            except OllamaError as e:
                self.events.put(("pull_error", str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _on_deleted(self, value: tuple[str, list[str]]) -> None:
        name, models = value
        self._set_models(models)
        self._pull_message(f"{name} ist gelöscht.")
        if not models:
            self.status.config(text='Kein Modell installiert. Klick oben auf "Modelle …" und lad eins herunter.', fg=ACCENT)

    def _pull_message(self, text: str, color: str = MUTED) -> None:
        if self.dialog and self.dialog.winfo_exists():
            self.pull_status.config(text=text, fg=color)
        else:
            self.status.config(text=text, fg=color)

    def start_pull(self, name: str) -> None:
        if not name or self.pulling:
            return
        if name in self.installed:
            self._pull_message(f"{name} ist schon installiert.")
            return
        self.pulling = name
        cancel = self.cancel_pull = threading.Event()
        self._refresh_dialog()
        self._pull_message(f"{name}: Download startet …")

        def work() -> None:
            last = [-1]

            def progress(percent: int, status: str) -> None:
                if percent != last[0]:
                    last[0] = percent
                    self.events.put(("pull_progress", (name, percent)))

            try:
                pull_model(name, self.url, progress, cancel)
                self.events.put(("pulled", (name, list_models(self.url))))
            except PullCancelled as e:
                self.events.put(("pull_cancelled", str(e)))
            except OllamaError as e:
                self.events.put(("pull_error", str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _on_pull_progress(self, value: tuple[str, int]) -> None:
        name, percent = value
        self._pull_message(f"{name}: {percent} % heruntergeladen. Du kannst das Fenster offen lassen und weiterarbeiten.")

    def _on_pulled(self, value: tuple[str, list[str]]) -> None:
        name, models = value
        self.pulling = None
        self._set_models(models)
        self._pull_message(f"{name} ist installiert und steht jetzt in der Modell-Auswahl.", GOOD)

    def _on_pull_error(self, message: str) -> None:
        self.pulling = None
        self._refresh_dialog()
        self._pull_message(message, ACCENT)

    def _on_pull_cancelled(self, message: str) -> None:
        self.pulling = None
        self._refresh_dialog()
        self._pull_message(message)

    def check_update(self) -> None:
        if self.updating:
            return
        self.updating = True
        self.update_button.config(state="disabled")
        self.status.config(text="Suche nach einer neueren Version …", fg=MUTED)

        def work() -> None:
            try:
                self.events.put(("update_checked", latest_build()))
            except UpdateError as e:
                self.events.put(("update_error", str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _update_done(self, text: str, color: str = MUTED) -> None:
        self.updating = False
        self.update_button.config(state="normal")
        self.status.config(text=text, fg=color)

    def _on_update_error(self, message: str) -> None:
        self._update_done(message, ACCENT)

    def _on_update_checked(self, latest: str) -> None:
        if latest == BUILD:
            self._update_done("Du hast die neueste Version.")
        elif not getattr(sys, "frozen", False):
            self._update_done(f"Diese Kopie läuft aus dem Quelltext und aktualisiert sich nicht selbst. "
                              f"Die aktuelle Version: github.com/{REPO}")
        elif not messagebox.askyesno("Update", "Es gibt eine neuere Version. Jetzt herunterladen und neu starten?",
                                     parent=self.root):
            self._update_done("Update abgebrochen. Es gibt eine neuere Version.")
        else:
            target = sys.executable + ".new"

            def work() -> None:
                last = [-1]

                def progress(percent: int) -> None:
                    if percent != last[0]:
                        last[0] = percent
                        self.events.put(("update_progress", percent))

                try:
                    download_file(EXE_URL, target, progress)
                    self.events.put(("update_ready", target))
                except UpdateError as e:
                    self.events.put(("update_error", str(e)))

            threading.Thread(target=work, daemon=True).start()

    def _on_update_progress(self, percent: int) -> None:
        self.status.config(text=f"Lade Update … {percent} %", fg=MUTED)

    def _on_update_ready(self, new: str) -> None:
        try:
            swap_executable(sys.executable, new)
            # Ohne das erbt die neue .exe das Arbeitsverzeichnis der alten, das beim Beenden verschwindet.
            env = {k: v for k, v in os.environ.items() if k != "_MEIPASS2"}
            env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
            subprocess.Popen([sys.executable], env=env)
        except OSError as e:
            self._update_done(f"Das Update ließ sich nicht einspielen ({e}). Die App bleibt, wie sie ist.", ACCENT)
            return
        self.root.destroy()

    def load_text(self) -> None:
        path = filedialog.askopenfilename(title="Text laden", filetypes=[
            ("Texte", "*.docx *.pdf *.txt"), ("Word", "*.docx"), ("PDF", "*.pdf"), ("Text", "*.txt")])
        if not path:
            return
        try:
            text = read_document(path)
        except DocumentError as e:
            self.status.config(text=str(e), fg=ACCENT)
            return
        self.input.delete("1.0", "end")
        self.input.insert("1.0", text)
        self.status.config(text=f"Geladen: {os.path.basename(path)} ({len(text.split())} Wörter)", fg=MUTED)

    def add_sources(self) -> None:
        paths = filedialog.askopenfilenames(title="Quellen wählen (Literaturverzeichnis, Quellen-PDFs)", filetypes=[
            ("Quellen", "*.docx *.pdf *.txt"), ("Word", "*.docx"), ("PDF", "*.pdf"), ("Text", "*.txt")])
        problems = []
        for path in paths:
            try:
                read_document(path)
            except DocumentError as e:
                problems.append(str(e))
                continue
            if path not in self.source_paths:
                self.source_paths.append(path)
        self.settings["quellen"] = self.source_paths
        save_settings(self.settings)
        self._show_sources()
        if problems:
            self.status.config(text="  ".join(problems), fg=ACCENT)

    def clear_sources(self) -> None:
        self.source_paths = []
        self.settings["quellen"] = []
        save_settings(self.settings)
        self._show_sources()

    def _show_sources(self) -> None:
        n = len(self.source_paths)
        self.sources_label.config(text=f"{n} Quelle{'n' if n != 1 else ''} geladen" if n else "keine Quellen")
        if n:
            self.sources_clear.pack(side="left")
        else:
            self.sources_clear.pack_forget()

    def _source_texts(self) -> list[str]:
        texts = []
        for path in self.source_paths:
            try:
                texts.append(read_document(path))
            except (DocumentError, OSError):
                continue
        return texts

    def open_own_texts(self) -> None:
        folder = user_dir()
        try:
            open_folder(folder)
        except OSError as e:
            self.status.config(text=f"Der Ordner ließ sich nicht öffnen: {e}", fg=ACCENT)
            return
        self.status.config(fg=MUTED, text=(
            f"Leg dort .txt-Dateien mit Texten ab, die du selbst geschrieben hast. Ordner: {folder}"))

    def _on_result(self, value: tuple[str, str, float, str, int, list[str]]) -> None:
        source, result, seconds, note, passes, qualifiers = value
        self.output.delete("1.0", "end")
        self.output.insert("1.0", result)
        self.busy = False
        self._sync_go()
        gone, added = diff_spans(source, result)
        for start, end in added:
            self.output.tag_add("neu", f"1.0+{start}c", f"1.0+{end}c")
        raw = self.input.get("1.0", "end-1c")
        if raw.strip() == source:
            lead = len(raw) - len(raw.lstrip())
            for start, end in gone:
                self.input.tag_add("weg", f"1.0+{lead + start}c", f"1.0+{lead + end}c")
        self.status.config(fg=MUTED, text=(
            f"Fertig in {seconds:.0f} s{f' ({passes - 1}× nachgebessert)' if passes > 1 else ''}  ·  "
            f"{changed_share(result, added)} % neu formuliert  ·  "
            f"Satzlängen-Streuung {burstiness(source)} → {burstiness(result)}  ·  "
            f"KI-Floskeln {tell_count(source)} → {tell_count(result)}"))
        strict = self.last_style == "Akademisch"
        self.warning.config(text="  ".join(filter(None, [warnings(source, result, qualifiers, strict),
                                                         source_hints(source, self._source_texts()), note])))

    def _on_cleared(self, count: int) -> None:
        self.clear.config(state="normal")
        self.status.config(fg=MUTED, text=(
            "Es war kein Modell geladen, der Speicher ist schon frei." if count == 0 else
            f"Speicher freigegeben: {count} Modell{'e' if count > 1 else ''} entladen. "
            "Das nächste Umschreiben dauert dadurch etwas länger."))

    def clear_cache(self) -> None:
        """Entlädt die Modelle aus dem Speicher. Ollama hält sie sonst noch Minuten nach dem letzten Text."""
        if self.busy:
            self.status.config(text="Gerade läuft ein Umschreiben. Danach noch einmal klicken.", fg=MUTED)
            return
        self.clear.config(state="disabled")

        def work() -> None:
            try:
                self.events.put(("cleared", unload_models(self.url)))
            except OllamaError as e:
                self.events.put(("error", str(e)))

        threading.Thread(target=work, daemon=True).start()

    def run(self) -> None:
        text = self.input.get("1.0", "end").strip()
        if not text or str(self.go["state"]) == "disabled":
            return
        self.busy = True
        self._sync_go()
        self.input.tag_remove("weg", "1.0", "end")
        self.warning.config(text="")
        self.status.config(text="Schreibe um … das kann bei langen Texten ein, zwei Minuten dauern.", fg=MUTED)
        model, style, source = self.model.get(), self.style.get(), self.source.get()
        self.last_style = style

        def work() -> None:
            start = time.time()
            pool, note = plan_pool(source, style, load_texts(user_dir()) if source == "Meine Texte" else [])
            try:
                result, passes, qualifiers = humanize_checked(
                    text, style, model, self.url, pool,
                    progress=lambda done, total: self.events.put(("progress", (done, total))))
                self.events.put(("result", (text, result, time.time() - start, note, passes, qualifiers)))
            except OllamaError as e:
                self.events.put(("error", str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _on_progress(self, value: tuple[int, int]) -> None:
        done, total = value
        self.status.config(text=f"Schreibe um … Absatz {done} von {total}", fg=MUTED)

    def copy_output(self) -> None:
        text = self.output.get("1.0", "end").strip()
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            # Nur kurz anzeigen, damit Zeit und Werte des letzten Durchgangs danach wieder lesbar sind.
            before, color = self.status["text"], self.status["fg"]
            self.status.config(text="Ausgabe kopiert.", fg=MUTED)
            self.root.after(1500, lambda: self.status["text"] == "Ausgabe kopiert." and
                            self.status.config(text=before, fg=color))


# --- Texte und Quellen aus Dateien ------------------------------------------------------------------------------

class DocumentError(Exception):
    pass


WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def read_docx(path: str) -> str:
    """Text einer Word-Datei (.docx), Absatz für Absatz. Braucht kein Zusatzpaket: .docx ist ein ZIP mit XML."""
    try:
        with zipfile.ZipFile(path) as z:
            root = ElementTree.fromstring(z.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as e:
        raise DocumentError(f"{os.path.basename(path)} ist keine lesbare Word-Datei ({e}).") from e
    lines = []
    for para in root.iter(WORD_NS + "p"):
        text = ""
        for node in para.iter():
            if node.tag == WORD_NS + "t":
                text += node.text or ""
            elif node.tag == WORD_NS + "tab":
                text += "\t"
            elif node.tag in (WORD_NS + "br", WORD_NS + "cr"):
                text += "\n"
        lines.append(text)
    return "\n".join(lines).strip()


def read_pdf(path: str) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise DocumentError("PDFs lesen braucht das Paket pypdf (pip install pypdf). In der Humanizer.exe ist es dabei.") from e
    try:
        reader = PdfReader(path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as e:  # pypdf wirft je nach Fehler verschiedene Ausnahmen
        raise DocumentError(f"{os.path.basename(path)} ließ sich nicht lesen ({e}).") from e
    if not text.strip():
        raise DocumentError(f"In {os.path.basename(path)} ist kein Text gefunden worden, vermutlich ein Scan.")
    return text


def read_document(path: str) -> str:
    """Text aus .txt, .docx oder .pdf."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        return read_docx(path)
    if ext == ".pdf":
        return read_pdf(path)
    if ext in (".txt", ".md", ""):
        for encoding in ("utf-8-sig", "cp1252"):
            try:
                return open(path, encoding=encoding).read()
            except UnicodeDecodeError:
                continue
    raise DocumentError(f"{os.path.basename(path)}: Dieses Format kann die App nicht lesen (nur .txt, .docx, .pdf).")


def _searchable(text: str) -> str:
    """Für die Zitatsuche: Groß/Klein, Anführungszeichen, Silbentrennung am Zeilenende und Leerraum egal."""
    text = text.replace("\u00ad", "")
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
    text = re.sub(r"[„“”\"»«‚‘’']", "", text)
    text = re.sub(r"[‐‑‒–—]", "-", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def quotes_not_in_sources(text: str, sources: list[str]) -> list[str]:
    """Direkte Zitate des Texts, die in keiner geladenen Quelle vorkommen."""
    haystack = " ".join(_searchable(s) for s in sources)
    missing = []
    for quote in dict.fromkeys(QUOTE.findall(text)):
        needle = _searchable(quote).rstrip(".,;:")
        if len(needle.split()) >= 2 and needle not in haystack:
            missing.append(quote)
    return missing


def citations_not_in_sources(text: str, sources: list[str]) -> list[str]:
    """Quellenangaben, deren Autor oder Jahr in keiner geladenen Quelle (Literaturverzeichnis oder Quelle selbst)
    vorkommt."""
    haystack = " ".join(sources)
    missing = []
    for citation in dict.fromkeys(CITATION.findall(text)):
        if TOKEN.fullmatch(citation):
            continue
        for part in citation.strip("()").split(";"):
            authors = [a for a in citation_parts("(" + part + ")")[0] if a not in ("S", "Vgl", "Editors")]
            years = re.findall(r"\b1[4-9]\d\d\b|\b20\d\d\b", part)
            if any(not re.search(r"\b" + re.escape(a) + r"\b", haystack) for a in authors) or \
                    any(y not in haystack for y in years):
                missing.append(part.strip())
    return list(dict.fromkeys(missing))


def source_hints(text: str, sources: list[str]) -> str:
    if not sources:
        return ""
    hints = []
    quotes = quotes_not_in_sources(text, sources)
    if quotes:
        hints.append("Zitat nicht in den Quellen gefunden: " + " / ".join(q[:70] for q in quotes))
    citations = citations_not_in_sources(text, sources)
    if citations:
        hints.append("Quelle nicht in den geladenen Dateien: " + "; ".join(citations))
    return ("Quellen-Check: " + "  ·  ".join(hints)) if hints else "Quellen-Check: alle Zitate und Angaben gefunden."


def selftest(target: str) -> None:
    """Prüfung für den Build: schreibt, welche Version das ist und ob die Beispieltexte in der .exe stecken."""
    with open(target, "w", encoding="utf-8") as out:
        try:
            import pypdf  # noqa: F401  (muss im Build stecken, sonst kann die App keine PDFs lesen)
            has_pdf = True
        except ImportError:
            has_pdf = False
        json.dump({"build": BUILD, "pdf": has_pdf,
                   **{g: len(bundled_texts(g)) for g in ("sachlich", "bericht", "locker")}}, out)


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--selftest":
        selftest(sys.argv[2])
        return
    try:  # sonst ist die Schrift auf Windows-Laptops mit Skalierung unscharf
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    if getattr(sys, "frozen", False):
        cleanup_old(sys.executable)
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()

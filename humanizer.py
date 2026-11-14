"""Humanizer als Desktop-App: schreibt KI-Texte lokal über Ollama so um, dass sie menschlich klingen.
Braucht nur Python und Ollama, keine weiteren Pakete. Start: pythonw humanizer.py
"""
import difflib
import json
import os
import queue
import re
import subprocess
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
from tkinter import scrolledtext, ttk

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
PREFERRED_MODEL = "gemma3:12b"
# Ollamas Standard-Kontext ist klein und schneidet lange Texte stillschweigend ab.
OLLAMA_CONTEXT = 8192

SYSTEM = """Du schreibst deutsche Texte so um, dass sie klingen, als hätte sie ein Mensch geschrieben. Regeln:
- Die Ausgabe ist immer Deutsch. Inhalt, Fakten, Zahlen und Zitate bleiben exakt erhalten. Erfinde nichts dazu.
- Übernimm die Schreibweise der Vorlage (ß oder ss, österreichische und Schweizer Wörter bleiben, wie sie sind).
- Mische die Satzlängen stark: Sätze mit drei Wörtern neben langen, verschachtelten.
- Absätze sind ungleich lang.
- Streiche KI-Floskeln: "darüber hinaus", "des Weiteren", "zusammenfassend lässt sich sagen",
  "es ist wichtig zu beachten", "spielt eine entscheidende Rolle", "in der heutigen Zeit",
  "nicht nur ... sondern auch", "eintauchen", "nahtlos", "maßgeblich", "vielfältig", "ganzheitlich".
- Löse Nominalstil auf: Verben statt Substantivierungen, keine Substantivketten, wenig Passiv.
- Keine Dreier-Aufzählungen aus Gewohnheit, keine Gedankenstrich-Ketten, kein Fazit-Satz am Ende jedes Absatzes.
- Keine aus dem Englischen übersetzte Satzstellung. Schreib, wie man auf Deutsch wirklich formuliert.
- Nimm konkrete Wörter statt abstrakter. Sätze dürfen mit "Und" oder "Aber" anfangen.
- Wo das Register es erlaubt: Modalpartikeln (halt, eben, ja, schon, eigentlich), sparsam.
- Gib nur den umgeschriebenen Text aus, sonst nichts."""

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
    "ermöglicht es", "stellt sicher",
]

MONTHS = "Januar|Jänner|Februar|Feber|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember"
ABBREVIATIONS = re.compile(
    r"\b(z\.\s?B|d\.\s?h|u\.\s?a|o\.\s?ä|u\.\s?U|bzw|bspw|usw|ca|Nr|vgl|etc|evtl|ggf|inkl|exkl|sog|Dr|Prof|Abb|Mio|Mrd|St)\."
)
NUMBER_DOT = re.compile(rf"(\d)\.(?=\d|\s+[a-zäöü]|\s+(?:{MONTHS})\b)")

BG, PANEL, FG, MUTED, ACCENT = "#141414", "#232323", "#f2f2f2", "#9a9a9a", "#ff4b4b"
ADDED, REMOVED = "#1f4d2e", "#5a2326"


def sentences(text: str) -> list[str]:
    """Zerlegt in Sätze, ohne an Abkürzungen (z. B., bzw.) oder Datumsangaben (28.09.) zu trennen."""
    masked = ABBREVIATIONS.sub(lambda m: m.group(1).replace(".", ""), text)
    masked = NUMBER_DOT.sub(r"\1", masked)
    return [s for s in re.split(r"(?<=[.!?…])\s+", masked.strip()) if s]


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


def _request(url: str, payload: dict | None = None, timeout: int = 600) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
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
        raise OllamaUnreachable("Ollama ist nicht installiert. Im Terminal: winget install Ollama.Ollama") from e
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


def humanize(text: str, style: str, model: str, url: str = OLLAMA_URL) -> str:
    reply = _request(url + "/api/chat", {
        "model": model,
        "stream": False,
        "options": {"num_ctx": OLLAMA_CONTEXT},
        "messages": [{"role": "system", "content": SYSTEM + "\nStil: " + STYLES[style]},
                     {"role": "user", "content": "Schreib um:\n\n" + text}],
    })
    return reply["message"]["content"].strip()


class App:
    def __init__(self, root: tk.Tk, url: str = OLLAMA_URL):
        self.root, self.url = root, url
        self.events: queue.Queue = queue.Queue()
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
        self.model = ttk.Combobox(bar, state="readonly", width=28, font=("Segoe UI", 10))
        self.model.pack(side="left", padx=(8, 24))
        tk.Label(bar, text="Stil", bg=BG, fg=MUTED, font=("Segoe UI", 10)).pack(side="left")
        self.style = ttk.Combobox(bar, state="readonly", width=14, values=list(STYLES), font=("Segoe UI", 10))
        self.style.current(0)
        self.style.pack(side="left", padx=8)

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
        self.status = tk.Label(bottom, text="Suche Ollama …", bg=BG, fg=MUTED, font=("Segoe UI", 10), anchor="w")
        self.status.pack(side="left", fill="x", expand=True, padx=8)

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
        try:
            self.events.put(("models", ensure_ollama(self.url)))
        except OllamaError as e:
            self.events.put(("error", str(e)))

    def _on_models(self, models: list[str]) -> None:
        if not models:
            self.status.config(text=f"Kein Modell installiert. Im Terminal: ollama pull {PREFERRED_MODEL}", fg=ACCENT)
            return
        self.model.config(values=models)
        self.model.set(PREFERRED_MODEL if PREFERRED_MODEL in models else models[0])
        self.go.config(state="normal")
        self.status.config(text="Bereit. Text einfügen und Umschreiben klicken (oder Strg+Enter).", fg=MUTED)

    def _on_error(self, message: str) -> None:
        self.status.config(text=message, fg=ACCENT)
        self.clear.config(state="normal")
        if self.model.get():
            self.go.config(state="normal")

    def _on_result(self, value: tuple[str, str, float]) -> None:
        source, result, seconds = value
        self.output.delete("1.0", "end")
        self.output.insert("1.0", result)
        self.go.config(state="normal")
        gone, added = diff_spans(source, result)
        for start, end in added:
            self.output.tag_add("neu", f"1.0+{start}c", f"1.0+{end}c")
        raw = self.input.get("1.0", "end-1c")
        if raw.strip() == source:
            lead = len(raw) - len(raw.lstrip())
            for start, end in gone:
                self.input.tag_add("weg", f"1.0+{lead + start}c", f"1.0+{lead + end}c")
        self.status.config(fg=MUTED, text=(
            f"Fertig in {seconds:.0f} s  ·  {changed_share(result, added)} % neu formuliert  ·  "
            f"Satzlängen-Streuung {burstiness(source)} → {burstiness(result)}  ·  "
            f"KI-Floskeln {tell_count(source)} → {tell_count(result)}"))

    def _on_cleared(self, count: int) -> None:
        self.clear.config(state="normal")
        self.status.config(fg=MUTED, text=(
            "Es war kein Modell geladen, der Speicher ist schon frei." if count == 0 else
            f"Speicher freigegeben: {count} Modell{'e' if count > 1 else ''} entladen. "
            "Das nächste Umschreiben dauert dadurch etwas länger."))

    def clear_cache(self) -> None:
        """Entlädt die Modelle aus dem Speicher. Ollama hält sie sonst noch Minuten nach dem letzten Text."""
        if str(self.go["state"]) == "disabled" and self.model.get():
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
        self.go.config(state="disabled")
        self.input.tag_remove("weg", "1.0", "end")
        self.status.config(text="Schreibe um … das kann bei langen Texten ein, zwei Minuten dauern.", fg=MUTED)
        model, style = self.model.get(), self.style.get()

        def work() -> None:
            start = time.time()
            try:
                self.events.put(("result", (text, humanize(text, style, model, self.url), time.time() - start)))
            except OllamaError as e:
                self.events.put(("error", str(e)))

        threading.Thread(target=work, daemon=True).start()

    def copy_output(self) -> None:
        text = self.output.get("1.0", "end").strip()
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.status.config(text="Ausgabe kopiert.", fg=MUTED)


def main() -> None:
    try:  # sonst ist die Schrift auf Windows-Laptops mit Skalierung unscharf
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()

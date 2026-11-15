"""Tests für die Desktop-App. Die Fenster-Tests brauchen einen Bildschirm (unter Linux: xvfb-run)."""
import json
import threading
import time
import tkinter as tk
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import humanizer as h


@pytest.fixture(autouse=True)
def eigener_ordner(tmp_path, monkeypatch):
    """Kein Test liest oder schreibt die echten Einstellungen und Texte des Rechners, auf dem er läuft."""
    monkeypatch.setattr(h, "user_dir", lambda: str(tmp_path / "nutzer" / "texte"))


@pytest.fixture
def fake_ollama():
    seen = []
    state = {"models": ["llama3.2:3b", "gemma3:12b"], "loaded": ["gemma3:12b"]}

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, payload):
            self.send_response(code)
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

        def do_DELETE(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, body))
            if body["model"] not in state["models"]:
                return self._send(404, {"error": "model not found"})
            state["models"].remove(body["model"])
            self.send_response(200)
            self.end_headers()

        def do_GET(self):
            seen.append((self.path, None))
            if self.path == "/release":
                return self._send(200, {"target_commitish": "abc123"})
            if self.path == "/file":
                self.send_response(200)
                self.send_header("Content-Length", "200000")
                self.end_headers()
                self.wfile.write(b"x" * 200000)
                return
            names = state["loaded"] if self.path == "/api/ps" else state["models"]
            self._send(200, {"models": [{"name": n} for n in names]})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, body))
            if self.path == "/api/pull":
                self.send_response(200)
                self.end_headers()
                if body["model"] == "langsam":
                    try:
                        for i in range(200):
                            self.wfile.write(json.dumps({"status": "pulling a", "digest": "a", "total": 200, "completed": i}).encode() + b"\n")
                            time.sleep(0.02)
                    except OSError:
                        state["abgebrochen"] = True
                    return
                if body["model"] == "gibtsnicht":
                    self.wfile.write(b'{"error":"pull model manifest: file does not exist"}\n')
                    return
                for line in [{"status": "pulling manifest"},
                             {"status": "pulling a", "digest": "a", "total": 300, "completed": 150},
                             {"status": "pulling b", "digest": "b", "total": 100, "completed": 100},
                             {"status": "pulling a", "digest": "a", "total": 300, "completed": 300},
                             {"status": "success"}]:
                    self.wfile.write(json.dumps(line).encode() + b"\n")
                state["models"].append(body["model"])
                return
            if self.path == "/api/generate":
                state["loaded"].remove(body["model"])
                return self._send(200, {"done": True})
            if body["model"] == "kaputt":
                return self._send(500, {"error": "boom"})
            self._send(200, {"message": {"role": "assistant", "content": " Kurz. Und dann ein deutlich längerer Satz hinterher. \n"}})

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", seen, state
    server.shutdown()


LONG = ("Das Festival beginnt am Abend mit einem kurzen Konzert. Danach spielen mehrere Bands bis tief in die Nacht, "
        "während das Publikum tanzt.")


def test_saetze_und_kennzahlen():
    assert len(h.sentences("Das gilt z. B. für Kaffee bzw. Tee. Am 28.09.2026 geht es los.")) == 2
    assert h.burstiness("Nur ein Satz.") == 0.0
    assert h.tell_count("Darüber hinaus spielt das eine entscheidende Rolle – nahtlos.") == 4


def test_diff_spans():
    old, new = "Der Kaffee ist sehr gut.", "Der Kaffee schmeckt gut."
    gone, added = h.diff_spans(old, new)
    assert [old[s:e] for s, e in gone] == ["ist sehr"]
    assert [new[s:e] for s, e in added] == ["schmeckt"]
    assert h.diff_spans("gleich", "gleich") == ([], [])
    assert h.changed_share(new, added) == 25
    assert h.changed_share("", []) == 0


def test_list_models_sortiert(fake_ollama):
    url, _, _ = fake_ollama
    assert h.list_models(url) == ["gemma3:12b", "llama3.2:3b"]


def test_humanize_anfrage(fake_ollama):
    url, seen, _ = fake_ollama
    messages = [{"role": "system", "content": h.system_prompt("Locker", [])}, {"role": "user", "content": "Text"}]
    assert h._chat("gemma3:12b", url, messages).startswith("Kurz.")
    path, body = seen[-1]
    assert path == "/api/chat" and body["stream"] is False
    assert body["options"]["num_ctx"] == h.OLLAMA_CONTEXT
    assert h.STYLES["Locker"] in body["messages"][0]["content"]


def test_unload_models(fake_ollama):
    url, seen, state = fake_ollama
    assert h.unload_models(url) == 1
    assert seen[-1] == ("/api/generate", {"model": "gemma3:12b", "keep_alive": 0})
    assert state["loaded"] == []
    assert h.unload_models(url) == 0


def test_pull_model_meldet_fortschritt(fake_ollama):
    url, seen, state = fake_ollama
    progress = []
    h.pull_model("gemma3:4b", url, lambda percent, status: progress.append(percent))
    assert progress == [0, 50, 62, 100, 100]
    assert seen[-1] == ("/api/pull", {"model": "gemma3:4b", "stream": True})
    assert "gemma3:4b" in state["models"]


def test_pull_model_unbekanntes_modell(fake_ollama):
    url, _, _ = fake_ollama
    with pytest.raises(h.OllamaError, match="gibtsnicht"):
        h.pull_model("gibtsnicht", url)


def test_pull_model_abbrechen(fake_ollama):
    url, _, state = fake_ollama
    cancel = threading.Event()
    seen = []

    def progress(percent, status):
        seen.append(percent)
        if len(seen) == 3:
            cancel.set()

    with pytest.raises(h.PullCancelled):
        h.pull_model("langsam", url, progress, cancel)
    assert len(seen) == 3
    assert "langsam" not in state["models"]


def test_delete_model(fake_ollama):
    url, seen, state = fake_ollama
    h.delete_model("llama3.2:3b", url)
    assert seen[-1] == ("/api/delete", {"model": "llama3.2:3b"})
    assert state["models"] == ["gemma3:12b"]
    with pytest.raises(h.OllamaError, match="404"):
        h.delete_model("llama3.2:3b", url)


def test_latest_build_und_download(fake_ollama, tmp_path):
    url, _, _ = fake_ollama
    assert h.latest_build(url + "/release") == "abc123"
    with pytest.raises(h.UpdateError):
        h.latest_build("http://127.0.0.1:1/release")
    target, progress = tmp_path / "neu.exe", []
    h.download_file(url + "/file", str(target), progress.append)
    assert target.stat().st_size == 200000 and progress[-1] == 100
    with pytest.raises(h.UpdateError):
        h.download_file("http://127.0.0.1:1/file", str(target))


def test_swap_executable(tmp_path):
    current, new = tmp_path / "Humanizer.exe", tmp_path / "Humanizer.exe.new"
    current.write_text("alt")
    new.write_text("neu")
    (tmp_path / "Humanizer.old.exe").write_text("uralt")
    h.swap_executable(str(current), str(new))
    assert current.read_text() == "neu"
    assert (tmp_path / "Humanizer.old.exe").read_text() == "alt"
    assert not new.exists()
    h.cleanup_old(str(current))
    assert not (tmp_path / "Humanizer.old.exe").exists()
    h.cleanup_old(str(current))


def test_swap_executable_rollt_zurueck(tmp_path):
    current = tmp_path / "Humanizer.exe"
    current.write_text("alt")
    with pytest.raises(OSError):
        h.swap_executable(str(current), str(tmp_path / "fehlt.new"))
    assert current.read_text() == "alt"


def test_verdict():
    assert h.verdict(10, 16, 32, 8) == "läuft, aber langsamer"
    assert h.verdict(4, 8, 31.7, 7.996) == "läuft flüssig"
    assert h.verdict(20, 32, 16, 8) == "zu groß für diesen Rechner"
    assert h.verdict(4, 8, 16, None) == "läuft, aber langsamer"
    assert h.verdict(4, 8, None, None) == ""


def test_katalog_und_speicher():
    assert h.PREFERRED_MODEL in [row[0] for row in h.CATALOG]
    assert all(len(row) == 5 and row[1] > 0 and row[2] <= row[3] for row in h.CATALOG)
    ram, vram = h.system_memory()
    assert ram is None or ram > 0


def test_fehler_von_ollama(fake_ollama):
    url, _, _ = fake_ollama
    with pytest.raises(h.OllamaError, match="500"):
        h._chat("kaputt", url, [{"role": "user", "content": "Text"}])


def test_nicht_erreichbar():
    with pytest.raises(h.OllamaUnreachable):
        h.list_models("http://127.0.0.1:1")


def pump(root, until, timeout=10):
    end = time.time() + timeout
    while time.time() < end and not until():
        root.update()
        time.sleep(0.02)
    assert until()


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("kein Bildschirm")
    yield r
    r.destroy()


def test_app_laedt_modelle_und_schreibt_um(root, fake_ollama):
    url, _, _ = fake_ollama
    app = h.App(root, url)
    pump(root, lambda: str(app.go["state"]) == "normal")
    assert list(app.model["values"]) == ["gemma3:12b", "llama3.2:3b"]
    assert app.model.get() == "gemma3:12b"

    app.input.insert("1.0", "Darüber hinaus ist das wichtig für alle Leute im Team. Es ist nahtlos und gut so für uns.")
    app.run()
    assert str(app.go["state"]) == "disabled"
    pump(root, lambda: app.output.get("1.0", "end").strip() != "")
    assert app.output.get("1.0", "end").strip().startswith("Kurz.")
    assert "KI-Floskeln 2 → 0" in app.status["text"]
    assert "% neu formuliert" in app.status["text"]
    out = app.output.get("1.0", "end-1c")
    marked = app.output.tag_ranges("neu")
    assert marked and app.output.get(marked[0], marked[1]) == out.split(" ist")[0][:len(app.output.get(marked[0], marked[1]))]
    assert app.input.tag_ranges("weg")
    assert str(app.go["state"]) == "normal"

    app.copy_output()
    assert root.clipboard_get().startswith("Kurz.")


def test_app_ohne_modelle(root, fake_ollama):
    url, _, state = fake_ollama
    state["models"] = []
    app = h.App(root, url)
    pump(root, lambda: "Kein Modell installiert" in app.status["text"])
    assert str(app.go["state"]) == "disabled"


def test_app_zeigt_fehler_und_bleibt_bedienbar(root, fake_ollama):
    url, _, _ = fake_ollama
    app = h.App(root, url)
    pump(root, lambda: str(app.go["state"]) == "normal")
    app.model.set("kaputt")
    app.input.insert("1.0", LONG)
    app.run()
    pump(root, lambda: "500" in app.status["text"])
    assert str(app.go["state"]) == "normal"


def test_app_cache_leeren(root, fake_ollama):
    url, _, state = fake_ollama
    app = h.App(root, url)
    pump(root, lambda: str(app.go["state"]) == "normal")
    app.clear_cache()
    pump(root, lambda: "1 Modell entladen" in app.status["text"])
    assert state["loaded"] == []
    assert str(app.clear["state"]) == "normal"
    app.clear_cache()
    pump(root, lambda: "kein Modell geladen" in app.status["text"])


def test_app_modell_herunterladen(root, fake_ollama, monkeypatch):
    url, _, state = fake_ollama
    monkeypatch.setattr(h, "system_memory", lambda: (32.0, 8.0))
    app = h.App(root, url)
    pump(root, lambda: str(app.go["state"]) == "normal")
    app.open_models()
    assert "32 GB RAM, 8 GB Grafikspeicher" in app.machine["text"]
    installed_button, _ = app.rows["gemma3:12b"]
    assert installed_button["text"] == "Löschen" and "Installiert" in app.rows["gemma3:12b"][1]["text"]
    button, fit = app.rows["gemma3:4b"]
    assert button["text"] == "Herunterladen" and "läuft flüssig" in fit["text"]
    assert "zu groß" not in app.rows["gemma3:27b"][1]["text"] and "langsamer" in app.rows["gemma3:27b"][1]["text"]

    button.invoke()
    pump(root, lambda: "ist installiert" in app.pull_status["text"])
    assert "gemma3:4b" in app.model["values"]
    assert button["text"] == "Löschen"
    assert app.model.get() == "gemma3:12b"
    assert str(app.rows["gemma3:1b"][0]["state"]) == "normal"

    app.custom.insert(0, "gibtsnicht")
    app.custom_button.invoke()
    pump(root, lambda: "fehlgeschlagen" in app.pull_status["text"])
    assert app.pulling is None and str(app.custom_button["state"]) == "normal"


def test_app_ohne_modelle_dann_download(root, fake_ollama):
    url, _, state = fake_ollama
    state["models"] = []
    app = h.App(root, url)
    pump(root, lambda: "Modelle" in app.status["text"])
    app.open_models()
    app.rows["gemma3:12b"][0].invoke()
    pump(root, lambda: str(app.go["state"]) == "normal")
    assert app.model.get() == "gemma3:12b"


def test_app_download_abbrechen(root, fake_ollama):
    url, _, state = fake_ollama
    app = h.App(root, url)
    pump(root, lambda: str(app.go["state"]) == "normal")
    app.open_models()
    app.custom.insert(0, "langsam")
    app.custom_button.invoke()
    pump(root, lambda: "heruntergeladen" in app.pull_status["text"])
    assert app.custom_button["text"] == "Abbrechen"
    assert str(app.rows["gemma3:4b"][0]["state"]) == "disabled"
    app.custom_button.invoke()
    pump(root, lambda: app.pulling is None)
    assert "abgebrochen" in app.pull_status["text"]
    assert app.custom_button["text"] == "Herunterladen"
    assert str(app.rows["gemma3:4b"][0]["state"]) == "normal"
    assert "langsam" not in app.installed


def test_app_download_in_zeile_abbrechen(root, fake_ollama):
    url, _, _ = fake_ollama
    app = h.App(root, url)
    pump(root, lambda: str(app.go["state"]) == "normal")
    app.open_models()
    h.CATALOG.append(("langsam", 1, 1, 1, "Testmodell"))
    try:
        app.dialog.destroy()
        app.open_models()
        button = app.rows["langsam"][0]
        button.invoke()
        pump(root, lambda: button["text"] == "Abbrechen")
        button.invoke()
        pump(root, lambda: app.pulling is None)
        assert button["text"] == "Herunterladen"
    finally:
        h.CATALOG.pop()


def test_app_modell_loeschen(root, fake_ollama, monkeypatch):
    url, _, state = fake_ollama
    asked = []
    monkeypatch.setattr(h.messagebox, "askyesno", lambda title, text, **kw: asked.append(text) or True)
    app = h.App(root, url)
    pump(root, lambda: str(app.go["state"]) == "normal")
    app.open_models()
    assert [w["text"] for w in app.extra.winfo_children()][:2] == ["Weitere installierte Modelle", "llama3.2:3b"]

    app.delete("llama3.2:3b")
    pump(root, lambda: "llama3.2:3b" not in app.installed)
    assert app.extra.winfo_children() == []
    assert app.model.get() == "gemma3:12b"

    app.rows["gemma3:12b"][0].invoke()
    pump(root, lambda: app.installed == [])
    assert asked[-1] == "gemma3:12b wirklich löschen? Das gibt rund 8,1 GB frei."
    assert app.model.get() == "" and str(app.go["state"]) == "disabled"
    assert "Kein Modell installiert" in app.status["text"]
    assert app.rows["gemma3:12b"][0]["text"] == "Herunterladen"


def test_app_loeschen_abgelehnt(root, fake_ollama, monkeypatch):
    url, _, state = fake_ollama
    monkeypatch.setattr(h.messagebox, "askyesno", lambda *a, **kw: False)
    app = h.App(root, url)
    pump(root, lambda: str(app.go["state"]) == "normal")
    app.open_models()
    app.rows["gemma3:12b"][0].invoke()
    pump(root, lambda: True)
    assert state["models"] == ["llama3.2:3b", "gemma3:12b"]


def test_app_update_knopf(root, fake_ollama, monkeypatch):
    url, _, _ = fake_ollama
    app = h.App(root, url)
    pump(root, lambda: str(app.go["state"]) == "normal")

    monkeypatch.setattr(h, "latest_build", lambda: h.BUILD)
    app.update_button.invoke()
    pump(root, lambda: "neueste Version" in app.status["text"])
    assert str(app.update_button["state"]) == "normal"

    monkeypatch.setattr(h, "latest_build", lambda: "neuer")
    app.update_button.invoke()
    pump(root, lambda: "Quelltext" in app.status["text"])

    def kaputt():
        raise h.UpdateError("GitHub ist gerade nicht erreichbar.")

    monkeypatch.setattr(h, "latest_build", kaputt)
    app.update_button.invoke()
    pump(root, lambda: "nicht erreichbar" in app.status["text"])
    assert not app.updating


def test_app_update_laedt_und_tauscht(root, fake_ollama, monkeypatch, tmp_path):
    url, _, _ = fake_ollama
    exe = tmp_path / "Humanizer.exe"
    exe.write_text("alt")
    started = []
    monkeypatch.setattr(h.sys, "frozen", True, raising=False)
    monkeypatch.setattr(h.sys, "executable", str(exe))
    monkeypatch.setattr(h, "EXE_URL", url + "/file")
    monkeypatch.setattr(h, "latest_build", lambda: "neuer")
    monkeypatch.setattr(h.messagebox, "askyesno", lambda *a, **kw: True)
    monkeypatch.setattr(h.subprocess, "Popen", lambda cmd, **kw: started.append((cmd, kw["env"])))
    destroyed = []
    app = h.App(root, url)
    monkeypatch.setattr(app.root, "destroy", lambda: destroyed.append(True))
    pump(root, lambda: str(app.go["state"]) == "normal")
    app.update_button.invoke()
    pump(root, lambda: destroyed)
    assert exe.stat().st_size == 200000
    assert (tmp_path / "Humanizer.old.exe").read_text() == "alt"
    assert started[0][0] == [str(exe)] and started[0][1]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


# --- Stilvorlage, eigene Texte, Fakten- und Längenprüfung ---
import random


def test_load_texts(tmp_path):
    (tmp_path / "b.txt").write_text("Zweiter Text.", encoding="utf-8")
    (tmp_path / "a.txt").write_bytes("Größe in cp1252".encode("cp1252"))
    (tmp_path / "c.txt").write_text("   ", encoding="utf-8")
    (tmp_path / "d.md").write_text("kein txt", encoding="utf-8")
    (tmp_path / "e.txt").write_bytes("﻿Mit BOM".encode("utf-8"))
    assert h.load_texts(str(tmp_path)) == ["Größe in cp1252", "Zweiter Text.", "Mit BOM"]
    assert h.load_texts(str(tmp_path / "fehlt")) == []


def test_system_prompt_mit_und_ohne_vorlage():
    plain = h.system_prompt("Akademisch", [])
    assert "<beispiel>" not in plain and h.STYLES["Akademisch"] in plain
    with_examples = h.system_prompt("Akademisch", ["Ein echter Satz."])
    assert "<beispiel>\nEin echter Satz.\n</beispiel>" in with_examples
    assert "NIE Inhalte" in with_examples


def test_missing_facts_und_kuerzung():
    source = "Am 28.09.2026 kamen 150 Leute, z. B. 3,5 % mehr als 2025."
    assert h.missing_facts(source, source) == []
    assert h.missing_facts(source, "Am 28. September kamen 150 Leute, 3,5 % mehr als 2025.") == ["28.09.2026"]
    assert h.missing_facts(source, "Es kamen Leute.") == ["28.09.2026", "150", "3,5 %", "2025"]
    assert h.shrinkage("eins zwei drei vier", "eins zwei") == 50
    assert h.shrinkage("", "x") == 0
    assert h.warnings(source, source) == ""
    warning = h.warnings("a b c d e f g h i j 7", "a b c")
    assert "fehlt in der Ausgabe: 7" in warning and "73 % kürzer" in warning


def test_mitgelieferte_texte():
    counts = {g: len(h.bundled_texts(g)) for g in ("sachlich", "bericht", "locker")}
    assert all(n >= 20 for n in counts.values()), counts
    for g in counts:
        for text in h.bundled_texts(g):
            assert 100 <= len(text.split()) <= 450
            assert "daß" not in text and "{{" not in text and "[[" not in text and "<ref" not in text
            assert not h.re.search(r"(?i)neger|zigeun|judensau", text)


def test_selftest(tmp_path):
    target = tmp_path / "selftest.json"
    h.selftest(str(target))
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["build"] == h.BUILD and data["sachlich"] >= 20


def test_app_warnung_bei_fehlendem_datum(root, fake_ollama, monkeypatch):
    url, _, _ = fake_ollama
    monkeypatch.setattr(h, "user_dir", lambda: "/gibt/es/nicht")
    app = h.App(root, url)
    pump(root, lambda: str(app.go["state"]) == "normal")
    assert app.source.get() == "Mitgeliefert"
    app.input.insert("1.0", "Das Fest ist am 28.09.2026 in Dornbirn mit 300 Gästen. Alle kamen pünktlich und blieben lange.")
    app.run()
    pump(root, lambda: app.warning["text"] != "")
    assert "28.09.2026" in app.warning["text"] and "300" in app.warning["text"]
    app.run()
    assert app.warning["text"] == ""


def test_app_meine_texte_leer_gibt_hinweis(root, fake_ollama, monkeypatch, tmp_path):
    url, seen, _ = fake_ollama
    monkeypatch.setattr(h, "user_dir", lambda: str(tmp_path / "texte"))
    opened = []
    monkeypatch.setattr(h, "open_folder", opened.append)
    app = h.App(root, url)
    pump(root, lambda: str(app.go["state"]) == "normal")
    app.source.set("Meine Texte")
    app.input.insert("1.0", LONG)
    app.run()
    pump(root, lambda: "noch nichts" in app.warning["text"])
    assert "<beispiel>" in seen[-1][1]["messages"][0]["content"]
    app.open_own_texts()
    assert opened == [str(tmp_path / "texte")]


def test_app_waehlt_meine_texte_wenn_vorhanden(root, fake_ollama, monkeypatch, tmp_path):
    url, seen, _ = fake_ollama
    own = ("Kurz gesagt: so nicht. Der zweite Satz dagegen erklärt ausführlich und mit Nebensätzen, worum es in "
           "dieser Hausarbeit eigentlich gehen soll.")
    (tmp_path / "hausarbeit.txt").write_text(own, encoding="utf-8")
    monkeypatch.setattr(h, "user_dir", lambda: str(tmp_path))
    app = h.App(root, url)
    assert app.source.get() == "Meine Texte"
    pump(root, lambda: str(app.go["state"]) == "normal")
    app.input.insert("1.0", LONG)
    app.run()
    pump(root, lambda: seen[-1][0] == "/api/chat")
    assert own in seen[-1][1]["messages"][0]["content"]


# --- Ziel-Länge und automatisches Nachbessern ---
UNIFORM = " ".join(f"Satz Nummer {i} hat genau sieben Wörter drin." for i in range(10))
VARIED = (
    "Kurz. Dieser Satz ist dagegen ziemlich lang, und er hat mehrere Nebensätze, die erklären, warum etwas passiert, "
    "obwohl es niemand erwartet hätte, sodass am Ende alle staunen. Na gut. Wer morgens um sechs am Bahnsteig steht "
    "und auf einen Zug wartet, der schon zweimal ausgefallen ist, versteht ziemlich schnell, was Geduld bedeutet und "
    "wie wenig sie nützt. Stimmt. Als die Halle endlich offen war, drängten sich die Leute an den Kassen, die Musik "
    "lief schon, und draußen regnete es so stark, dass niemand mehr an die Zelte denken wollte. Egal. Dass die "
    "Technik am Ende hielt, lag weniger am Glück als an den drei Leuten, die die ganze Nacht Kabel geprüft und "
    "Scheinwerfer neu ausgerichtet hatten, ohne dass es jemand merkte. Fertig. Obwohl die Kasse am Abend nicht "
    "stimmte, ging am nächsten Morgen alles wieder von vorn los, mit neuen Bändchen, neuen Listen und demselben Kaffee "
    "aus der Thermoskanne vom Vortag. ")


def test_quellenangaben_trennen_keinen_satz():
    text = "Besucher erwarten Planung (vgl. Berger 2021, S. 45). Die Anforderungen steigen. Siehe Kap. 3 und Abs. 2."
    assert len(h.sentences(text)) == 3


@pytest.fixture
def scripted_ollama():
    """Ollama-Ersatz, der der Reihe nach vorgegebene Antworten liefert."""
    replies, seen = [], []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            answer = replies.pop(0)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"message": {"content": answer}}).encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", replies, seen
    server.shutdown()


def test_app_zeigt_nachgebessert(root, scripted_ollama, monkeypatch):
    url, replies, _ = scripted_ollama
    monkeypatch.setattr(h, "ensure_ollama", lambda url: ["m"])
    monkeypatch.setattr(h, "user_dir", lambda: "/gibt/es/nicht")
    replies += [UNIFORM[:150], VARIED, VARIED]
    app = h.App(root, url)
    pump(root, lambda: str(app.go["state"]) == "normal")
    app.input.insert("1.0", VARIED)
    app.run()
    pump(root, lambda: "Fertig" in app.status["text"])
    assert "× nachgebessert)" in app.status["text"]
    assert app.update_button.master is app.go.master


def test_app_merkt_sich_auswahl(root, fake_ollama, monkeypatch, tmp_path):
    url, _, _ = fake_ollama
    monkeypatch.setattr(h, "user_dir", lambda: str(tmp_path / "texte"))
    app = h.App(root, url)
    pump(root, lambda: str(app.go["state"]) == "normal")
    assert app.model.get() == "gemma3:12b" and app.style.get() == "Natürlich"
    app.model.set("llama3.2:3b")
    app.style.set("Akademisch")
    app.source.set("Aus")
    app.model.event_generate("<<ComboboxSelected>>")
    pump(root, lambda: (tmp_path / "einstellungen.json").exists())
    app2 = h.App(root, url)
    pump(root, lambda: str(app2.go["state"]) == "normal")
    assert (app2.model.get(), app2.style.get(), app2.source.get()) == ("llama3.2:3b", "Akademisch", "Aus")


def test_einstellungen_kaputt_oder_fremd(tmp_path, monkeypatch):
    monkeypatch.setattr(h, "user_dir", lambda: str(tmp_path / "texte"))
    assert h.load_settings() == {}
    (tmp_path / "einstellungen.json").write_text("{kaputt", encoding="utf-8")
    assert h.load_settings() == {}
    (tmp_path / "einstellungen.json").write_text("[1, 2]", encoding="utf-8")
    assert h.load_settings() == {}


SOURCE = """Am 24.07.2010 kamen viele Besucher nach Duisburg. Die Planung der Fluchtwege war mangelhaft.

Beim Schallschutz gilt ein Richtwert von 100 dB(A) am Mischpult. Anrainer müssen geschützt werden.

Abschließend zeigt sich: Nachhaltigkeit und Sicherheit bilden gemeinsam das Fundament jeder Veranstaltung."""


def test_added_facts():
    assert h.added_facts(SOURCE, SOURCE) == []
    assert h.added_facts(SOURCE, SOURCE + " Dabei starben 21 Menschen, 21 zu viel.") == ["21"]


def test_crutches():
    text = " ".join(f"Das gilt, weil es so ist. Zudem stimmt das {i}." for i in range(4))
    found = h.crutches(text)
    assert any("4-mal" in f for f in found) and any("4 Sätze mit Zudem begonnen" in f for f in found)
    assert h.crutches(VARIED) == []


def test_problems_und_warnung_bei_erfundenem_und_fehlendem():
    result = h.paragraphs(SOURCE)[0] + " Dabei starben 21 Menschen.\n\n" + h.paragraphs(SOURCE)[1]
    warning = h.warnings(SOURCE, result)
    assert "neu, steht nicht im Original: 21" in warning and "Absatz fehlt" not in warning




# --- Absatz für Absatz nach Bauplan ---
PARA = ("Ein zentraler Aspekt ist der Energieverbrauch der Technik. Licht und Ton verursachen bei 50.000 Gästen bis "
        "zu 1,2 Gigawattstunden (vgl. Hofer 2019, S. 112). Mit LED sinkt der Verbrauch um etwa 60 %.")


def test_paragraph_pool_und_quellen():
    pool = h.paragraph_pool(["Eins zwei drei. Vier fünf sechs sieben.\n\nNur ein Satz hier.", "  "])
    assert pool == [(7, [3, 4], "Eins zwei drei. Vier fünf sechs sieben.")]
    groups = {"sachlich": [(5, [2, 3], "S")], "bericht": [(5, [2, 3], "B")], "locker": [(5, [2, 3], "L")]}
    assert h.plan_pool("Aus", "Akademisch", ["x"], groups.__getitem__) == ([], "")
    pool, note = h.plan_pool("Mitgeliefert", "Akademisch", [], groups.__getitem__)
    assert [p[2] for p in pool] == ["S", "B"] and note == ""
    pool, note = h.plan_pool("Meine Texte", "Locker", [], groups.__getitem__)
    assert [p[2] for p in pool] == ["L", "B"] and "noch nichts" in note
    own = ["Kurz und gut. Dieser zweite Satz ist deutlich länger als der erste."]
    assert h.plan_pool("Meine Texte", "Locker", own, groups.__getitem__)[0][0][2] == own[0]


def test_sentence_plan():
    pool = [(36, [4, 20, 12], "Vorbild A."), (300, [100, 200], "zu lang"), (36, [12, 12, 12], "zu gleichmäßig")]
    plan, example = h.sentence_plan(PARA, pool, random.Random(1))
    assert example == "Vorbild A." and len(plan) == 3
    assert abs(sum(plan) - len(PARA.split())) <= 3 and h.usable_plan(plan)
    plan, example = h.sentence_plan(PARA, [], random.Random(1))
    assert example == "" and plan == h.fallback_plan(len(PARA.split()))
    assert h.usable_plan(h.fallback_plan(64))
    assert not h.usable_plan([58, 3]) and not h.usable_plan([3, 4, 30]) and not h.usable_plan([10, 10, 10])


def test_plan_fit():
    assert h.plan_fit([2, 3], "Eins zwei. Drei vier fünf.") == 0
    assert h.plan_fit([10, 10], "Eins zwei. Drei vier fünf.") > 0.4
    assert h.plan_fit([2, 3, 4, 5], "Eins zwei. Drei vier fünf.") > 0.3
    assert h.plan_fit([2], "") == 1.0


def test_paragraph_request():
    request = h.paragraph_request(PARA, [20, 5, 12])
    assert "genau 3 Sätze" in request and "Satz 2: etwa 5 Wörter" in request
    assert "(vgl. Hofer 2019, S. 112)" in request and "50.000" in request and request.endswith(PARA)


def test_missing_citations_und_unchanged():
    assert h.missing_citations(PARA, PARA) == []
    assert h.missing_citations(PARA, PARA.replace("S. 112", "S. 121")) == ["(vgl. Hofer 2019, S. 112)"]
    assert len(h.unchanged_sentences(PARA, PARA)) == 3
    assert h.unchanged_sentences(PARA, "Ganz anders formuliert. Wirklich ganz anders.") == []
    warning = h.warnings(PARA, PARA)
    assert "3 Sätze kaum verändert" in warning


def test_paragraph_problems():
    plan = [12, 14, 9]
    found = h.paragraph_problems(PARA, PARA.replace("(vgl. Hofer 2019, S. 112)", "") + " Dazu 21 Tote.", plan)
    text = " ".join(found)
    assert "21" in text and "(vgl. Hofer 2019, S. 112)" in text and "fast wörtlich" in text
    assert "Bauplan" in " ".join(h.paragraph_problems(PARA, "Ein einziger Satz mit 1,2 und 50.000 und 60 und 2019 "
                                                          "und 112 (vgl. Hofer 2019, S. 112).", plan))


def test_needs_rewrite():
    assert not h.needs_rewrite("Nachhaltigkeit und Sicherheit bei Großveranstaltungen")
    assert not h.needs_rewrite("Ein einziger, recht langer Satz ohne einen zweiten danach und ohne Ende in Sicht.")
    assert h.needs_rewrite(PARA)


def test_rewrite_paragraph_bessert_nach_und_nimmt_beste(scripted_ollama):
    url, replies, seen = scripted_ollama
    good = ("Bei 50.000 Gästen verursachen Licht und Ton bis zu 1,2 Gigawattstunden (vgl. Hofer 2019, S. 112), "
            "was den Energiebedarf zum Kernthema macht. Viel ist das. LED drückt den Bedarf um etwa 60 %.")
    replies += ["Kaputt ohne Zahlen. Wirklich.", good, "Wieder kaputt. Ganz."]
    pool = [(36, [17, 3, 9], "Ein echter Absatz als Vorbild.")]
    result, extra, _ = h.rewrite_paragraph(PARA, "Akademisch", "m", url, pool, rng=random.Random(1))
    assert result == good and extra >= 1
    assert "<beispiel>\nEin echter Absatz als Vorbild.\n</beispiel>" in seen[0]["messages"][0]["content"]
    assert "Bauplan: genau 3 Sätze" in seen[0]["messages"][1]["content"]
    assert seen[1]["messages"][2]["content"] == "Kaputt ohne Zahlen. Wirklich."


def test_humanize_checked_absatzweise(scripted_ollama):
    url, replies, seen = scripted_ollama
    text = "Überschrift ohne Punkt\n\n" + PARA + "\n\n" + LONG
    replies += ["Erster Absatz neu. Mit 50.000 und 1,2 und 60 (vgl. Hofer 2019, S. 112)."] * 3 + ["Zweiter neu. Ja."] * 3
    steps = []
    result, passes, _ = h.humanize_checked(text, "Akademisch", "m", url, [], progress=lambda d, t: steps.append((d, t)))
    parts = h.paragraphs(result)
    assert parts[0] == "Überschrift ohne Punkt" and parts[1].startswith("Erster") and parts[2].startswith("Zweiter")
    assert steps == [(1, 2), (2, 2)] and passes == 1 + (len(seen) - 2)


def test_app_zeigt_fortschritt_und_kopieren_stellt_status_wieder_her(root, fake_ollama):
    url, _, _ = fake_ollama
    app = h.App(root, url)
    pump(root, lambda: str(app.go["state"]) == "normal")
    app._on_progress((2, 5))
    assert app.status["text"] == "Schreibe um … Absatz 2 von 5"
    app.output.insert("1.0", "Etwas")
    app.status.config(text="Fertig in 3 s")
    app.copy_output()
    assert app.status["text"] == "Ausgabe kopiert."
    pump(root, lambda: app.status["text"] == "Fertig in 3 s", timeout=5)


def test_ausgeschriebene_zahl_zaehlt_als_vorhanden():
    assert h.missing_facts("Maximal 2 Personen pro Quadratmeter.", "Höchstens zwei Personen je Quadratmeter.") == []
    assert h.missing_facts("Es kamen 50.000 Gäste.", "Es kamen fünfzigtausend Gäste.") == ["50.000"]


def test_habits_und_wiederholung_ueber_absaetze():
    assert h.habits("Die Technik stellt einen zentralen Aspekt dar.") == ['"… stellt … dar"', '"zentraler Aspekt/Punkt"']
    assert h.habits("Kurz und klar.") == []
    found = h.paragraph_problems(PARA, "Das stellt viel dar. Ganz anders.", [3, 2], ['"… stellt … dar"'])
    assert any("früheren Absätzen" in f for f in found)
    assert "verwende sie hier nicht" in h.paragraph_request(PARA, [10, 10], ['"somit"'])


def test_humanize_checked_gibt_gewohnheiten_weiter(scripted_ollama):
    url, replies, seen = scripted_ollama
    replies += ["Die Lage stellt viel dar. Sonst nichts."] * 6
    h.humanize_checked(PARA + "\n\n" + LONG, "Akademisch", "m", url, [], retries=0)
    assert "stellt … dar" not in seen[0]["messages"][1]["content"]
    assert '"… stellt … dar"' in seen[1]["messages"][1]["content"]



def test_jahreszahl_aus_quellenangabe_im_text_ist_erfunden():
    source = "Die Anforderungen stiegen (vgl. Berger 2021, S. 45)."
    assert h.added_facts(source, source) == []
    assert h.added_facts(source, "Die Anforderungen stiegen seit 2021 (vgl. Berger 2021, S. 45).") == ["2021"]
    doubled = "Erst (vgl. Berger 2021, S. 45), dann nochmal (vgl. Berger 2021, S. 45)."
    assert h.doubled_citations(source, doubled) == ["(vgl. Berger 2021, S. 45)"]
    assert any("öfter" in f for f in h.paragraph_problems(source, doubled, [3, 4]))



# --- Inhaltstreue ---
def test_zahlen_mit_einheit():
    source = "Der Verbrauch sinkt um etwa 60 %, gemessen über 30 Minuten bei 100 dB(A) und maximal 2 Personen."
    assert h.missing_facts(source, source) == []
    assert h.missing_facts(source, source.replace("60 %", "60 Prozent")) == []
    assert h.missing_facts(source, source.replace("60 %", "60")) == ["60 %"]
    assert h.missing_facts(source, source.replace("30 Minuten", "30 Sekunden")) == ["30 Minuten"]
    assert h.missing_facts(source, source.replace("2 Personen", "zwei Personen")) == []
    assert h.missing_facts("Im Jahr 2023 stieg es.", "Laut Studie von 2023 stieg es um 4 %.") == []
    assert [f[2] for f in h.facts("Es sind 100 dB(A) und 1,2 GWh.")] == ["100 dB(A)", "1,2 GWh"]


def test_einschraenkungen_finden_und_pruefen():
    para = ("In Österreich gilt im Freien häufig ein Richtwert von 100 dB(A) am Mischpult, im Bereich der Bühne "
            "und in der Regel bei einem mehrtägigen Festival. Laut 38 % der europäischen Festivalveranstalter, aus dem "
            "Jahr 2023, zwischen Publikumserlebnis und Schutz, durch technische Innovationen.")
    found = h.extract_qualifiers(para)
    assert found == ["In Österreich", "im Freien", "am Mischpult", "bei einem mehrtägigen Festival",
                     "europäischen Festivalveranstalter"]
    out = "Draußen gilt oft ein Richtwert von 100 dB(A) am Mischpult."
    assert h.missing_qualifiers(found[:3], out) == ["In Österreich", "im Freien"]
    assert h.missing_qualifiers(["europäischen Festivalveranstalter"], "38 % der europäischen Festivalveranstaltern") == []
    assert h.missing_qualifiers(["europäischen Festivalveranstalter"], "38 % der Veranstalter") == ["europäischen Festivalveranstalter"]


def test_einschraenkungen_landen_in_auftrag_und_rueckmeldung(scripted_ollama):
    url, replies, seen = scripted_ollama
    para = ("In Österreich gilt bei Konzerten im Freien häufig ein Richtwert von 100 dB(A). "
            "Gleichzeitig müssen Anrainer vor Lärm geschützt werden.")
    good = ("Anrainer müssen vor Lärm geschützt werden, auch wenn in Österreich bei Konzerten im Freien oft ein "
            "Richtwert von 100 dB(A) gilt. Eben.")
    replies += ["Für Konzerte gilt ein Richtwert von 100 dB(A). Anrainer brauchen Schutz.", good, good]
    result, extra, found = h.rewrite_paragraph(para, "Akademisch", "m", url, [], rng=random.Random(1))
    assert found == ["In Österreich", "bei Konzerten", "im Freien"]
    assert "Diese Einschränkungen müssen erhalten bleiben: In Österreich; bei Konzerten; im Freien" in \
        seen[0]["messages"][1]["content"]
    assert "In Österreich; im Freien" in seen[1]["messages"][-1]["content"]
    assert result == good
    assert "Einschränkung fehlt: In Österreich; bei Konzerten; im Freien" in h.warnings(para, "Kurz. Anders.", found)


def test_verrutschte_quelle():
    source = ("Digitale Systeme ermöglichen eine präzisere Steuerung von Besucherströmen. Laut einer Studie setzen bereits "
              "38 % der europäischen Festivalveranstalter derartige Systeme ein (vgl. Event Industry Report 2023, S. 9).")
    moved = ("38 % der europäischen Festivalveranstalter setzen solche Systeme ein. Studien zeigen, dass Echtzeit-Monitoring "
             "und Prognosemodelle die Steuerung verbessern (vgl. Event Industry Report 2023, S. 9).")
    kept = ("Solche Systeme setzen bereits 38 % der europäischen Festivalveranstalter ein (vgl. Event Industry Report "
            "2023, S. 9). Sie steuern Besucherströme präziser.")
    assert h.misplaced_citations(source, source) == []
    assert h.misplaced_citations(source, kept) == []
    found = h.misplaced_citations(source, moved)
    assert [c for c, _ in found] == ["(vgl. Event Industry Report 2023, S. 9)"]
    assert "38 % der europäischen Festivalveranstalter" in found[0][1]
    assert "belegt diese Aussage" in h.paragraph_request(source, [10, 20])
    assert any("falschen Aussage" in f for f in h.paragraph_problems(source, moved, [12, 15]))
    assert "Quelle verrutscht: (vgl. Event Industry Report 2023, S. 9)" in h.warnings(source, moved)


def test_wiederholung_und_umbrueche():
    text = ("Nachhaltigkeit und Sicherheit bilden gemeinsam das Fundament zukunftsfähiger Veranstaltungen. Kurz. "
            "Gemeinsam bilden Sicherheit und Nachhaltigkeit das Fundament zukunftsfähiger Veranstaltungen.")
    assert len(h.repeated_sentences(text)) == 1
    assert h.repeated_sentences(VARIED) == []
    assert h.flatten("Erste Zeile.\nZweite Zeile.\n\n  Dritte.") == "Erste Zeile. Zweite Zeile. Dritte."


def test_quelle_als_fliesstext_zaehlt():
    source = "Der Bedarf liegt bei bis zu 1,2 Gigawattstunden (vgl. Hofer/Lindner 2019, S. 112)."
    narrative = "Wie Hofer und Lindner (2019, S. 112) zeigen, liegt der Bedarf bei bis zu 1,2 Gigawattstunden."
    assert h.citation_parts("(vgl. Hofer/Lindner 2019, S. 112)") == (["Hofer", "Lindner"], ["2019", "112"])
    assert h.missing_citations(source, narrative) == [] and h.added_facts(source, narrative) == []
    wrong_page = narrative.replace("S. 112", "S. 113")
    assert h.missing_citations(source, wrong_page) == ["(vgl. Hofer/Lindner 2019, S. 112)"]
    assert h.added_facts(source, wrong_page) == ["2019", "113"]


# --- Verknüpfungen und Sätze ohne Grundlage ---
SAFETY = ("Ein Crowd-Management-Konzept umfasst die Analyse von Besucherströmen und die Schulung des Personals. "
          "Gemäß der Versammlungsstättenverordnung sind bei Stehplätzen 2 Personen pro Quadratmeter zulässig.")


def test_neue_verknuepfungen():
    wrong = ("Das Personal muss geschult werden, obwohl die Versammlungsstättenverordnung bei Stehplätzen nur "
             "2 Personen pro Quadratmeter zulässt. Die Sicherheit steht vorn, sodass Besucherströme analysiert werden.")
    found = h.new_connectors(SAFETY, wrong)
    assert [(w, n) for w, n, _ in found] == [("obwohl", 1), ("sodass", 1)]
    assert "obwohl" in found[0][2][0]
    assert h.new_connectors("Obwohl es regnet, kommen alle.", "Alle kommen, obwohl es regnet.") == []
    text = " ".join(h.paragraph_problems(SAFETY, wrong, [14, 13]))
    assert 'Mit "obwohl" behauptest du einen Gegensatz' in text and 'Mit "sodass" behauptest du eine Folge' in text
    assert "neue Begründung oder Gegensatz, prüfen: obwohl (1×), sodass (1×)" in h.warnings(SAFETY, wrong)


def test_saetze_ohne_grundlage():
    filler = SAFETY + " Das gilt für alle Bereiche."
    assert h.unsupported_sentences(SAFETY, filler) == ["Das gilt für alle Bereiche."]
    reworded = ("Das Personal zu schulen und Besucherströme zu analysieren, gehört zu jedem Crowd-Management-Konzept. "
                "Bei Stehplätzen erlaubt die Verordnung 2 Personen pro Quadratmeter.")
    assert h.unsupported_sentences(SAFETY, reworded) == []
    assert h.unsupported_sentences("Es nutzen 38 % der europäischen Festivalveranstalter solche Systeme.",
                                   "Viele Veranstalter nutzen sie schon.") == []
    assert h.unsupported_sentences(SAFETY, SAFETY + " Dabei starben 21 Menschen bei Unfällen.") == \
        ["Dabei starben 21 Menschen bei Unfällen."]
    assert 'keine Grundlage in der Vorlage, streich ihn: "Das gilt für alle Bereiche."' in \
        " ".join(h.paragraph_problems(SAFETY, filler, [14, 13, 5]))
    assert "ohne Grundlage im Original" in h.warnings(SAFETY, filler)


def test_ein_satz_weniger_als_geplant_ist_erlaubt():
    assert h.plan_fit([5, 2, 3], "Eins zwei drei vier fünf. Eins zwei drei.") == 0
    assert h.plan_fit([5, 3], "Eins zwei drei vier fünf.") == 0
    assert h.plan_fit([5, 3, 4, 6], "Eins zwei drei vier fünf.") > 0.4


def test_auftrag_ohne_alte_verbindungsliste():
    request = h.paragraph_request(PARA, [10, 10, 10])
    assert "mit \"obwohl\", \"während\", \"sodass\"" not in request
    assert "kein \"obwohl\" ohne Gegensatz in der Vorlage" in request

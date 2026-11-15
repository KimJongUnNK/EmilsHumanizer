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
    assert h.humanize("Text", "Locker", "gemma3:12b", url).startswith("Kurz.")
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
        h.humanize("Text", "Locker", "kaputt", url)


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

    app.input.insert("1.0", "Darüber hinaus ist das wichtig. Es ist nahtlos.")
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
    app.input.insert("1.0", "Text")
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


def test_excerpt_schneidet_am_satzende():
    text = "Eins zwei drei. Vier fünf sechs sieben. Acht neun zehn elf zwölf."
    assert h.excerpt(text, 100) == text
    assert h.excerpt(text, 9) == "Eins zwei drei. Vier fünf sechs sieben."
    assert h.excerpt("ein langer satz ohne punkt und ende", 3) == "ein langer satz …"


def test_pick_examples_budget_und_pools():
    rng = random.Random(1)
    main = [" ".join(["haupt"] * 1000) + f" {i}" for i in range(10)]
    side = ["neben " * 50]
    picked = h.pick_examples([main, side], budget=600, count=3, rng=rng)
    assert len(picked) == 3
    assert sum(len(p.split()) for p in picked) <= 600 + 3
    assert sum(p.startswith("haupt") for p in picked) == 2 and sum(p.startswith("neben") for p in picked) == 1
    assert h.pick_examples([[], []]) == []
    assert len(h.pick_examples([["nur einer"]], count=3)) == 1


def test_style_examples_quellen():
    groups = {"sachlich": ["Sachtext."], "bericht": ["Bericht."], "locker": ["Locker."]}
    bundled = groups.__getitem__
    assert h.style_examples("Aus", "Akademisch", ["Eigen."], bundled) == ([], "")
    examples, note = h.style_examples("Meine Texte", "Akademisch", ["Eigen."], bundled)
    assert examples == ["Eigen."] and note == ""
    examples, note = h.style_examples("Meine Texte", "Akademisch", [], bundled)
    assert set(examples) == {"Sachtext.", "Bericht."} and "noch nichts" in note
    examples, _ = h.style_examples("Mitgeliefert", "Locker", ["Eigen."], bundled)
    assert set(examples) == {"Locker.", "Bericht."}
    assert set(h.style_examples("Mitgeliefert", "Natürlich", [], bundled)[0]) == {"Bericht.", "Locker.", "Sachtext."}


def test_system_prompt_mit_und_ohne_vorlage():
    plain = h.system_prompt("Akademisch", [])
    assert "<beispiel>" not in plain and h.STYLES["Akademisch"] in plain
    with_examples = h.system_prompt("Akademisch", ["Ein echter Satz."])
    assert "<beispiel>\nEin echter Satz.\n</beispiel>" in with_examples
    assert "NIE Inhalte" in with_examples


def test_humanize_schickt_vorlage(fake_ollama):
    url, seen, _ = fake_ollama
    h.humanize("Text", "Locker", "gemma3:12b", url, ["Vorbild."])
    assert "<beispiel>\nVorbild.\n</beispiel>" in seen[-1][1]["messages"][0]["content"]
    assert seen[-1][1]["options"]["num_ctx"] == 16384


def test_missing_facts_und_kuerzung():
    source = "Am 28.09.2026 kamen 150 Leute, z. B. 3,5 % mehr als 2025."
    assert h.missing_facts(source, source) == []
    assert h.missing_facts(source, "Am 28. September kamen 150 Leute, 3,5 % mehr als 2025.") == ["28.09.2026"]
    assert h.missing_facts(source, "Es kamen Leute.") == ["28.09.2026", "150", "3,5", "2025"]
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
    app.input.insert("1.0", "Das Fest ist am 28.09.2026 in Dornbirn mit 300 Gästen.")
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
    app.input.insert("1.0", "Kurz. Und dann ein deutlich längerer Satz hinterher.")
    app.run()
    pump(root, lambda: "noch nichts" in app.warning["text"])
    assert "<beispiel>" in seen[-1][1]["messages"][0]["content"]
    app.open_own_texts()
    assert opened == [str(tmp_path / "texte")]


def test_app_waehlt_meine_texte_wenn_vorhanden(root, fake_ollama, monkeypatch, tmp_path):
    url, seen, _ = fake_ollama
    (tmp_path / "hausarbeit.txt").write_text("Mein eigener Satz aus der Hausarbeit.", encoding="utf-8")
    monkeypatch.setattr(h, "user_dir", lambda: str(tmp_path))
    app = h.App(root, url)
    assert app.source.get() == "Meine Texte"
    pump(root, lambda: str(app.go["state"]) == "normal")
    app.input.insert("1.0", "Text")
    app.run()
    pump(root, lambda: seen[-1][0] == "/api/chat")
    assert "Mein eigener Satz aus der Hausarbeit." in seen[-1][1]["messages"][0]["content"]


# --- Ziel-Länge und automatisches Nachbessern ---
UNIFORM = " ".join(f"Satz Nummer {i} hat genau sieben Wörter drin." for i in range(10))
VARIED = ("Kurz. " + "Dieser Satz ist dagegen ziemlich lang, weil er mehrere Nebensätze hat, die erklären, warum "
          "etwas passiert, obwohl es niemand erwartet hätte, sodass am Ende alle staunen. ") * 5


def test_quellenangaben_trennen_keinen_satz():
    text = "Besucher erwarten Planung (vgl. Berger 2021, S. 45). Die Anforderungen steigen. Siehe Kap. 3 und Abs. 2."
    assert len(h.sentences(text)) == 3


def test_rewrite_request_nennt_ziel_laenge():
    request = h.rewrite_request(" ".join(["wort"] * 100))
    assert "hat 100 Wörter" in request and "90 bis 115 Wörter" in request


def test_problems():
    assert h.problems(VARIED, VARIED) == []
    found = h.problems(UNIFORM + " " + UNIFORM + " Am 24.07.2010 war es so.", UNIFORM)
    assert any("nur" in f and "Wörter" in f for f in found)
    assert any("24.07.2010" in f for f in found)
    assert any("gleich lang" in f for f in found)
    assert any("spielt eine" in f for f in h.problems(VARIED, VARIED + " Das spielt eine Rolle."))


@pytest.fixture
def scripted_ollama():
    """Ollama-Ersatz, der der Reihe nach vorgegebene Antworten liefert."""
    replies, seen = [], []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"message": {"content": replies.pop(0)}}).encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", replies, seen
    server.shutdown()


def test_humanize_checked_passt_gleich(scripted_ollama):
    url, replies, seen = scripted_ollama
    replies.append(VARIED)
    assert h.humanize_checked(VARIED, "Akademisch", "m", url) == (VARIED.strip(), 1)
    assert len(seen) == 1 and "Wörter. Deine Fassung hat" in seen[0]["messages"][1]["content"]


def test_humanize_checked_bessert_nach(scripted_ollama):
    url, replies, seen = scripted_ollama
    replies += [UNIFORM[:150], VARIED]
    result, passes = h.humanize_checked(VARIED, "Akademisch", "m", url)
    assert passes == 2 and result == VARIED.strip()
    follow_up = seen[1]["messages"]
    assert [m["role"] for m in follow_up] == ["system", "user", "assistant", "user"]
    assert follow_up[2]["content"] == UNIFORM[:150].strip() and "passt noch nicht" in follow_up[3]["content"]


def test_humanize_checked_behaelt_erste_wenn_zweite_schlechter(scripted_ollama):
    url, replies, _ = scripted_ollama
    first = VARIED[:len(VARIED) // 2]
    replies += [first, "Kaputt."]
    result, passes = h.humanize_checked(VARIED + " Am 24.07.2010.", "Akademisch", "m", url)
    assert passes == 2 and result == first.strip()


def test_app_zeigt_nachgebessert(root, scripted_ollama, monkeypatch):
    url, replies, _ = scripted_ollama
    monkeypatch.setattr(h, "ensure_ollama", lambda url: ["m"])
    monkeypatch.setattr(h, "user_dir", lambda: "/gibt/es/nicht")
    replies += [UNIFORM[:150], VARIED]
    app = h.App(root, url)
    pump(root, lambda: str(app.go["state"]) == "normal")
    app.input.insert("1.0", VARIED)
    app.run()
    pump(root, lambda: "Fertig" in app.status["text"])
    assert "(nachgebessert)" in app.status["text"]
    assert app.update_button.master is app.go.master


def test_badness_ordnet_fassungen():
    source = VARIED + " Am 24.07.2010."
    assert h.badness(source, source) == 0
    assert h.badness(source, VARIED) == 25
    assert h.badness(source, "Kaputt.") > h.badness(source, VARIED[:len(VARIED) // 2] + " Am 24.07.2010.")


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

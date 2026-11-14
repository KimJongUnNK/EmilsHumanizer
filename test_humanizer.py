"""Tests für die Desktop-App. Die Fenster-Tests brauchen einen Bildschirm (unter Linux: xvfb-run)."""
import json
import threading
import time
import tkinter as tk
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import humanizer as h


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

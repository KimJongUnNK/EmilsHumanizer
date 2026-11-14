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

        def do_GET(self):
            seen.append((self.path, None))
            names = state["loaded"] if self.path == "/api/ps" else state["models"]
            self._send(200, {"models": [{"name": n} for n in names]})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, body))
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
    pump(root, lambda: "ollama pull" in app.status["text"])
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

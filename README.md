# Emils Humanizer

Desktop-App, die KI-Texte so umschreibt, dass sie klingen wie von einem Menschen geschrieben. Gebaut für deutsche Texte. Läuft komplett lokal über [Ollama](https://ollama.com): kein Konto, keine Kosten, die Texte verlassen den Rechner nicht.

## Was die App macht

- Schreibt den Text mit einem lokalen Sprachmodell um: Satzlängen mischen, KI-Floskeln streichen, Nominalstil und Passiv auflösen.
- Drei Stile: Natürlich, Akademisch, Locker.
- Zeigt nach dem Umschreiben, was sich geändert hat: links rot = gestrichen, rechts grün = neu formuliert.
- Zeigt Kennzahlen: Anteil neu formulierter Wörter, Streuung der Satzlängen, Anzahl KI-Floskeln vorher und nachher.

Die App garantiert nicht, dass ein Text an KI-Detektoren vorbeikommt. Lokale Modelle können außerdem Inhalte leicht verändern oder kürzen, also die Ausgabe gegenlesen.

## Voraussetzungen

- Windows, macOS oder Linux
- Python 3.10 oder neuer (ohne Zusatzpakete)
- Ollama mit mindestens einem Modell

## Installation unter Windows

In PowerShell:

```
winget install Ollama.Ollama
ollama pull gemma3:12b
```

`gemma3:12b` ist rund 8 GB groß und schreibt für seine Größe gutes Deutsch. Auf schwächeren Rechnern geht `gemma3:4b`, das ist schneller, schreibt aber schlechter.

Dann `humanizer.py` aus diesem Repo herunterladen (oben auf **Code → Download ZIP** und entpacken) und starten:

```
python humanizer.py
```

## Desktop-Symbol anlegen

Im Ordner, in dem `humanizer.py` liegt, in PowerShell ausführen:

```
$pyw = (python -c "import sys; print(sys.executable)").Replace("python.exe", "pythonw.exe")
$lnk = (New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath("Desktop") + "\Humanizer.lnk")
$lnk.TargetPath = $pyw
$lnk.Arguments = '"' + (Join-Path (Get-Location) "humanizer.py") + '"'
$lnk.Save()
```

Danach startet ein Doppelklick auf "Humanizer" am Desktop die App ohne Terminal-Fenster.

## Modelle in der App herunterladen

Der Knopf **Modelle …** neben der Modell-Auswahl öffnet eine Liste empfohlener Modelle. Zu jedem steht die Download-Größe, was es an Grafikspeicher oder RAM braucht, und wie es auf deinem Rechner voraussichtlich läuft. Ein Klick auf **Herunterladen** holt das Modell über Ollama, der Fortschritt steht unten im Fenster. Über "Anderes Modell" lässt sich jedes Modell aus der [Ollama-Bibliothek](https://ollama.com/library) per Name laden.

| Modell | Download | Braucht |
| --- | --- | --- |
| gemma3:1b | 0,8 GB | 2 GB Grafikspeicher oder 4 GB RAM |
| gemma3:4b | 3,3 GB | 4 GB Grafikspeicher oder 8 GB RAM |
| gemma3:12b | 8,1 GB | 10 GB Grafikspeicher oder 16 GB RAM |
| mistral-nemo:12b | 7,1 GB | 10 GB Grafikspeicher oder 16 GB RAM |
| mistral-small3.2:24b | 15 GB | 18 GB Grafikspeicher oder 32 GB RAM |
| gemma3:27b | 17 GB | 20 GB Grafikspeicher oder 32 GB RAM |

Die Werte sind Richtwerte. Reicht der Grafikspeicher nicht, läuft ein Modell über den RAM, nur deutlich langsamer. Die App erkennt den Grafikspeicher nur bei NVIDIA-Karten.

## Bedienung

1. Modell und Stil oben auswählen. Die Liste zeigt alle in Ollama installierten Modelle.
2. Text links einfügen.
3. **Umschreiben** klicken oder Strg+Enter drücken.
4. Ergebnis rechts prüfen und mit **Kopieren** übernehmen.

**Cache leeren** wirft das Modell aus dem Arbeits- und Grafikspeicher. Ollama hält es sonst noch einige Minuten nach dem letzten Text geladen. Sinnvoll, wenn du den Speicher gleich für etwas anderes brauchst, etwa ein Spiel oder einen Videoschnitt. Das nächste Umschreiben dauert danach etwas länger, weil das Modell neu geladen wird.

Sehr lange Texte (grob über 2.000 Wörter) in Teilen umschreiben, sonst schneidet Ollama den Anfang stillschweigend ab.

Läuft Ollama auf einem anderen Rechner oder Port, die Adresse über die Umgebungsvariable `OLLAMA_URL` setzen (Standard: `http://localhost:11434`).

## Tests

```
pip install pytest
pytest test_humanizer.py
```

Die Tests laufen gegen einen nachgebauten Ollama-Server und brauchen kein installiertes Modell. Die Fenster-Tests brauchen einen Bildschirm, unter Linux ohne Bildschirm: `xvfb-run -a pytest test_humanizer.py`.

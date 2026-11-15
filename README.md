# Emils Humanizer

Desktop-App, die KI-Texte so umschreibt, dass sie klingen wie von einem Menschen geschrieben. Gebaut für deutsche Texte. Läuft komplett lokal über [Ollama](https://ollama.com): kein Konto, keine Kosten, die Texte verlassen den Rechner nicht.

## Download (Windows)

**[Humanizer.exe herunterladen](https://github.com/KimJongUnNK/EmilsHumanizer/releases/latest/download/Humanizer.exe)**

1. [Ollama installieren](https://ollama.com/download) und einmal starten.
2. `Humanizer.exe` herunterladen und per Doppelklick starten. Python ist nicht nötig.
3. In der App auf **Modelle …** klicken und ein Modell herunterladen. Empfehlung: `gemma3:12b`.

Windows zeigt beim ersten Start die Warnung "Der Computer wurde durch Windows geschützt", weil die Datei nicht signiert ist. Auf **Weitere Informationen** und dann **Trotzdem ausführen** klicken. Manche Virenscanner schlagen bei so gebauten Programmen fälschlich an. Wer der Datei nicht traut, startet die App direkt aus dem Quelltext (siehe unten).

## Was die App macht

- Schreibt den Text mit einem lokalen Sprachmodell um: Satzlängen mischen, KI-Floskeln streichen, Nominalstil und Passiv auflösen.
- Drei Stile: Natürlich, Akademisch, Locker.
- Zeigt nach dem Umschreiben, was sich geändert hat: links rot = gestrichen, rechts grün = neu formuliert.
- Zeigt Kennzahlen: Anteil neu formulierter Wörter, Streuung der Satzlängen, Anzahl KI-Floskeln vorher und nachher.
- Lädt Modelle direkt in der App herunter und zeigt, was jedes braucht.

Die App garantiert nicht, dass ein Text an KI-Detektoren vorbeikommt. Lokale Modelle können außerdem Inhalte leicht verändern oder kürzen, also die Ausgabe gegenlesen.

## Bedienung

1. Modell und Stil oben auswählen. Die Liste zeigt alle in Ollama installierten Modelle.
2. Text links einfügen.
3. **Umschreiben** klicken oder Strg+Enter drücken.
4. Ergebnis rechts prüfen und mit **Kopieren** übernehmen.

**Cache leeren** wirft das Modell aus dem Arbeits- und Grafikspeicher. Ollama hält es sonst noch einige Minuten nach dem letzten Text geladen. Sinnvoll, wenn du den Speicher gleich für etwas anderes brauchst, etwa ein Spiel oder einen Videoschnitt. Das nächste Umschreiben dauert danach etwas länger, weil das Modell neu geladen wird.

Sehr lange Texte (grob über 2.000 Wörter) in Teilen umschreiben, sonst schneidet Ollama den Anfang stillschweigend ab.

## Stilvorlage: echte Menschentexte

Vor jedem Umschreiben bekommt das Modell drei kurze Auszüge aus Texten, die nachweislich Menschen geschrieben haben. Daran sieht es, wie menschliches Deutsch klingt: wechselnde Satzlängen, Sprünge, Ton. Inhalte übernimmt es daraus nicht. Das Modell wird dabei nicht trainiert, die Auszüge wechseln bei jedem Durchlauf.

Oben in der App unter **Stilvorlage**:

- **Mitgeliefert:** Texte, die mit der App kommen, passend zum Stil ausgewählt. "Akademisch" nimmt sachliche Texte (Technik, Physik, Architektur, Geschichte, Musik, Essays, Fachaufsätze), "Locker" nimmt Feuilletons und Glossen, "Natürlich" vor allem Reiseberichte und Reportagen.
- **Meine Texte:** Eigene Texte. **Meine Texte …** öffnet den Ordner (`%APPDATA%\EmilsHumanizer\texte`), dort `.txt`-Dateien ablegen. Am besten wirken eigene frühere Arbeiten. Der Ordner liegt nur auf deinem Rechner und kommt nie ins Repo.
- **Aus:** ohne Vorlage.

## Prüfen und Nachbessern

Das Modell bekommt eine Ziel-Wortzahl (90 bis 115 % des Originals). Danach prüft die App die Fassung:

- fehlen Zahlen oder Daten aus dem Original, oder sind welche dazugekommen, die das Modell erfunden hat?
- fehlt ein ganzer Absatz, etwa der Schluss?
- ist sie mehr als 15 % kürzer?
- sind die Sätze fast alle gleich lang, stehen noch KI-Floskeln drin, hängt sie ständig ", weil …" an?

Findet sie etwas, schickt sie dem Modell eine konkrete Rückmeldung und lässt es nachbessern, höchstens zweimal. Behalten wird die beste Fassung, die Statuszeile zeigt, wie oft nachgebessert wurde. Was danach noch fehlt oder erfunden ist, steht rot unter den Textfeldern.

Erfundene Aussagen ohne Zahl (etwa ein dazugedichteter Grund) erkennt die Prüfung nicht. Vor allem bei Uni-Texten die Ausgabe gegen das Original lesen.

Die mitgelieferten Texte stammen von [Wikisource](https://de.wikisource.org), wo nur gemeinfreie Texte stehen (Urheberrecht abgelaufen). Darunter Kurt Tucholsky, Franz Kafka, Ludwig Thoma und viele Artikel aus Zeitschriften wie der "Gartenlaube". Gedichte und Dramen sind aussortiert, Stellen mit rassistischen oder antisemitischen Begriffen entfernt, die Rechtschreibung ist an die heutige angepasst (daß → dass). Das Skript dafür liegt unter `werkzeuge/`.

## Update

Der Knopf **Update** oben rechts prüft, ob es eine neuere Version gibt. Wenn ja, lädt die App sie nach einer Rückfrage herunter, ersetzt sich selbst und startet neu. Die App prüft nur auf Klick, nie von allein. Wer aus dem Quelltext startet, lädt die neue Version selbst von dieser Seite.

## Modelle

Der Knopf **Modelle …** öffnet eine Liste empfohlener Modelle. Zu jedem steht die Download-Größe, was es an Grafikspeicher oder RAM braucht, und wie es auf deinem Rechner voraussichtlich läuft. **Herunterladen** holt das Modell über Ollama, der Fortschritt steht unten im Fenster. Über "Anderes Modell" lässt sich jedes Modell aus der [Ollama-Bibliothek](https://ollama.com/library) per Name laden.

| Modell | Download | Braucht |
| --- | --- | --- |
| gemma3:1b | 0,8 GB | 2 GB Grafikspeicher oder 4 GB RAM |
| gemma3:4b | 3,3 GB | 4 GB Grafikspeicher oder 8 GB RAM |
| gemma3:12b | 8,1 GB | 10 GB Grafikspeicher oder 16 GB RAM |
| mistral-nemo:12b | 7,1 GB | 10 GB Grafikspeicher oder 16 GB RAM |
| mistral-small3.2:24b | 15 GB | 18 GB Grafikspeicher oder 32 GB RAM |
| gemma3:27b | 17 GB | 20 GB Grafikspeicher oder 32 GB RAM |

Ein laufender Download lässt sich mit **Abbrechen** stoppen. Was schon geladen ist, bleibt liegen, beim nächsten Versuch geht es dort weiter. Installierte Modelle haben einen **Löschen**-Knopf, das gibt den Speicherplatz wieder frei.

Die Werte sind Richtwerte. Reicht der Grafikspeicher nicht, läuft ein Modell über den RAM, nur deutlich langsamer. Die App erkennt den Grafikspeicher nur bei NVIDIA-Karten.

## Aus dem Quelltext starten (Windows, macOS, Linux)

Braucht Python 3.10 oder neuer, keine Zusatzpakete. [ZIP herunterladen](https://github.com/KimJongUnNK/EmilsHumanizer/archive/refs/heads/main.zip), entpacken und im Ordner:

```
python humanizer.py
```

Läuft Ollama auf einem anderen Rechner oder Port, die Adresse über die Umgebungsvariable `OLLAMA_URL` setzen (Standard: `http://localhost:11434`).

## Tests

```
pip install pytest
pytest test_humanizer.py
```

Die Tests laufen gegen einen nachgebauten Ollama-Server und brauchen kein installiertes Modell. Die Fenster-Tests brauchen einen Bildschirm, unter Linux ohne Bildschirm: `xvfb-run -a pytest test_humanizer.py`.

Bei jedem Stand auf `main` testet GitHub die App unter Windows und baut daraus die `Humanizer.exe` zum Download.

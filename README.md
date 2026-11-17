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

Die Baupläne und Hörproben stammen aus Texten, die nachweislich Menschen geschrieben haben. Daran sieht das Modell, wie menschliches Deutsch klingt: wechselnde Satzlängen, Sprünge, Ton. Inhalte übernimmt es daraus nicht. Das Modell wird dabei nicht trainiert, die Vorbilder wechseln bei jedem Absatz.

Oben in der App unter **Stilvorlage**:

- **Mitgeliefert:** Texte, die mit der App kommen, passend zum Stil ausgewählt. "Akademisch" nimmt sachliche Texte (Technik, Physik, Architektur, Geschichte, Musik, Essays, Fachaufsätze), "Locker" nimmt Feuilletons und Glossen, "Natürlich" vor allem Reiseberichte und Reportagen.
- **Meine Texte:** Eigene Texte. **Meine Texte …** öffnet den Ordner (`%APPDATA%\EmilsHumanizer\texte`), dort `.txt`-Dateien ablegen. Am besten wirken eigene frühere Arbeiten. Der Ordner liegt nur auf deinem Rechner und kommt nie ins Repo.
- **Aus:** ohne Vorlage.

## Absatz für Absatz nach Bauplan

Die App schreibt nicht den ganzen Text auf einmal um, sondern jeden Absatz einzeln. Überschriften und Einzeiler bleiben stehen.

Für jeden Absatz sucht sie unter den Stilvorlagen einen echten, von einem Menschen geschriebenen Absatz ähnlicher Länge und übernimmt davon nur die Abfolge der Satzlängen, zum Beispiel 32, 20 und 12 Wörter. Das Modell bekommt diesen Bauplan als genaue Vorgabe, dazu den echten Absatz als Hörprobe und die Liste der Angaben, die wörtlich bleiben müssen: Zahlen, Daten, Quellenangaben wie "(vgl. Berger 2021, S. 45)". Bei Stilvorlage "Aus" nimmt die App einen festen abwechslungsreichen Bauplan.

Danach prüft sie jeden Absatz:

- fehlen Zahlen, Daten oder Quellenangaben, oder haben Zahlen ihre Einheit verloren ("60 %" wird zu "60")? Sind welche dazugekommen, steht eine Quellenangabe doppelt?
- fehlen Einschränkungen wie Orte, Zeiträume oder Gruppen ("In Österreich", "europäischen Festivalveranstalter", "am Mischpult", "bei einem mehrtägigen Festival")? Die sucht die App vor dem Umschreiben nach festen Regeln aus dem Absatz heraus, gibt sie dem Modell als Pflichtangaben mit und prüft danach, ob ihre Kernwörter noch dastehen.
- steht jede Quellenangabe noch bei der Aussage, die sie im Original belegt, oder ist sie zu einer anderen gerutscht?
- wiederholt ein Satz, was schon dasteht?
- behauptet der Absatz mit "obwohl", "jedoch", "sodass", "daher" & Co. einen Gegensatz oder eine Folge, die das Original nicht nennt?
- gibt es Sätze ohne Grundlage im Original, etwa "Das gilt für alle Bereiche." oder einen dazugedichteten Grund? Eine Jahreszahl, die nur in einer Quellenangabe stand und plötzlich im Fließtext auftaucht, gilt als erfunden.
- wiederholen sich Wendungen wie "… stellt … dar" oder "ist von … Bedeutung" über mehrere Absätze?
- ist der Absatz mehr als 20 % kürzer oder länger?
- passen Satzanzahl und Satzlängen zum Bauplan?
- sind Sätze fast wörtlich aus dem Original übernommen?
- stehen noch KI-Floskeln drin, hängt er ständig ", weil …" an?

Was sie findet, repariert sie gezielt, Schritt für Schritt:

1. Ist der Entwurf grob daneben, schreibt das Modell den Absatz einmal neu, mit konkreter Rückmeldung.
2. Sätze ohne Grundlage und Satzfragmente fliegen raus.
3. Jeder Satz mit Floskel, wörtlicher Übernahme oder neuer Verknüpfung wird einzeln repariert. Einfache Floskelwörter tauscht die App ohne Modell aus ("Des Weiteren" → "Außerdem", "essenzielle Rolle" → "große Rolle"). Eine Reparatur zählt nur, wenn der Satz danach besser ist, nichts verliert und keinen neuen Zusammenhang behauptet.
4. Fehlt eine Zahl, Quelle oder ganze Aussage, oder ist etwas erfunden oder verrutscht, kommt der Originalsatz zurück und wird noch einmal einzeln umformuliert.
5. Sind die Sätze zu gleich lang, legt die App zwei Nachbarn zusammen oder teilt den längsten.

Die Statuszeile zeigt den Fortschritt ("Absatz 3 von 6") und am Ende, wie oft eingegriffen wurde. Was danach noch fehlt, erfunden oder kaum verändert ist, steht rot unter den Textfeldern.

Nicht erkannt werden verdrehte Zusammenhänge ohne Signalwort ("das Konzept begrenzt die Dichte" statt "die Verordnung schreibt sie vor"), erfundene Teilsätze in sonst passenden Sätzen und Wiederholungen mit ganz anderen Worten. Ein Satz, der fast nur aus Synonymen besteht, kann umgekehrt fälschlich als "ohne Grundlage" gemeldet werden. Vor allem bei Uni-Texten die Ausgabe gegen das Original lesen.

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

## Testreihe: so gut ist der Stand gemessen

In `werkzeuge/testtexte/` liegen fünf KI-typische Texte zu Event-Engineering-Themen (Nachhaltigkeit, Technikgeschichte, Sponsoring, Zeitplanung, Kaffeekultur), vier akademisch, einer locker. Die Quellenangaben darin sind erfunden. `werkzeuge/testreihe.py` schreibt jeden Text um und prüft das Ergebnis gegen feste Kriterien:

| Kriterium | Grenze |
|---|---|
| Zahlen und Daten fehlen oder erfunden | keine |
| Quellenangaben fehlen oder verrutscht | keine |
| Einschränkungen (Orte, Zeiträume, Gruppen) fehlen | höchstens 1 |
| neu behauptete Zusammenhänge ("obwohl", "sodass", "weil" …) | höchstens 1 |
| Sätze ohne Grundlage im Original | höchstens 1 |
| Satzfragmente (akademisch) | keine |
| Floskeln | höchstens 2, wie bei echten Menschentexten |
| Streuung der Satzlängen | ab 0,45 |
| fast wörtlich übernommene Sätze | höchstens 20 % |
| Länge im Vergleich zum Original | 80 bis 120 % |

**Gemessen mit `gemma3:12b`: 8 von 10 Läufen bestanden** (fünf Texte, je zwei Läufe). Kein Lauf hat eine Zahl, Quelle oder Einschränkung verloren oder etwas erfunden. Beide Fehlschläge betreffen den Sponsoring-Text: Er wurde auf 72 bzw. 78 % gekürzt, weil der Testtext voller Floskeln steckt ("In der heutigen Zeit", "Abschließend lässt sich sagen"), die beim Umschreiben wegfallen.

Selbst laufen lassen, zum Beispiel mit dem 24b-Modell (dauert je nach Rechner eine bis mehrere Stunden):

```
python werkzeuge/testreihe.py --model mistral-small3.2:24b
```

Was die Testreihe nicht sieht: abgeschwächte Aussagen ("muss" wird zu "sollte"), weggelassene Halbsätze ohne Zahl und verdrehte Zusammenhänge ohne Signalwort. Vor allem bei Uni-Texten die Ausgabe gegen das Original lesen.

## Tests

```
pip install pytest
pytest test_humanizer.py
```

Die Tests laufen gegen einen nachgebauten Ollama-Server und brauchen kein installiertes Modell. Die Fenster-Tests brauchen einen Bildschirm, unter Linux ohne Bildschirm: `xvfb-run -a pytest test_humanizer.py`.

Bei jedem Stand auf `main` testet GitHub die App unter Windows und baut daraus die `Humanizer.exe` zum Download.
